"""
Convierte resultados/cruce.json en los archivos de datos del dashboard (resultados/dashboard/*.json).
Uso:  python analisis_powerlab/exportar_dashboard.py
"""
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RES = AQUI / "resultados"
OUT = RES / "dashboard"
CODIGO = (AQUI / "cruce_powerlab_radar.py").read_text(encoding="utf-8")

SG_PAR = "par4"   # el filtro Savitzky-Golay opcional se ofrece en la prueba simulada de 10 min
R = json.loads((RES / "cruce.json").read_text(encoding="utf-8"))


def rnd(x, nd=1):
    return None if x is None else round(x, nd)


def meta(entrada):
    return [{"label": "cruce_powerlab_radar.py", "value": CODIGO, "type": "code", "lang": "python"},
            {"label": "Entrada", "value": entrada}]


resumen, metricas, series, ondas, puntos, fases, eventos = [], [], [], [], [], [], []

for r in R:
    p = r["id"]
    m = r["metricas"]
    fr_usa_onda = any("Canal 4" in a for a in r["alertas"])
    fc_ref = m["hr"]
    fr_ref = m["br_onda"] if fr_usa_onda else m["br"]
    bl = [b for b in r["bloques_powerlab"] if b["solape_s"] > 0]
    resumen.append({
        "par": p, "nombre": r["nombre"],
        "archivo_powerlab": r["archivos"]["powerlab"], "archivo_radar": r["archivos"]["radar"],
        "archivo_cmae": r["archivos"]["cmae"] or "",
        "inicio": r["ventana"]["inicio"].replace("T", " "), "fin": r["ventana"]["fin"][11:],
        "duracion_s": r["ventana"]["duracion_s"],
        "bloques_total": len(r["bloques_powerlab"]),
        "bloque_usado": ", ".join(str(b["bloque"]) for b in bl),
        "periodo_hr_s": rnd(r["periodo_radar_s"]["HR"], 1),
        "periodo_bw_s": rnd(r["periodo_radar_s"]["BW_trama"], 1),
        "fc_mae": rnd(fc_ref.get("mae")), "fc_sesgo": rnd(fc_ref.get("sesgo")),
        "fc_r": rnd(fc_ref.get("r"), 2), "fc_tol": rnd(fc_ref.get("dentro_tol"), 0),
        "fr_mae": rnd(fr_ref.get("mae")), "fr_sesgo": rnd(fr_ref.get("sesgo")),
        "fr_r": rnd(fr_ref.get("r"), 2), "fr_tol": rnd(fr_ref.get("dentro_tol"), 0),
        "fr_ref": "onda (canal 1)" if fr_usa_onda else "canal 4",
        "fr_clave": "onda" if fr_usa_onda else "c4",
        "onda_r": rnd(abs(r["desfase"]["onda"]["r"]) if r["desfase"]["onda"]["r"] is not None else None, 2),
        "onda_invertida": bool(r["desfase"]["onda"]["r"] is not None and r["desfase"]["onda"]["r"] < 0),
        "onda_lag_s": rnd(r["desfase"]["onda"]["lag_s"], 1),
        "cob_fc": rnd(r["cobertura"]["hr_radar"], 0), "cob_fr": rnd(r["cobertura"]["br_radar"], 0),
        "alertas": r["alertas"],
    })

    def fila(var, clave, comp, mm, tol):
        if not mm or mm.get("n", 0) < 3:
            metricas.append({"clave": f"{p}-{var}-{clave}", "par": p, "variable": var, "comparacion": comp,
                             "n": mm.get("n", 0) if mm else 0, "mae": None, "rmse": None, "sesgo": None,
                             "loa_inf": None, "loa_sup": None, "r": None, "dentro_tol": None,
                             "tolerancia": tol, "ref_media": None, "radar_media": None})
            return
        metricas.append({"clave": f"{p}-{var}-{clave}", "par": p, "variable": var, "comparacion": comp,
                         "n": mm["n"], "mae": rnd(mm["mae"]), "rmse": rnd(mm["rmse"]), "sesgo": rnd(mm["sesgo"]),
                         "loa_inf": rnd(mm["loa_inf"]), "loa_sup": rnd(mm["loa_sup"]), "r": rnd(mm["r"], 2),
                         "dentro_tol": rnd(mm["dentro_tol"], 0), "tolerancia": tol,
                         "ref_media": rnd(mm["ref_media"]), "radar_media": rnd(mm["est_media"])})

    fila("FC", "c3", "Radar vs PowerLab canal 3", m["hr"], "±5 lpm")
    if p == SG_PAR:
        sg = r["savgol"]
        fila("FC", "c3_sg", f"Radar vs PowerLab canal 3 filtrado (Savitzky-Golay {sg['ventana_s']} s, orden {sg['orden']})",
             m["hr_sg"], "±5 lpm")
    fila("FC", "onda", "Radar vs PowerLab onda de pulso (canal 2)", m["hr_onda"], "±5 lpm")
    fila("FR", "c4", "Radar vs PowerLab canal 4", m["br"], "±2 rpm")
    fila("FR", "onda", "Radar vs PowerLab onda respiratoria (canal 1)", m["br_onda"], "±2 rpm")
    if "cmae" in r:
        c = r["cmae"]
        fila("FC", "cmae_ecg", "Radar vs CMAE ECG", c["radar_vs_ecg"], "±5 lpm")
        fila("FC", "cmae_ox", "Radar vs CMAE oxímetro", c["radar_vs_ox"], "±5 lpm")
        fila("FC", "ecg_vs_pl", "CMAE ECG vs PowerLab canal 3 (control)", c["ecg_vs_powerlab"], "±5 lpm")
        fila("FC", "ox_vs_pl", "CMAE oxímetro vs PowerLab canal 3 (control)", c["ox_vs_powerlab"], "±5 lpm")

    s = r["serie"]
    for i, t in enumerate(s["t"]):
        row = {"par": p, "t": t}
        for k in (["hr_pl_sg"] if p == SG_PAR else []) + ["hr_pl", "hr_pl_onda", "hr_radar", "br_pl", "br_pl_onda", "br_radar", "dist",
                  "hr_cmae_ecg", "hr_cmae_ox", "spo2"]:
            if k in s:
                row[k] = s[k][i]
        series.append(row)

    fs = r["onda"]["fs"]
    for i, (a, b) in enumerate(zip(r["onda"]["pl"], r["onda"]["radar"])):
        if a is None and b is None:
            continue
        ondas.append({"par": p, "t": round(i / fs, 1), "pl": a, "radar": b})

    for a, b in r["pares_ba"]["hr"]:
        puntos.append({"par": p, "variable": "FC", "ref_clave": "c3", "ref": a, "radar": b})
    for a, b in r["pares_ba"]["br"]:
        puntos.append({"par": p, "variable": "FR", "ref_clave": "c4", "ref": a, "radar": b})
    for a, b in r["pares_ba_onda"]["br"]:
        puntos.append({"par": p, "variable": "FR", "ref_clave": "onda", "ref": a, "radar": b})

    for f in r["por_fase"]:
        fases.append({"clave": f"{p}-{f['fase']}", "par": p, "fase": f["fase"], "condicion": f["condicion"],
                      "duracion_s": f["duracion_s"],
                      "fc_n": f["hr"].get("n", 0), "fc_mae": rnd(f["hr"].get("mae")), "fc_sesgo": rnd(f["hr"].get("sesgo")),
                      "fr_n": f["br"].get("n", 0), "fr_mae": rnd(f["br"].get("mae")), "fr_sesgo": rnd(f["br"].get("sesgo"))})
    for f in r["fases"]:
        eventos.append({"par": p, "t": round(f["ini"], 1), "fin": round(f["fin"], 1), "tipo": "FASE",
                        "valor": f["condicion"]})
    for e in r["eventos"]:
        eventos.append({"par": p, "t": round(e["t"], 1), "fin": None, "tipo": "RADAR_" + e["tipo"], "valor": e["valor"]})
    for c in r["comentarios_powerlab"]:
        eventos.append({"par": p, "t": round(c["t"], 1), "fin": None, "tipo": "COMENTARIO_POWERLAB", "valor": c["texto"]})

OUT.mkdir(parents=True, exist_ok=True)
ent = "datos powerlab/*.txt + datos/MR60BHA1_*.csv (4 pares)"
for nombre, rows, con_meta in [("resumen", resumen, True), ("metricas", metricas, True), ("series", series, False),
                               ("ondas", ondas, False), ("puntos", puntos, False), ("fases", fases, False),
                               ("eventos", eventos, False)]:
    doc = {"rows": rows, "meta": meta(ent)} if con_meta else rows
    (OUT / f"{nombre}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(nombre, len(rows), (OUT / f"{nombre}.json").stat().st_size // 1024, "KB")
