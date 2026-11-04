// Columna izquierda del Resultado: estado final, siguiente adquisición
// (configuración conservada) y exportación de imágenes PNG.

import { Download, Play } from "lucide-react";
import { fmt, mmss, pad } from "../lib/format";
import { AMBER, GREEN, RED } from "../lib/phases";

const KINDS = {
  ok: { title: "ADQUISICIÓN COMPLETADA", color: GREEN, tint: "oklch(0.97 0.02 152)", ink: "oklch(0.36 0.08 152)" },
  stop: { title: "ADQUISICIÓN DETENIDA MANUALMENTE", color: AMBER, tint: "oklch(0.97 0.03 85)", ink: "oklch(0.40 0.09 62)" },
  error: { title: "ADQUISICIÓN TERMINADA CON ERROR", color: RED, tint: "oklch(0.97 0.015 27)", ink: "oklch(0.38 0.12 27)" },
};

export const endKind = (status) => (status.error ? "error" : status.detenido ? "stop" : "ok");

const dl = { display: "grid", gridTemplateColumns: "auto minmax(0,1fr)", gap: "3px 12px", margin: 0, fontSize: 13 };
const dt = { fontWeight: 400, color: "var(--color-neutral-700)" };

export default function ResultPanel({ session, status, nEnd, cfgSummary, onStart, onEdit, startError, starting, exp, onDpi, onGenerate, onDownload, exportProgress }) {
  const k = KINDS[endKind(status)];
  const seq = session.proto === "seq";
  const nImages = exportProgress?.total || (seq ? Math.max(1, nEnd) : 1);
  const running = exp.state === "running";
  const done = exportProgress?.done ?? 0;
  const total = exportProgress?.total || nImages;
  const current = exportProgress?.file || `medicion_${pad(Math.min(total, done + 1))}.png`;
  const expText = running
    ? `Generando imágenes… ${done} de ${total} (${current})`
    : exp.state === "done"
      ? `graficos_mediciones.zip · ${exp.n} ${exp.n === 1 ? "imagen" : "imágenes"} a ${exp.dpi} DPI`
      : "";
  const pct = running && total ? Math.round((done / total) * 100) : 0;

  return (
    <>
      <section className="card border-0" style={{ boxShadow: "var(--shadow-sm)", flex: "none", padding: 16, gap: 8, background: k.tint }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: k.ink }}>
          <span style={{ width: 14, height: 14, borderRadius: "50%", background: k.color, flex: "none" }} />
          <h1 style={{ fontSize: 24, margin: 0, letterSpacing: ".02em", lineHeight: 1.1 }}>{k.title}</h1>
        </div>
        {status.error && <div style={{ fontSize: 14, color: k.ink }}>{status.error}</div>}
        <dl style={dl}>
          <dt style={dt}>Archivo</dt>
          <dd style={{ margin: 0, fontFamily: "ui-monospace,monospace", fontSize: 12, wordBreak: "break-all" }}>{session.path}</dd>
          <dt style={dt}>Registros guardados</dt>
          <dd style={{ margin: 0, fontWeight: 500 }}>{fmt(status.n_saved)}</dd>
          <dt style={dt}>Mediciones</dt>
          <dd style={{ margin: 0 }}>{seq ? `Mediciones completas ${nEnd} de ${status.total}` : "Captura continua"}</dd>
          <dt style={dt}>Duración</dt>
          <dd style={{ margin: 0 }}>{mmss(status.t)}</dd>
        </dl>
      </section>

      <section className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", flex: "none", padding: 16, gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h2 style={{ fontSize: 20, margin: 0, flex: 1 }}>Siguiente adquisición</h2>
          <span className="badge rounded-pill" style={{ background: "var(--color-accent-100)", color: "var(--color-accent-800)", fontWeight: 500, fontSize: 11 }}>Configuración conservada</span>
        </div>
        <dl style={dl}>
          {cfgSummary.map((s) => (
            <div key={s.k} style={{ display: "contents" }}>
              <dt style={dt}>{s.k}</dt>
              <dd style={{ margin: 0, wordBreak: "break-all" }}>{s.v}</dd>
            </div>
          ))}
        </dl>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-primary d-inline-flex align-items-center gap-2" onClick={onStart} disabled={starting} style={{ flex: 1, justifyContent: "center" }}>
            <Play size={14} strokeWidth={1.5} fill="currentColor" />
            Iniciar adquisición
          </button>
          <button className="btn btn-outline-secondary" onClick={onEdit}>Editar configuración</button>
        </div>
        {startError && (
          <div role="alert" className="alert mb-0 enter-down" style={{ padding: "8px 10px", fontSize: 13, border: `1px solid ${RED}`, background: "oklch(0.96 0.02 27)", color: "oklch(0.38 0.12 27)" }}>
            {startError.msg}
          </div>
        )}
      </section>

      <section className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", flex: 1, minHeight: 0, padding: 16, gap: 10, overflow: "hidden" }}>
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
              <span style={{ fontSize: 13, color: "var(--color-neutral-700)" }}>{expText}</span>
            </>
          )}
        </div>
      </section>
    </>
  );
}
