// Sección Análisis: por ahora solo el esqueleto con el indicador global.
// Se diseña en la siguiente etapa.

import { useNow } from "../lib/hooks";
import { phaseOf } from "../lib/phases";
import { indicatorDetail } from "./Header";

export default function AnalysisPage({ live, liveActive, onBack }) {
  useNow(1000, liveActive);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 30, margin: 0 }}>Análisis de mediciones</h1>
      {liveActive && (
        <div className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", flexDirection: "row", display: "flex", alignItems: "center", gap: 16, padding: "14px 16px" }}>
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: phaseOf(live.status.fase).bg, flex: "none" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 500 }}>
              Hay una adquisición en curso · {phaseOf(live.status.fase).name} · {indicatorDetail(live)}
            </div>
            <div style={{ fontSize: 13, color: "var(--color-neutral-700)" }}>
              Se sigue grabando en {live.session.file}. Puedes revisar archivos guardados mientras tanto.
            </div>
          </div>
          <button className="btn btn-outline-secondary" onClick={onBack}>Volver a Adquisición</button>
        </div>
      )}
      <div style={{ padding: "32px 0", color: "var(--color-neutral-700)", fontSize: 14 }}>
        La sección Análisis se diseña en la siguiente etapa. Aquí se muestra solo el indicador global.
      </div>
    </div>
  );
}
