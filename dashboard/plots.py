# ============================================================
# GRÁFICOS MR60BHA1 (basados en HRBRWF.py)
#
# SUBPLOT 1 -> Waveform BW
# SUBPLOT 2 -> HR
# SUBPLOT 3 -> BR
#
# PUNTOS -> NARANJO
# LÍNEA  -> AZUL
# ============================================================

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from acquisition import WAVE_COLS
from data_io import phase_intervals

COLOR_PUNTOS = "orange"
COLOR_LINEA = "blue"

X_INDICE = "Índice de muestra"
X_TIEMPO = "Tiempo (s)"

PHASE_COLORS = {
    "NORMAL": "rgba(46, 204, 113, 0.13)",
    "PREP": "rgba(241, 196, 15, 0.22)",
    "HOLD": "rgba(231, 76, 60, 0.18)",
    "RECOVERY": "rgba(52, 152, 219, 0.13)",
}

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
# FIGURA INTERACTIVA (PLOTLY)
# ============================================================

def figure_hrbrwf(
    df: pd.DataFrame,
    title: str = "",
    x_mode: str = X_INDICE,
    show_phases: bool = True,
    height: int = 820,
) -> go.Figure:
    series = extract_series(df)
    use_time = x_mode == X_TIEMPO

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=use_time,
        vertical_spacing=0.09,
        subplot_titles=[s[0] for s in SUBPLOTS],
    )

    data = [
        (series.wave_t, series.wave, 4),
        (series.hr_t, series.hr, 7),
        (series.br_t, series.br, 7),
    ]

    for row, ((name, ylabel, xlabel), (t, y, size)) in enumerate(zip(SUBPLOTS, data), start=1):
        x = t if use_time else np.arange(len(y))
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers",
                name=name,
                line=dict(color=COLOR_LINEA, width=1.2),
                marker=dict(color=COLOR_PUNTOS, size=size),
                showlegend=False,
            ),
            row=row,
            col=1,
        )
        fig.update_yaxes(title_text=ylabel, row=row, col=1)
        fig.update_xaxes(
            title_text=X_TIEMPO if use_time else xlabel,
            showticklabels=True,
            row=row,
            col=1,
        )

    if use_time and show_phases:
        for fase, t0, t1 in phase_intervals(df):
            color = PHASE_COLORS.get(fase)
            if color is None or t1 <= t0:
                continue
            fig.add_vrect(x0=t0, x1=t1, fillcolor=color, line_width=0, layer="below", row="all", col=1)
            fig.add_annotation(
                x=(t0 + t1) / 2, y=0.98, xref="x", yref="y domain",
                text=fase, showarrow=False, yanchor="top",
                font=dict(size=10, color="#555"),
            )

    for ann in fig.layout.annotations[:3]:
        ann.update(x=0, xanchor="left", font=dict(size=14, color="#111"))

    axis_style = dict(
        showgrid=True, gridcolor="rgba(0,0,0,0.15)", griddash="dash",
        zerolinecolor="rgba(0,0,0,0.3)", linecolor="#444", showline=True,
        color="#222",
    )
    fig.update_xaxes(**axis_style)
    fig.update_yaxes(**axis_style)
    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=18, color="#111")),
        height=height,
        margin=dict(l=60, r=20, t=80 if title else 40, b=40),
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(color="#222"),
        uirevision="constant",
    )
    return fig


# ============================================================
# EXPORTAR PNG (MATPLOTLIB, IGUAL A HRBRWF.py)
# ============================================================

def figure_matplotlib(df: pd.DataFrame, title: str) -> plt.Figure:
    series = extract_series(df)
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    data = [(series.wave, 12), (series.hr, 25), (series.br, 25)]

    for ax, (name, ylabel, xlabel), (y, size) in zip(axes, SUBPLOTS, data):
        if len(y) > 0:
            x = np.arange(len(y))
            ax.plot(x, y, color=COLOR_LINEA, linewidth=1.2, zorder=1)
            ax.scatter(x, y, color=COLOR_PUNTOS, s=size, zorder=2)
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


def export_zip(df: pd.DataFrame, dpi: int = 300) -> bytes:
    """Una imagen por medición, como en HRBRWF.py (medicion_XX.png)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for medicion in sorted(df["medicion"].dropna().unique()):
            datos = df[df["medicion"] == medicion]
            fig = figure_matplotlib(datos, f"Medición {medicion} — MR60BHA1")
            zf.writestr(f"medicion_{int(medicion):02d}.png", png_bytes(fig, dpi))
    return buffer.getvalue()
