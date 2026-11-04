// Formatos de números, horas y duraciones (es-CL: "1.284", "12,5").

export const pad = (n) => String(n).padStart(2, "0");

export function fmt(v, d = 0) {
  if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** Valor de un dato del sensor: enteros sin decimales; valores chicos (simulador) con 2. */
export function fmtVal(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  if (Number.isInteger(v)) return fmt(v);
  return Math.abs(v) < 10 ? fmt(v, 2) : fmt(v, 1);
}

export const stampOf = (d) =>
  `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;

export const clock = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

export function mmss(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600);
  return (h ? h + ":" : "") + pad(Math.floor(s / 60) % 60) + ":" + pad(s % 60);
}

/** Hora del PC que corresponde a t segundos desde el inicio. */
export function clockAt(t0Wall, t) {
  if (!t0Wall) return "—";
  return clock(new Date(new Date(t0Wall).getTime() + t * 1000));
}

export const defaultFileName = (proto, stamp) =>
  proto === "seq" ? `MR60BHA1_mediciones_${stamp}.csv` : `MR60BHA1_experimento_${stamp}.csv`;

export function finalFileName(file, proto, stamp) {
  let n = (file || "").trim() || defaultFileName(proto, stamp);
  if (!n.toLowerCase().endsWith(".csv")) n += ".csv";
  return n;
}

/** "Puerto COM4 · 115.200 baudios" o "Simulador (sin hardware)". */
export function sourceLabel(src, port, baud) {
  return src === "sim" ? "Simulador (sin hardware)" : `Puerto ${port || "—"} · ${fmt(+baud)} baudios`;
}
