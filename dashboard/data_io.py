# ============================================================
# LECTURA DE ARCHIVOS CSV
#
# Convierte los CSV de ambos protocolos (y los registros en vivo)
# a un formato largo común:
#   t, medicion, fase, tipo, valor_1..valor_5, evento
# ============================================================

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from acquisition import WAVE_COLS, parse_record

FORMATO_SECUENCIA = "secuencia"
FORMATO_CONTINUO = "continuo"

LONG_COLUMNS = ["t", "medicion", "fase", "tipo", *WAVE_COLS, "evento"]


def detect_format(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    if {"tipo", "medicion", *WAVE_COLS} <= cols:
        return FORMATO_SECUENCIA
    if {"HR", "BR", "raw"} <= cols:
        return FORMATO_CONTINUO
    raise ValueError(
        "Formato de CSV no reconocido. Se esperaban las columnas de "
        "MEDICION20SEQRES (tipo, medicion, valor_1..5) o de tomadatosSEPT (HR, BR, raw)."
    )


def records_to_long(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=LONG_COLUMNS)
    return pd.DataFrame.from_records(records, columns=LONG_COLUMNS)


# Lecturas de la placa CMAE en memoria (para graficar en vivo)
PBM_RECORD_COLUMNS = ["t", "medicion", "fase", "bpm", "spo2", "bpm_ok", "spo2_ok"]


def pbm_records_to_frame(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=PBM_RECORD_COLUMNS)
    return pd.DataFrame.from_records(records, columns=PBM_RECORD_COLUMNS)


def sequence_to_long(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"], errors="coerce")
    out["t"] = (ts - ts.min()).dt.total_seconds()
    out["evento"] = np.where(out["tipo"] == "EVENT", out["valor_1"].astype(str), None)
    for col in WAVE_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["medicion"] = pd.to_numeric(out["medicion"], errors="coerce").astype("Int64")
    return out[LONG_COLUMNS]


def continuous_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """El formato continuo guarda la línea original en 'raw'; se re-interpreta."""
    t = pd.to_numeric(df["timestamp"], errors="coerce").to_numpy()
    records = []
    for ti, raw in zip(t, df["raw"].astype(str)):
        parts = [p.strip() for p in raw.split(",")]
        record = parse_record(parts[0], parts, float(ti), 1, "CONTINUO")
        if record is not None:
            records.append(record)
    return records_to_long(records)


def load_csv(data: bytes) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Devuelve (formato, dataframe original, dataframe en formato largo)."""
    raw = pd.read_csv(io.BytesIO(data))
    fmt = detect_format(raw)
    if fmt == FORMATO_SECUENCIA:
        return fmt, raw, sequence_to_long(raw)
    return fmt, raw, continuous_to_long(raw)


# ============================================================
# FASES Y RESÚMENES
# ============================================================

def phase_intervals(df: pd.DataFrame) -> list[tuple[str, float, float]]:
    """Intervalos (fase, t_inicio, t_fin) a partir de las marcas PHASE/END."""
    if df.empty:
        return []
    marks = df[df["tipo"].isin(["PHASE", "END"])].sort_values("t")
    t_last = float(df["t"].max())
    intervals = []
    rows = list(marks[["tipo", "fase", "t"]].itertuples(index=False))
    for i, row in enumerate(rows):
        if row.tipo != "PHASE":
            continue
        t_end = float(rows[i + 1].t) if i + 1 < len(rows) else t_last
        intervals.append((str(row.fase), float(row.t), t_end))
    return intervals


def phase_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Media, desviación y n de HR, BR y distancia por medición y fase."""
    data = df[df["tipo"].isin(["HR", "BR", "DIST"])].dropna(subset=["valor_1"])
    if data.empty:
        return pd.DataFrame()
    summary = (
        data.groupby(["medicion", "fase", "tipo"], sort=False)["valor_1"]
        .agg(media="mean", desv="std", n="count")
        .unstack("tipo")
    )
    summary.columns = [f"{tipo} {stat}" for stat, tipo in summary.columns]
    order = [c for t in ("HR", "BR", "DIST") for c in (f"{t} media", f"{t} desv", f"{t} n") if c in summary.columns]
    return summary[order].round(2)
