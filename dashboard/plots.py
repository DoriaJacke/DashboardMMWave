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
from scipy.signal import savgol_filter

from acquisition import WAVE_COLS
from data_io import phase_intervals

COLOR_PUNTOS = "orange"
COLOR_LINEA = "blue"
COLOR_FILTRADA = "crimson"

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
# FIGURA INTERACTIVA (PLOTLY)
# ============================================================

def figure_hrbrwf(
    df: pd.DataFrame,
    title: str = "",
    x_mode: str = X_INDICE,
    show_phases: bool = True,
    height: int = 820,
    savgol: SavgolConfig | None = None,
) -> go.Figure:
    series = extract_series(df)
    use_time = x_mode == X_TIEMPO
    overlay = savgol is not None and len(series.wave) > 0

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
        is_overlay = overlay and row == 1
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers",
                name="BW bruta" if is_overlay else name,
                line=dict(color=COLOR_LINEA, width=1.2),
                marker=dict(color=COLOR_PUNTOS, size=size),
                opacity=0.55 if is_overlay else 1.0,
                showlegend=is_overlay,
            ),
            row=row,
            col=1,
        )
        if is_overlay:
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=savgol_segments(t, y, savgol),
                    mode="lines",
                    name=savgol_label(t, savgol),
                    line=dict(color=COLOR_FILTRADA, width=2.4),
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
        legend=dict(orientation="h", x=1, xanchor="right", y=1.0, yanchor="bottom", font=dict(size=11)),
        uirevision="constant",
    )
    return fig


# ============================================================
# MEDIDOR DE DISTANCIA
# ============================================================

@dataclass
class DistanceZone:
    minimo: float = 40.0
    maximo: float = 150.0
    escala: float = 300.0
    unidad: str = "cm"

    def estado(self, value: float | None, stale: bool) -> tuple[str, str]:
        """(texto, color) según la zona en que está la persona."""
        if value is None:
            return "Sin datos de distancia", "#95a5a6"
        if stale:
            return "Sin datos recientes", "#95a5a6"
        if value < self.minimo:
            return "Muy cerca del radar", "#e67e22"
        if value > self.maximo:
            return "Muy lejos del radar", "#c0392b"
        return "Distancia adecuada", "#27ae60"


def figure_distance_gauge(value: float | None, zone: DistanceZone, stale: bool = False) -> go.Figure:
    texto, color = zone.estado(value, stale)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number" if value is not None else "gauge",
            value=value if value is not None else 0,
            number=dict(suffix=f" {zone.unidad}", valueformat=".1f", font=dict(size=40, color=color)),
            title=dict(text=texto, font=dict(size=18, color=color)),
            gauge=dict(
                axis=dict(range=[0, zone.escala], ticksuffix="", tickcolor="#444"),
                bar=dict(color=color, thickness=0.3),
                steps=[
                    dict(range=[0, zone.minimo], color="rgba(230, 126, 34, 0.25)"),
                    dict(range=[zone.minimo, zone.maximo], color="rgba(39, 174, 96, 0.25)"),
                    dict(range=[zone.maximo, zone.escala], color="rgba(192, 57, 43, 0.25)"),
                ],
                threshold=dict(line=dict(color=color, width=4), thickness=0.85,
                               value=value if value is not None else 0),
            ),
        )
    )
    fig.update_layout(
        height=280, margin=dict(l=30, r=30, t=60, b=10),
        paper_bgcolor="white", font=dict(color="#222"),
    )
    return fig


def figure_distance_trend(history: list[tuple[float, float]], zone: DistanceZone, segundos: float = 60) -> go.Figure:
    datos = [(t, d) for t, d in history if t >= -segundos]
    fig = go.Figure()
    fig.add_hrect(y0=zone.minimo, y1=zone.maximo, fillcolor="rgba(39, 174, 96, 0.15)",
                  line_width=0, layer="below")
    if datos:
        t, d = zip(*datos)
        fig.add_trace(go.Scatter(
            x=t, y=d, mode="lines+markers",
            line=dict(color=COLOR_LINEA, width=1.2),
            marker=dict(color=COLOR_PUNTOS, size=6),
            showlegend=False,
        ))
    axis_style = dict(showgrid=True, gridcolor="rgba(0,0,0,0.15)", griddash="dash",
                      linecolor="#444", showline=True, color="#222")
    fig.update_xaxes(title_text="Segundos atrás", range=[-segundos, 0], **axis_style)
    fig.update_yaxes(title_text=f"Distancia ({zone.unidad})",
                     range=None if datos else [0, zone.escala], **axis_style)
    fig.update_layout(
        title=dict(text=f"Distancia — últimos {segundos:.0f} s", x=0, font=dict(size=14, color="#111")),
        height=280, margin=dict(l=60, r=20, t=40, b=40),
        paper_bgcolor="white", plot_bgcolor="white", font=dict(color="#222"),
        uirevision="constant",
    )
    return fig


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


def export_zip(df: pd.DataFrame, dpi: int = 300, savgol: SavgolConfig | None = None) -> bytes:
    """Una imagen por medición, como en HRBRWF.py (medicion_XX.png)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for medicion in sorted(df["medicion"].dropna().unique()):
            datos = df[df["medicion"] == medicion]
            fig = figure_matplotlib(datos, f"Medición {medicion} — MR60BHA1", savgol)
            zf.writestr(f"medicion_{int(medicion):02d}.png", png_bytes(fig, dpi))
    return buffer.getvalue()
