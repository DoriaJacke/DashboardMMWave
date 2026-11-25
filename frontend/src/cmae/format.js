// Formato de números para los gráficos de la placa CMAE (coma decimal).
// Subconjunto de dashboard-cmae/frontend/src/lib/format.js.

const cache = new Map();

function formatter(digits) {
  let f = cache.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("es-CL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    cache.set(digits, f);
  }
  return f;
}

/** Número con una cantidad fija de decimales. "—" si no hay valor. */
export function num(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return formatter(digits).format(value);
}

/** Etiqueta de un eje: tantos decimales como pida el paso entre marcas. */
export function tick(value, incr) {
  const digits = incr >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(incr) - 1e-9));
  return value.toFixed(digits).replace(".", ",").replace(/^-0(,0+)?$/, "0");
}

/** Color definido en cmae/cmae.css, por ejemplo "--cm-ecg". */
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}
