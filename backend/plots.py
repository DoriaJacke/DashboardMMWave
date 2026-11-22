# ============================================================
# GRÁFICOS MR60BHA1 (basados en HRBRWF.py)
#
# SUBPLOT 1 -> Waveform BW
# SUBPLOT 2 -> HR
# SUBPLOT 3 -> BR
#
# PUNTOS -> NARANJO
# LÍNEA  -> AZUL
#
# Los gráficos interactivos se dibujan en el frontend (React).
# Aquí quedan la extracción de series, el filtro Savitzky-Golay
# y la exportación de imágenes PNG con Matplotlib.
# ============================================================

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from .acquisition import WAVE_COLS

COLOR_PUNTOS = "orange"
COLOR_LINEA = "blue"
COLOR_FILTRADA = "crimson"

SUBPLOTS = [
    ("Waveform BW", "BW", "Índice de muestra de waveform"),
    ("Frecuencia cardíaca", "HR (BPM)", "Índice de muestra"),
    ("Frecuencia respiratoria", "BR (resp/min)", "Índice de muestra"),
]


# ============================================================
# EXTRAER SERIES
# ============================================================

@dataclass
class Series:
    wave_t: np.ndarray
    wave: np.ndarray
    hr_t: np.ndarray
    hr: np.ndarray
    br_t: np.ndarray
    br: np.ndarray


def extract_series(df: pd.DataFrame) -> Series:
    bw = df[df["tipo"] == "BW"]
    hr = df[df["tipo"] == "HR"].dropna(subset=["valor_1"])
    br = df[df["tipo"] == "BR"].dropna(subset=["valor_1"])

    # Cada trama BW trae 5 muestras: se reparten en el intervalo entre tramas.
    frame_t = bw["t"].to_numpy(dtype=float)
    frame_dt = float(np.median(np.diff(frame_t))) if len(frame_t) > 1 else 0.2
    wave_t, wave = [], []
    for t, values in zip(frame_t, bw[WAVE_COLS].to_numpy(dtype=float)):
        n = len(values)
        for k, v in enumerate(values):
            if not np.isnan(v):
                wave_t.append(t - frame_dt + (k + 1) * frame_dt / n)
                wave.append(v)

    return Series(
        wave_t=np.array(wave_t),
        wave=np.array(wave),
        hr_t=hr["t"].to_numpy(dtype=float),
        hr=hr["valor_1"].to_numpy(dtype=float),
        br_t=br["t"].to_numpy(dtype=float),
        br=br["valor_1"].to_numpy(dtype=float),
    )


# ============================================================
# FILTRO SAVITZKY-GOLAY (WAVEFORM BW)
# ============================================================

@dataclass
class SavgolConfig:
    ventana_s: float = 0.8
    orden: int = 2


def savgol_window(t: np.ndarray, cfg: SavgolConfig) -> tuple[float, int]:
    """Periodo de muestreo estimado y largo de ventana en muestras (impar, > orden)."""
    diffs = np.diff(t)
    diffs = diffs[diffs > 0]
    dt = float(np.median(diffs)) if len(diffs) else 0.04
    window = int(round(cfg.ventana_s / dt))
    if window % 2 == 0:
        window += 1
    min_window = cfg.orden + 1 if (cfg.orden + 1) % 2 else cfg.orden + 2
    return dt, max(window, min_window)


def savgol_segments(t: np.ndarray, y: np.ndarray, cfg: SavgolConfig) -> np.ndarray:
    """
    Aplica el filtro por tramos continuos: no cruza los huecos entre
    mediciones. Los tramos más cortos que la ventana quedan en NaN.
    """
    filtered = np.full(len(y), np.nan)
    if len(y) == 0:
        return filtered
    dt, window = savgol_window(t, cfg)
    breaks = np.where(np.diff(t) > max(1.0, 5 * dt))[0] + 1
    for segment in np.split(np.arange(len(y)), breaks):
        if len(segment) >= window:
            filtered[segment] = savgol_filter(y[segment], window, cfg.orden)
    return filtered


def savgol_label(t: np.ndarray, cfg: SavgolConfig) -> str:
    _, window = savgol_window(t, cfg)
    return f"Filtrada Savitzky-Golay ({window} muestras, orden {cfg.orden})"


# ============================================================
# EXPORTAR PNG (MATPLOTLIB, IGUAL A HRBRWF.py)
# ============================================================

def figure_matplotlib(df: pd.DataFrame, title: str, savgol: SavgolConfig | None = None) -> plt.Figure:
    series = extract_series(df)
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    data = [(series.wave, 12), (series.hr, 25), (series.br, 25)]

    for i, (ax, (name, ylabel, xlabel), (y, size)) in enumerate(zip(axes, SUBPLOTS, data)):
        if len(y) > 0:
            x = np.arange(len(y))
            overlay = savgol is not None and i == 0
            alpha = 0.55 if overlay else 1.0
            ax.plot(x, y, color=COLOR_LINEA, linewidth=1.2, alpha=alpha, zorder=1,
                    label="BW bruta" if overlay else None)
            ax.scatter(x, y, color=COLOR_PUNTOS, s=size, alpha=alpha, zorder=2)
            if overlay:
                ax.plot(x, savgol_segments(series.wave_t, y, savgol), color=COLOR_FILTRADA,
                        linewidth=2.4, zorder=3, label=savgol_label(series.wave_t, savgol))
                ax.legend(loc="upper right", fontsize=9)
        ax.set_title(name, fontsize=13, fontweight="bold", loc="left")
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_xlabel(xlabel, fontsize=10)
        ax.grid(True, alpha=0.25, linestyle="--")

    fig.suptitle(title, fontsize=16, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


def png_bytes(fig: plt.Figure, dpi: int = 300) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def export_zip(
    df: pd.DataFrame,
    dpi: int = 300,
    savgol: SavgolConfig | None = None,
    progress: Optional[Callable[[int, int, Optional[str]], None]] = None,
) -> bytes:
    """
    Una imagen por medición, como en HRBRWF.py (medicion_XX.png).
    `progress(hechas, total, archivo_en_curso)` se llama antes de cada imagen y al final.
    """
    mediciones = sorted(df["medicion"].dropna().unique())
    total = len(mediciones)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, medicion in enumerate(mediciones):
            nombre = f"medicion_{int(medicion):02d}.png"
            if progress is not None:
                progress(i, total, nombre)
            datos = df[df["medicion"] == medicion]
            fig = figure_matplotlib(datos, f"Medición {medicion} — MR60BHA1", savgol)
            zf.writestr(nombre, png_bytes(fig, dpi))
    if progress is not None:
        progress(total, total, None)
    return buffer.getvalue()
