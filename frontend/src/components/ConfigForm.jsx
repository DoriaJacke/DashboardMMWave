// Configuración de la adquisición: fuente de datos, protocolo y archivo de salida.
// Se usa en la pantalla "Nueva adquisición" y en el modal "Editar siguiente adquisición".

import { CircleAlert, Info, Play, RefreshCw } from "lucide-react";
import { mmss } from "../lib/format";

export const SEQ_FIELDS = [
  ["n", "Mediciones", 1, 200, true],
  ["tn", "Respiración normal (s)", 1, 600, false],
  ["th", "Retención (s)", 1, 120, false],
  ["tr", "Descanso (s)", 1, 600, false],
  ["cd", "Cuenta regresiva (s)", 0, 10, true],
  ["tp", "Pausa entre mediciones (s)", 0, 60, false],
];

const RED = "oklch(0.48 0.15 27)";
const kicker = { fontSize: 11, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--color-accent-700)" };
const card = { boxShadow: "var(--shadow-sm)", background: "#fff", padding: 18, gap: 14 };

/** Mensaje de error de un campo numérico, o null si está bien. */
export function fieldError(value, min, max, integer) {
  if (value === "" || value == null || Number.isNaN(Number(value))) return `Debe estar entre ${min} y ${max}.`;
  const v = Number(value);
  if (v < min || v > max) return `Debe estar entre ${min} y ${max}.`;
  if (integer && !Number.isInteger(v)) return "Debe ser un número entero.";
  return null;
}

export const durError = (v) => fieldError(v, 0, 36000, false);
export const baudError = (v) => (v === "" || !(Number(v) > 0) || !Number.isInteger(Number(v)) ? "Revisa el baudrate." : null);

export default function ConfigForm({ cfg, setCfg, ports, scannedAt, onRefreshPorts, fileValue, setFile, onStart, error, starting }) {
  const seq = cfg.proto === "seq";
  const hasPorts = ports.length > 0;
  const N = +cfg.n || 0;
  const total = N * (+cfg.tn + 1 + +cfg.cd + +cfg.th + +cfg.tr) + Math.max(0, N - 1) * +cfg.tp;
  const dErr = durError(cfg.duracion);
  const bErr = cfg.src === "serial" ? baudError(cfg.baud) : null;
  const portErr = error?.field === "port";
  const fileErr = error?.field === "file";

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1.35fr)", gap: 20 }}>
        <div className="card border-0" style={card}>
          <div style={kicker}>Fuente de datos</div>
          <div role="radiogroup" aria-label="Fuente de datos" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label className="form-check d-flex align-items-center gap-2 mb-0" style={{ cursor: "pointer", paddingLeft: 0 }}>
              <input className="form-check-input m-0" type="radio" name="src" checked={cfg.src === "serial"} onChange={() => setCfg({ src: "serial" })} />
              Puerto serial (ESP32)
            </label>
            <label className="form-check d-flex align-items-center gap-2 mb-0" style={{ cursor: "pointer", paddingLeft: 0 }}>
              <input className="form-check-input m-0" type="radio" name="src" checked={cfg.src === "sim"} onChange={() => setCfg({ src: "sim" })} />
              Simulador (sin hardware)
            </label>
          </div>
          {cfg.src === "serial" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 4 }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 8, alignItems: "end" }}>
                <div className="field">
                  <label htmlFor="cfg-port">Puerto</label>
                  {hasPorts ? (
                    <select id="cfg-port" className="form-select" value={cfg.port} onChange={(e) => setCfg({ port: e.target.value })} style={{ borderColor: portErr ? RED : undefined }}>
                      {ports.map((p) => (
                        <option key={p.device} value={p.device}>{p.description ? `${p.device} — ${p.description}` : p.device}</option>
                      ))}
                    </select>
                  ) : (
                    <input id="cfg-port" className="form-control" value={cfg.port} placeholder="COM4" onChange={(e) => setCfg({ port: e.target.value })} style={{ borderColor: portErr ? RED : "var(--color-divider)" }} />
                  )}
                </div>
                <button type="button" className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center gap-2" onClick={onRefreshPorts} style={{ minHeight: 36 }}>
                  <RefreshCw size={15} strokeWidth={1.5} />
                  Actualizar
                </button>
              </div>
              {!hasPorts && <div style={{ fontSize: 13, color: "oklch(0.42 0.09 60)" }}>No se detectaron puertos. Escribe el puerto manualmente.</div>}
              <div style={{ fontSize: 12, color: "var(--color-neutral-700)", marginTop: -4 }}>
                {ports.length} {ports.length === 1 ? "puerto detectado" : "puertos detectados"} · última búsqueda {scannedAt || "—"}
              </div>
              <div className="field" style={{ maxWidth: 200 }}>
                <label htmlFor="cfg-baud">Baudrate</label>
                <input id="cfg-baud" className="form-control" type="number" step="9600" value={cfg.baud} onChange={(e) => setCfg({ baud: e.target.value })} style={{ borderColor: bErr ? RED : undefined }} />
                {bErr && <div style={{ fontSize: 12, color: "oklch(0.42 0.13 27)", marginTop: 3 }}>{bErr}</div>}
              </div>
            </div>
          ) : (
            <p style={{ fontSize: 14, margin: 0, color: "var(--color-neutral-800)" }}>
              Genera datos sintéticos de HR, BR, distancia, eventos y waveform BW para probar el dashboard.
            </p>
          )}
        </div>

        <div className="card border-0" style={card}>
          <div style={kicker}>Protocolo</div>
          <div role="radiogroup" aria-label="Protocolo" style={{ display: "flex", gap: 24 }}>
            <label className="form-check d-flex align-items-center gap-2 mb-0" style={{ cursor: "pointer", paddingLeft: 0 }}>
              <input className="form-check-input m-0" type="radio" name="proto" checked={seq} onChange={() => setCfg({ proto: "seq" })} />
              Secuencia con retención
            </label>
            <label className="form-check d-flex align-items-center gap-2 mb-0" style={{ cursor: "pointer", paddingLeft: 0 }}>
              <input className="form-check-input m-0" type="radio" name="proto" checked={!seq} onChange={() => setCfg({ proto: "cont" })} />
              Captura continua
            </label>
          </div>
          {seq ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: "12px 14px" }}>
                {SEQ_FIELDS.map(([k, label, min, max, integer]) => {
                  const err = fieldError(cfg[k], min, max, integer);
                  return (
                    <div className="field" key={k}>
                      <label htmlFor={`cfg-${k}`}>{label}</label>
                      <input id={`cfg-${k}`} className="form-control" type="number" min={min} max={max} value={cfg[k]} onChange={(e) => setCfg({ [k]: e.target.value })}
                        aria-invalid={!!err} style={{ borderColor: err ? RED : "var(--color-divider)", fontVariantNumeric: "tabular-nums" }} />
                      <div style={{ fontSize: 12, color: err ? "oklch(0.42 0.13 27)" : "var(--color-neutral-600)", marginTop: 3 }}>{err || `Rango ${min}–${max}`}</div>
                    </div>
                  );
                })}
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
                <input className="form-check-input m-0" type="checkbox" checked={!!cfg.esperar} onChange={(e) => setCfg({ esperar: e.target.checked })} />
                Esperar confirmación antes de cada medición
              </label>
              <div style={{ fontSize: 13, color: "var(--color-neutral-700)" }}>
                Duración estimada {mmss(Number.isFinite(total) ? total : 0)}
                {cfg.esperar ? " más las esperas de confirmación." : "."}
              </div>
              <div className="alert mb-0 border-0" style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 12px", background: "var(--color-accent-100)", color: "var(--color-accent-800)", fontSize: 14 }}>
                <Info size={18} strokeWidth={1.5} style={{ flex: "none", marginTop: 1 }} />
                Durante la retención realiza solamente un aguante voluntario y cómodo. No fuerces la respiración.
              </div>
            </div>
          ) : (
            <div className="field" style={{ maxWidth: 260 }}>
              <label htmlFor="cfg-dur" style={{ display: "flex", justifyContent: "space-between" }}>
                <span>Duración (s, 0 = hasta detener)</span>
                <span style={{ color: "var(--color-neutral-600)" }}>0–36000</span>
              </label>
              <input id="cfg-dur" className="form-control" type="number" min="0" max="36000" value={cfg.duracion} onChange={(e) => setCfg({ duracion: e.target.value })}
                aria-invalid={!!dErr} style={{ borderColor: dErr ? RED : "var(--color-divider)" }} />
              <div style={{ fontSize: 12, color: dErr ? "oklch(0.42 0.13 27)" : "var(--color-neutral-700)", marginTop: 4 }}>
                {dErr || (+cfg.duracion > 0 ? `Se detiene sola a los ${mmss(+cfg.duracion)}.` : "Sin límite: graba hasta que presiones «Detener adquisición».")}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card border-0" style={{ ...card, gap: 10 }}>
        <div style={kicker}>Archivo de salida</div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 16, alignItems: "start" }}>
          <div className="field">
            <div style={{ display: "flex", alignItems: "stretch" }}>
              <span style={{ display: "flex", alignItems: "center", padding: "0 10px", border: "1px solid var(--color-divider)", borderRight: 0, fontFamily: "ui-monospace,monospace", fontSize: 13, color: "var(--color-neutral-700)" }}>
                datos/
              </span>
              <input className="form-control" aria-label="Nombre del archivo" value={fileValue} onChange={(e) => setFile(e.target.value)}
                style={{ fontFamily: "ui-monospace,monospace", fontSize: 13, borderColor: fileErr ? RED : "var(--color-divider)" }} />
            </div>
            <div style={{ fontSize: 12, color: "var(--color-neutral-700)", marginTop: 5 }}>Si falta la extensión se agrega .csv. Nunca se sobrescribe un archivo existente.</div>
          </div>
          <button className="btn btn-primary d-inline-flex align-items-center justify-content-center gap-2" onClick={onStart} disabled={starting} style={{ minHeight: 48, padding: "0 26px", fontSize: 19 }}>
            <Play size={16} strokeWidth={1.5} fill="currentColor" />
            Iniciar adquisición
          </button>
        </div>
        {error && (
          <div role="alert" className="alert mb-0 enter-down" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", border: `1px solid ${RED}`, background: "oklch(0.96 0.02 27)", color: "oklch(0.38 0.12 27)", fontSize: 14 }}>
            <CircleAlert size={18} strokeWidth={1.5} />
            {error.msg}
          </div>
        )}
      </div>
    </>
  );
}
