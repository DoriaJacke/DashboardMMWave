// Banner de fase: el elemento principal de la vista en vivo, legible a distancia
// por el participante. Fondo del color de la fase, texto grande, cuenta regresiva
// o segundos restantes, avance de mediciones y botones de confirmación y marca.

import { Flag } from "lucide-react";
import { EASE, useAnimateOnChange, useNow } from "../lib/hooks";
import { clock, clockAt, fmt, mmss } from "../lib/format";
import { PH, SHADE, phaseOf, perMeasurement, plannedDurations } from "../lib/phases";

/** Segundos que faltan para terminar la secuencia (sin contar las esperas de confirmación). */
function remainingTotal(status, p, N, rem) {
  const per = perMeasurement(p);
  const tp = +p.tp;
  const durs = plannedDurations(p);
  const m = status.medicion;
  const fase = status.fase;
  if (fase === "FIN") return 0;
  if (fase === "CONECTANDO" || !m) return N * per + (N - 1) * tp;
  if (fase === "ESPERA") return (N - m + 1) * per + (N - m) * tp;
  if (fase === "PAUSA") return (rem || 0) + (N - m) * per + Math.max(0, N - m - 1) * tp;
  const i = SHADE.indexOf(fase);
  if (i < 0) return 0;
  let r = rem || 0;
  for (const ph of SHADE.slice(i + 1)) r += durs[ph];
  return r + (N - m) * per + (N - m) * tp;
}

export default function Banner({ status, session, receivedAt, nMarkers, onConfirm, onMark, onSeeResult }) {
  const active = !status.terminado;
  const now = useNow(250, active);
  const dtLocal = active ? Math.max(0, (now - receivedAt) / 1000) : 0;
  const t = status.t + dtLocal;
  const fase = status.fase;
  const seq = session.proto === "seq";
  const p = session.params;
  const N = status.total;
  const m = status.medicion;
  const rem = status.remaining_s != null && active ? Math.max(0, status.remaining_s - dtLocal) : null;
  const error = !!status.error;

  let bg = phaseOf(fase).bg;
  const top = seq ? (m ? `MEDICIÓN ${m}/${N}` : "") : "CAPTURA CONTINUA";
  let text = fase === "FIN" ? status.estado : phaseOf(fase).label;
  let count = null;
  let remain = null;
  let sub = null;

  if (fase === "PREP" && status.cuenta != null && active) count = String(status.cuenta);
  else if (["NORMAL", "PREP", "HOLD", "RECOVERY", "PAUSA"].includes(fase) && rem != null && active) {
    if (fase !== "PREP") remain = `${fmt(Math.ceil(rem - 1e-6))} s`;
  } else if (fase === "CONTINUO" && active) {
    const elapsed = (status.phase_elapsed_s ?? 0) + dtLocal;
    if (rem != null) remain = `Quedan ${mmss(Math.ceil(rem - 1e-6))}`;
    else {
      remain = `${mmss(elapsed)} transcurridos`;
      sub = "Sin duración fija · se detiene con «Detener adquisición»";
    }
  } else if (fase === "ESPERA" && active) {
    sub = status.esperando_usuario ? "Ubícate frente al radar. El operador confirmará cuando estés listo." : null;
  } else if (fase === "CONECTANDO" && active) {
    sub = session.source.kind === "sim" ? "Iniciando el simulador…" : `Abriendo Puerto ${session.source.port} · ${fmt(session.source.baud)} baudios…`;
  }

  if (error) {
    bg = PH.FIN.bg;
    text = "ADQUISICIÓN DETENIDA POR ERROR";
    count = null;
    remain = null;
    const saved = status.n_saved > 0 ? ` Los datos recibidos hasta las ${clockAt(status.t0_wall, status.t)} quedaron guardados.` : " No se guardaron datos.";
    sub = `${status.error}${saved}`;
  }

  // Barra de tiempo de la fase (se reinicia sin transición al empezar una fase).
  let pct = 0;
  const el = status.phase_elapsed_s;
  if (!error && active && el != null && status.remaining_s != null && el + status.remaining_s > 0) {
    pct = Math.min(100, (el / (el + status.remaining_s)) * 100);
  }
  const barTransition = el != null && el < 1 ? "none" : "width 1s linear";

  // Avance de mediciones.
  let cells = [];
  let progText = "";
  if (seq && N > 0) {
    const curDone = Math.max(0, m - (["PAUSA", "FIN"].includes(fase) ? 0 : 1));
    cells = Array.from({ length: N }, (_, i) => {
      const k = i + 1;
      const done = k <= curDone;
      const cur = k === m && !done && active;
      return { k, done, cur };
    });
    progText = `${curDone} de ${N} completadas`;
    // Con error ya no hay tiempo restante que mostrar.
    if (!error) {
      const remainAll = remainingTotal(status, p, N, rem);
      progText += ` · restante ${mmss(remainAll)}${p.esperar ? " más las esperas" : ""} · fin aprox. ${clock(new Date(Date.now() + remainAll * 1000))}`;
    }
  }

  const canMark = active && status.recording;
  const showConfirm = active && fase === "ESPERA" && status.esperando_usuario;

  const textRef = useAnimateOnChange(text, [{ opacity: 0, transform: "translateY(20px) scale(.97)" }, { opacity: 1, transform: "none" }], { duration: 500, easing: EASE });
  const countRef = useAnimateOnChange(count, [{ opacity: 0, transform: "scale(1.6)" }, { opacity: 1, transform: "scale(1)" }], { duration: 460, easing: EASE }, true);

  return (
    <section
      aria-live="polite"
      style={{
        flex: "none", position: "relative", overflow: "hidden", borderRadius: "var(--bs-border-radius-lg)", boxShadow: "var(--shadow-md)",
        transition: "background-color .6s ease", background: bg, color: "var(--color-bg)", display: "grid",
        gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "center", gap: 28,
        padding: "clamp(8px,1.8vh,16px) 28px clamp(22px,3.4vh,30px)", minHeight: "clamp(118px,22vh,190px)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 20, alignItems: "baseline", flexWrap: "wrap", minHeight: 26 }}>
          <span style={{ fontFamily: "var(--font-heading)", fontSize: "clamp(17px,2.8vh,24px)", letterSpacing: ".2em" }}>{top}</span>
          <span style={{ fontSize: 14, opacity: 0.9, marginLeft: "auto" }}>{progText}</span>
        </div>
        <div ref={textRef} style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: "clamp(36px, min(5.6vw, 8.5vh), 80px)", lineHeight: 1, letterSpacing: ".005em", textWrap: "balance" }}>
          {text}
        </div>
        {sub && (
          <div role={error ? "alert" : "status"} style={{ fontSize: "clamp(14px,2.2vh,18px)", opacity: 0.95 }}>
            {sub}
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6, minWidth: 200 }}>
        {count != null && (
          <div ref={countRef} style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: canMark ? "clamp(70px, 13vh, 120px)" : "clamp(90px, 18vh, 160px)", lineHeight: 0.9, fontVariantNumeric: "tabular-nums" }}>
            {count}
          </div>
        )}
        {error && (
          <button className="btn btn-light" onClick={onSeeResult} style={{ fontSize: 18, padding: "10px 20px", color: "var(--color-text)", whiteSpace: "nowrap" }}>
            Ver resultado
          </button>
        )}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          {remain && (
            <div style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: "clamp(44px, 8vh, 68px)", lineHeight: 1, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
              {remain}
            </div>
          )}
          {canMark && (
            <>
              <button className="btn btn-light d-inline-flex align-items-center gap-2" onClick={onMark}
                title="Agrega una marca en los tres gráficos en el instante actual (tecla M)"
                style={{ fontSize: 17, padding: "7px 16px", color: "var(--color-text)", whiteSpace: "nowrap" }}>
                <Flag size={16} strokeWidth={1.5} />
                Marcar punto de interés
                <span style={{ fontFamily: "var(--font-body)", fontWeight: 400, fontSize: 12, border: "1px solid rgba(29,31,32,.3)", padding: "0 6px", borderRadius: 4 }}>M</span>
              </button>
              <span style={{ fontSize: 12, opacity: 0.88 }}>
                {nMarkers ? `${nMarkers} ${nMarkers === 1 ? "marca" : "marcas"} · se guardan en el CSV` : "Las marcas se guardan en el CSV"}
              </span>
            </>
          )}
        </div>
        {showConfirm && (
          <div className="enter-up" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
            <button className="btn btn-light" autoFocus onClick={onConfirm}
              style={{
                fontSize: "clamp(17px,2.7vh,24px)", padding: "clamp(8px,1.6vh,14px) 24px", borderRadius: "var(--bs-border-radius-lg)",
                color: "var(--color-text)", animation: "pulseRingW 2.2s ease-out infinite", whiteSpace: "nowrap", lineHeight: 1.1,
              }}>
              Estoy en posición — comenzar medición {m}
            </button>
            <span style={{ fontSize: 12, opacity: 0.85 }}>o presiona Enter</span>
          </div>
        )}
      </div>

      {seq && cells.length > 0 && (
        <div role="progressbar" aria-label="Avance de mediciones" aria-valuemin={0} aria-valuemax={N} aria-valuenow={cells.filter((c) => c.done).length}
          style={{ position: "absolute", left: 28, right: 28, bottom: 12, display: "grid", gridTemplateColumns: `repeat(${N},minmax(0,1fr))`, gap: 3 }}>
          {cells.map((c) => (
            <div key={c.k} title={`Medición ${c.k}${c.done ? " · completada" : c.cur ? " · en curso" : ""}`}
              style={{
                height: 8, background: c.done || c.cur ? "rgba(255,255,255,.92)" : "rgba(255,255,255,.24)", borderRadius: 2,
                transition: "background-color .5s ease", animation: c.cur ? "cellPulse 1.6s ease-in-out infinite" : "none",
              }} />
          ))}
        </div>
      )}
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 4, background: "rgba(255,255,255,.18)" }}>
        <div style={{ height: "100%", width: `${pct.toFixed(1)}%`, background: "var(--color-bg)", transition: barTransition }} />
      </div>
    </section>
  );
}
