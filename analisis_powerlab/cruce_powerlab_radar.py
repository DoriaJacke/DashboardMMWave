"""
Análisis cruzado PowerLab (referencia) vs radar MR60BHA1, par por par.

1. Convierte cada .txt de PowerLab (LabChart, 1 kHz, varios bloques) a CSV con hora absoluta.
2. Para cada par PowerLab/radar recorta la ventana en que ambos registran a la vez y compara:
   - FC: canal 3 PowerLab vs HR radar (y CMAE ECG/oxímetro si existe).
   - FR: canal 4 PowerLab vs BR radar.
   - Onda respiratoria: canal 1 PowerLab vs forma de onda BW del radar.
   Además estima FC/FR desde las ondas crudas del PowerLab (canales 1 y 2) como control
   de calidad de los canales 3 y 4.
3. Escribe resultados/cruce.json (para el artifact) y CSV alineados a 1 s por par.

Uso:  python analisis_powerlab/cruce_powerlab_radar.py
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
PL_DIR = ROOT / "datos powerlab"
RADAR_DIR = ROOT / "datos"
OUT = Path(__file__).resolve().parent / "resultados"
CSV_OUT = PL_DIR / "csv"

PARES = [
    {"id": "par1", "nombre": "Apnea simulada 1", "powerlab": "apeaSimulada1.txt",
     "radar": "MR60BHA1_mediciones_20261124_103110.csv"},
    {"id": "par2", "nombre": "Prueba FR Cris 1", "powerlab": "FrCrisPrueba1.txt",
     "radar": "MR60BHA1_experimento_20261123_201315.csv"},
    {"id": "par3", "nombre": "Prueba FR Cris 2", "powerlab": "FrCrisPrueba2.txt",
     "radar": "MR60BHA1_experimento_20261124_100331.csv",
     "cmae": "MR60BHA1_experimento_20261124_100331_cmae.csv"},
    {"id": "par4", "nombre": "Prueba simulada 10 min", "powerlab": "PruebaSimulada10min.txt",
     "radar": "MR60BHA1_apnea_20261124_104647.csv"},
]

HR_RANGO = (35.0, 200.0)
BR_RANGO = (3.0, 45.0)
TOL = {"hr": 5.0, "br": 2.0}       # tolerancia clínica habitual: ±5 lpm, ±2 rpm
FS_ONDA = 5.0                       # Hz común para comparar ondas (BW del radar = 5 muestras/s)
MAX_STALE = 10.0                    # s que se mantiene el último valor del radar
SG_VENTANA_S = 21                   # Savitzky-Golay opcional sobre la FC del PowerLab (serie a 1 s)
SG_ORDEN = 3


# --------------------------------------------------------------------------- PowerLab
def leer_powerlab(path: Path) -> pd.DataFrame:
    """Devuelve un DataFrame con todos los bloques, con hora absoluta."""
    texto = path.read_text(encoding="latin-1")
    partes = re.split(r"(?m)^(?=Interval=)", texto)
    bloques = []
    for n, parte in enumerate(p for p in partes if p.strip()):
        lineas = parte.splitlines()
        cab = {l.split("=", 1)[0]: l.split("=", 1)[1].strip() for l in lineas[:6] if "=" in l}
        fecha = cab["ExcelDateTime"].split("\t")[-1].strip()
        inicio = datetime.strptime(fecha, "%m/%d/%Y %H:%M:%S.%f")
        df = pd.read_csv(io.StringIO("\n".join(lineas[6:])), sep="\t", header=None,
                         names=["t_bloque_s", "c1", "c2", "c3", "c4", "comentario"], na_values=["NaN"],
                         dtype={"t_bloque_s": float, "c1": float, "c2": float, "c3": float, "c4": float,
                                "comentario": str})
        df["comentario"] = df["comentario"].str.strip()
        df.insert(0, "bloque", n + 1)
        df["inicio"] = inicio
        bloques.append(df)
    out = pd.concat(bloques, ignore_index=True)
    out["datetime"] = out["inicio"] + pd.to_timedelta(out["t_bloque_s"], unit="s")
    return out


def exportar_csv_powerlab(df: pd.DataFrame, nombre: str) -> Path:
    CSV_OUT.mkdir(parents=True, exist_ok=True)
    dest = CSV_OUT / (Path(nombre).stem + ".csv")
    out = pd.DataFrame({
        "bloque": df["bloque"],
        "datetime": df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3],
        "t_bloque_s": df["t_bloque_s"].round(3),
        "canal1_onda_resp_V": df["c1"],
        "canal2_pulso_V": df["c2"],
        "canal3_FC_lpm": df["c3"].round(3),
        "canal4_FR_rpm": df["c4"].round(3),
        "comentario": df["comentario"].fillna(""),
    })
    out.to_csv(dest, index=False)
    return dest


# --------------------------------------------------------------------------- Radar
def leer_radar(path: Path) -> dict:
    """Unifica los dos formatos de CSV del dashboard en eventos (t, tipo, valores)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    filas = []
    fases = []
    if "tipo" in df.columns:                       # formato protocolo (mediciones / apnea)
        for _, r in df.iterrows():
            t = pd.Timestamp(r["timestamp"])
            vals = [r[f"valor_{i}"] for i in range(1, 6)]
            filas.append((t, r["tipo"], vals))
            if r["tipo"] == "PHASE":
                fases.append((t, r["fase"], r["condicion"]))
    else:                                          # formato experimento (raw)
        for _, r in df.iterrows():
            raw = r["raw"]
            tipo = raw.split(",", 1)[0]
            if tipo in {"HR", "BR", "BW", "DIST", "EVENT", "MARK"}:
                filas.append((pd.Timestamp(r["datetime"]), tipo, raw.split(",")[1:]))
    return {"filas": filas, "fases": fases}


def serie_radar(filas, tipo) -> pd.Series:
    t, v = [], []
    for ts, tp, vals in filas:
        if tp == tipo and vals and vals[0] not in ("", None):
            try:
                x = float(vals[0])
            except ValueError:
                continue
            t.append(ts)
            v.append(x)
    return pd.Series(v, index=pd.DatetimeIndex(t), dtype=float).sort_index()


def onda_radar(filas) -> pd.Series:
    """BW: cada trama trae 5 muestras del último segundo -> 5 Hz."""
    t, v = [], []
    for ts, tp, vals in filas:
        if tp != "BW":
            continue
        nums = [float(x) for x in vals if x not in ("", None)]
        for i, x in enumerate(nums):
            t.append(ts - timedelta(seconds=(len(nums) - 1 - i) / FS_ONDA))
            v.append(x)
    return pd.Series(v, index=pd.DatetimeIndex(t), dtype=float).sort_index()


def leer_cmae(path: Path) -> dict[str, pd.Series]:
    df = pd.read_csv(path, usecols=["timestamp", "senal", "valor"])
    df = df[df["senal"].isin(["BPM_ECG", "BPM_OXIMETRO", "SPO2_pct"])]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return {s: g.set_index("timestamp")["valor"].astype(float).sort_index()
            for s, g in df.groupby("senal")}


# --------------------------------------------------------------------------- utilidades
def a_grilla(s: pd.Series, grilla: pd.DatetimeIndex, stale=MAX_STALE) -> np.ndarray:
    """Último valor conocido (step-hold) en cada punto de la grilla, si no es muy antiguo."""
    s = s.dropna()
    if s.empty:
        return np.full(len(grilla), np.nan)
    idx = s.index.searchsorted(grilla, side="right") - 1
    out = np.full(len(grilla), np.nan)
    ok = idx >= 0
    out[ok] = s.values[idx[ok]]
    edad = np.full(len(grilla), np.inf)
    edad[ok] = (grilla[ok] - s.index[idx[ok]]).total_seconds()
    out[edad > stale] = np.nan
    return out


def limpiar_canal(s: pd.Series, rango) -> pd.Series:
    """Canales 3/4 de LabChart: valores fuera de rango fuera, mediana por segundo y móvil de 5 s."""
    s = s.where((s >= rango[0]) & (s <= rango[1]))
    s = s.resample("1s").median()
    return s.rolling(5, center=True, min_periods=2).median()


def tasa_desde_onda(x: np.ndarray, fs: float, banda, ventana_s, paso_s, t0) -> pd.Series:
    """Frecuencia dominante (por minuto) en ventanas deslizantes mediante Welch."""
    b, a = signal.butter(2, [banda[0] / (fs / 2), banda[1] / (fs / 2)], "band")
    x = np.nan_to_num(x - np.nanmean(x))
    xf = signal.filtfilt(b, a, x)
    n, p = int(ventana_s * fs), int(paso_s * fs)
    tt, vv = [], []
    for i in range(0, len(xf) - n, p):
        seg = xf[i:i + n]
        f, pxx = signal.welch(seg, fs, nperseg=min(n, int(fs * ventana_s)), nfft=max(8192, n))
        m = (f >= banda[0]) & (f <= banda[1])
        tt.append(t0 + timedelta(seconds=(i + n / 2) / fs))
        vv.append(f[m][np.argmax(pxx[m])] * 60)
    return pd.Series(vv, index=pd.DatetimeIndex(tt))


def metricas(ref: np.ndarray, est: np.ndarray, tol: float) -> dict:
    m = ~np.isnan(ref) & ~np.isnan(est)
    n = int(m.sum())
    if n < 3:
        return {"n": n}
    r_, e_ = ref[m], est[m]
    d = e_ - r_
    sd = float(np.std(d, ddof=1))
    r = float(np.corrcoef(r_, e_)[0, 1]) if np.std(r_) > 0 and np.std(e_) > 0 else None
    return {
        "n": n,
        "mae": float(np.mean(np.abs(d))),
        "rmse": float(np.sqrt(np.mean(d ** 2))),
        "sesgo": float(np.mean(d)),
        "loa_inf": float(np.mean(d) - 1.96 * sd),
        "loa_sup": float(np.mean(d) + 1.96 * sd),
        "mape": float(np.mean(np.abs(d) / r_) * 100),
        "r": r,
        "dentro_tol": float(np.mean(np.abs(d) <= tol) * 100),
        "ref_media": float(np.mean(r_)),
        "est_media": float(np.mean(e_)),
    }


def mejor_desfase(ref: np.ndarray, est: np.ndarray, max_lag=30) -> dict:
    """Desfase (s) que minimiza el MAE. lag>0: el radar va atrasado respecto del PowerLab."""
    curva = []
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = ref[:len(ref) - lag], est[lag:]
        else:
            a, b = ref[-lag:], est[:len(est) + lag]
        m = ~np.isnan(a) & ~np.isnan(b)
        curva.append([lag, float(np.mean(np.abs(a[m] - b[m]))) if m.sum() > 10 else None])
    validos = [c for c in curva if c[1] is not None]
    mejor = min(validos, key=lambda c: c[1]) if validos else [0, None]
    return {"lag_s": mejor[0], "mae": mejor[1], "curva": curva}


def savgol_segmentos(x: np.ndarray, ventana: int = SG_VENTANA_S, orden: int = SG_ORDEN) -> np.ndarray:
    """Savitzky-Golay por tramos continuos (huecos de hasta 5 s se interpolan antes)."""
    s = pd.Series(x).interpolate(limit=5, limit_area="inside")
    out = np.full(len(x), np.nan)
    valido = s.notna().values
    i = 0
    while i < len(valido):
        if not valido[i]:
            i += 1
            continue
        j = i
        while j < len(valido) and valido[j]:
            j += 1
        if j - i >= ventana:
            out[i:j] = signal.savgol_filter(s.values[i:j], ventana, orden)
        i = j
    return out


def bandpass(x, fs, lo, hi):
    b, a = signal.butter(2, [lo / (fs / 2), hi / (fs / 2)], "band")
    return signal.filtfilt(b, a, np.nan_to_num(x - np.nanmean(x)))


def zscore(x):
    s = np.nanstd(x)
    return (x - np.nanmean(x)) / s if s > 0 else x * 0


def r3(x, nd=2):
    if x is None:
        return None
    if isinstance(x, (list, np.ndarray)):
        return [None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(float(v), nd)
                for v in x]
    return None if np.isnan(x) else round(float(x), nd)


# --------------------------------------------------------------------------- análisis de un par
def analizar_par(par: dict, pl: pd.DataFrame) -> dict:
    radar = leer_radar(RADAR_DIR / par["radar"])
    hr_r = serie_radar(radar["filas"], "HR").replace(0, np.nan)
    br_r = serie_radar(radar["filas"], "BR").replace(0, np.nan)
    dist_r = serie_radar(radar["filas"], "DIST")
    bw_r = onda_radar(radar["filas"])
    eventos = [(t, tp, v[0] if v else "") for t, tp, v in radar["filas"] if tp in ("EVENT", "MARK")]

    r_ini = min(s.index.min() for s in (hr_r, br_r, bw_r) if not s.empty)
    r_fin = max(s.index.max() for s in (hr_r, br_r, bw_r) if not s.empty)

    # bloque(s) del PowerLab que se solapan con el radar
    bloques = []
    for b, g in pl.groupby("bloque"):
        ini, fin = g["datetime"].iloc[0], g["datetime"].iloc[-1]
        sol = max(timedelta(0), min(fin, r_fin) - max(ini, r_ini)).total_seconds()
        bloques.append({"bloque": int(b), "inicio": ini.isoformat(timespec="seconds"),
                        "fin": fin.isoformat(timespec="seconds"),
                        "duracion_s": round((fin - ini).total_seconds(), 1),
                        "solape_s": round(sol, 1)})
    usados = [b["bloque"] for b in bloques if b["solape_s"] > 0]
    plw = pl[pl["bloque"].isin(usados)].set_index("datetime").sort_index()
    plw = plw[~plw.index.duplicated()]

    t0 = max(plw.index.min(), r_ini).ceil("1s")
    t1 = min(plw.index.max(), r_fin).floor("1s")
    plw = plw.loc[t0:t1]
    grilla = pd.date_range(t0, t1, freq="1s")

    # referencia PowerLab: canales 3/4 limpios + estimación desde las ondas crudas
    hr_pl = limpiar_canal(plw["c3"], HR_RANGO).reindex(grilla).values
    br_pl = limpiar_canal(plw["c4"], BR_RANGO).reindex(grilla).values
    c1_100 = plw["c1"].resample("10ms").mean().interpolate(limit=50)
    c2_100 = plw["c2"].resample("10ms").mean().interpolate(limit=50)
    br_onda = tasa_desde_onda(c1_100.values, 100, (0.08, 0.8), 30, 2, c1_100.index[0])
    hr_onda = tasa_desde_onda(c2_100.values, 100, (0.7, 3.0), 10, 1, c2_100.index[0])
    br_onda_g = a_grilla(br_onda, grilla, stale=3)
    hr_onda_g = a_grilla(hr_onda, grilla, stale=2)

    hr_rad = a_grilla(hr_r, grilla)
    br_rad = a_grilla(br_r, grilla)
    dist_g = a_grilla(dist_r, grilla, stale=5)

    # comparación en los instantes en que el radar reporta (muestras independientes)
    def emparejar(s_radar, ref_g):
        s = s_radar.loc[t0:t1].dropna()
        pos = ((s.index - t0).total_seconds()).round().astype(int)
        ok = (pos >= 0) & (pos < len(grilla))
        return ref_g[pos[ok]], s.values[ok], (s.index[ok] - t0).total_seconds()

    hr_ref_p, hr_est_p, hr_t_p = emparejar(hr_r, hr_pl)
    br_ref_p, br_est_p, br_t_p = emparejar(br_r, br_pl)

    # sin señal de pulso (sensor suelto) la FC estimada desde la onda es ruido
    alertas = []
    if np.nanstd(plw["c2"].values) < 0.005:
        hr_onda_g[:] = np.nan
        alertas.append("Canal 2 (pulso) prácticamente plano en esta ventana: el sensor de pulso no registró señal.")
    if np.isnan(hr_pl).all():
        alertas.append("Canal 3 (FC) sin valores fisiológicos válidos (35–200 lpm) en esta ventana.")
    ratio = np.nanmean(br_pl) / np.nanmean(br_onda_g) if np.isfinite(br_onda_g).any() else np.nan
    if np.isfinite(ratio) and ratio > 1.5:
        alertas.append(f"Canal 4 (FR) promedia {ratio:.1f}× la FR estimada desde la onda respiratoria "
                       "(canal 1): el detector de ciclos de LabChart probablemente contó picos de más. "
                       "Para este par la referencia de FR más confiable es la onda.")

    res_hr = metricas(hr_ref_p, hr_est_p, TOL["hr"])
    res_br = metricas(br_ref_p, br_est_p, TOL["br"])
    _r, _e, _ = emparejar(hr_r, hr_onda_g)
    res_hr_onda = metricas(_r, _e, TOL["hr"])
    _r, _e, _ = emparejar(br_r, br_onda_g)
    res_br_onda = metricas(_r, _e, TOL["br"])
    hr_pl_sg = savgol_segmentos(hr_pl)
    _r, _e, _ = emparejar(hr_r, hr_pl_sg)
    res_hr_sg = metricas(_r, _e, TOL["hr"])
    lag_hr = mejor_desfase(hr_pl, hr_rad)
    lag_br = mejor_desfase(br_pl, br_rad)

    # control de calidad de los canales 3/4 contra la onda cruda
    qc = {"hr_c3_vs_onda": metricas(hr_onda_g, hr_pl, TOL["hr"]),
          "br_c4_vs_onda": metricas(br_onda_g, br_pl, TOL["br"]),
          "hr_radar_vs_onda": metricas(hr_onda_g, hr_rad, TOL["hr"]),
          "br_radar_vs_onda": metricas(br_onda_g, br_rad, TOL["br"])}

    # cobertura: % del tiempo con valor válido
    cobertura = {"hr_radar": float(np.mean(~np.isnan(hr_rad)) * 100),
                 "br_radar": float(np.mean(~np.isnan(br_rad)) * 100),
                 "hr_powerlab": float(np.mean(~np.isnan(hr_pl)) * 100),
                 "br_powerlab": float(np.mean(~np.isnan(br_pl)) * 100)}

    # ondas respiratorias a 5 Hz
    g5 = pd.date_range(t0, t1, freq=f"{int(1000 / FS_ONDA)}ms")
    pl5 = plw["c1"].resample(f"{int(1000 / FS_ONDA)}ms").mean().reindex(g5).interpolate(limit=10).values
    bw = bw_r.loc[t0 - timedelta(seconds=2):t1 + timedelta(seconds=2)]
    bw = bw[~bw.index.duplicated()]
    bw5 = (bw.reindex(bw.index.union(g5)).interpolate(method="time", limit=10).reindex(g5).values)
    pl5f = zscore(bandpass(pl5, FS_ONDA, 0.08, 0.8))
    bw5f = zscore(bandpass(bw5, FS_ONDA, 0.08, 0.8))
    validos = ~np.isnan(pl5) & ~np.isnan(bw5)
    pl5f[~validos] = np.nan
    bw5f[~validos] = np.nan
    max_l = int(5 * FS_ONDA)
    xc = []
    for l in range(-max_l, max_l + 1):
        a = pl5f[max(0, -l):len(pl5f) - max(0, l)]
        b = bw5f[max(0, l):len(bw5f) - max(0, -l)]
        m = ~np.isnan(a) & ~np.isnan(b)
        xc.append([l / FS_ONDA, float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 20 else None])
    xc_ok = [c for c in xc if c[1] is not None]
    mejor_xc = max(xc_ok, key=lambda c: abs(c[1])) if xc_ok else [0, None]
    lag_n = int(round(mejor_xc[0] * FS_ONDA))
    bw_al = np.roll(bw5f, -lag_n)
    if lag_n > 0:
        bw_al[-lag_n:] = np.nan
    elif lag_n < 0:
        bw_al[:-lag_n] = np.nan
    if mejor_xc[1] is not None and mejor_xc[1] < 0:
        bw_al = -bw_al                       # polaridad invertida: se reporta y se corrige al graficar
    # correlación móvil de 20 s (ya alineada)
    w = int(20 * FS_ONDA)
    corr_movil = pd.Series(pl5f).rolling(w, center=True, min_periods=w // 2).corr(pd.Series(bw_al))
    corr_1s = corr_movil.values[::int(FS_ONDA)]

    # fases y eventos
    fases = []
    for i, (t, fase, cond) in enumerate(radar["fases"]):
        fin = radar["fases"][i + 1][0] if i + 1 < len(radar["fases"]) else r_fin
        fases.append({"fase": fase, "condicion": cond,
                      "ini": (t - t0).total_seconds(), "fin": (fin - t0).total_seconds()})
    por_fase = []
    for f in fases:
        m_hr = (hr_t_p >= f["ini"]) & (hr_t_p < f["fin"])
        m_br = (br_t_p >= f["ini"]) & (br_t_p < f["fin"])
        por_fase.append({"fase": f["fase"], "condicion": f["condicion"],
                         "duracion_s": round(f["fin"] - f["ini"], 1),
                         "hr": metricas(hr_ref_p[m_hr], hr_est_p[m_hr], TOL["hr"]),
                         "br": metricas(br_ref_p[m_br], br_est_p[m_br], TOL["br"])})

    # tasas de muestreo efectivas del radar
    def periodo(s):
        d = np.diff(s.index.values).astype("timedelta64[ms]").astype(float) / 1000
        return float(np.median(d)) if len(d) else None

    out = {
        "id": par["id"], "nombre": par["nombre"],
        "archivos": {"powerlab": par["powerlab"], "radar": par["radar"], "cmae": par.get("cmae")},
        "ventana": {"inicio": t0.isoformat(timespec="seconds"), "fin": t1.isoformat(timespec="seconds"),
                    "duracion_s": len(grilla)},
        "bloques_powerlab": bloques,
        "radar_rango": {"inicio": r_ini.isoformat(timespec="seconds"), "fin": r_fin.isoformat(timespec="seconds")},
        "periodo_radar_s": {"HR": periodo(hr_r), "BR": periodo(br_r), "BW_trama": periodo(bw_r[::5]) if len(bw_r) else None},
        "metricas": {"hr": res_hr, "br": res_br, "hr_onda": res_hr_onda, "br_onda": res_br_onda,
                     "hr_sg": res_hr_sg},
        "savgol": {"ventana_s": SG_VENTANA_S, "orden": SG_ORDEN},
        "alertas": alertas,
        "pares_ba_onda": {"br": [[r3(a, 1), r3(b, 0)] for a, b in zip(*emparejar(br_r, br_onda_g)[:2])
                                 if not np.isnan(a)]},
        "desfase": {"hr": lag_hr, "br": lag_br,
                    "onda": {"lag_s": mejor_xc[0], "r": mejor_xc[1], "curva": xc}},
        "cobertura": cobertura,
        "qc": qc,
        "por_fase": por_fase,
        "fases": fases,
        "eventos": [{"t": (t - t0).total_seconds(), "tipo": tp, "valor": v}
                    for t, tp, v in eventos if t0 <= t <= t1],
        "comentarios_powerlab": [{"t": (t - t0).total_seconds(), "texto": c}
                                 for t, c in plw["comentario"].dropna().items()],
        "serie": {
            "t": list(range(len(grilla))),
            "hr_pl": r3(hr_pl, 1), "hr_pl_sg": r3(hr_pl_sg, 1), "hr_pl_onda": r3(hr_onda_g, 1), "hr_radar": r3(hr_rad, 0),
            "br_pl": r3(br_pl, 1), "br_pl_onda": r3(br_onda_g, 1), "br_radar": r3(br_rad, 0),
            "dist": r3(dist_g, 2), "corr_onda": r3(corr_1s, 2),
        },
        "onda": {"fs": FS_ONDA, "pl": r3(pl5f, 2), "radar": r3(bw_al, 2)},
        "pares_ba": {"hr": [[r3(a, 1), r3(b, 0)] for a, b in zip(hr_ref_p, hr_est_p) if not np.isnan(a)],
                     "br": [[r3(a, 1), r3(b, 0)] for a, b in zip(br_ref_p, br_est_p) if not np.isnan(a)]},
    }

    tabla = pd.DataFrame({"datetime": grilla, "t_s": range(len(grilla)),
                          "FC_powerlab_c3": hr_pl, "FC_powerlab_c3_savgol": hr_pl_sg, "FC_powerlab_onda": hr_onda_g, "FC_radar": hr_rad,
                          "FR_powerlab_c4": br_pl, "FR_powerlab_onda": br_onda_g, "FR_radar": br_rad,
                          "distancia_radar_m": dist_g})

    if par.get("cmae"):
        cm = leer_cmae(RADAR_DIR / par["cmae"])
        ecg = cm.get("BPM_ECG", pd.Series(dtype=float))
        ox = cm.get("BPM_OXIMETRO", pd.Series(dtype=float))
        spo2 = cm.get("SPO2_pct", pd.Series(dtype=float))
        ecg = ecg.where((ecg >= HR_RANGO[0]) & (ecg <= HR_RANGO[1]))
        ox = ox.where((ox >= HR_RANGO[0]) & (ox <= HR_RANGO[1]))
        ecg_g, ox_g, spo2_g = (a_grilla(s.dropna(), grilla, stale=5) for s in (ecg, ox, spo2))
        out["serie"].update({"hr_cmae_ecg": r3(ecg_g, 1), "hr_cmae_ox": r3(ox_g, 1), "spo2": r3(spo2_g, 1)})
        out["cmae"] = {
            "ecg_vs_powerlab": metricas(hr_pl, ecg_g, TOL["hr"]),
            "ox_vs_powerlab": metricas(hr_pl, ox_g, TOL["hr"]),
            "radar_vs_ecg": metricas(ecg_g, hr_rad, TOL["hr"]),
            "radar_vs_ox": metricas(ox_g, hr_rad, TOL["hr"]),
            "spo2_media": float(np.nanmean(spo2_g)) if np.isfinite(spo2_g).any() else None,
            "spo2_min": float(np.nanmin(spo2_g)) if np.isfinite(spo2_g).any() else None,
        }
        tabla["FC_cmae_ecg"] = ecg_g
        tabla["FC_cmae_oximetro"] = ox_g
        tabla["SpO2_cmae"] = spo2_g

    OUT.mkdir(parents=True, exist_ok=True)
    tabla.round(3).to_csv(OUT / f"{par['id']}_alineado_1s.csv", index=False)
    return out


def limpiar_json(o):
    if isinstance(o, dict):
        return {k: limpiar_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpiar_json(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), 3)
    if isinstance(o, np.integer):
        return int(o)
    return o


def main():
    resultados = []
    for par in PARES:
        print(f"[{par['id']}] leyendo {par['powerlab']} ...")
        pl = leer_powerlab(PL_DIR / par["powerlab"])
        dest = exportar_csv_powerlab(pl, par["powerlab"])
        print(f"   CSV -> {dest.relative_to(ROOT)}  ({len(pl):,} filas, {pl['bloque'].nunique()} bloques)")
        r = analizar_par(par, pl)
        m = r["metricas"]
        print(f"   ventana {r['ventana']['duracion_s']} s | FC MAE {m['hr'].get('mae')} | FR MAE {m['br'].get('mae')}"
              f" | onda r {r['desfase']['onda']['r']} @ {r['desfase']['onda']['lag_s']} s")
        resultados.append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cruce.json").write_text(json.dumps(limpiar_json(resultados), ensure_ascii=False,
                                               separators=(",", ":")), encoding="utf-8")
    print(f"JSON -> {(OUT / 'cruce.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
