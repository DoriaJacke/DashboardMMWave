// Matemática de los gráficos (portada del prototipo de diseño):
// escalas "redondas", búsqueda binaria, trazado con reducción mín/máx,
// cortes en huecos y filtro Savitzky-Golay.

/** Primer índice con a[i].t >= x (a ordenado por t). */
export function lb(a, x) {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (a[m].t < x) lo = m + 1;
    else hi = m;
  }
  return lo;
}

/** Escala con números redondos entre lo y hi, con ~n divisiones. */
export function nice(lo, hi, n) {
  const raw = (hi - lo) / Math.max(1, n);
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const f = raw / p;
  const st = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
  const a = Math.floor(lo / st) * st;
  const b = Math.ceil(hi / st) * st;
  const ticks = [];
  for (let v = a; v <= b + st * 1e-6; v += st) ticks.push(+v.toFixed(10));
  return { lo: a, hi: b, ticks, st };
}

/**
 * Trazado SVG de los puntos n0..n1. Con más de 1,5 puntos por píxel se reduce
 * a mínimo/máximo por bloque. Un salto mayor que `gap` en X corta la línea.
 */
export function pathOf(n0, n1, X, V, sx, sy, gap, PW) {
  const n = n1 - n0 + 1;
  if (n <= 0) return "";
  const step = Math.max(1, Math.floor(n / (PW * 1.5)));
  let d = "";
  let prev = null;
  for (let i = n0; i <= n1; i += step) {
    const j1 = Math.min(n1, i + step - 1);
    let order = [i];
    if (step > 1) {
      let mn = -1;
      let mx = -1;
      for (let j = i; j <= j1; j++) {
        const v = V(j);
        if (v == null) continue;
        if (mn < 0 || v < V(mn)) mn = j;
        if (mx < 0 || v > V(mx)) mx = j;
      }
      order = mn < 0 ? [] : mn < mx ? [mn, mx] : [mx, mn];
    }
    for (const j of order) {
      const v = V(j);
      if (v == null) {
        prev = null;
        continue;
      }
      const xv = X(j);
      d += (prev === null || xv - prev > gap ? "M" : "L") + sx(xv).toFixed(1) + " " + sy(v).toFixed(1);
      prev = xv;
    }
  }
  return d;
}

/** Coeficientes de suavizado Savitzky-Golay (ventana 2h+1, polinomio de orden p). */
export function sgCoef(h, p) {
  const m = p + 1;
  const M = [];
  for (let a = 0; a < m; a++) {
    M.push([]);
    for (let b = 0; b < m; b++) {
      let s = 0;
      for (let i = -h; i <= h; i++) s += Math.pow(i, a + b);
      M[a].push(s);
    }
    M[a].push(a === 0 ? 1 : 0);
  }
  for (let c = 0; c < m; c++) {
    let pv = c;
    for (let r = c + 1; r < m; r++) if (Math.abs(M[r][c]) > Math.abs(M[pv][c])) pv = r;
    [M[c], M[pv]] = [M[pv], M[c]];
    for (let r = 0; r < m; r++) {
      if (r === c) continue;
      const f = M[r][c] / M[c][c];
      for (let k = c; k <= m; k++) M[r][k] -= f * M[c][k];
    }
  }
  const x = M.map((r, i) => r[m] / r[i]);
  const out = [];
  for (let i = -h; i <= h; i++) {
    let s = 0;
    for (let a = 0; a < m; a++) s += x[a] * Math.pow(i, a);
    out.push(s);
  }
  return out;
}

/** Ventana en muestras (impar y mayor que el orden), como plots.savgol_window. */
export function sgWindow(sgw, sgo, dt) {
  let w = Math.round(sgw / dt);
  if (w % 2 === 0) w++;
  const mn = (sgo + 1) % 2 ? sgo + 1 : sgo + 2;
  return Math.max(w, mn);
}

/** Mediana de los intervalos positivos entre los primeros 200 puntos. */
export function medianDt(pts, fallback = 0.1) {
  if (pts.length < 3) return fallback;
  const ds = [];
  for (let i = 1; i < Math.min(pts.length, 200); i++) {
    const d = pts[i].t - pts[i - 1].t;
    if (d > 0) ds.push(d);
  }
  ds.sort((a, b) => a - b);
  return ds[ds.length >> 1] || fallback;
}

/** Punto más cercano a x dentro de ±1,5 s, o null. */
export function nearest(pts, x, tol = 1.5) {
  if (!pts.length) return null;
  let i = lb(pts, x);
  if (i >= pts.length) i = pts.length - 1;
  if (i > 0 && Math.abs(pts[i - 1].t - x) < Math.abs(pts[i].t - x)) i--;
  return Math.abs(pts[i].t - x) <= tol ? pts[i] : null;
}

/** Segmento de fase vigente en el instante t. */
export function segAt(segs, t) {
  let r = null;
  for (const s of segs) {
    if (s.t0 <= t) r = s;
    else break;
  }
  return r;
}
