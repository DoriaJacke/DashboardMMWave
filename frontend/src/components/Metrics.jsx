// Métricas actuales: HR (con corazón que late), BR, Evento y líneas recibidas/guardadas.
// Un dato con más de 3 s (12 s para Evento) se muestra en gris como "antiguo".

import { EASE, useAnimateOnChange, useNow } from "../lib/hooks";
import { fmt, fmtVal } from "../lib/format";

const HEART = "M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z";

function Value({ value, size }) {
  const ref = useAnimateOnChange(value, [{ transform: "translateY(-4px)", opacity: 0.55 }, { transform: "none", opacity: 1 }], { duration: 320, easing: EASE });
  return (
    <span ref={ref} style={{ display: "inline-block", fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: size, lineHeight: 1.1, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
      {value}
    </span>
  );
}

function Card({ kicker, tag, value, unit, meta, color, heart, size = "clamp(24px,4vh,32px)", animate = true }) {
  return (
    <div className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", padding: "7px 12px", gap: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
        <div title={kicker} style={{ fontSize: 11, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-accent-700)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flex: 1, minWidth: 0 }}>
          {kicker}
        </div>
        {tag && (
          <span className="badge rounded-pill" style={{ fontSize: 9, background: tag.bg, color: tag.ink, fontWeight: 500, flex: "none" }}>
            {tag.text}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, color, transition: "color .4s", minWidth: 0 }}>
        {heart && (
          <svg width="22" height="22" viewBox="0 0 24 24" fill={heart.on ? "oklch(0.6 0.18 22)" : "transparent"}
            stroke={heart.on ? "oklch(0.5 0.17 22)" : "var(--color-neutral-500)"} strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true"
            style={{ flex: "none", alignSelf: "center", transformOrigin: "center", animation: heart.anim, transition: "fill .4s,stroke .4s" }}>
            <path d={HEART} />
          </svg>
        )}
        {animate ? <Value value={value} size={size} /> : (
          <span style={{ display: "inline-block", fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: size, lineHeight: 1.1, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{value}</span>
        )}
        <span style={{ fontSize: 13, color: "var(--color-neutral-700)" }}>{unit}</span>
        <span title={meta} style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-neutral-700)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>
          {meta}
        </span>
      </div>
    </div>
  );
}

export default function Metrics({ status, receivedAt }) {
  const active = !status.terminado;
  const now = useNow(500, active);
  const dtLocal = active ? Math.max(0, (now - receivedAt) / 1000) : 0;
  const L = status.latest || {};
  const age = (d) => (d && d.age != null ? d.age + dtLocal : null);
  const ageTxt = (d, lim) => {
    const a = age(d);
    if (!d || a == null) return "Sin datos";
    return a > lim ? `antiguo · hace ${fmt(a)} s` : `hace ${fmt(Math.max(0, a))} s`;
  };
  const colorOf = (d, lim) => (!d || age(d) == null || age(d) > lim ? "var(--color-neutral-500)" : "var(--color-text)");

  const hr = L.HR;
  const hrOn = !!hr && hr.v > 0 && age(hr) <= 3 && active;
  const rec = status.recording && active;

  return (
    <div style={{ flex: "none", display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 }}>
      <Card kicker="HR · Frec. cardíaca" value={hr ? fmtVal(hr.v) : "—"} unit="BPM"
        meta={hr && hr.v === 0 ? "0 = sin estimación" : ageTxt(hr, 3)} color={colorOf(hr, 3)}
        heart={{ on: hrOn, anim: hrOn ? `heartbeat ${(60 / hr.v).toFixed(2)}s ease-in-out infinite` : "none" }} />
      <Card kicker="BR · Frec. respiratoria" value={L.BR ? fmtVal(L.BR.v) : "—"} unit="resp/min" meta={ageTxt(L.BR, 3)} color={colorOf(L.BR, 3)} />
      <Card kicker="Evento" value={L.EVENT ? L.EVENT.v : "—"} unit="" meta={L.EVENT ? ageTxt(L.EVENT, 12) : "sin eventos"} color={colorOf(L.EVENT, 12)} />
      <Card kicker="Líneas recibidas / guardadas" value={`${fmt(status.n_lines)} / ${fmt(status.n_lines_saved)}`} unit=""
        meta={rec ? "se graba" : "no se graba"} color="var(--color-text)" size="clamp(20px,3.2vh,26px)" animate={false}
        tag={rec ? { text: "GRABANDO", bg: "oklch(0.94 0.04 152)", ink: "oklch(0.38 0.08 152)" } : { text: "SIN GRABAR", bg: "var(--color-neutral-200)", ink: "var(--color-neutral-800)" }} />
    </div>
  );
}
