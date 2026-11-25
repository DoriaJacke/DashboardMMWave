# ============================================================
# SINCRONÍA PLACA CMAE ↔ ADQUISICIÓN DEL RADAR
#
# La placa marca cada muestra con su propio reloj (ms desde que se
# encendió). La adquisición del radar usa t = segundos desde su inicio,
# medidos con time.monotonic() del PC. Aquí se pasa de uno a otro:
#
#   RelojPlaca      estima a qué hora del PC corresponde cada ms de la placa.
#   RegistroCMAE    durante una adquisición, etiqueta cada muestra con la
#                   medición y la fase vigentes en SU instante, la escribe en
#                   <archivo>_cmae.csv y la guarda para graficarla junto al radar.
#
# Como en el radar, solo se graban las muestras de las fases que se graban
# (NORMAL, PREP, HOLD, RECOVERY, MONITOREO, CONTINUO). Las de la espera de
# posicionamiento y la pausa entre mediciones no se guardan.
# ============================================================

from __future__ import annotations

import bisect
import csv
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Señales que se graban y se grafican con el radar:
# clave corta -> (serie de backend/cmae/en_vivo.py, nombre en el CSV)
SENALES: Dict[str, Tuple[str, str]] = {
    "ecg": ("ecg_filtered_final_uV", "ECG_uV"),
    "ppg": ("ppg_ir", "PPG_IR"),
    "spo2": ("spo2", "SPO2_pct"),
    "bpm": ("bpm_float", "BPM_OXIMETRO"),
    "bpm_ecg": ("ecg_bpm", "BPM_ECG"),
    "pres": ("pressure_hpa", "PRESION_hPa"),
    "dp": ("differential_pressure_pa", "PRESION_DIF_Pa"),
}
COLUMNAS_CSV = ["timestamp", "t", "medicion", "fase", "flag_hold", "senal", "valor"]

SALTO_RELOJ_S = 3.0        # si la placa parece "adelantarse" más que esto, se reinició
CORRECCION_DERIVA = 0.0002 # cuánto se acerca el ajuste a cada lectura (deriva entre relojes)
FLUSH_S = 0.5


class RelojPlaca:
    """
    hora del PC (monotonic) ≈ ms de la placa / 1000 + desfase.

    Cada trama llega un poco después de que la placa la midió (Bluetooth, USB).
    La trama con menos demora es la que mejor dice el desfase, así que se toma
    el mínimo de (hora de llegada − hora de la placa). Muy de a poco se deja
    subir, por si los relojes no avanzan exactamente igual.
    """

    def __init__(self) -> None:
        self.desfase: Optional[float] = None

    def reiniciar(self) -> None:
        self.desfase = None

    def observar(self, t_placa_ms: float, llegada_pc: float) -> None:
        candidato = llegada_pc - t_placa_ms / 1000.0
        d = self.desfase
        if d is None or candidato < d or candidato - d > SALTO_RELOJ_S:
            self.desfase = candidato
        else:
            self.desfase = d + (candidato - d) * CORRECCION_DERIVA

    def a_pc(self, t_placa_ms: float) -> Optional[float]:
        return None if self.desfase is None else t_placa_ms / 1000.0 + self.desfase


def ruta_cmae(ruta_radar: Path) -> Path:
    """datos/MR60BHA1_x.csv -> datos/MR60BHA1_x_cmae.csv (sin pisar uno existente)."""
    ruta = ruta_radar.with_name(f"{ruta_radar.stem}_cmae.csv")
    n = 2
    while ruta.exists():
        ruta = ruta_radar.with_name(f"{ruta_radar.stem}_cmae_{n}.csv")
        n += 1
    return ruta


class RegistroCMAE:
    """Datos de la placa de UNA adquisición del radar, en su misma escala de tiempo."""

    def __init__(self, sesion: Any) -> None:
        self.sesion = sesion
        self.ruta = ruta_cmae(Path(sesion.output_path))
        self._lock = threading.Lock()
        self.t: Dict[str, List[float]] = {k: [] for k in SENALES}
        self.v: Dict[str, List[float]] = {k: [] for k in SENALES}
        self.n = 0
        # Cambios de fase leídos de los registros del radar: (t, medicion, fase, se_graba)
        self._cambios_t: List[float] = []
        self._cambios: List[Tuple[Any, str, bool]] = []
        self._leidos = 0
        self._archivo = None
        self._csv = None
        self._ultimo_flush = 0.0
        self.cerrado = False

    # ---------------- fases ----------------

    def _actualizar_fases(self) -> None:
        s = self.sesion
        with s.lock:
            nuevos = s.records[self._leidos:]
            self._leidos = len(s.records)
        for r in nuevos:
            if r["tipo"] == "PHASE":
                self._cambios_t.append(r["t"])
                self._cambios.append((r["medicion"], r["fase"], True))
            elif r["tipo"] == "END":
                self._cambios_t.append(r["t"])
                self._cambios.append((r["medicion"], "END", False))

    def _fase_en(self, t: float) -> Optional[Tuple[Any, str]]:
        i = bisect.bisect_right(self._cambios_t, t) - 1
        if i < 0:
            return None
        medicion, fase, graba = self._cambios[i]
        return (medicion, fase) if graba else None

    # ---------------- entrada ----------------

    def agregar(self, muestras: List[Tuple[str, float, float]], reloj: RelojPlaca) -> None:
        """muestras: (clave corta, ms de la placa, valor)."""
        if self.cerrado:
            return
        s = self.sesion
        self._actualizar_fases()
        t_fin = s.t_end
        filas = []
        with self._lock:
            for clave, t_ms, valor in muestras:
                pc = reloj.a_pc(t_ms)
                if pc is None:
                    continue
                t = pc - s.t0
                if t < 0 or (t_fin is not None and t > t_fin):
                    continue
                fase = self._fase_en(t)
                if fase is None:
                    continue
                self.t[clave].append(t)
                self.v[clave].append(valor)
                self.n += 1
                filas.append((t, fase[0], fase[1], clave, valor))
        if filas:
            self._escribir(filas)
        if s.status.terminado:
            self.cerrar()

    def _escribir(self, filas) -> None:
        if self._archivo is None:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self._archivo = open(self.ruta, "w", newline="", encoding="utf-8")
            self._csv = csv.writer(self._archivo)
            self._csv.writerow(COLUMNAS_CSV)
        t0_wall = self.sesion.t0_wall
        for t, medicion, fase, clave, valor in filas:
            self._csv.writerow([
                (t0_wall + timedelta(seconds=t)).isoformat(timespec="milliseconds"),
                f"{t:.4f}", medicion, fase, 1 if fase == "HOLD" else 0,
                SENALES[clave][1], f"{valor:.6g}",
            ])
        ahora = time.monotonic()
        if ahora - self._ultimo_flush >= FLUSH_S:
            self._ultimo_flush = ahora
            self._archivo.flush()

    def cerrar(self) -> None:
        with self._lock:
            if self.cerrado:
                return
            self.cerrado = True
            if self._archivo is not None:
                self._archivo.close()

    # ---------------- salida ----------------

    def desde(self, cursor: Optional[Dict[str, int]]) -> Tuple[Dict[str, list], Dict[str, int]]:
        """Muestras nuevas desde `cursor` ({clave: n}) como {clave: [[t...], [v...]]}."""
        cursor = cursor or {}
        out: Dict[str, list] = {}
        nuevo: Dict[str, int] = {}
        with self._lock:
            for k in SENALES:
                a = cursor.get(k, 0)
                b = len(self.t[k])
                nuevo[k] = b
                if b > a:
                    out[k] = [[round(x, 4) for x in self.t[k][a:b]], [round(x, 3) for x in self.v[k][a:b]]]
        return out, nuevo

    def resumen(self) -> Dict[str, Any]:
        return {"file": self.ruta.name, "path": f"datos/{self.ruta.name}", "n": self.n,
                "saved": self._archivo is not None}
