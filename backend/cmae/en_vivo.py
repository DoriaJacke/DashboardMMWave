"""
Prepara los datos de la placa para mostrarlos en vivo.

Copiado de CMAE_RECEPTOR_PORTABLE/dashboard-cmae/backend/en_vivo.py. Único
cambio: ProcesadorVivo acepta la lista de series que se guardan y envían.

Recibe cada trama, la convierte en "series" (una lista de puntos tiempo/valor
por cada curva que se dibuja) y las deja en dos lugares:

  - pendientes: lo nuevo, que se envía a la pantalla unas 30 veces por segundo;
  - historia:   los últimos minutos, para llenar los gráficos cuando la
                pantalla se abre o se recarga.

También lleva el estado de cada sensor (si llega, a qué ritmo), las banderas
(dedo puesto, electrodos conectados, señal GPS) y cuántas muestras se pierden.

Los nombres de las series son los mismos del dashboard original
(receivers/cmae_selective_dashboard.py) y de las columnas de los CSV.
"""
from __future__ import annotations

import math
import struct
import threading
import time
from array import array
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

from . import protocolo as p
from .pulso_ecg import DetectorPulsoECG


@dataclass(frozen=True)
class Serie:
    clave: str
    capacidad: int                 # puntos de historia que se guardan
    min_intervalo_ms: float = 0.0  # no enviar puntos más seguido que esto (señales lentas)


# El orden define el número de cada serie en el envío binario; la pantalla
# recibe este catálogo al conectarse, así que se puede cambiar sin tocarla.
SERIES: List[Serie] = [
    # ECG (600 Hz nominales): 30 s
    Serie("ecg_filtered_final_uV", 20480),
    # PPG crudo (~105 Hz)
    Serie("ppg_red", 4096),
    Serie("ppg_ir", 4096),
    # Oximetría (~7 Hz)
    Serie("spo2", 4096),
    Serie("bpm_float", 4096),
    # TEMPORAL: pulso calculado en el dashboard desde el ECG crudo (backend/pulso_ecg.py)
    Serie("ecg_bpm", 4096),
    # IMU (~64 Hz por BLE)
    Serie("ax_g", 4096),
    Serie("ay_g", 4096),
    Serie("az_g", 4096),
    Serie("gx_dps", 4096),
    Serie("gy_dps", 4096),
    Serie("gz_dps", 4096),
    # Orientación
    Serie("pitch_x_deg", 4096),
    Serie("roll_y_deg", 4096),
    Serie("yaw_z_deg", 4096),
    Serie("accel_pitch_x_deg", 4096),   # estas tres solo llegan por UART
    Serie("accel_yaw_z_deg", 4096),
    Serie("mag_roll_y_deg", 4096),
    # Temperaturas (cambian lento: como mucho un punto por segundo)
    Serie("bme680_temperature_c", 4096, 900.0),
    Serie("ds18b20_temperature_c_avg", 4096, 900.0),
    Serie("scd40_temperature_c", 4096, 900.0),
    Serie("sdp810_temperature_c", 4096, 1000.0),
    Serie("icm42670p_temperature_c", 4096, 1000.0),
    Serie("pcba_temperature_mean_c", 4096, 1000.0),
    # Alturas
    Serie("bme680_altitude_m", 4096),
    Serie("gps_height_msl_m", 4096),
    Serie("gps_alt_ref_m", 4096),
    # Ambiente
    Serie("bme680_humidity_pct", 4096),
    Serie("scd40_humidity_pct", 4096),
    Serie("co2_ppm", 4096),
    Serie("gas_kohms", 4096),
    # Presiones
    Serie("pressure_hpa", 4096),
    Serie("differential_pressure_pa", 16384, 20.0),
    # Calidad GPS
    Serie("gps_hacc_m", 4096),
    Serie("gps_vacc_m", 4096),
    Serie("gps_pdop", 4096),
    Serie("gps_num_sv", 4096),
    Serie("gps_ground_speed_kmh", 4096),
    # Posición GPS promediada cada 5 s (metros respecto del primer punto)
    Serie("gps_east_m", 1024),
    Serie("gps_north_m", 1024),
]
INDICE: Dict[str, int] = {s.clave: i for i, s in enumerate(SERIES)}

# tipo de paquete -> (sensor, ¿sus muestras cuentan para el ritmo del sensor?)
SENSOR_DE_FUENTE: Dict[int, Tuple[str, bool]] = {
    p.SRC_SPI_ADS1220_ECG: ("ads1220", True),
    p.SRC_BLE_BLOCK_ADS1220_ECG: ("ads1220", True),
    p.SRC_I2C1_MAX30102_RAW: ("max30102", True),
    p.SRC_BLE_BLOCK_MAX30102_RAW: ("max30102", True),
    p.SRC_I2C1_MAX30102_RESULT: ("max30102", False),
    p.SRC_I2C0_ICM42670P: ("icm42670p", True),
    p.SRC_BLE_BLOCK_ICM42670P: ("icm42670p", True),
    p.SRC_I2C0_ORIENTATION: ("orientacion", True),
    p.SRC_BLE_BLOCK_ORIENTATION: ("orientacion", True),
    p.SRC_I2C0_QMC5883P: ("qmc5883p", True),
    p.SRC_I2C0_SDP810: ("sdp810", True),
    p.SRC_I2C1_BME680: ("bme680", True),
    p.SRC_I2C1_SCD40: ("scd40", True),
    p.SRC_ONEWIRE_DS18B20: ("ds18b20", True),
    p.SRC_GPS_MAXM10S_PVT: ("gps", True),
    p.SRC_GPS_MAXM10S_POS_AVG: ("gps", False),
    p.SRC_GPS_MAXM10S_ALT_REF: ("gps", False),
}

NOMBRE_BLOQUE = {
    p.SRC_BLE_BLOCK_ADS1220_ECG: "ecg",
    p.SRC_BLE_BLOCK_MAX30102_RAW: "ppg",
    p.SRC_BLE_BLOCK_ICM42670P: "imu",
    p.SRC_BLE_BLOCK_ORIENTATION: "orientacion",
}

FUENTES_PCBA = ("scd40_temperature_c", "sdp810_temperature_c", "icm42670p_temperature_c")
EDAD_MAX_PCBA_MS = 15000.0      # igual que el dashboard original
VENTANA_POSICION_MS = 5000.0    # promedio de posición cada 5 s
SALTO_REINICIO_MS = 1000.0      # si el tiempo de la placa retrocede más que esto, se reinició
RADIO_TIERRA_M = 6371000.0

LOTE = 1    # puntos nuevos: se agregan a lo que hay en pantalla
FOTO = 2    # historia completa: reemplaza lo que hay en pantalla


def _finito(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def empaquetar(tipo: int, bloques: List[Tuple[int, array, array]]) -> bytes:
    """
    Arma el mensaje binario para la pantalla. Todo queda alineado a 8 bytes para
    que el navegador pueda leerlo sin copiar:

        u8 versión | u8 tipo | u16 cantidad de series | u32 reservado
        por cada serie:
            u16 número de serie | u16 reservado | u32 n
            n tiempos (float64, ms de la placa) | n valores (float32) | relleno
    """
    partes = [struct.pack("<BBHI", 1, tipo, len(bloques), 0)]
    for indice, tiempos, valores in bloques:
        n = len(tiempos)
        partes.append(struct.pack("<HHI", indice, 0, n))
        partes.append(tiempos.tobytes())
        partes.append(valores.tobytes())
        if n & 1:
            partes.append(b"\x00\x00\x00\x00")
    return b"".join(partes)


class ProcesadorVivo:
    def __init__(self, claves: Optional[List[str]] = None) -> None:
        """
        claves: series que se guardan y se envían a la pantalla (por defecto, todas).
        El dashboard del radar solo muestra algunas: así no viaja lo que no se dibuja.
        """
        self._lock = threading.Lock()
        self._activas = None if claves is None else {INDICE[k] for k in claves}
        self.reiniciar()

    # --------------------------------------------------------
    # Inicio de una conexión
    # --------------------------------------------------------

    def reiniciar(self) -> None:
        """Deja todo en blanco. Se llama al empezar una conexión nueva."""
        with self._lock:
            self._borrar_series()
            self._banderas: Dict[str, Any] = {}
            self._gps: Dict[str, Any] = {}
            self._posicion: Dict[str, Any] = {}
            self._sensores: Dict[str, Dict[str, float]] = {}
            self._perdidas: Dict[str, List[int]] = {}
            self._tramas = 0
            self._bytes = 0
            self._ritmo_tramas = 0.0
            self._ritmo_bytes = 0.0
            self._marca_ritmo = (time.monotonic(), 0, 0)
        # Lo que sigue solo lo toca el hilo que recibe datos.
        self._ult_secuencia: Dict[str, int] = {}
        self._reiniciar_calculos()

    def _borrar_series(self) -> None:
        self._hist_t: List[Deque[float]] = [deque(maxlen=s.capacidad) for s in SERIES]
        self._hist_v: List[Deque[float]] = [deque(maxlen=s.capacidad) for s in SERIES]
        self._pend_t: List[array] = [array("d") for _ in SERIES]
        self._pend_v: List[array] = [array("f") for _ in SERIES]
        self._ult_t: List[Optional[float]] = [None] * len(SERIES)
        self._reemplazar = True

    def _reiniciar_calculos(self) -> None:
        self._ult_lenta: Dict[int, float] = {}
        self._temp: Dict[str, Tuple[float, float]] = {}
        self._pos_inicio_ms: Optional[float] = None
        self._pos_puntos: List[Tuple[float, float, float, float, int, int]] = []
        self._pos_origen: Optional[Tuple[float, float]] = None
        self._pos_fuente: Optional[str] = None
        self._pos_avg_visto_ms: Optional[float] = None
        self._pulso_ecg = DetectorPulsoECG()

    # --------------------------------------------------------
    # Entrada: una trama completa
    # --------------------------------------------------------

    def procesar(self, trama: bytes, protocolo: str) -> None:
        muestras: List[Tuple[int, float, float]] = []
        banderas: Dict[str, Any] = {}
        vistos: List[Tuple[str, bool, int]] = []
        perdidas: List[Tuple[str, int, int]] = []

        for tipo, seq, t_ms, contenido in p.iter_paquetes(trama):
            try:
                tabla, filas = p.leer_paquete(0, tipo, seq, t_ms, contenido, protocolo)
                if tabla != "raw_passthrough" and filas:
                    self._interpretar(tabla, filas, muestras, banderas)
            except Exception:
                continue

            sensor = SENSOR_DE_FUENTE.get(tipo)
            if sensor is not None and tabla != "raw_passthrough":
                vistos.append((sensor[0], sensor[1], len(filas)))

            nombre = NOMBRE_BLOQUE.get(tipo) if protocolo == p.BLE else None
            if nombre is not None and len(contenido) >= p.TAM_CABECERA_BLOQUE:
                cab = p.leer_cabecera_bloque(contenido)
                anterior = self._ult_secuencia.get(nombre)
                hueco = 0
                if anterior is not None:
                    salto = int(cab["first_sequence"]) - anterior - 1
                    if 0 < salto < 1_000_000:
                        hueco = salto
                self._ult_secuencia[nombre] = int(cab["last_sequence"])
                perdidas.append((nombre, int(cab["sample_count"]), hueco))

        ahora = time.monotonic()
        with self._lock:
            self._tramas += 1
            self._bytes += len(trama)
            self._banderas.update(banderas)
            for sensor, cuenta, n in vistos:
                s = self._sensores.get(sensor)
                if s is None:
                    s = self._sensores[sensor] = {"ultimo": ahora, "muestras": 0, "marca": 0, "hz": 0.0}
                s["ultimo"] = ahora
                if cuenta:
                    s["muestras"] += n
            for nombre, recibidas, hueco in perdidas:
                c = self._perdidas.setdefault(nombre, [0, 0])
                c[0] += recibidas
                c[1] += hueco
            self._agregar(muestras)

    def _agregar(self, muestras: List[Tuple[int, float, float]]) -> None:
        """Guarda las muestras en pendientes e historia. Se llama con el candado tomado."""
        for i, t, v in muestras:
            if self._activas is not None and i not in self._activas:
                continue
            anterior = self._ult_t[i]
            if anterior is not None:
                if t + SALTO_REINICIO_MS < anterior:
                    # La placa se reinició (o el archivo volvió a empezar): se parte de cero.
                    self._borrar_series()
                    self._ult_secuencia = {}
                    self._reiniciar_calculos()
                elif t <= anterior:
                    # La placa marca el tiempo en milisegundos enteros y a veces dos
                    # muestras seguidas quedan con el mismo. Los gráficos necesitan
                    # tiempos crecientes: se corre medio milisegundo, solo para dibujar.
                    t = anterior + 0.5
            self._ult_t[i] = t
            self._hist_t[i].append(t)
            self._hist_v[i].append(v)
            self._pend_t[i].append(t)
            self._pend_v[i].append(v)

    # --------------------------------------------------------
    # De filas (como en los CSV) a series para dibujar
    # --------------------------------------------------------

    def _emitir(self, clave: str, t_ms: float, valor: Any, out: List[Tuple[int, float, float]]) -> None:
        if not _finito(valor):
            return
        out.append((INDICE[clave], float(t_ms), float(valor)))

    def _lenta(self, clave: str, t_ms: float) -> bool:
        """True si ya pasó el intervalo mínimo de una serie lenta (se revisa antes de calcular)."""
        i = INDICE[clave]
        anterior = self._ult_lenta.get(i)
        if anterior is not None and 0 <= t_ms - anterior < SERIES[i].min_intervalo_ms:
            return False
        self._ult_lenta[i] = t_ms
        return True

    def _temperatura(self, clave: str, t_ms: float, valor: Any, out: List[Tuple[int, float, float]]) -> None:
        if not _finito(valor):
            return
        self._temp[clave] = (float(t_ms), float(valor))
        if self._lenta(clave, t_ms):
            self._emitir(clave, t_ms, valor, out)
        # Estimación de la temperatura de la placa: promedio de los sensores
        # soldados en ella que tengan una lectura reciente.
        if self._lenta("pcba_temperature_mean_c", t_ms):
            valores = [
                v for k in FUENTES_PCBA
                for (tv, v) in [self._temp.get(k, (None, None))]
                if tv is not None and max(0.0, t_ms - tv) <= EDAD_MAX_PCBA_MS
            ]
            if valores:
                self._emitir("pcba_temperature_mean_c", t_ms, sum(valores) / len(valores), out)

    def _interpretar(self, tabla: str, filas: List[p.Fila], out: List[Tuple[int, float, float]],
                     banderas: Dict[str, Any]) -> None:
        ultima = filas[-1]

        if tabla == "ecg_block":
            i = INDICE["ecg_filtered_final_uV"]
            for f in filas:
                v = f["filtered_input_uV"]
                if math.isfinite(v):
                    out.append((i, f["t_ms"], v))
                self._pulso_desde_ecg(f, out)
            banderas["electrodos_ok"] = ultima["electrodes_ok"]
            banderas["ecg_pulso_valido"] = self._pulso_ecg.valido

        elif tabla in ("ads1220_ecg", "ecg_passthrough"):
            self._emitir("ecg_filtered_final_uV", ultima["t_ms"], ultima["ecg_lp40_input_est_uV"], out)
            for f in filas:
                self._pulso_desde_ecg(f, out)
            banderas["electrodos_ok"] = ultima["electrodes_ok"]
            banderas["ecg_pulso_valido"] = self._pulso_ecg.valido

        elif tabla in ("ppg_block", "max30102_raw"):
            i_red, i_ir = INDICE["ppg_red"], INDICE["ppg_ir"]
            for f in filas:
                out.append((i_red, f["t_ms"], float(f["red"])))
                out.append((i_ir, f["t_ms"], float(f["ir"])))
            banderas["dedo"] = ultima["finger_detected"]

        elif tabla in ("imu_block", "icm42670p"):
            claves = ("ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps")
            indices = [INDICE[k] for k in claves]
            for f in filas:
                t = f["t_ms"]
                for k, i in zip(claves, indices):
                    v = f[k]
                    if math.isfinite(v):
                        out.append((i, t, v))
                self._temperatura("icm42670p_temperature_c", t, f["icm42670p_temperature_c"], out)

        elif tabla in ("orientation_block", "orientation"):
            claves = ["pitch_x_deg", "roll_y_deg", "yaw_z_deg"]
            if tabla == "orientation":
                claves += ["accel_pitch_x_deg", "accel_yaw_z_deg", "mag_roll_y_deg"]
            indices = [INDICE[k] for k in claves]
            for f in filas:
                t = f["t_ms"]
                for k, i in zip(claves, indices):
                    v = f[k]
                    if math.isfinite(v):
                        out.append((i, t, v))
            banderas["mag_valido"] = ultima["mag_valid"]

        elif tabla == "max30102_result":
            f = ultima
            dedo = f["finger_detected"]
            banderas["dedo"] = dedo
            banderas["bpm_valido"] = bool(dedo and f["bpm_valid"])
            banderas["spo2_valido"] = bool(dedo and f["spo2_valid"])
            # Un valor no válido no es una lectura: sin dedo la placa envía 0 o NaN.
            if banderas["spo2_valido"]:
                self._emitir("spo2", f["t_ms"], f["spo2"], out)
            if banderas["bpm_valido"]:
                self._emitir("bpm_float", f["t_ms"], f["bpm_float"], out)

        elif tabla == "ds18b20":
            f = ultima
            banderas["ds18b20_conectado"] = f["connected"]
            banderas["ds18b20_valido"] = f["valid"]
            if f["connected"] and f["valid"]:
                if self._lenta("ds18b20_temperature_c_avg", f["t_ms"]):
                    self._emitir("ds18b20_temperature_c_avg", f["t_ms"], f["temperature_c_avg"], out)

        elif tabla == "bme680":
            f = ultima
            t = f["t_ms"]
            self._temperatura("bme680_temperature_c", t, f["bme680_temperature_c"], out)
            self._emitir("bme680_humidity_pct", t, f["humidity_pct"], out)
            self._emitir("pressure_hpa", t, f["pressure_hpa"], out)
            self._emitir("gas_kohms", t, f["gas_kohms"], out)
            self._emitir("bme680_altitude_m", t, f["altitude_m"], out)
            banderas["gas_valido"] = f["gas_valid"]

        elif tabla == "scd40":
            f = ultima
            t = f["t_ms"]
            banderas["scd40_listo"] = f["data_ready"]
            # Antes de la primera medición el sensor informa 0 ppm: eso no se dibuja.
            if f["data_ready"] or f["co2_ppm"] > 0:
                self._emitir("co2_ppm", t, f["co2_ppm"], out)
                self._temperatura("scd40_temperature_c", t, f["scd40_temperature_c"], out)
                self._emitir("scd40_humidity_pct", t, f["humidity_pct"], out)

        elif tabla == "sdp810":
            f = ultima
            t = f["t_ms"]
            if self._lenta("differential_pressure_pa", t):
                self._emitir("differential_pressure_pa", t, f["differential_pressure_pa"], out)
            self._temperatura("sdp810_temperature_c", t, f["sdp810_temperature_c"], out)

        elif tabla == "gps_pvt":
            self._gps_pvt(ultima, out, banderas)

        elif tabla == "gps_alt_ref":
            f = ultima
            banderas["gps_alt_ref_lista"] = f["ready"]
            # Sin referencia lista la placa envía 0 m, que no es una altura real.
            if f["ready"]:
                self._emitir("gps_alt_ref_m", f["t_ms"], f["altitude_msl_m"], out)

        elif tabla == "gps_pos_avg":
            f = ultima
            self._pos_avg_visto_ms = f["t_ms"]
            self._posicion_promedio(f["t_ms"], f["lat_avg_deg"], f["lon_avg_deg"], f["avg_hacc_m"],
                                    f["avg_pdop"], f["samples"], f["fill_pct"], "POS_AVG", out)

    def _pulso_desde_ecg(self, f: p.Fila, out: List[Tuple[int, float, float]]) -> None:
        """TEMPORAL: se usa raw24 porque el valor filtrado de la placa llega con la escala rota."""
        if not f.get("drdy_ok", True):
            return
        bpm = self._pulso_ecg.agregar(float(f["t_ms"]), int(f["raw24"]))
        if bpm is not None:
            self._emitir("ecg_bpm", f["t_ms"], bpm, out)

    def _gps_pvt(self, f: p.Fila, out: List[Tuple[int, float, float]], banderas: Dict[str, Any]) -> None:
        t = f["t_ms"]
        con_senal = bool(f["gnss_fix_ok"]) and f["fix_type"] >= 2
        banderas["gps_fix"] = f["fix_type"]
        banderas["gps_fix_ok"] = con_senal
        banderas["gps_calidad_ok"] = f["quality_ok"]
        banderas["gps_satelites"] = f["num_sv"]

        self._emitir("gps_num_sv", t, f["num_sv"], out)
        gps: Dict[str, Any] = {"satelites": f["num_sv"], "fix": f["fix_type"], "con_senal": con_senal}
        if con_senal:
            # Sin señal la placa envía valores de relleno (precisión de miles de km): no se dibujan.
            self._emitir("gps_height_msl_m", t, f["height_msl_m"], out)
            self._emitir("gps_hacc_m", t, f["hacc_m"], out)
            self._emitir("gps_vacc_m", t, f["vacc_m"], out)
            self._emitir("gps_pdop", t, f["pdop"], out)
            self._emitir("gps_ground_speed_kmh", t, f["ground_speed_kmh"], out)
            gps.update({
                "lat": f["lat_deg"], "lon": f["lon_deg"], "altura_m": f["height_msl_m"],
                "hacc_m": f["hacc_m"], "vacc_m": f["vacc_m"], "pdop": f["pdop"],
                "velocidad_kmh": f["ground_speed_kmh"],
                "utc": "%04d-%02d-%02d %02d:%02d:%02d" % (
                    f["year"], f["month"], f["day"], f["hour"], f["minute"], f["second"]),
            })
            # Por BLE la placa no envía POS_AVG. Si no llegó ninguno en los últimos
            # 10 s, la posición se promedia a partir de estas lecturas directas.
            sin_pos_avg = self._pos_avg_visto_ms is None or t - self._pos_avg_visto_ms > 10000.0
            if sin_pos_avg:
                self._posicion_promedio(t, f["lat_deg"], f["lon_deg"], f["hacc_m"], f["pdop"], 0, 0, "PVT", out)
        with self._lock:
            self._gps = gps

    def _posicion_promedio(self, t_ms: float, lat: float, lon: float, hacc: float, pdop: float,
                           muestras: int, llenado: int, fuente: str,
                           out: List[Tuple[int, float, float]]) -> None:
        """Junta las posiciones de 5 s y entrega un punto promedio, en metros desde el primero."""
        if not (_finito(lat) and _finito(lon)):
            return
        if fuente != self._pos_fuente:
            self._pos_fuente = fuente
            self._pos_puntos = []
            self._pos_inicio_ms = None
        if self._pos_inicio_ms is None:
            self._pos_inicio_ms = t_ms
        self._pos_puntos.append((lat, lon, hacc, pdop, int(muestras), int(llenado)))
        if t_ms - self._pos_inicio_ms < VENTANA_POSICION_MS:
            return

        puntos = self._pos_puntos
        self._pos_puntos = []
        self._pos_inicio_ms = t_ms
        n = len(puntos)
        lat_m = sum(q[0] for q in puntos) / n
        lon_m = sum(q[1] for q in puntos) / n
        if self._pos_origen is None:
            self._pos_origen = (lat_m, lon_m)
        lat0, lon0 = self._pos_origen
        norte = RADIO_TIERRA_M * math.radians(lat_m - lat0)
        este = RADIO_TIERRA_M * math.cos(math.radians(lat0)) * math.radians(lon_m - lon0)

        self._emitir("gps_east_m", t_ms, este, out)
        self._emitir("gps_north_m", t_ms, norte, out)
        posicion = {
            "fuente": fuente,
            "t_ms": t_ms,
            "lat": lat_m,
            "lon": lon_m,
            "este_m": este,
            "norte_m": norte,
            # Primer punto: con él la pantalla pasa el recorrido (este/norte) a lat/lon para el mapa.
            "lat0": lat0,
            "lon0": lon0,
            "hacc_m": sum(q[2] for q in puntos) / n,
            "pdop": sum(q[3] for q in puntos) / n,
            "eventos": n,
            "muestras_fw": puntos[-1][4],
            "llenado_fw": puntos[-1][5],
        }
        with self._lock:
            self._posicion = posicion

    # --------------------------------------------------------
    # Salida hacia la pantalla
    # --------------------------------------------------------

    def _foto(self) -> bytes:
        bloques = [
            (i, array("d", self._hist_t[i]), array("f", self._hist_v[i]))
            for i in range(len(SERIES)) if self._hist_t[i]
        ]
        return empaquetar(FOTO, bloques)

    def _vaciar_pendientes(self) -> Optional[bytes]:
        if self._reemplazar:
            self._reemplazar = False
            for i in range(len(SERIES)):
                if self._pend_t[i]:
                    self._pend_t[i] = array("d")
                    self._pend_v[i] = array("f")
            return self._foto()
        bloques = []
        for i in range(len(SERIES)):
            if self._pend_t[i]:
                bloques.append((i, self._pend_t[i], self._pend_v[i]))
                self._pend_t[i] = array("d")
                self._pend_v[i] = array("f")
        return empaquetar(LOTE, bloques) if bloques else None

    def drenar(self) -> Optional[bytes]:
        """Lo nuevo desde la última vez, listo para enviar. None si no hay nada."""
        with self._lock:
            return self._vaciar_pendientes()

    def drenar_y_foto(self) -> Tuple[Optional[bytes], bytes]:
        """
        Para cuando se abre una pantalla nueva: entrega lo pendiente (para las
        pantallas que ya estaban) y la historia completa (para la nueva), en un
        solo paso, así la nueva no pierde ni repite puntos.
        """
        with self._lock:
            return self._vaciar_pendientes(), self._foto()

    # --------------------------------------------------------
    # Estado para mostrar
    # --------------------------------------------------------

    def actualizar_ritmos(self) -> None:
        """Calcula tramas/s, bytes/s y muestras/s de cada sensor. Llamar ~1 vez por segundo."""
        ahora = time.monotonic()
        with self._lock:
            t0, tramas0, bytes0 = self._marca_ritmo
            dt = ahora - t0
            if dt < 0.2:
                return
            self._ritmo_tramas = (self._tramas - tramas0) / dt
            self._ritmo_bytes = (self._bytes - bytes0) / dt
            self._marca_ritmo = (ahora, self._tramas, self._bytes)
            for s in self._sensores.values():
                s["hz"] = (s["muestras"] - s["marca"]) / dt
                s["marca"] = s["muestras"]

    def estado(self) -> Dict[str, Any]:
        ahora = time.monotonic()
        with self._lock:
            recibidas = sum(c[0] for c in self._perdidas.values())
            perdidas = sum(c[1] for c in self._perdidas.values())
            return {
                "tramas": self._tramas,
                "bytes": self._bytes,
                "tramas_s": round(self._ritmo_tramas, 1),
                "bytes_s": round(self._ritmo_bytes),
                "sensores": {
                    k: {"edad_s": round(ahora - s["ultimo"], 2), "hz": round(s["hz"], 1)}
                    for k, s in self._sensores.items()
                },
                "perdidas": {k: {"recibidas": c[0], "perdidas": c[1]} for k, c in self._perdidas.items()},
                "perdida_pct": round(100.0 * perdidas / (recibidas + perdidas), 2) if recibidas else None,
                "banderas": dict(self._banderas),
                "gps": dict(self._gps),
                "posicion": dict(self._posicion),
            }
