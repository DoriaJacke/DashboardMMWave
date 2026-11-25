"""
Placa simulada (sin hardware).

Genera tramas con el mismo formato que la placa real, a los mismos ritmos que
se midieron en una captura real (ECG ~586 Hz, PPG ~105 Hz, IMU ~64 Hz, etc.).
Como son tramas de verdad, pasan por el mismo lector que los datos reales: sirve
para probar toda la app, y para mostrarla, sin tener la placa conectada.

Los valores son inventados. No usar una grabación simulada como dato real.
"""
from __future__ import annotations

import math
import random
import struct
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Tuple

from . import protocolo as p

T_ARRANQUE_MS = 20000.0     # la placa real empieza a enviar unos 20 s después de encender
LAT0, LON0 = -33.4489, -70.6693


# ==================================================
# Armado de tramas (el camino inverso al de protocolo.py)
# ==================================================

def armar_paquete(tipo: int, seq: int, t_ms: float, contenido: bytes) -> bytes:
    return struct.pack("<HIIH", tipo, seq & 0xFFFFFFFF, int(t_ms) & 0xFFFFFFFF, len(contenido)) + contenido


def armar_trama(reloj_ms: float, paquetes: List[bytes]) -> bytes:
    cuerpo = p.MAGIC + struct.pack("<BBI", p.VERSION_TRAMA, len(paquetes), int(reloj_ms) & 0xFFFFFFFF) + b"".join(paquetes)
    return cuerpo + struct.pack("<H", p.crc16(cuerpo))


def armar_bloque(tipo_original: int, ritmo_hz: int, t0_ms: float, t1_ms: float,
                 seq0: int, muestras: List[bytes]) -> bytes:
    paso = len(muestras[0])
    cab = struct.pack(
        "<HHHHIIIIB", tipo_original, len(muestras), paso, ritmo_hz,
        int(t0_ms), int(t1_ms), seq0, seq0 + len(muestras) - 1, 0,
    )
    return cab + b"".join(muestras)


def _campana(x: float, centro: float, ancho: float) -> float:
    return math.exp(-((x - centro) / ancho) ** 2)


class SimuladorPlaca:
    """Entrega las tramas que corresponden al tiempo transcurrido desde la última llamada."""

    def __init__(self, formato: str = p.BLE, reloj: Callable[[], float] = time.monotonic) -> None:
        self.formato = formato
        self._reloj = reloj     # se puede cambiar por un reloj falso para las pruebas
        self._inicio = reloj()
        self._generadas: Dict[str, int] = {}
        self._seq: Dict[int, int] = {}
        self._bloques: Dict[str, List[Tuple[float, bytes]]] = {}
        self._latidos: List[Tuple[float, float]] = [(0.0, 60.0 / 72.0)]   # (inicio en s, duración)
        self._bpm = 72.0
        self._spo2 = 97.6
        self._ruido = random.Random(7)

    # ---------------- señales ----------------

    def _fase_latido(self, t: float) -> float:
        """Avance dentro del latido actual, entre 0 y 1."""
        while self._latidos[-1][0] + self._latidos[-1][1] <= t:
            inicio, dur = self._latidos[-1]
            objetivo = 60.0 / (72.0 + 6.0 * math.sin(inicio / 17.0))
            self._latidos.append((inicio + dur, objetivo + self._ruido.gauss(0, 0.012)))
            if len(self._latidos) > 64:
                del self._latidos[:32]
        for inicio, dur in reversed(self._latidos):
            if inicio <= t:
                return min((t - inicio) / dur, 0.999)
        return 0.0

    def _ecg_uv(self, t: float) -> float:
        f = self._fase_latido(t)
        onda = (110.0 * _campana(f, 0.18, 0.025) - 80.0 * _campana(f, 0.262, 0.010)
                + 1000.0 * _campana(f, 0.280, 0.011) - 180.0 * _campana(f, 0.300, 0.012)
                + 260.0 * _campana(f, 0.52, 0.045))
        return onda + 25.0 * math.sin(2 * math.pi * 0.22 * t) + self._ruido.gauss(0, 6.0)

    def _pulso(self, t: float) -> float:
        f = (self._fase_latido(t) - 0.30) % 1.0   # el pulso llega al dedo después del latido
        return _campana(f, 0.16, 0.07) + 0.35 * _campana(f, 0.44, 0.09)

    @staticmethod
    def _orientacion(t: float) -> Tuple[float, float, float]:
        pitch = 18.0 * math.sin(0.35 * t)
        roll = 12.0 * math.sin(0.27 * t + 1.0)
        yaw = 40.0 * math.sin(0.11 * t)
        return pitch, roll, yaw

    # ---------------- envío ----------------

    def _siguiente_seq(self, tipo: int) -> int:
        n = self._seq.get(tipo, 0)
        self._seq[tipo] = n + 1
        return n

    def _pendientes(self, nombre: str, ritmo_hz: float, ahora: float) -> List[float]:
        """Tiempos (en s) de las muestras de esta señal que tocan desde la última llamada."""
        n = self._generadas.get(nombre, 0)
        tiempos = []
        while n / ritmo_hz <= ahora:
            tiempos.append(n / ritmo_hz)
            n += 1
        self._generadas[nombre] = n
        return tiempos

    def _suelto(self, salida: List[bytes], tipo: int, t: float, contenido: bytes) -> None:
        t_ms = T_ARRANQUE_MS + t * 1000.0
        salida.append(armar_trama(t_ms, [armar_paquete(tipo, self._siguiente_seq(tipo), t_ms, contenido)]))

    def _rapida(self, salida: List[bytes], nombre: str, ritmo_real: float, ritmo_nominal: int,
                por_bloque: int, tipo_bloque: int, tipo_suelto: int, ahora: float,
                muestra_bloque: Callable[[float], bytes], muestra_suelta: Callable[[float], bytes]) -> None:
        """Por BLE las señales rápidas van en bloques; por UART, un paquete por muestra."""
        for t in self._pendientes(nombre, ritmo_real, ahora):
            if self.formato == p.UART:
                self._suelto(salida, tipo_suelto, t, muestra_suelta(t))
                continue
            cola = self._bloques.setdefault(nombre, [])
            cola.append((t, muestra_bloque(t)))
            if len(cola) >= por_bloque:
                t0 = T_ARRANQUE_MS + cola[0][0] * 1000.0
                t1 = T_ARRANQUE_MS + cola[-1][0] * 1000.0
                seq0 = self._seq.get(tipo_suelto, 0)
                self._seq[tipo_suelto] = seq0 + len(cola)
                contenido = armar_bloque(tipo_suelto, ritmo_nominal, t0, t1, seq0, [m for _, m in cola])
                salida.append(armar_trama(t1, [armar_paquete(tipo_bloque, self._siguiente_seq(tipo_bloque), t0, contenido)]))
                self._bloques[nombre] = []

    def paso(self) -> List[bytes]:
        ahora = self._reloj() - self._inicio
        salida: List[bytes] = []
        g = self._ruido.gauss

        # --- ECG ---
        def ecg_bloque(t: float) -> bytes:
            uv = self._ecg_uv(t)
            return struct.pack("<ifB", int(uv * 8.0), uv, 0x03)   # drdy_ok + electrodos conectados

        def ecg_suelto(t: float) -> bytes:
            uv = self._ecg_uv(t)
            return struct.pack("<iffffBBBB", int(uv * 8.0), uv / 10.0, uv, uv / 10.0, uv, 1, 0, 0, 1)

        self._rapida(salida, "ecg", 586.0, 600, 30, p.SRC_BLE_BLOCK_ADS1220_ECG, p.SRC_SPI_ADS1220_ECG,
                     ahora, ecg_bloque, ecg_suelto)

        # --- PPG crudo ---
        def ppg_valores(t: float) -> Tuple[int, int]:
            pulso = self._pulso(t)
            lenta = math.sin(2 * math.pi * 0.25 * t)
            red = int(32000 + 100 * lenta + 350 * pulso + g(0, 8))
            ir = int(50000 + 150 * lenta + 600 * pulso + g(0, 12))
            return red, ir

        self._rapida(salida, "ppg", 104.6, 400, 40, p.SRC_BLE_BLOCK_MAX30102_RAW, p.SRC_I2C1_MAX30102_RAW, ahora,
                     lambda t: struct.pack("<IIB", *ppg_valores(t), 0x03),
                     lambda t: struct.pack("<IIBB", *ppg_valores(t), 1, 1))

        # --- IMU ---
        def imu_valores(t: float) -> Tuple[float, float, float, float, float, float, float]:
            pitch, roll, _yaw = self._orientacion(t)
            pr, rr = math.radians(pitch), math.radians(roll)
            ax = math.sin(rr) + g(0, 0.004)
            ay = -math.sin(pr) + g(0, 0.004)
            az = math.cos(pr) * math.cos(rr) + g(0, 0.004)
            gx = 18.0 * 0.35 * math.cos(0.35 * t) + g(0, 0.15)
            gy = 12.0 * 0.27 * math.cos(0.27 * t + 1.0) + g(0, 0.15)
            gz = 40.0 * 0.11 * math.cos(0.11 * t) + g(0, 0.15)
            return ax, ay, az, gx, gy, gz, 28.5 + 0.4 * math.sin(t / 90.0)

        def imu_suelto(t: float) -> bytes:
            ax, ay, az, gx, gy, gz, temp = imu_valores(t)
            return struct.pack("<hhhhhhhhffffff", int(ax * 2048), int(ay * 2048), int(az * 2048),
                               int(gx * 16.4), int(gy * 16.4), int(gz * 16.4), 0, int(temp * 100),
                               ax, ay, az, gx, gy, gz)

        def imu_bloque(t: float) -> bytes:
            ax, ay, az, gx, gy, gz, temp = imu_valores(t)
            return struct.pack("<ffffffh", ax, ay, az, gx, gy, gz, int(temp * 100))

        self._rapida(salida, "imu", 64.2, 100, 10, p.SRC_BLE_BLOCK_ICM42670P, p.SRC_I2C0_ICM42670P,
                     ahora, imu_bloque, imu_suelto)

        # --- Orientación ---
        def ori_suelta(t: float) -> bytes:
            pitch, roll, yaw = self._orientacion(t)
            ax, ay, az, gx, gy, gz, _temp = imu_valores(t)
            return struct.pack("<fffffffffffffffB", pitch, roll, yaw, pitch + g(0, 0.6), yaw + g(0, 1.5),
                               roll + g(0, 0.8), ax, ay, az, gx, gy, gz, 0.21, -0.05, 0.38, 1)

        self._rapida(salida, "orientacion", 64.2, 100, 10, p.SRC_BLE_BLOCK_ORIENTATION, p.SRC_I2C0_ORIENTATION, ahora,
                     lambda t: struct.pack("<fffB", *self._orientacion(t), 1), ori_suelta)

        # --- Oximetría (resultado del algoritmo de la placa) ---
        for t in self._pendientes("max_resultado", 6.9, ahora):
            self._bpm += 0.05 * ((72.0 + 6.0 * math.sin(t / 17.0)) - self._bpm) + g(0, 0.2)
            self._spo2 = min(100.0, self._spo2 + 0.05 * (97.6 - self._spo2) + g(0, 0.06))
            valido = t >= 4.0     # los primeros segundos el algoritmo todavía calcula
            red, ir = ppg_valores(t)
            self._suelto(salida, p.SRC_I2C1_MAX30102_RESULT, t, struct.pack(
                "<IIffffffhBBBBB", red, ir, float(red), float(ir), g(0, 80.0), 0.52,
                self._spo2 if valido else math.nan, self._bpm if valido else math.nan,
                int(self._bpm) if valido else -1, 1, int(valido), int(valido), 0, 0))

        # --- Magnetómetro ---
        for t in self._pendientes("qmc", 6.8, ahora):
            _p, _r, yaw = self._orientacion(t)
            mx, my = 0.25 * math.cos(math.radians(yaw)), 0.25 * math.sin(math.radians(yaw))
            self._suelto(salida, p.SRC_I2C0_QMC5883P, t, struct.pack(
                "<hhhfffB", int(mx * 3750), int(my * 3750), 1425, mx, my, 0.38, 0))

        # --- Presión diferencial (respiración) ---
        for t in self._pendientes("sdp810", 8.6, ahora):
            dp = 2.5 * math.sin(2 * math.pi * 0.25 * t) + g(0, 0.05)
            self._suelto(salida, p.SRC_I2C0_SDP810, t, struct.pack("<ff", dp, 27.3 + 0.2 * math.sin(t / 70.0)))

        # --- Ambiente ---
        for t in self._pendientes("bme680", 1.0, ahora):
            presion = 951.30 + 0.05 * math.sin(t / 30.0) + g(0, 0.01)
            altura = 44330.0 * (1.0 - (presion / 1013.25) ** 0.1903)
            self._suelto(salida, p.SRC_I2C1_BME680, t, struct.pack(
                "<ffffffffIBB", 24.8 + 0.3 * math.sin(t / 60.0), 42.0 + 1.5 * math.sin(t / 45.0), presion,
                45.0 + g(0, 0.4), altura, 1013.25, math.nan, math.nan, 0, 1, 0))

        for t in self._pendientes("scd40", 0.2, ahora):
            self._suelto(salida, p.SRC_I2C1_SCD40, t, struct.pack(
                "<HffB", int(650 + 40 * math.sin(t / 40.0) + g(0, 2)), 26.5 + 0.2 * math.sin(t / 80.0),
                44.0 + 1.2 * math.sin(t / 50.0), 1))

        for t in self._pendientes("ds18b20", 0.82, ahora):
            temp = round((31.5 + 0.4 * math.sin(t / 120.0)) * 16) / 16
            self._suelto(salida, p.SRC_ONEWIRE_DS18B20, t, struct.pack("<ffHBBBBII", temp, temp, 10, 1, 1, 1, 12, 0, 0))

        # --- GPS: los primeros segundos sin señal, como al encender la placa ---
        for t in self._pendientes("gps", 1.0, ahora):
            utc = datetime.now(timezone.utc)
            fecha = (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)
            con_senal = t >= 6.0
            if con_senal:
                angulo = t / 40.0
                lat = LAT0 + (12.0 * math.sin(angulo) + g(0, 0.4)) / 111320.0
                lon = LON0 + (12.0 * math.cos(angulo) + g(0, 0.4)) / (111320.0 * math.cos(math.radians(LAT0)))
                hacc, vacc, pdop = 1.6 + abs(g(0, 0.2)), 2.4 + abs(g(0, 0.3)), 1.3 + abs(g(0, 0.05))
                pvt = struct.pack("<ddfffffffHBBBBBBBBBB", lat, lon, 585.0, 562.0 + g(0, 0.3), hacc, vacc,
                                  1.1 + abs(g(0, 0.2)), 0.4, pdop, *fecha, 3, 1, 10 + int(2 * math.sin(t / 25.0)), 1, 1)
            else:
                pvt = struct.pack("<ddfffffffHBBBBBBBBBB", 0.0, 0.0, 0.0, -17.0, 4294967.5, 3750000.25,
                                  0.0, 158.0, 99.99, *fecha, 0, 0, min(int(t), 4), 0, 0)
            self._suelto(salida, p.SRC_GPS_MAXM10S_PVT, t, pvt)

            lista = t >= 12.0
            self._suelto(salida, p.SRC_GPS_MAXM10S_ALT_REF, t + 0.001, struct.pack(
                "<ffffHBBBBIIIII", 562.0 if lista else 0.0, 1.7 if lista else 0.0, 2.5 if lista else 0.0,
                1.3 if lista else 0.0, min(50, max(0, int(t - 6))), int(lista), min(100, max(0, int((t - 6) * 2))),
                0, 1, int(lista), 0, max(0, int(t - 6)), int(min(t, 6.0)), int(min(t, 6.0))))

            # Por BLE la placa real no envía el promedio de posición; por UART sí.
            if self.formato == p.UART and con_senal:
                self._suelto(salida, p.SRC_GPS_MAXM10S_POS_AVG, t + 0.002, struct.pack(
                    "<ddffHBBII", lat, lon, hacc, pdop, 10, 100, 1, int(t), 0))

        return salida
