# ============================================================
# CONEXIÓN BLE CON LA PLACA BIOMÉDICA CMAE (PBM)
#
# La conexión corre en un hilo propio (bleak usa asyncio) porque
# Streamlit vuelve a ejecutar app.py en cada refresco.
#
#   - Cada lectura de BPM/SpO2 se entrega a quien esté escuchando
#     (la sesión de adquisición, que la guarda en el CSV PBM_...).
#   - La última lectura y los últimos segundos de la onda PPG quedan
#     en memoria para la vista en vivo. La onda PPG no se guarda.
#   - Si la conexión se pierde después de haber conectado, se
#     reintenta sola hasta que el usuario presione Desconectar.
#   - Placa simulada (sin hardware): genera BPM, SpO2 y onda PPG
#     sintéticos con la misma interfaz, para probar el dashboard.
# ============================================================

from __future__ import annotations

import asyncio
import math
import random
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

import numpy as np
from bleak import BleakClient, BleakScanner

from cmae_protocolo import FragmentReassembler, Lectura, decode_frame

# Parámetros de la placa, iguales a los del receptor original
TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"   # la placa envía datos
RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"   # se le escribe START / STOP
SCAN_TIMEOUT_S = 8.0
CONNECT_TIMEOUT_S = 30.0
CONNECT_RETRIES = 3
RETRY_DELAY_S = 2.0

RECONNECT_DELAY_S = 2.0      # pausa entre intentos de reconexión
STALL_TIMEOUT_S = 10.0       # conectada pero sin datos este tiempo: se trata como corte
LATEST_MAX_AGE_S = 3.0       # una lectura más vieja que esto ya no se muestra como actual
PPG_KEEP_S = 15.0            # segundos de onda PPG que se guardan en memoria
RESTART_JUMP_MS = 1000.0     # si el tiempo de la placa retrocede más que esto, se reinició


class Estado(Enum):
    DESCONECTADA = "Desconectada"
    CONECTANDO = "Conectando"
    CONECTADA = "Conectada"
    RECONECTANDO = "Reconectando"
    DESCONECTANDO = "Desconectando"
    ERROR = "Error"


class _Detenida(Exception):
    """El usuario presionó Desconectar mientras se buscaba o conectaba."""


def nombre_ble(numero: int) -> str:
    return f"CMAE-{numero}-S3-N16R8"


NOMBRE_SIMULADA = "placa simulada (sin hardware)"


class SimuladorPlaca:
    """
    Datos sintéticos con el ritmo de la placa real: BPM y SpO2 unas 7 veces
    por segundo y onda PPG a 104 Hz. Los primeros segundos no son válidos
    (como el algoritmo real mientras calcula). Durante la retención el BPM
    baja un poco, igual que en el simulador del radar.
    """

    LECTURA_HZ = 7.0
    PPG_HZ = 104.0
    CALENTAMIENTO_S = 3.0

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._n_lectura = 0
        self._n_ppg = 0
        self._bpm = 72.0
        self._spo2 = 97.6
        self._fase_pulso = 0.0

    def paso(self, hold: bool) -> tuple[list[Lectura], list[tuple[float, float]]]:
        """Genera lo que corresponde al tiempo transcurrido desde el último paso."""
        ahora = time.monotonic() - self._t0

        ppg: list[tuple[float, float]] = []
        while self._n_ppg / self.PPG_HZ <= ahora:
            t = self._n_ppg / self.PPG_HZ
            self._fase_pulso = (self._fase_pulso + self._bpm / 60.0 / self.PPG_HZ) % 1.0
            f = self._fase_pulso
            pulso = math.exp(-((f - 0.18) / 0.07) ** 2) + 0.35 * math.exp(-((f - 0.50) / 0.09) ** 2)
            ir = 50000.0 + 150.0 * math.sin(2 * math.pi * 0.25 * t) + 600.0 * pulso + random.gauss(0, 12)
            ppg.append((t * 1000.0, ir))
            self._n_ppg += 1

        lecturas: list[Lectura] = []
        while self._n_lectura / self.LECTURA_HZ <= ahora:
            t = self._n_lectura / self.LECTURA_HZ
            self._bpm += 0.05 * ((66.0 if hold else 72.0) - self._bpm) + random.gauss(0, 0.25)
            self._spo2 += 0.05 * ((96.8 if hold else 97.6) - self._spo2) + random.gauss(0, 0.08)
            self._spo2 = min(self._spo2, 100.0)
            valido = t >= self.CALENTAMIENTO_S
            lecturas.append(Lectura(
                t_ms=t * 1000.0,
                bpm=self._bpm if valido else math.nan,
                spo2=self._spo2 if valido else math.nan,
                dedo=True, bpm_valido=valido, spo2_valido=valido,
            ))
            self._n_lectura += 1
        return lecturas, ppg


class PlacaCMAE:
    """Una conexión a la vez con la placa CMAE, real (BLE) o simulada."""

    SIM_PASO_S = 0.05

    def __init__(self) -> None:
        self.estado = Estado.DESCONECTADA
        self.detalle = ""
        self.numero: Optional[int] = None
        self.simulada = False
        self.tramas_ok = 0
        self.tramas_malas = 0
        self.cortes = 0

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._oyente: Optional[Callable[[Lectura], None]] = None
        self._conecto_alguna_vez = False
        self._ultimo_dato = 0.0
        self._errores_vistos = 0
        self._hold = False

        self._ultima: Optional[Lectura] = None
        self._ultima_en = 0.0
        self._ppg_t: deque[float] = deque()
        self._ppg_v: deque[float] = deque()
        self._ppg_en = 0.0

    # --------------------------------------------------------
    # Uso desde la interfaz
    # --------------------------------------------------------

    @property
    def activa(self) -> bool:
        """Hay un hilo trabajando: buscando, conectada, reconectando o cerrando."""
        return self.estado in (Estado.CONECTANDO, Estado.CONECTADA, Estado.RECONECTANDO, Estado.DESCONECTANDO)

    @property
    def disponible(self) -> bool:
        """Sirve para grabar: conectada, o reconectando después de un corte."""
        return self.estado in (Estado.CONECTADA, Estado.RECONECTANDO)

    @property
    def nombre(self) -> str:
        return NOMBRE_SIMULADA if self.simulada else nombre_ble(self.numero or 0)

    def conectar(self, numero: int, simulada: bool = False) -> None:
        if self.activa:
            return
        with self._lock:
            self._ultima = None
            self._ppg_t.clear()
            self._ppg_v.clear()
        self.numero = int(numero)
        self.simulada = bool(simulada)
        self.tramas_ok = 0
        self.tramas_malas = 0
        self.cortes = 0
        self._conecto_alguna_vez = False
        self._hold = False
        self.estado = Estado.CONECTANDO
        self.detalle = ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(self.numero, self.simulada), daemon=True)
        self._thread.start()

    def set_hold(self, hold: bool) -> None:
        """Fase de retención. Solo la usa la placa simulada, igual que el simulador del radar."""
        self._hold = hold

    def desconectar(self) -> None:
        if self.activa:
            self.estado = Estado.DESCONECTANDO
            self.detalle = ""
            self._stop.set()

    def escuchar(self, oyente: Callable[[Lectura], None]) -> None:
        """Registra quién recibe cada lectura (una sola sesión a la vez)."""
        with self._lock:
            self._oyente = oyente

    def dejar_de_escuchar(self, oyente: Callable[[Lectura], None]) -> None:
        with self._lock:
            if self._oyente == oyente:
                self._oyente = None

    def ultima(self) -> Optional[Lectura]:
        """Última lectura, o None si hace más de LATEST_MAX_AGE_S que no llega ninguna."""
        with self._lock:
            if self._ultima is None or time.monotonic() - self._ultima_en > LATEST_MAX_AGE_S:
                return None
            return self._ultima

    def ppg(self) -> tuple[np.ndarray, np.ndarray]:
        """Onda PPG reciente: (segundos respecto de la última muestra, siempre <= 0; valor IR)."""
        with self._lock:
            if not self._ppg_t or time.monotonic() - self._ppg_en > LATEST_MAX_AGE_S:
                return np.array([]), np.array([])
            t = np.array(self._ppg_t, dtype=float)
            v = np.array(self._ppg_v, dtype=float)
        return (t - t[-1]) / 1000.0, v

    # --------------------------------------------------------
    # Datos recibidos
    # --------------------------------------------------------

    def _on_frame(self, frame: bytes) -> None:
        lecturas, ppg = decode_frame(frame)
        self.tramas_ok += 1
        self._entregar(lecturas, ppg)

    def _entregar(self, lecturas: list[Lectura], ppg: list[tuple[float, float]]) -> None:
        """Deja los datos en memoria para la vista en vivo y pasa cada lectura al oyente."""
        now = time.monotonic()
        self._ultimo_dato = now
        with self._lock:
            if ppg:
                if self._ppg_t and ppg[0][0] + RESTART_JUMP_MS < self._ppg_t[-1]:
                    self._ppg_t.clear()
                    self._ppg_v.clear()
                for t_ms, ir in ppg:
                    self._ppg_t.append(t_ms)
                    self._ppg_v.append(ir)
                cutoff = self._ppg_t[-1] - PPG_KEEP_S * 1000.0
                while self._ppg_t[0] < cutoff:
                    self._ppg_t.popleft()
                    self._ppg_v.popleft()
                self._ppg_en = now
            if lecturas:
                self._ultima = lecturas[-1]
                self._ultima_en = now
            oyente = self._oyente
        if oyente is not None:
            for lectura in lecturas:
                try:
                    oyente(lectura)
                except Exception:
                    pass  # un error al guardar no debe cortar la conexión

    def _contar_errores(self, reassembler: FragmentReassembler) -> None:
        nuevos = reassembler.errors - self._errores_vistos
        if nuevos > 0:
            self.tramas_malas += nuevos
            self._errores_vistos = reassembler.errors

    # --------------------------------------------------------
    # Hilo de conexión
    # --------------------------------------------------------

    def _run(self, numero: int, simulada: bool) -> None:
        try:
            if simulada:
                self._simular()
            else:
                asyncio.run(self._ciclo(nombre_ble(numero)))
        except _Detenida:
            pass
        except Exception as exc:
            self.estado = Estado.ERROR
            self.detalle = str(exc) or type(exc).__name__
            return
        self.estado = Estado.DESCONECTADA
        self.detalle = ""

    def _simular(self) -> None:
        """Placa simulada: se 'conecta' en 1 s y entrega datos hasta que se presione Desconectar."""
        self.detalle = "Iniciando placa simulada..."
        if self._stop.wait(1.0):
            return
        simulador = SimuladorPlaca()
        self._conecto_alguna_vez = True
        self.estado = Estado.CONECTADA
        self.detalle = NOMBRE_SIMULADA
        while not self._stop.wait(self.SIM_PASO_S):
            lecturas, ppg = simulador.paso(self._hold)
            if lecturas or ppg:
                self.tramas_ok += 1
                self._entregar(lecturas, ppg)

    async def _ciclo(self, nombre: str) -> None:
        """Conecta; si la conexión se pierde después de haber conectado, reintenta sin fin."""
        while not self._stop.is_set():
            try:
                await self._sesion(nombre)
                return
            except _Detenida:
                raise
            except Exception as exc:
                if not self._conecto_alguna_vez:
                    raise
                if self.estado == Estado.CONECTADA:
                    self.cortes += 1
                if self._stop.is_set():
                    return
                self.estado = Estado.RECONECTANDO
                self.detalle = f"{exc}. Reintentando..."
                await self._until_stopped(asyncio.sleep(RECONNECT_DELAY_S))

    async def _until_stopped(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Espera coro, pero la cancela si el usuario presiona Desconectar."""
        task = asyncio.ensure_future(coro)
        while not task.done():
            if self._stop.is_set():
                task.cancel()
                raise _Detenida()
            await asyncio.sleep(0.1)
        return task.result()

    async def _buscar(self, nombre: str) -> Any:
        self.detalle = f"Buscando {nombre}..."
        devices = await self._until_stopped(BleakScanner.discover(timeout=SCAN_TIMEOUT_S, return_adv=True))
        for device, adv in devices.values():
            if (device.name or adv.local_name or "") == nombre:
                return device
        raise ConnectionError(f"No encontré la placa {nombre}")

    async def _conectar_con_reintentos(self, device: Any, nombre: str) -> BleakClient:
        last_exc: Optional[Exception] = None
        for intento in range(1, CONNECT_RETRIES + 1):
            self.detalle = f"Conectando a {nombre} (intento {intento}/{CONNECT_RETRIES})..."
            client = BleakClient(device, timeout=CONNECT_TIMEOUT_S)
            try:
                await self._until_stopped(client.connect())
                return client
            except _Detenida:
                raise
            except Exception as exc:
                last_exc = exc
                await self._until_stopped(asyncio.sleep(RETRY_DELAY_S))
        raise last_exc or ConnectionError(f"No pude conectar a {nombre}")

    async def _sesion(self, nombre: str) -> None:
        """Una conexión completa. Vuelve solo si el usuario pide desconectar; si se corta, lanza error."""
        device = await self._buscar(nombre)
        client = await self._conectar_con_reintentos(device, nombre)
        reassembler = FragmentReassembler()
        self._errores_vistos = 0

        def on_notify(_sender: Any, data: bytearray) -> None:
            frame = reassembler.feed(bytes(data))
            if frame is not None:
                self._on_frame(frame)
            self._contar_errores(reassembler)

        try:
            await client.start_notify(TX_CHAR_UUID, on_notify)
            await client.write_gatt_char(RX_CHAR_UUID, b"START", response=False)
            if not client.is_connected:
                raise ConnectionError("La placa se desconectó al iniciar la transmisión")
            self._conecto_alguna_vez = True
            self._ultimo_dato = time.monotonic()
            self.estado = Estado.CONECTADA
            self.detalle = nombre
            while not self._stop.is_set():
                await asyncio.sleep(0.1)
                reassembler.cleanup_old()
                self._contar_errores(reassembler)
                if not client.is_connected:
                    raise ConnectionError("Se perdió la conexión BLE con la placa")
                if time.monotonic() - self._ultimo_dato > STALL_TIMEOUT_S:
                    raise ConnectionError(f"La placa no envió datos en {STALL_TIMEOUT_S:.0f} s")
        finally:
            try:
                if client.is_connected:
                    await client.write_gatt_char(RX_CHAR_UUID, b"STOP", response=False)
                    await client.stop_notify(TX_CHAR_UUID)
                    await client.disconnect()
            except Exception:
                pass
