// Gráfico en vivo de una o más curvas (uPlot sobre canvas).
//
// No usa estado de React para los datos: cada vez que le toca dibujar lee el
// almacén (lib/store.js), toma solo lo que cae dentro de la ventana de tiempo
// y se lo pasa a uPlot. El eje X muestra tiempo relativo ("-8 s ... 0").

import { memo, useEffect, useRef } from "react";
import uPlot from "uplot";
import { addDrawable } from "./clock";
import { cssVar, tick } from "./format";
import { store } from "./store";

const EMPTY = [];
const X_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];

function xStep(windowS) {
  for (const s of X_STEPS) if (windowS / s <= 6) return s;
  return 3600;
}

function relLabel(seconds, windowS) {
  if (Math.abs(seconds) < 0.05) return "0";
  if (windowS >= 180) return `${String(Math.round((seconds / 60) * 10) / 10).replace(".", ",")} min`;
  return `${String(seconds).replace(".", ",")} s`;
}

/**
 * Arma los datos visibles en el formato de uPlot: [tiempos, valores1, valores2, ...].
 * Si todas las curvas comparten los mismos instantes (lo normal en un mismo
 * sensor), se entregan tramos del almacén sin copiar nada. Si no (por ejemplo,
 * temperaturas de sensores con ritmos distintos), se combinan en una sola
 * línea de tiempo.
 */
function visibleData(rings, xMin) {
  let first = null;
  let aligned = true;
  for (const r of rings) {
    if (!r || !r.length) {
      aligned = false;
      continue;
    }
    if (!first) first = r;
    else if (
      r.length !== first.length ||
      r.t[r.end - 1] !== first.t[first.end - 1] ||
      r.t[r.start] !== first.t[first.start]
    ) {
      aligned = false;
    }
  }
  if (!first) return null;

  if (aligned) {
    // Un punto antes de la ventana, para que la línea entre desde el borde.
    const i0 = Math.max(first.start, first.lowerBound(xMin) - 1);
    const skip = i0 - first.start;
    const data = [first.t.subarray(i0, first.end)];
    for (const r of rings) data.push(r.v.subarray(r.start + skip, r.end));
    return data;
  }

  const tables = [];
  for (const r of rings) {
    if (!r || !r.length) continue;
    const i0 = Math.max(r.start, r.lowerBound(xMin) - 1);
    tables.push([r.t.subarray(i0, r.end), r.v.subarray(i0, r.end)]);
  }
  const joined = uPlot.join(tables);
  const data = [joined[0]];
  let j = 1;
  for (const r of rings) {
    data.push(r && r.length ? joined[j++] : new Array(joined[0].length).fill(undefined));
  }
  return data;
}

function LiveChart({ series, windowS, fps = 30, minSpan = 1, yAxis = "full", xAxis = true, lineWidth = 1.5 }) {
  const boxRef = useRef(null);

  useEffect(() => {
    const box = boxRef.current;
    const keys = series.map((s) => s.key);
    const windowMs = windowS * 1000;
    const stepMs = xStep(windowS) * 1000;
    const text = cssVar("--cm-text-3");
    const grid = cssVar("--cm-grid");
    const font = `11px ${cssVar("--cm-font")}`;
    const compact = yAxis === "compact";

    // Escala vertical "con memoria": se abre de inmediato si la curva se sale
    // y se cierra de a poco, para que el gráfico no salte con cada dato.
    const range = { lo: null, hi: null };
    const yRange = (_u, dataMin, dataMax) => {
      if (dataMin == null || dataMax == null || !Number.isFinite(dataMin) || !Number.isFinite(dataMax)) {
        return range.lo === null ? [0, 1] : [range.lo, range.hi];
      }
      const span = Math.max(dataMax - dataMin, minSpan);
      const mid = (dataMin + dataMax) / 2;
      const lo = mid - span * 0.62;
      const hi = mid + span * 0.62;
      if (range.lo === null) {
        range.lo = lo;
        range.hi = hi;
      } else {
        range.lo = lo < range.lo ? lo : range.lo + (lo - range.lo) * 0.08;
        range.hi = hi > range.hi ? hi : range.hi + (hi - range.hi) * 0.08;
      }
      return [range.lo, range.hi];
    };

    const emptyData = [EMPTY, ...keys.map(() => EMPTY)];
    const opts = {
      width: Math.max(60, box.clientWidth),
      height: Math.max(40, box.clientHeight),
      padding: [compact ? 5 : 8, 10, 0, 0],
      legend: { show: false },
      cursor: { show: false },
      select: { show: false },
      scales: {
        x: { time: false, auto: false },
        y: { auto: true, range: yRange },
      },
      axes: [
        {
          scale: "x",
          stroke: text,
          font,
          size: xAxis ? 20 : 0,
          gap: 2,
          grid: { stroke: grid, width: 1 },
          ticks: { show: false },
          // Marcas fijas en pantalla: "hace 2 s", "hace 4 s"...
          splits: (_u, _i, min, max) => {
            const out = [];
            if (min == null || max == null) return out;
            for (let v = max; v >= min - 1; v -= stepMs) out.push(v);
            return out.reverse();
          },
          // El rótulo del borde izquierdo no se escribe: se pisaría con los números del eje vertical.
          values: (u, splits) =>
            splits.map((v) =>
              xAxis && v - u.scales.x.min > stepMs * 0.3
                ? relLabel(Math.round((v - u.scales.x.max) / 100) / 10, windowS)
                : "",
            ),
        },
        {
          scale: "y",
          stroke: text,
          font: compact ? `10px ${cssVar("--cm-font")}` : font,
          size: compact ? 40 : 48,
          gap: 4,
          space: compact ? 17 : 26,
          grid: { stroke: grid, width: 1 },
          ticks: { show: false },
          // Sin datos no hay escala que mostrar.
          values: (_u, splits, _i, _space, incr) => splits.map((v) => (range.lo === null ? "" : tick(v, incr))),
        },
      ],
      series: [
        {},
        ...series.map((s) => ({
          stroke: cssVar(s.color),
          width: s.width ?? lineWidth,
          points: { show: false },
          spanGaps: true,
        })),
      ],
    };

    const u = new uPlot(opts, emptyData, box);
    u.setScale("x", { min: -windowMs, max: 0 });

    let lastT = NaN;
    let lastRev = -1;
    let lastEpoch = store.epoch;

    const draw = (t) => {
      if (store.epoch !== lastEpoch) {
        lastEpoch = store.epoch;
        range.lo = null;
        range.hi = null;
        lastRev = -1;
      }
      const rings = keys.map((k) => store.get(k));
      let rev = 0;
      for (const r of rings) if (r) rev += r.rev;
      if (t === lastT && rev === lastRev) return; // nada cambió: no se redibuja
      lastT = t;
      lastRev = rev;

      if (t === null) {
        u.batch(() => {
          u.setData(emptyData, false);
          u.setScale("x", { min: -windowMs, max: 0 });
        });
        return;
      }
      const xMin = t - windowMs;
      const data = visibleData(rings, xMin) || emptyData;
      u.batch(() => {
        u.setData(data, false);
        u.setScale("x", { min: xMin, max: t });
      });
    };

    const remove = addDrawable(fps, draw, `grafico ${keys[0]}`);
    const observer = new ResizeObserver(() => {
      const w = box.clientWidth;
      const h = box.clientHeight;
      if (w > 0 && h > 0 && (w !== u.width || h !== u.height)) {
        u.setSize({ width: w, height: h });
        lastRev = -1;
      }
    });
    observer.observe(box);

    return () => {
      remove();
      observer.disconnect();
      u.destroy();
    };
  }, [series, windowS, fps, minSpan, yAxis, xAxis, lineWidth]);

  return <div ref={boxRef} className="cm-chart" />;
}

export default memo(LiveChart);
