// Valores actuales de la placa CMAE en la vista en vivo de una adquisición
// (columna izquierda, bajo las métricas del radar). Los números vienen directo
// del almacén en vivo de la placa, así que se ven también en la espera de
// posicionamiento, aunque en esa fase no se graben.

import { memo } from "react";
import LiveValue from "./LiveValue";
import { CmaeConnectButton } from "./CmaeView";
import { connectionTone, panelBadge } from "./panels";
import { num } from "./format";

const kicker = { fontSize: 11, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-accent-700)", whiteSpace: "nowrap" };
const big = { fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: "clamp(20px,3.2vh,28px)", lineHeight: 1.1, fontVariantNumeric: "tabular-nums" };
const unit = { fontSize: 12, color: "var(--color-neutral-700)" };

function Value({ label, serie, digits, u, color }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ ...kicker, display: "flex", alignItems: "center", gap: 5 }}>
        <span style={{ width: 10, height: 0, borderTop: `2px solid ${color}` }} />
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <LiveValue serie={serie} digits={digits} staleS={serie === "pressure_hpa" ? 15 : 4} className="" />
        <span style={unit}>{u}</span>
      </div>
    </div>
  );
}

function CmaeMetrics({ estado, rec }) {
  const tone = connectionTone(estado?.conexion);
  const b = estado?.banderas;
  const on = !!estado?.conexion?.activa;
  const avisos = on ? [panelBadge("ecg", b), panelBadge("pulse", b)].filter((x) => x && x.tone === "warn") : [];
  return (
    <div className="card border-0" style={{ flex: "none", boxShadow: "var(--shadow-sm)", background: "#fff", padding: "7px 12px", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 15 }}>Placa CMAE</span>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: tone.color }} />
        <span style={{ fontSize: 12, color: "var(--color-neutral-700)" }}>{tone.text}</span>
        {avisos.map((a) => (
          <span key={a.text} className="cm-badge cm-badge--warn">{a.text}</span>
        ))}
        <span style={{ marginLeft: "auto" }}>
          <CmaeConnectButton estado={estado} size="sm" />
        </span>
      </div>
      <div style={{ ...big, display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: "4px 10px" }}>
        <Value label="SpO₂" serie="spo2" digits={1} u="%" color="var(--cm-spo2)" />
        <Value label="Pulso oxímetro" serie="bpm_float" digits={0} u="BPM" color="var(--cm-bpm)" />
        <Value label="Pulso ECG" serie="ecg_bpm" digits={0} u="BPM" color="var(--cm-ecg)" />
        <Value label="Presión" serie="pressure_hpa" digits={2} u="hPa" color="var(--cm-teal)" />
      </div>
      <div style={{ fontSize: 11, color: "var(--color-neutral-700)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
        title={rec ? rec.path : undefined}>
        {rec
          ? <>Se graba en <span style={{ fontFamily: "ui-monospace,monospace" }}>{rec.path}</span> · {num(rec.n, 0)} muestras</>
          : on ? "Se graba en las fases que se graban, junto al CSV del radar" : "Sin conectar: la adquisición sigue solo con el radar"}
      </div>
    </div>
  );
}

export default memo(CmaeMetrics);
