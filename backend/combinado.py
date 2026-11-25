# ============================================================
# CSV COMBINADO RADAR + PLACA CMAE
#
# Junta en un solo archivo el CSV del radar y el de la placa CMAE
# (<archivo>_cmae.csv) de la misma adquisición:
#
#   datos/<archivo>_combinado.csv
#
# Formato largo, una fila por registro, ordenado por hora:
#   timestamp   hora del PC (ISO, ms)
#   t           segundos desde el primer registro (de cualquiera de las dos fuentes)
#   fuente      RADAR o CMAE
#   medicion, fase, condicion, flag_hold
#   tipo        radar: BW, HW, BR, HR, DIST, PHASE, END, MARK, EVENT...
#               placa: ECG_uV, PPG_IR, SPO2_pct, BPM_OXIMETRO, BPM_ECG,
#                      PRESION_hPa, PRESION_DIF_Pa
#   valor_1..valor_5  los valores del radar tal cual; la placa usa valor_1.
# ============================================================

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

from .acquisition import WAVE_COLS
from .data_io import FORMATO_SECUENCIA, detect_format, continuous_to_long, start_wall

COLUMNAS = ["timestamp", "t", "fuente", "medicion", "fase", "condicion", "flag_hold", "tipo", *WAVE_COLS]

# Archivos que acompañan al del radar y no son una adquisición por sí mismos.
ARCHIVO_ASOCIADO = re.compile(r"_(cmae(_\d+)?|combinado)\.csv$", re.IGNORECASE)


def ruta_combinado(ruta_radar: Path) -> Path:
    return ruta_radar.with_name(f"{ruta_radar.stem}_combinado.csv")


def buscar_cmae(ruta_radar: Path) -> Optional[Path]:
    """El CSV de la placa de esa adquisición (el más reciente si hay _cmae_2, _cmae_3...)."""
    candidatos = [ruta_radar.with_name(f"{ruta_radar.stem}_cmae.csv"),
                  *ruta_radar.parent.glob(f"{ruta_radar.stem}_cmae_*.csv")]
    candidatos = [p for p in candidatos if p.is_file()]
    return max(candidatos, key=lambda p: p.stat().st_mtime) if candidatos else None


def _radar(ruta: Path) -> pd.DataFrame:
    raw = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    fmt = detect_format(raw)
    if fmt == FORMATO_SECUENCIA:
        out = raw.reindex(columns=["timestamp", "medicion", "fase", "condicion", "flag_hold", "tipo", *WAVE_COLS],
                          fill_value="")
    else:
        # Formato continuo: se reinterpreta la línea original del sensor.
        long = continuous_to_long(pd.read_csv(ruta))
        inicio = start_wall(pd.read_csv(ruta), fmt)
        base = pd.Timestamp(inicio) if inicio else pd.Timestamp(ruta.stat().st_mtime, unit="s")
        out = pd.DataFrame({
            "timestamp": (base + pd.to_timedelta(long["t"], unit="s")).dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3],
            "medicion": long["medicion"].astype(str),
            "fase": long["fase"].astype(str),
            "condicion": "",
            "flag_hold": "0",
            "tipo": long["tipo"].astype(str),
        })
        for col in WAVE_COLS:
            out[col] = long[col].map(lambda v: "" if pd.isna(v) else f"{v:g}")
    out.insert(0, "fuente", "RADAR")
    return out


def _cmae(ruta: Path, condiciones: dict) -> pd.DataFrame:
    raw = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    out = pd.DataFrame({
        "fuente": "CMAE",
        "timestamp": raw["timestamp"],
        "medicion": raw["medicion"],
        "fase": raw["fase"],
        # La placa no graba la condición: se toma la del radar para esa medición y fase.
        "condicion": [condiciones.get((m, f), "") for m, f in zip(raw["medicion"], raw["fase"])],
        "flag_hold": raw["flag_hold"],
        "tipo": raw["senal"],
        "valor_1": raw["valor"],
    })
    for col in WAVE_COLS[1:]:
        out[col] = ""
    return out


def combinar(ruta_radar: Path, ruta_cmae: Optional[Path] = None) -> Path:
    """Escribe <archivo>_combinado.csv y devuelve su ruta. Sin CSV de la placa, solo trae el radar."""
    ruta_radar = Path(ruta_radar)
    ruta_cmae = ruta_cmae if ruta_cmae is not None else buscar_cmae(ruta_radar)

    radar = _radar(ruta_radar)
    partes = [radar]
    if ruta_cmae is not None and Path(ruta_cmae).is_file():
        condiciones = {(m, f): c for m, f, c in zip(radar["medicion"], radar["fase"], radar["condicion"]) if c}
        partes.append(_cmae(Path(ruta_cmae), condiciones))

    todo = pd.concat(partes, ignore_index=True)
    hora = pd.to_datetime(todo["timestamp"], errors="coerce")
    # Orden estable: ante la misma hora, el radar va primero (sus PHASE abren la fase).
    orden = hora.sort_values(kind="mergesort").index
    todo, hora = todo.loc[orden], hora.loc[orden]
    t0 = hora.min()
    todo["t"] = ((hora - t0).dt.total_seconds()).map(lambda v: "" if pd.isna(v) else f"{v:.4f}")

    salida = ruta_combinado(ruta_radar)
    tmp = salida.with_suffix(".csv.tmp")
    todo[COLUMNAS].to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(salida)
    return salida
