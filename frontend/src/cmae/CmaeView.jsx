// Conexión de la placa CMAE y pestaña "Placa CMAE":
//   - CmaeConnectButton: Conectar (abre la ventana) o Desconectar, según el estado.
//   - CmaeSourceCard:    tarjeta para la pantalla "Nueva adquisición".
//   - CmaePage:          pestaña con sus gráficos en grande, con el reloj de la
//                        placa (sin depender de una adquisición).
// Durante una adquisición, los datos se grafican sincronizados con el radar en
// una tarjeta propia (ChartsCard variant="cmae") y sus valores en CmaeMetrics.jsx.
// El estado llega de useCmae() (App.jsx); las curvas, del almacén (cmae/store.js).

import { useState } from "react";
import { Bluetooth, FlaskConical, Plug, Unplug, Usb } from "lucide-react";
import CmaeConnect from "./CmaeConnect";
import CmaePanel from "./CmaePanel";
import { PANELS, TIME_SCALES, connectionTone } from "./panels";
import { cmaeApi } from "./api";
import { num } from "./format";

const [ECG, PPG, PULSE, PRESSURE] = PANELS;
const ORIGIN_ICON = { ble: Bluetooth, uart: Usb, simulada: FlaskConical };
const card = { background: "#fff", boxShadow: "var(--shadow-sm)", borderRadius: "var(--bs-border-radius)" };
const muted = { color: "var(--color-neutral-700)" };

/** Punto de color + "Conectada", para el encabezado y la barra de conexión. */
export function CmaeDot({ estado }) {
  const tone = connectionTone(estado?.conexion);
  return <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: "50%", background: tone.color, display: "inline-block", flex: "none" }} />;
}

function ConnectionBar({ estado, onConnect, timeScale, setTimeScale }) {
  const [error, setError] = useState(null);
  const c = estado?.conexion;
  const tone = connectionTone(c);
  const Icon = ORIGIN_ICON[c?.origen] || Plug;
  const f = estado?.flujo;

  const disconnect = () => {
    setError(null);
    cmaeApi.disconnect().catch((e) => setError(e.message));
  };

  return (
    <div style={{ ...card, flex: "none", display: "flex", alignItems: "center", gap: 16, padding: "10px 14px", flexWrap: "wrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <Icon size={20} strokeWidth={1.5} color="var(--color-accent-700)" aria-hidden="true" />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CmaeDot estado={estado} />
            <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 18 }}>
              {estado ? tone.text : "Sin conexión con el backend"}
            </span>
            {c?.activa && c.nombre && <span style={{ fontSize: 13 }}>{c.nombre}</span>}
          </div>
          <div style={{ fontSize: 12, ...muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {c?.estado !== "Conectada" && c?.detalle}
            {c?.estado === "Conectada" && f && (
              <>
                {num(f.tramas_s, 1)} tramas/s
                {f.perdida_pct != null && ` · ${num(f.perdida_pct, 2)} % perdido`}
                {c.cortes ? ` · ${c.cortes} cortes` : ""}
              </>
            )}
            {!c?.activa && !c?.detalle && "Conecta la placa para ver ECG, pulsómetro, BPM, SpO₂ y presiones."}
          </div>
          {c?.uart?.texto && (
            <div style={{ fontSize: 12, color: "oklch(0.42 0.09 62)" }} title={c.uart.texto}>
              Llegan datos por USB pero no son tramas de la placa (¿solo texto de arranque?).
            </div>
          )}
          {error && <div style={{ fontSize: 12, color: "var(--cm-bad)" }}>{error}</div>}
        </div>
      </div>

      {setTimeScale && (
        <div className="btn-group btn-group-sm ms-auto" role="group" aria-label="Ventana de tiempo de los gráficos">
          {TIME_SCALES.map((t) => (
            <button key={t.value} type="button" title={t.hint} onClick={() => setTimeScale(t.value)}
              className={`btn btn-outline-primary${timeScale === t.value ? " active" : ""}`}>
              {t.label}
            </button>
          ))}
        </div>
      )}
      <div style={{ marginLeft: setTimeScale ? 0 : "auto" }}>
        {c?.activa ? (
          <button type="button" className="btn btn-outline-secondary d-inline-flex align-items-center gap-2" onClick={disconnect}
            disabled={c.estado === "Desconectando"}>
            <Unplug size={15} strokeWidth={1.5} /> Desconectar
          </button>
        ) : (
          <button type="button" className="btn btn-primary d-inline-flex align-items-center gap-2" onClick={onConnect} disabled={!estado}>
            <Plug size={15} strokeWidth={1.5} /> Conectar placa
          </button>
        )}
      </div>
    </div>
  );
}

export function CmaePage({ estado }) {
  const [modal, setModal] = useState(false);
  const [timeScale, setTimeScale] = useState(1);
  return (
    <section aria-label="Placa CMAE" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 12 }}>
      <ConnectionBar estado={estado} onConnect={() => setModal(true)} timeScale={timeScale} setTimeScale={setTimeScale} />
      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gridTemplateRows: "minmax(0,1fr) minmax(0,1fr)", gap: 12 }}>
        <CmaePanel panel={ECG} estado={estado} timeScale={timeScale} style={{ gridColumn: "1 / 3" }} />
        <CmaePanel panel={PPG} estado={estado} timeScale={timeScale} />
        <CmaePanel panel={PULSE} estado={estado} timeScale={timeScale} style={{ gridColumn: "1 / 3" }} />
        <CmaePanel panel={PRESSURE} estado={estado} timeScale={timeScale} />
      </div>
      <CmaeConnect show={modal} onHide={() => setModal(false)} />
    </section>
  );
}

/** Botón Conectar placa (con su ventana) o Desconectar, según el estado de la placa. */
export function CmaeConnectButton({ estado, size }) {
  const [modal, setModal] = useState(false);
  const [error, setError] = useState(null);
  const c = estado?.conexion;
  const sm = size === "sm" ? " btn-sm" : "";
  const disconnect = () => {
    setError(null);
    cmaeApi.disconnect().catch((e) => setError(e.message));
  };
  return (
    <>
      {c?.activa ? (
        <button type="button" className={`btn btn-outline-secondary${sm} d-inline-flex align-items-center gap-2`} onClick={disconnect}
          disabled={c.estado === "Desconectando"} title={error || undefined}>
          <Unplug size={14} strokeWidth={1.5} /> Desconectar
        </button>
      ) : (
        <button type="button" className={`btn btn-primary${sm} d-inline-flex align-items-center gap-2`} onClick={() => setModal(true)} disabled={!estado}>
          <Plug size={14} strokeWidth={1.5} /> Conectar placa
        </button>
      )}
      <CmaeConnect show={modal} onHide={() => setModal(false)} />
    </>
  );
}

/** Tarjeta "Placa CMAE" de la pantalla Nueva adquisición. */
export function CmaeSourceCard({ estado }) {
  const c = estado?.conexion;
  const tone = connectionTone(c);
  const Icon = ORIGIN_ICON[c?.origen] || Plug;
  const detalle = c?.estado === "Conectada" ? c.nombre : c?.detalle;
  return (
    <div className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", padding: 18, gap: 10 }}>
      <div style={{ fontSize: 11, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--color-accent-700)" }}>
        Placa CMAE · referencia (opcional)
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Icon size={20} strokeWidth={1.5} color="var(--color-accent-700)" aria-hidden="true" />
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CmaeDot estado={estado} />
            <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 17 }}>{estado ? tone.text : "Sin conexión con el backend"}</span>
          </div>
          {detalle && <div style={{ fontSize: 12, ...muted }}>{detalle}</div>}
        </div>
        <CmaeConnectButton estado={estado} />
      </div>
      <p style={{ fontSize: 13, margin: 0, color: "var(--color-neutral-800)" }}>
        ECG, pulsómetro, BPM, SpO₂ y presión diferencial. Si está conectada al iniciar, se graban sincronizados con el
        protocolo en <code>&lt;archivo&gt;_cmae.csv</code> y se grafican aparte, con el mismo eje de tiempo.
      </p>
    </div>
  );
}
