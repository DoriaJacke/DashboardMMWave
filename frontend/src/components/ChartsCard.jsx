// Tarjeta de gráficos (compartida por En vivo y Resultado): tres filas BW, HR y BR
// con eje X compartido en modo Tiempo, sombreado de fases, marcas, filtro SG,
// tooltip unificado y zoom (arrastrar, botones o doble clic para restablecer).

import { Fragment, memo, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Settings2, ZoomIn, ZoomOut } from "lucide-react";
import { lb, medianDt, nearest, nice, pathOf, segAt, sgCoef, sgWindow } from "../lib/chartMath";
import { clockAt, fmt, fmtVal } from "../lib/format";
import { PH, SHADE } from "../lib/phases";
import { useSize } from "../lib/hooks";

const ML = 58;
const MR = 16;
const PT = 6;
const DEFS = [
  { title: "Onda de respiración BW", unit: "sin unidad · 5 muestras por línea BW", short: "", key: "BW", def: [0, 255] },
  { title: "Frecuencia cardíaca HR", unit: "BPM", short: "BPM", key: "HR", def: [40, 120] },
  { title: "Frecuencia respiratoria BR", unit: "resp/min", short: "resp/min", key: "BR", def: [0, 30] },
];
const PARTIAL_MSG = "Sin datos de onda BW. El firmware puede estar enviando solo HR y BR.";
const WIN_LABEL = { med: "Medición actual", 60: "Últimos 60 s", todo: "Todo" };
const muted = { color: "var(--color-neutral-700)" };

const decimals = (st) => (st < 0.1 ? 2 : st < 1 ? 1 : 0);

/** Alto del área de trazado de cada gráfico según el alto disponible. */
function layout(Hc, idx) {
  const xlab = idx ? 3 * 22 : 22 + 6 + 6;
  const avail = Hc - 20 - 6 - 3 * PT - xlab;
  let TH = 26;
  let PHc = Math.floor((avail - 3 * TH) / 3);
  const compact = PHc < 46;
  if (compact) {
    TH = 0;
    PHc = Math.floor(avail / 3);
  }
  return { TH, compact, PHc: Math.max(30, Math.min(220, PHc)) };
}

function buildCharts(o) {
  const { series, idx, dom, segs, now, sg, sgo, sgN, shade, partial, emptyMsg, markers, W, PHc, TH, compact, zoom } = o;
  const PW = Math.max(240, W - ML - MR);
  const z = zoom || [0, 1];
  return DEFS.map((df, ci) => {
    const pts = series[ci];
    let d0;
    let d1;
    if (idx) {
      d0 = 0;
      d1 = Math.max(1, pts.length - 1);
    } else [d0, d1] = dom;
    const sp = d1 - d0 || 1;
    const a = d0 + z[0] * sp;
    const b = d0 + z[1] * sp;
    let i0;
    let i1;
    if (idx) {
      i0 = Math.max(0, Math.ceil(a));
      i1 = Math.min(pts.length - 1, Math.floor(b));
    } else {
      i0 = lb(pts, a);
      i1 = lb(pts, b + 1e-9) - 1;
    }
    const n = Math.max(0, i1 - i0 + 1);

    let lo = Infinity;
    let hi = -Infinity;
    const stp = Math.max(1, Math.floor(n / 3000));
    for (let i = i0; i <= i1; i += stp) {
      const v = pts[i].v;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (!n) [lo, hi] = df.def;
    else {
      const pd = (hi - lo) * 0.08 || 2;
      lo -= pd;
      hi += pd;
    }
    const ny = nice(lo, hi, PHc < 70 ? 2 : PHc < 110 ? 3 : 4);
    lo = ny.lo;
    hi = ny.hi;
    const sx = (x) => ML + ((x - a) / (b - a)) * PW;
    const sy = (v) => PT + PHc - ((v - lo) / (hi - lo)) * PHc;
    const X = (j) => (idx ? j : pts[j].t);
    const path = pathOf(i0, i1, X, (j) => pts[j].v, sx, sy, idx ? Infinity : 2.5, PW);

    // Filtro Savitzky-Golay (solo BW): no cruza huecos entre tramos.
    let fpath = "";
    if (ci === 0 && sg && n > 0) {
      const h = (sgN - 1) / 2;
      const c = sgCoef(h, sgo);
      const dt = o.dt;
      const f = {};
      for (let i = Math.max(0, i0 - h); i <= Math.min(pts.length - 1, i1 + h); i++) {
        if (i - h < 0 || i + h >= pts.length || pts[i + h].t - pts[i - h].t > 2 * h * dt * 1.6) {
          f[i] = null;
          continue;
        }
        let s = 0;
        for (let k = -h; k <= h; k++) s += c[k + h] * pts[i + k].v;
        f[i] = s;
      }
      fpath = pathOf(i0, i1, X, (j) => f[j] ?? null, sx, sy, idx ? Infinity : 2.5, PW);
    }

    const dots = [];
    if (n > 0 && n <= PW / 7) for (let i = i0; i <= i1; i++) dots.push({ x: sx(X(i)), y: sy(pts[i].v) });

    const nx = nice(a, b, Math.max(3, Math.round(PW / 110)));
    const xTicks = nx.ticks
      .filter((v) => v >= a - 1e-9 && v <= b + 1e-9)
      .map((v) => ({ x: sx(v), label: fmt(v, nx.st < 1 ? 1 : 0) }));
    const yTicks = ny.ticks.map((v) => ({ y: sy(v), label: fmt(v, decimals(ny.st)) }));

    const rects = [];
    if (!idx && shade) {
      for (const s of segs) {
        if (!SHADE.includes(s.ph)) continue;
        const x0 = Math.max(s.t0, a);
        const x1 = Math.min(s.t1, b);
        if (x1 <= x0) continue;
        const w = sx(x1) - sx(x0);
        rects.push({
          x: sx(x0), w, fill: PH[s.ph].tint, ink: PH[s.ph].ink, label: s.ph,
          op: now != null && s.t0 > now ? 0.45 : 1, lx: sx(x0) + w / 2, showLabel: ci === 0 && w > 52,
        });
      }
    }

    const marks = [];
    for (const mk of markers) {
      let xv;
      if (idx) {
        if (!pts.length || mk.t < pts[0].t - 0.5 || mk.t > pts[pts.length - 1].t + 0.5) continue;
        let j = lb(pts, mk.t);
        if (j >= pts.length) j = pts.length - 1;
        xv = j;
      } else xv = mk.t;
      if (xv < a || xv > b) continue;
      marks.push({ x: sx(xv), mk });
    }

    const showX = idx || ci === 2;
    const H = PT + PHc + (showX ? 22 : 6);
    const nowX = now != null && !idx && now >= a && now <= b ? sx(now) : null;
    const empty = n ? "" : ci === 0 && partial ? PARTIAL_MSG : emptyMsg;
    return {
      ci, df, pts, a, b, idx, PW, W, H, TH, PHc, compact, path, fpath, dots, xTicks, yTicks, rects, marks,
      showX, nowX, empty, rawOp: sg && ci === 0 ? 0.35 : 1,
    };
  });
}

function tooltipLines(c, charts, frac, segs, markers, t0Wall) {
  const lines = [];
  if (!c.idx) {
    const xv = c.a + frac * (c.b - c.a);
    lines.push({ k: "Tiempo", v: `${fmt(xv, 1)} s` });
    lines.push({ k: "Hora", v: clockAt(t0Wall, xv) });
    const sg = segAt(segs, xv);
    if (sg && PH[sg.ph] && xv < sg.t1) lines.push({ k: "Fase", v: PH[sg.ph].name });
    const mk = markers.find((m) => Math.abs(m.t - xv) <= (c.b - c.a) * 0.01 + 0.3);
    if (mk) lines.push({ k: "Marca", v: mk.label });
    charts.forEach((cc) => {
      const p = nearest(cc.pts, xv);
      lines.push({ k: cc.df.key, v: p ? fmtVal(p.v) + (cc.df.short ? ` ${cc.df.short}` : "") : "—" });
    });
  } else {
    const i = Math.round(c.a + frac * (c.b - c.a));
    const p = c.pts[i];
    lines.push({ k: "Índice", v: fmt(i) });
    if (p) {
      lines.push({ k: "Tiempo", v: `${fmt(p.t, 1)} s` });
      lines.push({ k: "Hora", v: clockAt(t0Wall, p.t) });
      lines.push({ k: c.df.key, v: fmtVal(p.v) + (c.df.short ? ` ${c.df.short}` : "") });
    }
  }
  return lines;
}

function markTitle(mk, proto, t0Wall) {
  const where = proto === "seq" && mk.m ? ` · medición ${mk.m} · ${PH[mk.ph]?.name ?? mk.ph}` : "";
  return `${mk.label}${where} · t = ${fmt(mk.t, 1)} s · ${clockAt(t0Wall, mk.t)}`;
}

function ChartRow({ c, sgLegend, hover, brush, tip, handlers, proto, t0Wall, onReset }) {
  const yb = PT + c.PHc;
  const xr = ML + c.PW;
  const hovHere = hover && (!c.idx || hover.ci === c.ci);
  const brHere = brush && (!c.idx || brush.ci === c.ci);
  return (
    <div style={{ position: "relative" }}>
      <div
        style={{
          display: c.compact ? "none" : "flex", alignItems: "baseline", gap: 10, height: c.TH,
          boxSizing: "border-box", padding: "6px 16px 0 58px", overflow: "hidden",
        }}
      >
        <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 16 }}>{c.df.title}</span>
        <span style={{ fontSize: 12, ...muted }}>{c.df.unit}</span>
        <span style={{ marginLeft: "auto", alignSelf: "center", display: "flex", gap: 14, fontSize: 12, lineHeight: 1.2, whiteSpace: "nowrap", ...muted }}>
          {c.ci === 0 &&
            sgLegend.map((lg) => (
              <span key={lg.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 16, height: 0, borderTop: lg.line }} />
                {lg.label}
              </span>
            ))}
        </span>
      </div>
      <svg width={c.W} height={c.H} style={{ display: "block" }} role="img" aria-label={`${c.df.title}${c.empty ? `: ${c.empty}` : ""}`}>
        {c.rects.map((r, i) => (
          <rect key={i} x={r.x} y={PT} width={r.w} height={c.PHc} fill={r.fill} opacity={r.op} />
        ))}
        {c.marks.map((m, i) => (
          <line key={i} x1={m.x} x2={m.x} y1={PT} y2={yb} stroke="#1d2d3d" strokeWidth="1.5" strokeDasharray="5 3" />
        ))}
        {c.yTicks.map((t, i) => (
          <line key={i} x1={ML} x2={xr} y1={t.y} y2={t.y} stroke="rgba(29,31,32,.09)" />
        ))}
        {c.xTicks.map((t, i) => (
          <line key={i} x1={t.x} x2={t.x} y1={PT} y2={yb} stroke="rgba(29,31,32,.06)" />
        ))}
        <line x1={ML} x2={ML} y1={PT} y2={yb} stroke="rgba(29,31,32,.35)" />
        <line x1={ML} x2={xr} y1={yb} y2={yb} stroke="rgba(29,31,32,.35)" />
        <path d={c.path} fill="none" stroke="var(--color-accent-700)" strokeWidth="1.25" opacity={c.rawOp} strokeLinejoin="round" />
        {c.dots.map((d, i) => (
          <circle key={i} cx={d.x} cy={d.y} r="2.6" fill="var(--color-bg)" stroke="var(--color-accent-700)" strokeWidth="1.25" opacity={c.rawOp} />
        ))}
        {c.fpath && <path d={c.fpath} fill="none" stroke="var(--color-text)" strokeWidth="2.2" strokeLinejoin="round" />}
        {c.nowX != null && <line x1={c.nowX} x2={c.nowX} y1={PT} y2={yb} stroke="var(--color-text)" strokeDasharray="2 3" />}
        {hovHere && <line x1={ML + hover.px} x2={ML + hover.px} y1={PT} y2={yb} stroke="var(--color-accent-800)" />}
        {brHere && (
          <rect x={ML + Math.min(brush.a, brush.b)} y={PT} width={Math.abs(brush.b - brush.a)} height={c.PHc}
            fill="var(--color-accent-500)" opacity=".18" stroke="var(--color-accent-600)" />
        )}
      </svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: c.TH, height: c.H, pointerEvents: "none" }}>
        {c.ci === 0 &&
          c.marks.map((m, i) => (
            <div key={i} title={markTitle(m.mk, proto, t0Wall)}
              style={{
                position: "absolute", top: 6, left: m.x, transform: "translateX(-50%)", fontSize: 11, fontWeight: 500,
                lineHeight: 1, padding: "3px 6px", borderRadius: 999, background: "#1d2d3d", color: "#f2f2f3",
                zIndex: 1, whiteSpace: "nowrap", pointerEvents: "auto",
              }}>
              {m.mk.label}
            </div>
          ))}
        {c.rects.map((r, i) =>
          r.showLabel ? (
            <div key={i} style={{ position: "absolute", top: 9, left: r.lx, transform: "translateX(-50%)", fontSize: 11, letterSpacing: ".06em", fontWeight: 500, color: r.ink, opacity: r.op }}>
              {r.label}
            </div>
          ) : null,
        )}
        {c.yTicks.map((t, i) => (
          <div key={i} style={{ position: "absolute", left: 0, width: 50, textAlign: "right", top: t.y, transform: "translateY(-50%)", fontSize: 11, fontVariantNumeric: "tabular-nums", ...muted }}>
            {t.label}
          </div>
        ))}
        {c.showX &&
          c.xTicks.map((t, i) => (
            <div key={i} style={{ position: "absolute", top: yb + 3, left: t.x, transform: "translateX(-50%)", fontSize: 11, fontVariantNumeric: "tabular-nums", ...muted }}>
              {t.label}
            </div>
          ))}
        {c.compact && (
          <div style={{ position: "absolute", left: 64, top: 7, fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 13, background: "rgba(255,255,255,.85)", padding: "0 4px", borderRadius: 3 }}>
            {c.df.title} <span style={{ fontFamily: "var(--font-body)", fontWeight: 400, fontSize: 11, ...muted }}>{c.df.short}</span>
          </div>
        )}
        {c.empty && (
          <div style={{ position: "absolute", left: ML, right: MR, top: PT + c.PHc / 2 - 9, textAlign: "center", fontSize: 13, ...muted }}>
            {c.empty}
          </div>
        )}
      </div>
      <div
        onMouseMove={(e) => handlers.move(e, c)}
        onMouseDown={(e) => handlers.down(e, c)}
        onMouseUp={(e) => handlers.up(e, c)}
        onMouseLeave={handlers.leave}
        onDoubleClick={onReset}
        style={{ position: "absolute", left: ML, top: PT + c.TH, width: c.PW, height: c.PHc, cursor: "crosshair" }}
      />
      {tip && (
        <div
          style={{
            position: "absolute", top: 30, left: tip.left, width: 200, pointerEvents: "none", background: "var(--color-bg)",
            border: "1px solid var(--bs-border-color)", borderRadius: 6, boxShadow: "var(--shadow-lg)", padding: "8px 10px",
            fontSize: 12, display: "flex", flexDirection: "column", gap: 2, zIndex: 2,
          }}
        >
          {tip.lines.map((l, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <span style={muted}>{l.k}</span>
              <span style={{ fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{l.v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Área de los tres gráficos: mide su espacio y reparte la altura. */
function ChartsArea({ data, view, zoom, setZoom, proto, sgInfo }) {
  const [ref, size] = useSize();
  const [hover, setHover] = useState(null);
  const [brush, setBrush] = useState(null);
  const drag = useRef(null);
  const idx = view.x === "i";
  const lay = layout(size.h || 460, idx);

  const charts = useMemo(
    () =>
      size.w
        ? buildCharts({
            series: data.series, idx, dom: data.dom, segs: data.segs, now: data.now, sg: view.sg, sgo: +view.sgo,
            sgN: sgInfo.sgN, dt: sgInfo.dt, shade: view.shade && proto === "seq", partial: data.partial,
            emptyMsg: data.emptyMsg, markers: data.markers, W: size.w, ...lay, zoom,
          })
        : [],
    // data.version cambia cuando llegan datos nuevos
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, idx, view.sg, view.sgo, view.shade, sgInfo, size.w, lay.PHc, lay.TH, zoom, proto],
  );

  const handlers = {
    move: (e, c) => {
      const px = Math.max(0, Math.min(c.PW, e.nativeEvent.offsetX));
      setHover({ ci: c.ci, px });
      if (drag.current) setBrush({ ci: c.ci, a: drag.current.a, b: px });
    },
    down: (e) => {
      drag.current = { a: e.nativeEvent.offsetX };
    },
    up: (e, c) => {
      const d = drag.current;
      drag.current = null;
      if (!d) return;
      const px = e.nativeEvent.offsetX;
      setBrush(null);
      if (Math.abs(px - d.a) < 6) return;
      const zz = zoom || [0, 1];
      const w = zz[1] - zz[0];
      setZoom([zz[0] + (Math.min(d.a, px) / c.PW) * w, zz[0] + (Math.max(d.a, px) / c.PW) * w]);
    },
    leave: () => {
      drag.current = null;
      setHover(null);
      setBrush(null);
    },
  };

  let tip = null;
  if (hover && charts[hover.ci]) {
    const c = charts[hover.ci];
    const lines = tooltipLines(c, charts, hover.px / c.PW, data.segs, data.markers, data.t0Wall);
    const left = ML + hover.px + 14 + 210 > size.w ? ML + hover.px - 214 : ML + hover.px + 14;
    tip = { ci: hover.ci, lines, left };
  }

  const sgLegend = view.sg
    ? [
        { line: "1.5px solid var(--color-accent-700)", label: "BW original (atenuada)" },
        { line: "2.5px solid var(--color-text)", label: `Filtrada Savitzky-Golay (${sgInfo.sgN} muestras, orden ${view.sgo})` },
      ]
    : [];

  return (
    <div ref={ref} style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 2, userSelect: "none", minWidth: 0 }}>
      {charts.map((c) => (
        <ChartRow key={c.ci} c={c} sgLegend={sgLegend} hover={hover} brush={brush} tip={tip && tip.ci === c.ci ? tip : null}
          handlers={handlers} proto={proto} t0Wall={data.t0Wall} onReset={() => setZoom(null)} />
      ))}
      <div style={{ paddingLeft: 58, fontSize: 12, display: "flex", justifyContent: "space-between", paddingTop: 2, ...muted }}>
        <span>{idx ? "Eje X · Índice de muestra de cada serie" : "Eje X compartido · Tiempo (s) desde el inicio"}</span>
        <span>Arrastra para acercar · doble clic para restablecer</span>
      </div>
    </div>
  );
}

function OptionsPanel({ isLive, isResult, proto, view, setView, medOptions, shadeDisabled, sgNote, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const wins = (proto === "seq" ? ["med"] : []).concat(["60", "todo"]);
  const seg = (name, value, label, on, set) => (
    <Fragment key={value}>
      <input type="radio" className="btn-check" id={`${name}-${value}`} name={name} checked={on} onChange={set} />
      <label className="btn btn-outline-primary" htmlFor={`${name}-${value}`}>{label}</label>
    </Fragment>
  );
  return (
    <div className="enter-down" role="dialog" aria-label="Opciones de visualización"
      style={{
        position: "absolute", top: 48, right: 14, zIndex: 6, width: "min(560px, calc(100% - 28px))", background: "#fff",
        border: "1px solid var(--bs-border-color)", borderRadius: "var(--bs-border-radius)", boxShadow: "var(--shadow-lg)",
        padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10,
      }}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 16, flex: 1 }}>Opciones de visualización</span>
        <button type="button" className="btn-close" aria-label="Cerrar" onClick={onClose} style={{ fontSize: 11 }} />
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px 16px", fontSize: 13 }}>
        {isResult && proto === "seq" && (
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            Medición
            <select className="form-select" value={view.med} onChange={(e) => setView({ med: e.target.value })}
              style={{ width: "auto", minHeight: 32, padding: "4px 28px 4px 8px", fontSize: 13 }}>
              {medOptions.map((o) => (
                <option key={o.v} value={o.v}>{o.label}</option>
              ))}
            </select>
          </label>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Eje X
          <div className="btn-group btn-group-sm" role="group">
            {seg("ax", "t", "Tiempo (s)", view.x === "t", () => setView({ x: "t" }))}
            {seg("ax", "i", "Índice de muestra", view.x === "i", () => setView({ x: "i" }))}
          </div>
        </div>
        {isLive && (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            Ventana
            <div className="btn-group btn-group-sm" role="group">
              {wins.map((w) => seg("win", w, WIN_LABEL[w], view.win === w, () => setView({ win: w })))}
            </div>
          </div>
        )}
        <label title={shadeDisabled ? "Disponible solo con eje Tiempo en archivos de secuencia" : ""}
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", opacity: shadeDisabled ? 0.5 : 1 }}>
          <input className="form-check-input m-0" type="checkbox" checked={view.shade} disabled={shadeDisabled}
            onChange={(e) => setView({ shade: e.target.checked })} />
          Sombrear fases
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input className="form-check-input m-0" type="checkbox" checked={view.sg} onChange={(e) => setView({ sg: e.target.checked })} />
          <span title="Filtro Savitzky-Golay en BW (solo visual)">
            Filtro SG en BW <span style={{ color: "var(--color-neutral-600)" }}>(visual)</span>
          </span>
        </label>
        {view.sg && (
          <>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }} title="Debe ser bastante menor que un ciclo respiratorio (~2-6 s)">
              Ventana SG
              <input type="range" className="form-range" min="0.1" max="3" step="0.1" value={view.sgw}
                onChange={(e) => setView({ sgw: +e.target.value })} style={{ width: 90 }} aria-label="Ventana del filtro en segundos" />
              <span style={{ fontVariantNumeric: "tabular-nums", minWidth: 38 }}>{fmt(view.sgw, 1)} s</span>
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              Orden
              <select className="form-select" value={view.sgo} onChange={(e) => setView({ sgo: +e.target.value })}
                style={{ width: "auto", minHeight: 30, padding: "3px 28px 3px 8px", fontSize: 13 }}>
                {[2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>
      {view.sg && (
        <div style={{ fontSize: 12, ...muted }}>
          {sgNote} Debe ser bastante menor que un ciclo respiratorio (~2-6 s). Los datos guardados no se modifican.
        </div>
      )}
    </div>
  );
}

const iconBtn = { width: 32, height: 32, padding: 0 };

/**
 * props.data: { series:[bw,hr,br], dom, segs, now, markers, emptyMsg, partial, t0Wall, version }
 */
function ChartsCard({ isLive, isResult, proto, title, data, view, setView, medOptions, tab, setTab, table, zoomKey }) {
  const [zoom, setZoom] = useState(null);
  const [optsOpen, setOptsOpen] = useState(false);

  // El zoom se reinicia al cambiar el eje X, la ventana, la medición o la adquisición.
  useEffect(() => setZoom(null), [view.x, view.win, view.med, zoomKey]);

  const dt = useMemo(() => medianDt(data.series[0]), [data]);
  const sgInfo = useMemo(() => ({ dt, sgN: view.sg ? sgWindow(view.sgw, +view.sgo, dt) : 0 }), [dt, view.sg, view.sgw, view.sgo]);
  const sgNote = `Muestreo BW estimado: ${fmt(1 / dt, 1)} Hz → ventana de ${sgInfo.sgN} muestras (${fmt(sgInfo.sgN * dt, 2)} s), polinomio de orden ${view.sgo}.`;

  const shadeDisabled = view.x !== "t" || proto !== "seq";
  const summary = [
    isResult && proto === "seq" ? (view.med === "todas" ? "Todas" : `Medición ${view.med}`) : null,
    view.x === "t" ? "Tiempo" : "Índice",
    isLive ? WIN_LABEL[view.win] : null,
    view.shade && !shadeDisabled ? "Fases" : null,
    view.sg ? `SG ${fmt(view.sgw, 1)} s` : null,
  ].filter(Boolean).join(" · ");

  const zoomBy = (f, shift) => {
    const z = zoom || [0, 1];
    const w = z[1] - z[0];
    const c = (z[0] + z[1]) / 2 + shift * w;
    const nw = Math.min(1, Math.max(0.02, w * f));
    let a = c - nw / 2;
    let b = c + nw / 2;
    if (a < 0) {
      b -= a;
      a = 0;
    }
    if (b > 1) {
      a -= b - 1;
      b = 1;
    }
    a = Math.max(0, a);
    setZoom(a <= 0.0001 && b >= 0.9999 ? null : [a, b]);
  };

  const showCharts = !isResult || tab === "charts";

  return (
    <div className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", minHeight: 0, minWidth: 0, padding: "10px 14px 6px", gap: 6, overflow: "auto", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flex: "none" }}>
        {isResult && (
          <div className="nav nav-pills result-pills" role="tablist">
            <button className={`nav-link ${tab === "charts" ? "active" : ""}`} role="tab" aria-selected={tab === "charts"}
              onClick={() => setTab("charts")} style={{ fontSize: 14, whiteSpace: "nowrap" }}>
              Gráficos
            </button>
            <button className={`nav-link ${tab === "table" ? "active" : ""}`} role="tab" aria-selected={tab === "table"}
              onClick={() => setTab("table")} style={{ fontSize: 14, whiteSpace: "nowrap" }} title="Resumen HR / BR / distancia por medición y fase">
              Resumen por fase
            </button>
          </div>
        )}
        <h3 title={title} style={{ fontSize: 20, margin: 0, flex: "1 1 140px", minWidth: 140, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {title}
        </h3>
        {showCharts && (
          <>
            <button className="btn btn-outline-secondary btn-sm d-inline-flex align-items-center gap-2" aria-expanded={optsOpen}
              onClick={() => setOptsOpen((v) => !v)} title={summary}
              style={{ height: 32, whiteSpace: "nowrap", maxWidth: "34%", minWidth: 0, flex: "0 1 auto", overflow: "hidden" }}>
              <Settings2 size={15} strokeWidth={1.5} style={{ flex: "none" }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", fontFamily: "var(--font-body)", fontWeight: 400 }}>{summary}</span>
            </button>
            <div style={{ display: "flex", gap: 4 }} role="toolbar" aria-label="Zoom del eje X">
              <button className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center" style={iconBtn} title="Desplazar a la izquierda" aria-label="Desplazar a la izquierda" onClick={() => zoomBy(1, -0.25)}>
                <ChevronLeft size={16} strokeWidth={1.5} />
              </button>
              <button className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center" style={iconBtn} title="Acercar" aria-label="Acercar" onClick={() => zoomBy(0.5, 0)}>
                <ZoomIn size={16} strokeWidth={1.5} />
              </button>
              <button className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center" style={iconBtn} title="Alejar" aria-label="Alejar" onClick={() => zoomBy(2, 0)}>
                <ZoomOut size={16} strokeWidth={1.5} />
              </button>
              <button className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center" style={iconBtn} title="Desplazar a la derecha" aria-label="Desplazar a la derecha" onClick={() => zoomBy(1, 0.25)}>
                <ChevronRight size={16} strokeWidth={1.5} />
              </button>
              <button className="btn btn-outline-secondary btn-sm" disabled={!zoom} onClick={() => setZoom(null)} style={{ height: 32 }}>
                Restablecer
              </button>
            </div>
          </>
        )}
      </div>
      {showCharts && optsOpen && (
        <OptionsPanel isLive={isLive} isResult={isResult} proto={proto} view={view} setView={setView} medOptions={medOptions}
          shadeDisabled={shadeDisabled} sgNote={sgNote} onClose={() => setOptsOpen(false)} />
      )}
      {showCharts && view.sg && (
        <div title={sgNote} style={{ flex: "none", fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", ...muted }}>
          {sgNote} Solo visual.
        </div>
      )}
      {showCharts ? (
        <ChartsArea data={data} view={view} zoom={zoom} setZoom={setZoom} proto={proto} sgInfo={sgInfo} />
      ) : (
        table
      )}
    </div>
  );
}

export default memo(ChartsCard);
