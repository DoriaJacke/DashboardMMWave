// Distancia al radar: medidor semicircular con tres zonas (muy cerca, adecuada,
// muy lejos) y tendencia de los últimos 60 s. Funciona también en ESPERA.
// La zona adecuada se configura en un panel flotante y se guarda en el backend.

import { useState } from "react";
import { Settings2 } from "lucide-react";
import { useNow } from "../lib/hooks";
import { fmt } from "../lib/format";
import { AMBER, GREEN, GREY, RED } from "../lib/phases";

const STALE_S = 5;
const CX = 160;
const CY = 152;
const R = 118;

export default function DistanceCard({ status, receivedAt, dist, zone, onZone }) {
  const [open, setOpen] = useState(false);
  const active = !status.terminado;
  const now = useNow(500, active);
  const dtLocal = active ? Math.max(0, (now - receivedAt) / 1000) : 0;
  const t = status.t;

  const zmin = +zone.min || 0;
  const zmax = Math.max(+zone.max || 0, zmin);
  const scale = Math.max(+zone.scale || 10, zmax);
  const unit = zone.unit || "";

  const last = status.latest?.DIST || null;
  const age = last && last.age != null ? last.age + dtLocal : null;
  const stale = !!last && age != null && age > STALE_S;

  let statusText;
  let color;
  if (!last) [statusText, color] = ["Sin datos de distancia", GREY];
  else if (stale) [statusText, color] = ["Sin datos recientes", GREY];
  else if (last.v < zmin) [statusText, color] = ["Muy cerca del radar", AMBER];
  else if (last.v > zmax) [statusText, color] = ["Muy lejos del radar", RED];
  else [statusText, color] = ["Distancia adecuada", GREEN];
  const dim = !last || stale;

  const ang = (v) => Math.PI * (1 - Math.min(Math.max(v, 0), scale) / scale);
  const pt = (a, rr) => [CX + rr * Math.cos(a), CY - rr * Math.sin(a)];
  const arc = (v0, v1, rr) => {
    const p0 = pt(ang(v0), rr);
    const p1 = pt(ang(v1), rr);
    return `M${p0[0].toFixed(1)} ${p0[1].toFixed(1)}A${rr} ${rr} 0 0 1 ${p1[0].toFixed(1)} ${p1[1].toFixed(1)}`;
  };
  const zones = [
    { d: arc(0, zmin, R), stroke: dim ? "#e7e7ea" : "oklch(0.92 0.06 75)" },
    { d: arc(zmin, zmax, R), stroke: dim ? "#d4d4d7" : "oklch(0.9 0.06 152)" },
    { d: arc(zmax, scale, R), stroke: dim ? "#e7e7ea" : "oklch(0.92 0.045 27)" },
  ];
  const frac = last ? Math.min(Math.max(last.v, 0), scale) / scale : 0;
  const tickVals = [...new Set([0, zmin, zmax, scale])];
  const ticks = tickVals.map((v) => {
    const a = ang(v);
    const p = pt(a, R + 14);
    const c = Math.cos(a);
    return { v, left: `${((p[0] / 320) * 100).toFixed(2)}%`, top: `${((p[1] / 178) * 100).toFixed(2)}%`, tf: `translate(${c > 0.3 ? "0" : c < -0.3 ? "-100%" : "-50%"},-50%)` };
  });

  // Tendencia de los últimos 60 s.
  const hist = dist.filter((p) => p.t >= t - 60);
  const ys = (v) => 166 - (Math.min(Math.max(v, 0), scale) / scale) * 156;
  const xs = (tt) => 44 + ((tt - (t - 60)) / 60) * 506;
  const trend = hist.map((p, i) => `${i ? "L" : "M"}${xs(p.t).toFixed(1)} ${ys(p.v).toFixed(1)}`).join("");

  const ageText = !last ? "" : stale ? `Último dato hace ${fmt(age)} s` : `Actualizado hace ${fmt(Math.max(0, age ?? 0))} s`;
  const fields = [
    ["Mínimo", "min", "number"],
    ["Máximo", "max", "number"],
    ["Escala del medidor", "scale", "number"],
    ["Unidad", "unit", "text"],
  ];

  return (
    <section className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", flex: 1, minHeight: 0, padding: "10px 14px", gap: 4, position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h2 style={{ fontSize: 18, margin: 0, flex: 1 }}>Distancia al radar</h2>
        <button className="btn btn-link btn-sm text-decoration-none d-inline-flex align-items-center gap-2" onClick={() => setOpen((v) => !v)} aria-expanded={open} style={{ padding: "2px 4px" }}>
          <Settings2 size={15} strokeWidth={1.5} />
          {fmt(zmin)}–{fmt(zmax)} {unit}
        </button>
      </div>
      <div style={{ flex: "none", display: "grid", gridTemplateColumns: "clamp(110px,18vh,180px) minmax(0,1fr)", gap: 12, alignItems: "center" }}>
        <div style={{ position: "relative", width: "100%" }}>
          <svg viewBox="0 0 320 178" style={{ width: "100%", display: "block" }} role="img"
            aria-label={`Distancia: ${last ? `${fmt(last.v, 1)} ${unit}` : "sin datos"}. ${statusText}.`}>
            {zones.map((z, i) => (
              <path key={i} d={z.d} fill="none" stroke={z.stroke} strokeWidth="22" style={{ transition: "stroke .4s" }} />
            ))}
            <path d={arc(0, scale, R - 17)} pathLength="100" fill="none" stroke={color} strokeWidth="6" strokeDasharray={`${(frac * 100).toFixed(2)} 100`}
              style={{ transition: "stroke-dasharray .8s cubic-bezier(.3,1.25,.5,1),stroke .4s" }} />
            <g style={{ transform: `rotate(${(frac * 180).toFixed(2)}deg)`, transformOrigin: "160px 152px", transition: "transform .8s cubic-bezier(.3,1.25,.5,1),opacity .4s", opacity: last ? 1 : 0.25 }}>
              <line x1="160" y1="152" x2="68" y2="152" stroke={color} strokeWidth="4" strokeLinecap="round" style={{ transition: "stroke .4s" }} />
            </g>
            <circle cx="160" cy="152" r="8" fill={color} style={{ transition: "fill .4s" }} />
          </svg>
          {ticks.map((tk) => (
            <div key={tk.v} style={{ position: "absolute", left: tk.left, top: tk.top, transform: tk.tf, fontSize: 10, color: "var(--color-neutral-700)", fontVariantNumeric: "tabular-nums" }}>
              {fmt(tk.v)}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 5, color, transition: "color .4s" }}>
            <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: "clamp(26px,4.6vh,40px)", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
              {last ? fmt(last.v, 1) : "—"}
            </span>
            <span style={{ fontSize: 15 }}>{last ? unit : ""}</span>
          </div>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.15, color, transition: "color .4s" }}>{statusText}</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-700)" }}>{ageText}</div>
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-700)" }}>Tendencia · últimos 60 s · zona adecuada sombreada</div>
      <div style={{ flex: 1, minHeight: 40, position: "relative" }}>
        <svg viewBox="0 0 560 190" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }} aria-hidden="true">
          <rect x="44" y={ys(zmax).toFixed(1)} width="506" height={(ys(zmin) - ys(zmax)).toFixed(1)} fill="oklch(0.93 0.045 152)" />
          {tickVals.map((v) => (
            <line key={v} x1="44" x2="550" y1={ys(v)} y2={ys(v)} stroke="rgba(29,31,32,.1)" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
          ))}
          <line x1="44" x2="44" y1="10" y2="166" stroke="rgba(29,31,32,.35)" vectorEffect="non-scaling-stroke" />
          <line x1="44" x2="550" y1="166" y2="166" stroke="rgba(29,31,32,.35)" vectorEffect="non-scaling-stroke" />
          <path d={trend} fill="none" stroke={dim ? GREY : "var(--color-accent-700)"} strokeWidth="1.75" vectorEffect="non-scaling-stroke" />
        </svg>
        {tickVals.map((v) => (
          <div key={v} style={{ position: "absolute", right: `${(100 - (38 / 560) * 100).toFixed(2)}%`, top: `${((ys(v) / 190) * 100).toFixed(2)}%`, transform: "translateY(-50%)", fontSize: 10, color: "var(--color-neutral-700)", paddingRight: 4 }}>
            {fmt(v)}
          </div>
        ))}
        {[-60, -45, -30, -15, 0].map((v) => (
          <div key={v} style={{ position: "absolute", left: `${((xs(t + v) / 560) * 100).toFixed(2)}%`, bottom: -2, transform: "translateX(-50%)", fontSize: 10, color: "var(--color-neutral-700)", whiteSpace: "nowrap" }}>
            {v ? `${v} s` : "ahora"}
          </div>
        ))}
        {!last && (
          <div style={{ position: "absolute", left: "12%", right: "2%", top: "35%", textAlign: "center", fontSize: 13, color: "var(--color-neutral-700)" }}>
            El radar aún no ha enviado datos de distancia.
          </div>
        )}
      </div>
      {open && (
        <div className="enter-down" style={{ position: "absolute", top: 44, left: 10, right: 10, zIndex: 5, background: "#fff", borderRadius: "var(--bs-border-radius)", boxShadow: "var(--shadow-lg)", border: "1px solid var(--bs-border-color)", padding: 12, display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 }}>
          {fields.map(([label, key, type]) => (
            <div className="field" key={key}>
              <label htmlFor={`zone-${key}`}>{key === "unit" ? label : `${label} (${unit})`}</label>
              <input id={`zone-${key}`} className="form-control form-control-sm" type={type} value={zone[key]} onChange={(e) => onZone({ [key]: e.target.value })} />
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ flex: 1, fontSize: 12, color: "var(--color-neutral-700)" }}>Según el protocolo de Seeed el MR60BHA1 entrega cm. La unidad real está por confirmar.</span>
            <button className="btn btn-primary btn-sm" onClick={() => setOpen(false)}>Listo</button>
          </div>
        </div>
      )}
    </section>
  );
}
