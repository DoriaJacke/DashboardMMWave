"""
Conexión con la placa CMAE.

Una sola conexión a la vez, de cuatro formas posibles:

  - "ble":      la placa real por Bluetooth (como en el receptor original).
  - "uart":     la placa real por USB (puerto COM, 921600 baudios).
  - "archivo":  reproduce una grabación .bin a su ritmo original.
  - "simulada": placa inventada, para probar o mostrar la app sin hardware.

Cada conexión corre en un hilo propio y entrega tramas completas a quien las
quiera (la vista en vivo y la grabación). Viene de dashboard/cmae_conexion.py
del dashboard del radar: mismos estados y misma reconexión automática por BLE.
"""
from __future__ import annotations

import asyncio
import bisect
import struct
import threading
import time
from array import array
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from . import protocolo as p
from .simulador import SimuladorPlaca

# Parámetros de la placa, iguales a los del receptor original
TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"   # la placa envía datos
RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"   # se le escribe START / STOP
SCAN_TIMEOUT_S = 8.0
CONNECT_TIMEOUT_S = 30.0
CONNECT_RETRIES = 3
RETRY_DELAY_S = 2.0
RECONNECT_DELAY_S = 2.0      # pausa entre intentos de reconexión
STALL_TIMEOUT_S = 10.0       # conectada pero sin datos este tiempo: se trata como corte

UART_BAUDRATE = 921600
UART_TIMEOUT_S = 0.02
UART_READ_CHUNK_BYTES = 8192

NOMBRE_SIMULADA = "Placa simulada (sin hardware)"


class Estado(Enum):
    DESCONECTADA = "Desconectada"
    CONECTANDO = "Conectando"
    CONECTADA = "Conectada"
    RECONECTANDO = "Reconectando"
    DESCONECTANDO = "Desconectando"
    ERROR = "Error"


class _Detenida(Exception):
    """El usuario pidió desconectar mientras se buscaba o conectaba."""


def nombre_ble(numero: int) -> str:
    return f"CMAE-{numero}-S3-N16R8"


def listar_puertos() -> List[Dict[str, Any]]:
    """Puertos COM del PC. Marca los que parecen ser la entrada 'USB Serial Carga' de la placa."""
    from serial.tools import list_ports

    puertos = []
    for puerto in list_ports.comports():
        puertos.append({
            "puerto": puerto.device,
            "descripcion": puerto.description or "",
            # El chip USB de la entrada de carga es un CP2102N (VID 10C4, PID EA60).
            "parece_placa": puerto.vid == 0x10C4 and puerto.pid == 0xEA60,
            # La entrada USB-Debug (VID 303A) no entrega datos de sensores.
            "es_debug": puerto.vid == 0x303A,
        })
    return puertos


def _explicar_error_ble(exc: BaseException) -> str:
    texto = str(exc) or type(exc).__name__
    bajo = texto.lower()
    if "adapter" in bajo or "radio" in bajo or "not ready" in bajo or "-2147020577" in bajo or "no bluetooth" in bajo:
        return "Este PC no tiene Bluetooth disponible, o está apagado."
    return texto


async def buscar_placas(segundos: float = 5.0) -> List[Dict[str, Any]]:
    """Busca por Bluetooth las placas CMAE que estén cerca y encendidas."""
    from bleak import BleakScanner

    try:
        dispositivos = await BleakScanner.discover(timeout=segundos, return_adv=True)
    except Exception as exc:
        raise ConnectionError(_explicar_error_ble(exc)) from exc

    placas = []
    for dispositivo, adv in dispositivos.values():
        nombre = dispositivo.name or adv.local_name or ""
        partes = nombre.split("-")
        if len(partes) >= 2 and partes[0] == "CMAE" and partes[1].isdigit():
            placas.append({"nombre": nombre, "numero": int(partes[1]), "senal_dbm": adv.rssi})
    placas.sort(key=lambda x: -(x["senal_dbm"] or -999))
    return placas


class Placa:
    """Maneja la conexión y entrega cada trama a `al_recibir(trama, protocolo)`."""

    PASO_SIMULADA_S = 0.02

    def __init__(self, al_recibir: Callable[[bytes, str], None],
                 al_empezar: Optional[Callable[[], None]] = None) -> None:
        self._al_recibir = al_recibir
        self._al_empezar = al_empezar
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ajuste = threading.Lock()

        self.estado = Estado.DESCONECTADA
        self.detalle = ""
        self.origen: Optional[str] = None
        self.nombre = ""
        self.numero: Optional[int] = None
        self.protocolo = p.BLE
        self._limpiar_contadores()

    def _limpiar_contadores(self) -> None:
        self.tramas_ok = 0
        self.tramas_malas = 0
        self.cortes = 0
        self.conectada_desde: Optional[float] = None
        self.uart: Dict[str, Any] = {}
        self.archivo: Dict[str, Any] = {}
        self._conecto_alguna_vez = False
        self._ultimo_dato = 0.0

    # --------------------------------------------------------
    # Uso desde la app
    # --------------------------------------------------------

    @property
    def activa(self) -> bool:
        """Hay un hilo trabajando: buscando, conectada, reconectando o cerrando."""
        return self.estado in (Estado.CONECTANDO, Estado.CONECTADA, Estado.RECONECTANDO, Estado.DESCONECTANDO)

    def conectar_ble(self, numero: int) -> None:
        self._empezar("ble", nombre_ble(numero), p.BLE, self._ciclo_ble, numero=numero)

    def conectar_uart(self, puerto: str, numero: Optional[int] = None) -> None:
        self._empezar("uart", puerto, p.UART, self._uart, puerto, numero=numero)

    def reproducir(self, ruta: Path, repetir: bool = True, inicio_s: float = 0.0) -> None:
        self._empezar("archivo", Path(ruta).name, p.BLE, self._reproducir, Path(ruta), repetir, inicio_s)

    def simular(self, formato: str = p.BLE) -> None:
        self._empezar("simulada", NOMBRE_SIMULADA, formato, self._simular, formato)

    def desconectar(self) -> None:
        if self.activa:
            self.estado = Estado.DESCONECTANDO
            self.detalle = ""
            self._stop.set()

    def esperar_cierre(self, segundos: float = 5.0) -> None:
        """Espera a que el hilo termine (por ejemplo, para enviar STOP antes de cerrar la app)."""
        hilo = self._thread
        if hilo is not None and hilo.is_alive():
            hilo.join(segundos)

    def _empezar(self, origen: str, nombre: str, protocolo: str, objetivo: Callable[..., None],
                 *args: Any, numero: Optional[int] = None) -> None:
        with self._ajuste:
            if self.activa:
                raise RuntimeError("Ya hay una conexión en curso. Desconecta primero.")
            self._limpiar_contadores()
            self.origen = origen
            self.nombre = nombre
            self.numero = numero
            self.protocolo = protocolo
            self.estado = Estado.CONECTANDO
            self.detalle = ""
            self._stop.clear()
            if self._al_empezar is not None:
                self._al_empezar()
            self._thread = threading.Thread(target=self._run, args=(objetivo, args), daemon=True)
            self._thread.start()

    # --------------------------------------------------------
    # Hilo de conexión
    # --------------------------------------------------------

    def _run(self, objetivo: Callable[..., None], args: tuple) -> None:
        try:
            objetivo(*args)
        except _Detenida:
            pass
        except Exception as exc:
            self.estado = Estado.ERROR
            self.detalle = str(exc) or type(exc).__name__
            return
        self.estado = Estado.DESCONECTADA
        self.detalle = ""

    def _entregar(self, trama: bytes) -> None:
        self.tramas_ok += 1
        self._ultimo_dato = time.monotonic()
        try:
            self._al_recibir(trama, self.protocolo)
        except Exception:
            pass  # un error al mostrar o guardar no debe cortar la conexión

    def _marcar_conectada(self, detalle: str) -> None:
        self._conecto_alguna_vez = True
        self._ultimo_dato = time.monotonic()
        if self.conectada_desde is None:
            self.conectada_desde = time.time()
        self.estado = Estado.CONECTADA
        self.detalle = detalle

    # ------------------------------ Simulada ------------------------------

    def _simular(self, formato: str) -> None:
        self.detalle = "Iniciando placa simulada..."
        if self._stop.wait(0.6):
            return
        simulador = SimuladorPlaca(formato)
        self._marcar_conectada(NOMBRE_SIMULADA)
        while not self._stop.wait(self.PASO_SIMULADA_S):
            for trama in simulador.paso():
                self._entregar(trama)

    # ------------------------------ Archivo -------------------------------

    def _reproducir(self, ruta: Path, repetir: bool, inicio_s: float) -> None:
        self.detalle = f"Leyendo {ruta.name}..."
        data = ruta.read_bytes()
        self.protocolo = p.adivinar_protocolo(data)

        # Índice de tramas: dónde empieza y termina cada una y qué hora marcaba la placa.
        inicios, fines, relojes = array("I"), array("I"), array("I")
        for a, b in p.iter_tramas_archivo(data):
            if self._stop.is_set():
                raise _Detenida()
            inicios.append(a)
            fines.append(b)
            relojes.append(struct.unpack_from("<I", data, a + 4)[0])
        if not inicios:
            raise ValueError(f"{ruta.name} no contiene tramas válidas de la placa")

        duracion_s = max(0.0, (relojes[-1] - relojes[0]) / 1000.0)
        self.archivo = {"duracion_s": round(duracion_s, 1), "posicion_s": 0.0, "tramas": len(inicios)}
        primero = 0
        if inicio_s > 0:
            primero = min(bisect.bisect_left(relojes, relojes[0] + int(inicio_s * 1000)), len(inicios) - 1)
        self._marcar_conectada(ruta.name)

        while not self._stop.is_set():
            t_pc = time.monotonic()
            base = relojes[primero]
            for i in range(primero, len(inicios)):
                reloj = relojes[i]
                # Un salto raro del reloj (reinicio de la placa o una pausa larga) no se espera.
                if i > primero and not (0 <= reloj - relojes[i - 1] <= 2000):
                    t_pc = time.monotonic()
                    base = reloj
                espera = (reloj - base) / 1000.0 - (time.monotonic() - t_pc)
                if espera > 0 and self._stop.wait(espera):
                    return
                if self._stop.is_set():
                    return
                self._entregar(data[inicios[i]:fines[i]])
                self.archivo["posicion_s"] = round((reloj - relojes[0]) / 1000.0, 1)
            if not repetir:
                self.detalle = f"{ruta.name} (terminó)"
                self._stop.wait()   # se queda mostrando lo último hasta que se desconecte
                return
            primero = 0

    # ------------------------------ UART ----------------------------------

    def _uart(self, puerto: str) -> None:
        import serial

        self.detalle = f"Abriendo {puerto}..."
        lector = p.LectorTramas()
        try:
            # serial_for_url abre un COM normal y también acepta loop:// para pruebas.
            ser = serial.serial_for_url(puerto, baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT_S, write_timeout=0)
        except Exception as exc:
            raise ConnectionError(f"No pude abrir {puerto}: {exc}") from exc

        texto = bytearray()
        with ser:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            self._marcar_conectada(puerto)
            while not self._stop.is_set():
                try:
                    data = ser.read(UART_READ_CHUNK_BYTES)
                except Exception as exc:
                    raise ConnectionError(f"Se perdió el puerto {puerto}: {exc}") from exc
                if not data:
                    time.sleep(0.002)
                else:
                    for trama in lector.alimentar(data):
                        self._entregar(trama)
                    if not lector.tramas_ok:
                        # Mientras no llegue ninguna trama se guarda el texto que manda la
                        # placa: ayuda a ver, por ejemplo, que solo envía el arranque.
                        texto += bytes(b for b in data if 32 <= b < 127 or b in (10, 13))
                        del texto[:-400]
                self.tramas_malas = lector.crc_malos
                self.uart = {
                    "bytes_recibidos": lector.bytes_recibidos,
                    "bytes_descartados": lector.bytes_descartados,
                    "tramas": lector.tramas_ok,
                    "texto": texto.decode("ascii", "replace")[-300:] if not lector.tramas_ok else "",
                }

    # ------------------------------ BLE -----------------------------------

    def _ciclo_ble(self) -> None:
        asyncio.run(self._ciclo(self.nombre))

    async def _ciclo(self, nombre: str) -> None:
        """Conecta; si la conexión se pierde después de haber conectado, reintenta sin fin."""
        # En Windows, bleak necesita que este hilo no esté en modo "ventana" (STA).
        try:
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                await self._sesion(nombre)
                return
            except _Detenida:
                raise
            except Exception as exc:
                if not self._conecto_alguna_vez:
                    raise ConnectionError(_explicar_error_ble(exc)) from exc
                if self.estado == Estado.CONECTADA:
                    self.cortes += 1
                if self._stop.is_set():
                    return
                self.estado = Estado.RECONECTANDO
                self.detalle = f"{_explicar_error_ble(exc)}. Reintentando..."
                await self._hasta_detener(asyncio.sleep(RECONNECT_DELAY_S))

    async def _hasta_detener(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Espera coro, pero la cancela si el usuario pide desconectar."""
        tarea = asyncio.ensure_future(coro)
        while not tarea.done():
            if self._stop.is_set():
                tarea.cancel()
                raise _Detenida()
            await asyncio.sleep(0.1)
        return tarea.result()

    async def _buscar(self, nombre: str) -> Any:
        from bleak import BleakScanner

        self.detalle = f"Buscando {nombre}..."
        dispositivos = await self._hasta_detener(BleakScanner.discover(timeout=SCAN_TIMEOUT_S, return_adv=True))
        for dispositivo, adv in dispositivos.values():
            if (dispositivo.name or adv.local_name or "") == nombre:
                return dispositivo
        raise ConnectionError(f"No encontré la placa {nombre}. Revisa que esté encendida y cerca.")

    async def _conectar_con_reintentos(self, dispositivo: Any, nombre: str) -> Any:
        from bleak import BleakClient

        ultimo: Optional[Exception] = None
        for intento in range(1, CONNECT_RETRIES + 1):
            self.detalle = f"Conectando a {nombre} (intento {intento}/{CONNECT_RETRIES})..."
            cliente = BleakClient(dispositivo, timeout=CONNECT_TIMEOUT_S)
            try:
                await self._hasta_detener(cliente.connect())
                return cliente
            except _Detenida:
                raise
            except Exception as exc:
                ultimo = exc
                await self._hasta_detener(asyncio.sleep(RETRY_DELAY_S))
        raise ultimo or ConnectionError(f"No pude conectar a {nombre}")

    async def _sesion(self, nombre: str) -> None:
        """Una conexión completa. Vuelve solo si el usuario pide desconectar; si se corta, lanza error."""
        dispositivo = await self._buscar(nombre)
        cliente = await self._conectar_con_reintentos(dispositivo, nombre)
        reensamblador = p.ReensambladorBLE()
        malas_antes = self.tramas_malas

        def al_notificar(_origen: Any, data: bytearray) -> None:
            trama = reensamblador.alimentar(bytes(data))
            if trama is not None:
                self._entregar(trama)

        try:
            await cliente.start_notify(TX_CHAR_UUID, al_notificar)
            await cliente.write_gatt_char(RX_CHAR_UUID, b"START", response=False)
            if not cliente.is_connected:
                raise ConnectionError("La placa se desconectó al iniciar la transmisión")
            self._marcar_conectada(nombre)
            while not self._stop.is_set():
                await asyncio.sleep(0.1)
                reensamblador.limpiar_viejas()
                self.tramas_malas = malas_antes + reensamblador.errores
                if not cliente.is_connected:
                    raise ConnectionError("Se perdió la conexión Bluetooth con la placa")
                if time.monotonic() - self._ultimo_dato > STALL_TIMEOUT_S:
                    raise ConnectionError(f"La placa no envió datos en {STALL_TIMEOUT_S:.0f} s")
        finally:
            try:
                if cliente.is_connected:
                    await cliente.write_gatt_char(RX_CHAR_UUID, b"STOP", response=False)
                    await cliente.stop_notify(TX_CHAR_UUID)
                    await cliente.disconnect()
            except Exception:
                pass

    # --------------------------------------------------------
    # Estado para mostrar
    # --------------------------------------------------------

    def resumen(self) -> Dict[str, Any]:
        return {
            "estado": self.estado.value,
            "detalle": self.detalle,
            "origen": self.origen,
            "nombre": self.nombre,
            "numero": self.numero,
            "protocolo": self.protocolo,
            "activa": self.activa,
            "tramas_malas": self.tramas_malas,
            "cortes": self.cortes,
            "segundos": round(time.time() - self.conectada_desde, 1) if self.conectada_desde and self.activa else None,
            "uart": dict(self.uart),
            "archivo": dict(self.archivo),
        }
