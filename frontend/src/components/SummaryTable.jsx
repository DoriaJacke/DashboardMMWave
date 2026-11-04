// Resumen por fase (solo archivos de secuencia): media ± DE y n de HR, BR y distancia.

import { fmt } from "../lib/format";
import { PH, SHADE } from "../lib/phases";

const right = { textAlign: "right" };
const n = { textAlign: "right", color: "var(--color-neutral-700)" };

function stat(s, unit = "") {
  if (!s || !s.n || s.media == null) return "—";
  const sd = s.desv == null ? "—" : fmt(s.desv, 1);
  return `${fmt(s.media, 1)} ± ${sd}${unit ? ` ${unit}` : ""}`;
}

export default function SummaryTable({ proto, rows, loading, error, unit }) {
  let body;
  if (proto !== "seq") {
    body = (
      <tr>
        <td colSpan={8} style={{ color: "var(--color-neutral-700)" }}>Disponible solo para archivos de secuencia</td>
      </tr>
    );
  } else if (error) {
    body = (
      <tr>
        <td colSpan={8} style={{ color: "oklch(0.38 0.12 27)" }}>{error}</td>
      </tr>
    );
  } else if (loading && !rows) {
    body = (
      <tr>
        <td colSpan={8} style={{ color: "var(--color-neutral-700)" }}>Calculando…</td>
      </tr>
    );
  } else {
    const sorted = [...(rows || [])]
      .filter((r) => SHADE.includes(r.fase) && (r.HR.n || r.BR.n))
      .sort((a, b) => a.medicion - b.medicion || SHADE.indexOf(a.fase) - SHADE.indexOf(b.fase));
    body = sorted.length ? (
      sorted.map((r, i) => {
        const first = i === 0 || sorted[i - 1].medicion !== r.medicion;
        return (
          <tr key={`${r.medicion}-${r.fase}`}>
            <td style={{ fontWeight: 500 }}>{first ? r.medicion : ""}</td>
            <td>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 10, height: 10, background: PH[r.fase].bg }} />
                {PH[r.fase].name}
              </span>
            </td>
            <td style={right}>{stat(r.HR)}</td>
            <td style={n}>{r.HR.n}</td>
            <td style={right}>{stat(r.BR)}</td>
            <td style={n}>{r.BR.n}</td>
            <td style={right}>{stat(r.DIST, unit)}</td>
            <td style={n}>{r.DIST.n}</td>
          </tr>
        );
      })
    ) : (
      <tr>
        <td colSpan={8} style={{ color: "var(--color-neutral-700)" }}>No hay datos para resumir.</td>
      </tr>
    );
  }
  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
      <table className="table table-hover align-middle mb-0 summary-table">
        <thead>
          <tr>
            <th>Medición</th>
            <th>Fase</th>
            <th style={right}>HR media ± DE (BPM)</th>
            <th style={right}>n</th>
            <th style={right}>BR media ± DE (resp/min)</th>
            <th style={right}>n</th>
            <th style={right}>Distancia media ± DE</th>
            <th style={right}>n</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  );
}
