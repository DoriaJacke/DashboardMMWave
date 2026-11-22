// Tarjeta "Exportar imágenes": DPI, generar el ZIP con un PNG por medición,
// avance de la generación y descarga.

import { Download } from "lucide-react";
import { pad } from "../lib/format";

export default function ExportCard({ exp, nImages, onDpi, onGenerate, onDownload, exportProgress, style }) {
  const running = exp.state === "running";
  const done = exportProgress?.done ?? 0;
  const total = exportProgress?.total || nImages;
  const current = exportProgress?.file || `medicion_${pad(Math.min(total, done + 1))}.png`;
  const expText = running
    ? `Generando imágenes… ${done} de ${total} (${current})`
    : exp.state === "done"
      ? `${exp.name} · ${exp.n} ${exp.n === 1 ? "imagen" : "imágenes"} a ${exp.dpi} DPI`
      : "";
  const pct = running && total ? Math.round((done / total) * 100) : 0;

  return (
    <section className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", padding: 16, gap: 10, overflow: "hidden", ...style }}>
      <h3 style={{ fontSize: 20, margin: 0 }}>Exportar imágenes</h3>
      <p style={{ fontSize: 13, margin: 0, color: "var(--color-neutral-800)" }}>
        Genera una imagen PNG por medición con el mismo estilo de HRBRWF.py (medicion_XX.png). Si el filtro Savitzky-Golay está activo, la onda filtrada se superpone también en las imágenes.
      </p>
      <div style={{ display: "flex", alignItems: "end", gap: 14, flexWrap: "wrap" }}>
        <div className="field" style={{ width: 120 }}>
          <label htmlFor="exp-dpi">DPI (72–600)</label>
          <input id="exp-dpi" className="form-control" type="number" min="72" max="600" step="50" value={exp.dpi} onChange={(e) => onDpi(e.target.value)} />
        </div>
        <button className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center gap-2" disabled={running} onClick={onGenerate} style={{ minHeight: 36 }}>
          Generar imágenes
        </button>
        {running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 320 }}>
            <span style={{ fontSize: 13 }}>{expText}</span>
            <div className="progress" style={{ height: 8 }} role="progressbar" aria-label="Avance de la exportación" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className="progress-bar progress-bar-striped progress-bar-animated" style={{ width: `${Math.max(pct, 4)}%`, backgroundColor: "var(--color-accent)", transition: "width .18s linear" }} />
            </div>
          </div>
        )}
        {exp.state === "done" && (
          <>
            <button className="btn btn-primary d-inline-flex align-items-center gap-2" onClick={onDownload} style={{ minHeight: 36 }}>
              <Download size={16} strokeWidth={1.5} />
              Descargar ZIP
            </button>
            <span style={{ fontSize: 13, color: "var(--color-neutral-700)", wordBreak: "break-all" }}>{expText}</span>
          </>
        )}
      </div>
    </section>
  );
}
