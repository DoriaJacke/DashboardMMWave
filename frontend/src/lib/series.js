// Convierte los registros que envía el backend ({t, m, f, k, v}) en las series
// de los gráficos y en los intervalos de fase para el sombreado.

import { SHADE, isSeqLike, phaseSeq, plannedDurations } from "./phases";

export function emptyStore() {
  return { hr: [], br: [], bwFrames: [], phaseMarks: [], markers: [], dist: [], cmae: {}, nEnd: 0, nRecords: 0 };
}

/**
 * Agrega registros nuevos al almacén (se llama con el historial y con cada incremento).
 * cmae: muestras de la placa CMAE ya en la escala de tiempo de la adquisición,
 * {señal: [[t...], [v...]]} (backend/cmae/sincronia.py). Quedan en store.cmae[señal] como {t, v}.
 */
export function ingest(store, records, dist, cmae) {
  for (const [key, pair] of Object.entries(cmae || {})) {
    const list = store.cmae[key] || (store.cmae[key] = []);
    const [ts, vs] = pair;
    for (let i = 0; i < ts.length; i++) list.push({ t: ts[i], v: vs[i] });
  }
  for (const r of records || []) {
    store.nRecords++;
    switch (r.k) {
      case "HR":
        if (r.v != null) store.hr.push({ t: r.t, v: r.v, m: r.m, ph: r.f });
        break;
      case "BR":
        if (r.v != null) store.br.push({ t: r.t, v: r.v, m: r.m, ph: r.f });
        break;
      case "BW":
        store.bwFrames.push(r);
        break;
      case "PHASE":
      case "END":
        store.phaseMarks.push({ k: r.k, t: r.t, m: r.m, ph: r.f });
        if (r.k === "END") store.nEnd++;
        break;
      case "MARK":
        store.markers.push({ label: r.v, t: r.t, m: r.m, ph: r.f });
        break;
      default:
        break;
    }
  }
  for (const [t, v] of dist || []) store.dist.push({ t, v });
}

/**
 * Las 5 muestras de cada línea BW se reparten en el intervalo entre líneas,
 * igual que plots.extract_series (intervalo = mediana entre tramas).
 */
export function expandBW(frames) {
  const out = [];
  if (!frames.length) return out;
  let dt = 0.2;
  if (frames.length > 1) {
    const ds = [];
    for (let i = 1; i < frames.length; i++) ds.push(frames[i].t - frames[i - 1].t);
    ds.sort((a, b) => a - b);
    dt = ds[ds.length >> 1] || 0.2;
  }
  for (const f of frames) {
    const vals = Array.isArray(f.v) ? f.v : [];
    const n = vals.length || 5;
    vals.forEach((v, k) => {
      if (v != null) out.push({ t: f.t - dt + ((k + 1) * dt) / n, v, m: f.m, ph: f.f });
    });
  }
  return out;
}

/** Intervalos {ph, m, t0, t1} a partir de las marcas PHASE/END (como data_io.phase_intervals). */
export function segmentsFrom(phaseMarks, tEnd) {
  const out = [];
  for (let i = 0; i < phaseMarks.length; i++) {
    const p = phaseMarks[i];
    if (p.k !== "PHASE") continue;
    const next = phaseMarks[i + 1];
    out.push({ ph: p.ph, m: p.m, t0: p.t, t1: next ? next.t : Math.max(p.t, tEnd) });
  }
  return out;
}

/**
 * Dominio, fases y filtro de la ventana en vivo.
 *  - "med": toda la duración planificada de la medición actual; las fases que
 *    faltan se dibujan atenuadas (planificadas desde el fin previsto de la actual).
 *  - "60": últimos 60 s.  - "300": últimos 5 min.  - "todo": desde el inicio.
 */
export function liveWindow({ win, status, params, proto, segs }) {
  const t = status.t;
  const fase = status.fase;
  const m = status.medicion;
  const result = { dom: [0, Math.max(t, 60)], segs, filter: null, emptyMsg: "Sin datos en esta ventana.", m };

  // La fase en curso termina (según lo planificado) en t + lo que le queda.
  const open = segs.length ? segs[segs.length - 1] : null;
  const closeOpen = (list) =>
    list.map((s) =>
      s === open && SHADE.includes(fase) && s.ph === fase && status.remaining_s != null
        ? { ...s, t1: Math.max(s.t1, t + status.remaining_s) }
        : s,
    );

  if (isSeqLike(proto) && win === "med") {
    const phases = phaseSeq(proto, params);
    const durs = plannedDurations(params);
    // Un monitoreo sin duración fija se dibuja con 60 s planificados y crece con el tiempo.
    const dur = (ph) => durs[ph] || 60;
    const per = phases.reduce((sum, ph) => sum + dur(ph), 0);
    const mine = closeOpen(segs.filter((s) => s.m === m && phases.includes(s.ph)));
    let shade;
    let s0;
    if (mine.length) {
      s0 = mine[0].t0;
      shade = [...mine];
      const cur = phases.indexOf(fase);
      if (cur >= 0 && shade[shade.length - 1].ph === fase) {
        let x = shade[shade.length - 1].t1;
        for (const ph of phases.slice(cur + 1)) {
          shade.push({ ph, m, t0: x, t1: x + dur(ph), planned: true });
          x += dur(ph);
        }
      }
    } else {
      s0 = t;
      let x = t;
      shade = phases.map((ph) => {
        const r = { ph, m, t0: x, t1: x + dur(ph), planned: true };
        x += dur(ph);
        return r;
      });
      if (fase === "ESPERA") result.emptyMsg = proto === "apnea" ? "La maniobra se graba al confirmar la posición." : `La medición ${m} se graba al confirmar la posición.`;
    }
    const end = Math.max(s0 + per, shade.length ? shade[shade.length - 1].t1 : 0, t);
    Object.assign(result, { dom: [s0, end], segs: shade, filter: (p) => p.m === m });
  } else if (win === "60") {
    result.dom = [t - 60, t];
    result.segs = closeOpen(segs);
  } else if (win === "300") {
    // Hasta completar 5 min se ve desde el inicio de lo grabado; después, los últimos 5 min.
    const lo = segs.length ? segs[0].t0 : 0;
    result.dom = t - lo < 300 ? [lo, lo + 300] : [t - 300, t];
    result.segs = closeOpen(segs);
  } else {
    result.segs = closeOpen(segs);
  }
  if (fase === "CONECTANDO") result.emptyMsg = "Conectando con el radar…";
  return result;
}

/** Dominio de tiempo de los datos de un resultado (primer y último punto). */
export function dataDomain(series) {
  let a = Infinity;
  let b = -Infinity;
  for (const s of series) {
    if (!s.length) continue;
    a = Math.min(a, s[0].t);
    b = Math.max(b, s[s.length - 1].t);
  }
  return Number.isFinite(a) ? [a, b + 0.5] : [0, 1];
}
