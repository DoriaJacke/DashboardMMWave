// Encabezado: marca, pestañas Adquisición / Análisis, datos de la adquisición en
// curso (en Adquisición) o indicador global (en Análisis).

import { Radio, Square } from "lucide-react";
import { useNow } from "../lib/hooks";
import { liveT } from "../lib/useLive";
import { fmt, mmss } from "../lib/format";
import { phaseOf } from "../lib/phases";

const tabStyle = (on) => ({
  fontFamily: "var(--font-heading)", fontSize: 16, padding: "0 14px", background: "transparent", border: 0,
  borderBottom: `2px solid ${on ? "var(--color-accent)" : "transparent"}`, transition: "border-color .25s",
  color: "var(--color-text)", cursor: "pointer",
});

/** Texto corto del avance: "Medición 3/20 · 12 s" o "Quedan 04:10". */
export function indicatorDetail(live) {
  const st = live.status;
  const seq = live.session.proto === "seq";
  const dtLocal = Math.max(0, (performance.now() - live.receivedAt) / 1000);
  const rem = st.remaining_s != null ? Math.max(0, st.remaining_s - dtLocal) : null;
  if (seq && st.medicion) return `Medición ${st.medicion}/${st.total}${rem != null ? ` · ${fmt(Math.ceil(rem - 1e-6))} s` : ""}`;
  if (seq) return "Conectando";
  return rem != null ? `Quedan ${mmss(rem)}` : "Sin duración fija";
}

function Indicator({ live, onClick }) {
  useNow(500);
  const fase = live.status.fase;
  return (
    <button onClick={onClick} title="Ir a la adquisición en curso"
      style={{ marginLeft: "auto", alignSelf: "center", display: "flex", alignItems: "center", gap: 10, padding: "4px 14px 4px 4px", background: "#fff", border: "1px solid var(--color-divider)", borderRadius: 999, transition: "box-shadow .2s", cursor: "pointer", font: "inherit", fontSize: 13, color: "var(--color-text)" }}>
      <span style={{ background: phaseOf(fase).bg, color: "var(--color-bg)", fontFamily: "var(--font-heading)", fontSize: 13, letterSpacing: ".06em", padding: "3px 10px", borderRadius: 999, transition: "background-color .5s" }}>
        {fase}
      </span>
      <span style={{ fontWeight: 500 }}>Adquisición en curso</span>
      <span style={{ color: "var(--color-neutral-700)" }}>{indicatorDetail(live)}</span>
      <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--color-neutral-700)" }}>{mmss(liveT(live))}</span>
    </button>
  );
}

export default function Header({ tab, setTab, live, liveActive, screen, onStop, sourceText, startedClock }) {
  // Se mantiene durante el error en vivo; el botón Detener solo aparece si sigue corriendo.
  const showLiveInfo = tab === "adq" && screen === "live";
  const s = live.session;
  return (
    <header style={{ flex: "none", display: "flex", alignItems: "stretch", gap: 24, padding: "0 20px", height: 56, background: "#fff", boxShadow: "var(--shadow-sm)", position: "relative", zIndex: 1020 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flex: "none" }}>
        <Radio size={22} strokeWidth={1.5} color="var(--color-accent-700)" aria-hidden="true" />
        <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 20, letterSpacing: "-.01em", whiteSpace: "nowrap" }}>Dashboard mmWave MR60BHA1</span>
      </div>
      <nav style={{ display: "flex", alignItems: "stretch", gap: 4 }} aria-label="Secciones">
        <button onClick={() => setTab("adq")} style={tabStyle(tab === "adq")} aria-current={tab === "adq" ? "page" : undefined}>Adquisición</button>
        <button onClick={() => setTab("ana")} style={tabStyle(tab === "ana")} aria-current={tab === "ana" ? "page" : undefined}>Análisis</button>
      </nav>
      {showLiveInfo && (
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 16, fontSize: 13, minWidth: 0 }}>
          <span style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: 17, whiteSpace: "nowrap" }}>
            {s.proto === "seq" ? "Secuencia con retención" : "Captura continua"}
          </span>
          <span style={{ color: "var(--color-neutral-700)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={s.path}>
            <span style={{ fontFamily: "ui-monospace,monospace", fontSize: 12, color: "var(--color-text)" }}>{s.path}</span>
          </span>
          <span style={{ color: "var(--color-neutral-700)", whiteSpace: "nowrap", flex: "none" }}>Iniciada {startedClock}</span>
          <span style={{ color: "var(--color-neutral-700)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0, flex: "0 1 auto" }}>{sourceText}</span>
          {!live.status.terminado && (
            <button className="btn btn-outline-secondary d-inline-flex align-items-center gap-2" onClick={onStop} style={{ flex: "none", height: 38, padding: "0 14px", fontSize: 15, whiteSpace: "nowrap" }}>
              <Square size={14} strokeWidth={1.5} />
              Detener adquisición
            </button>
          )}
        </div>
      )}
      {tab === "ana" && liveActive && <Indicator live={live} onClick={() => setTab("adq")} />}
    </header>
  );
}
