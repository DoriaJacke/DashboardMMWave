# ============================================================
# PLACA CMAE EN EL DASHBOARD DEL RADAR
#
# Conexión con la placa (Bluetooth, USB o simulada) y envío en vivo
# de sus gráficos a la pantalla. Es independiente de la adquisición
# del radar: la placa se conecta y desconecta por su cuenta.
#
#   GET  /api/cmae/estado        conexión, sensores y banderas
#   GET  /api/cmae/puertos       puertos COM (marca el de la placa)
#   POST /api/cmae/ble/buscar    placas CMAE cercanas por Bluetooth
#   POST /api/cmae/conectar      {origen: ble|uart|simulada, numero, puerto, formato}
#   POST /api/cmae/desconectar
#   GET/PUT /api/cmae/config     última forma de conexión usada
#   WS   /ws/cmae                catálogo y estado (JSON) + curvas (binario)
#
# El formato binario es el de backend/cmae/en_vivo.py (empaquetar).
#
# Mientras hay una adquisición del radar en curso, las muestras también
# pasan a su escala de tiempo y se graban con su fase (sincronia.py).
# ============================================================

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple, Union

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .conexion import Placa, buscar_placas, listar_puertos
from .en_vivo import INDICE, SERIES, ProcesadorVivo
from .sincronia import SENALES, RegistroCMAE, RelojPlaca

# Series que muestra el dashboard del radar. Las demás que entrega la placa
# (IMU, GPS, temperaturas...) se descartan antes de guardarlas o enviarlas.
SERIES_RADAR = [
    "ecg_filtered_final_uV",   # ECG filtrado (ADS1220)
    "ppg_ir",                  # pulsómetro: onda de pulso infrarroja (MAX30102, ~100 por segundo)
    "spo2",                    # oxímetro (MAX30102)
    "bpm_float",               # pulso del oxímetro (MAX30102)
    "ecg_bpm",                 # pulso calculado desde el ECG (TEMPORAL, ver pulso_ecg.py)
    "pressure_hpa",            # presión barométrica (BME680)
    "differential_pressure_pa",  # presión diferencial (SDP810): respiración, ~9 por segundo
]
# Sensores cuyo estado (llega / dejó de llegar) se informa a la pantalla.
SENSORES_RADAR = ("ads1220", "max30102", "bme680", "sdp810")

PERIODO_DATOS_S = 0.025    # lotes de curvas, unas 30 veces por segundo
PERIODO_ESTADO_S = 0.5
MAX_COLA = 300             # mensajes en espera antes de dar por atrasada a una pantalla

Mensaje = Union[bytes, str]


class PedidoConexion(BaseModel):
    origen: Literal["ble", "uart", "simulada"]
    numero: Optional[int] = Field(default=None, ge=1, le=999)
    puerto: Optional[str] = None
    formato: Literal["BLE", "UART"] = "BLE"


def _sin_nan(valor: Any) -> Any:
    """JSON no admite NaN ni infinito: la placa los usa para 'sin dato' y se cambian por null."""
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, dict):
        return {k: _sin_nan(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_sin_nan(v) for v in valor]
    return valor


# número de serie (en_vivo.SERIES) -> clave corta de sincronia.SENALES
_CLAVE_DE_SERIE = {INDICE[serie]: clave for clave, (serie, _csv) in SENALES.items()}


class _ProcesadorRadar(ProcesadorVivo):
    """ProcesadorVivo que además deja a mano las muestras de cada trama (para sincronizarlas)."""

    def __init__(self, claves: List[str]) -> None:
        self.nuevas: List[Tuple[int, float, float]] = []
        super().__init__(claves)

    def _agregar(self, muestras: List[Tuple[int, float, float]]) -> None:
        super()._agregar(muestras)
        self.nuevas.extend(muestras)

    def tomar_nuevas(self) -> List[Tuple[int, float, float]]:
        with self._lock:
            nuevas, self.nuevas = self.nuevas, []
        return nuevas


class _Pantalla:
    """Una pestaña conectada a /ws/cmae."""

    def __init__(self) -> None:
        self.cola: "asyncio.Queue[Mensaje]" = asyncio.Queue()
        self.atrasada = False


class ServicioCMAE:
    def __init__(self, carpeta_datos: Path) -> None:
        self.archivo_config = Path(carpeta_datos) / ".cmae_config.json"
        self.vivo = _ProcesadorRadar(SERIES_RADAR)
        self.reloj = RelojPlaca()
        self.placa = Placa(self._al_recibir, al_empezar=self._al_empezar)
        # Adquisición del radar en curso (la fija backend/main.py) y su registro de la placa.
        self.sesion_radar: Callable[[], Any] = lambda: None
        self._registros: Dict[int, RegistroCMAE] = {}
        self._pantallas: Set[_Pantalla] = set()
        self._tarea: Optional[asyncio.Task] = None
        self.router = APIRouter()
        self._rutas()

    # --------------------------------------------------------
    # Datos que llegan de la placa
    # --------------------------------------------------------

    def _al_empezar(self) -> None:
        self.vivo.reiniciar()
        self.reloj.reiniciar()

    def _al_recibir(self, trama: bytes, protocolo: str) -> None:
        llegada = time.monotonic()
        self.vivo.procesar(trama, protocolo)
        nuevas = self.vivo.tomar_nuevas()
        if not nuevas:
            return
        self.reloj.observar(max(t for _i, t, _v in nuevas), llegada)
        sesion = self.sesion_radar()
        if sesion is None or not sesion.running:
            return
        muestras = [(_CLAVE_DE_SERIE[i], t, v) for i, t, v in nuevas if i in _CLAVE_DE_SERIE]
        if muestras:
            self.registro(sesion, crear=True).agregar(muestras, self.reloj)

    def registro(self, sesion: Any, crear: bool = False) -> Optional[RegistroCMAE]:
        """Registro de la placa de una adquisición (se crea con su primera muestra)."""
        if sesion is None:
            return None
        reg = self._registros.get(id(sesion))
        if reg is not None and reg.sesion is not sesion:
            reg = None   # id() reutilizado por una sesión nueva
        if reg is None and crear:
            # Solo se conserva el de la adquisición actual: las anteriores ya están en su CSV.
            for viejo in self._registros.values():
                viejo.cerrar()
            reg = RegistroCMAE(sesion)
            self._registros = {id(sesion): reg}
        return reg

    def datos_sesion(self, sesion: Any, cursor: Optional[Dict[str, int]] = None) -> Tuple[Dict[str, list], Dict[str, int]]:
        """Muestras de la placa de esa adquisición desde `cursor`, en su escala de tiempo."""
        reg = self.registro(sesion)
        if reg is None:
            return {}, cursor or {}
        return reg.desde(cursor)

    def resumen_sesion(self, sesion: Any) -> Optional[Dict[str, Any]]:
        reg = self.registro(sesion)
        return reg.resumen() if reg is not None else None

    # --------------------------------------------------------
    # Ciclo de vida (lo llama el lifespan de backend/main.py)
    # --------------------------------------------------------

    async def iniciar(self) -> None:
        self._tarea = asyncio.create_task(self._difundir())

    async def cerrar(self) -> None:
        """Le avisa a la placa (STOP por Bluetooth) antes de cerrar el servidor."""
        if self._tarea is not None:
            self._tarea.cancel()
        self.placa.desconectar()
        await asyncio.to_thread(self.placa.esperar_cierre, 6.0)
        for reg in self._registros.values():
            reg.cerrar()

    # --------------------------------------------------------
    # Estado y envío
    # --------------------------------------------------------

    def estado(self) -> Dict[str, Any]:
        v = self.vivo.estado()
        return _sin_nan({
            "type": "estado",
            "conexion": self.placa.resumen(),
            "flujo": {k: v[k] for k in ("tramas", "tramas_s", "bytes_s", "perdida_pct")},
            "sensores": {k: s for k, s in v["sensores"].items() if k in SENSORES_RADAR},
            "banderas": v["banderas"],
        })

    def _catalogo(self) -> str:
        indices = {s.clave: i for i, s in enumerate(SERIES)}
        return json.dumps({
            "type": "catalogo",
            "series": [{"id": indices[k], "clave": k, "capacidad": SERIES[indices[k]].capacidad}
                       for k in SERIES_RADAR],
        })

    def _a_todas(self, mensaje: Mensaje) -> None:
        for pantalla in self._pantallas:
            if pantalla.atrasada:
                continue
            if pantalla.cola.qsize() > MAX_COLA:
                pantalla.atrasada = True    # se le manda la historia de nuevo cuando se ponga al día
                continue
            pantalla.cola.put_nowait(mensaje)

    async def _difundir(self) -> None:
        ultimo_estado = 0.0
        ultimo_ritmo = 0.0
        while True:
            await asyncio.sleep(PERIODO_DATOS_S)
            lote = self.vivo.drenar()
            if lote is not None:
                self._a_todas(lote)
            ahora = time.monotonic()
            if ahora - ultimo_ritmo >= 1.0:
                ultimo_ritmo = ahora
                self.vivo.actualizar_ritmos()
            if ahora - ultimo_estado >= PERIODO_ESTADO_S:
                ultimo_estado = ahora
                # El CSV de la placa se cierra cuando termina la adquisición, aunque no lleguen más datos.
                for reg in self._registros.values():
                    if not reg.cerrado and reg.sesion.status.terminado:
                        reg.cerrar()
                self._a_todas(json.dumps(self.estado()))

    # --------------------------------------------------------
    # Configuración recordada (número de placa, puerto)
    # --------------------------------------------------------

    def leer_config(self) -> Dict[str, Any]:
        try:
            config = json.loads(self.archivo_config.read_text(encoding="utf-8"))
            return config if isinstance(config, dict) else {}
        except (OSError, ValueError):
            return {}

    def guardar_config(self, cambios: Dict[str, Any]) -> Dict[str, Any]:
        config = self.leer_config()
        config.update({k: v for k, v in cambios.items() if k in ("origen", "numero", "puerto")})
        try:
            self.archivo_config.parent.mkdir(parents=True, exist_ok=True)
            self.archivo_config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass    # no poder recordarla no impide conectarse
        return config

    # --------------------------------------------------------
    # Rutas
    # --------------------------------------------------------

    def _rutas(self) -> None:
        r = self.router
        placa = self.placa

        @r.get("/api/cmae/estado")
        def get_estado() -> Dict[str, Any]:
            return self.estado()

        @r.get("/api/cmae/config")
        def get_config() -> Dict[str, Any]:
            return self.leer_config()

        @r.put("/api/cmae/config")
        def put_config(cambios: Dict[str, Any]) -> Dict[str, Any]:
            return self.guardar_config(cambios)

        @r.get("/api/cmae/puertos")
        def get_puertos() -> List[Dict[str, Any]]:
            return listar_puertos()

        @r.post("/api/cmae/ble/buscar")
        async def post_buscar() -> List[Dict[str, Any]]:
            if placa.activa and placa.origen == "ble":
                raise HTTPException(409, "Ya hay una conexión Bluetooth en curso.")
            try:
                return await buscar_placas()
            except ImportError:
                raise HTTPException(503, "Falta instalar bleak (pip install -r requirements.txt).")
            except Exception as exc:
                raise HTTPException(503, str(exc) or "No pude buscar por Bluetooth.")

        @r.post("/api/cmae/conectar")
        def post_conectar(pedido: PedidoConexion) -> Dict[str, Any]:
            if placa.activa:
                raise HTTPException(409, "La placa ya está conectada. Desconéctala primero.")
            try:
                if pedido.origen == "ble":
                    if pedido.numero is None:
                        raise HTTPException(400, "Falta el número de la placa.")
                    placa.conectar_ble(pedido.numero)
                    self.guardar_config({"origen": "ble", "numero": pedido.numero})
                elif pedido.origen == "uart":
                    if not pedido.puerto:
                        raise HTTPException(400, "Falta elegir el puerto COM.")
                    placa.conectar_uart(pedido.puerto, pedido.numero)
                    self.guardar_config({"origen": "uart", "puerto": pedido.puerto})
                else:
                    placa.simular(pedido.formato)
                    self.guardar_config({"origen": "simulada"})
            except RuntimeError as exc:
                raise HTTPException(409, str(exc))
            return self.estado()

        @r.post("/api/cmae/desconectar")
        def post_desconectar() -> Dict[str, Any]:
            placa.desconectar()
            return self.estado()

        @r.websocket("/ws/cmae")
        async def ws_cmae(ws: WebSocket) -> None:
            await ws.accept()
            pantalla = _Pantalla()

            def poner_al_dia() -> None:
                # Lo pendiente va a las pantallas que ya estaban; esta recibe la historia completa.
                lote, foto = self.vivo.drenar_y_foto()
                if lote is not None:
                    self._a_todas(lote)
                pantalla.cola.put_nowait(json.dumps(self.estado()))
                pantalla.cola.put_nowait(foto)
                pantalla.atrasada = False

            pantalla.cola.put_nowait(self._catalogo())
            poner_al_dia()
            self._pantallas.add(pantalla)
            try:
                while True:
                    mensaje = await pantalla.cola.get()
                    if isinstance(mensaje, bytes):
                        await ws.send_bytes(mensaje)
                    else:
                        await ws.send_text(mensaje)
                    if pantalla.atrasada and pantalla.cola.empty():
                        poner_al_dia()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
            finally:
                self._pantallas.discard(pantalla)
