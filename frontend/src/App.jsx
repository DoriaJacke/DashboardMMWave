// Dashboard mmWave MR60BHA1: sección Adquisición (Configuración → En vivo →
// Resultado) e indicador global. La sección Análisis es un esqueleto por ahora.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "react-bootstrap";
import AnalysisPage from "./components/AnalysisPage";
import Banner from "./components/Banner";
import ChartsCard from "./components/ChartsCard";
import ConfigForm, { SEQ_FIELDS, baudError, durError, fieldError } from "./components/ConfigForm";
import DistanceCard from "./components/DistanceCard";
import Header from "./components/Header";
import Metrics from "./components/Metrics";
import ResultPanel, { endKind } from "./components/ResultPanel";
import SummaryTable from "./components/SummaryTable";
import Toasts, { useToasts } from "./components/Toasts";
import { api } from "./lib/api";
import { clock, clockAt, defaultFileName, finalFileName, fmt, mmss, sourceLabel, stampOf } from "./lib/format";
import { EASE, useAnimateOnChange } from "./lib/hooks";
import { AMBER, GREEN, INK, PH, RED } from "./lib/phases";
import { dataDomain, expandBW, liveWindow, segmentsFrom } from "./lib/series";
import { useLive } from "./lib/useLive";

const LIVE_VIEW = { x: "t", win: "med", shade: true, sg: false, sgw: 0.8, sgo: 2 };
const RESULT_VIEW = { med: "1", x: "i", shade: true, sg: false, sgw: 0.8, sgo: 2 };
const NO_EXPORT = { state: null, blob: null, n: 0 };

const grid = { flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "400px minmax(0,1fr)", gridTemplateRows: "minmax(0,1fr)", gap: 14 };
const leftCol = { display: "flex", flexDirection: "column", gap: 12, minHeight: 0, overflow: "auto", padding: 2, margin: -2 };

export default function App() {
  const live = useLive();
  const { toasts, push: toast, close: closeToast } = useToasts();
  const [tab, setTab] = useState("adq");
  const [cfg, setCfgState] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [ports, setPorts] = useState({ list: [], scannedAt: "" });
  const [file, setFile] = useState("");
  const [stamp, setStamp] = useState(() => stampOf(new Date()));
  const [cfgErr, setCfgErr] = useState(null);
  const [starting, setStarting] = useState(false);
  const [modal, setModal] = useState(false);
  const [lv, setLv] = useState(LIVE_VIEW);
  const [rv, setRv] = useState(RESULT_VIEW);
  const [resTab, setResTab] = useState("charts");
  const [errAck, setErrAck] = useState({});
  const [exp, setExp] = useState({ ...NO_EXPORT, dpi: 300 });
  const [summary, setSummary] = useState({ id: null, rows: null, loading: false, error: null });
  const zoneTimer = useRef(null);

  const s = live.session;
  const st = live.status;
  const seq = s?.proto === "seq";
  const ended = !!st?.terminado;
  let screen = "config";
  if (s && st) screen = !ended || (st.error && !errAck[s.id] && !live.endedOnArrival) ? "live" : "result";
  const liveActive = !!s && !!st && !ended;

  // ---------- Carga inicial: configuración guardada y puertos ----------
  const refreshPorts = useCallback(() => {
    api
      .ports()
      .then((r) => setPorts({ list: r.ports, scannedAt: clock(new Date()) }))
      .catch(() => setPorts((p) => ({ ...p, scannedAt: clock(new Date()) })));
  }, []);

  useEffect(() => {
    api.config().then(setCfgState).catch((e) => setLoadError(e.message));
    refreshPorts();
  }, [refreshPorts]);

  // Si el puerto guardado no está entre los detectados, se elige el primero.
  useEffect(() => {
    if (cfg && ports.list.length && !ports.list.some((p) => p.device === cfg.port)) {
      setCfgState((c) => ({ ...c, port: ports.list[0].device }));
    }
  }, [cfg, ports.list]);

  const setCfg = useCallback((patch) => {
    setCfgState((c) => ({ ...c, ...patch }));
    setCfgErr(null);
  }, []);

  const onZone = useCallback(
    (patch) => {
      const zone = { ...cfg.zone, ...patch };
      setCfgState((c) => ({ ...c, zone }));
      clearTimeout(zoneTimer.current);
      zoneTimer.current = setTimeout(() => api.saveConfig({ zone }).catch(() => {}), 500);
    },
    [cfg],
  );

  // ---------- Cambios de estado: avisos y reinicios ----------
  const prevRef = useRef({ id: null, st: null });
  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = { id: s?.id ?? null, st };
    if (!s || !st) return;
    const isSeq = s.proto === "seq";
    const resetResult = () => {
      setRv({ ...RESULT_VIEW, med: isSeq ? "1" : "todas" });
      setResTab("charts");
      setExp((e) => ({ ...e, ...NO_EXPORT }));
      setSummary({ id: null, rows: null, loading: false, error: null });
    };
    const onEnd = () => {
      const k = endKind(st);
      toast(
        k === "ok" ? "Adquisición completada" : k === "stop" ? "Adquisición detenida manualmente" : "Adquisición terminada con error",
        k === "ok" ? GREEN : k === "stop" ? AMBER : RED,
      );
      setFile("");
      setStamp(stampOf(new Date()));
      setModal(false);
      resetResult();
    };
    if (prev.id !== s.id) {
      // Adquisición nueva (o la que ya estaba al abrir la página).
      setLv((v) => ({ ...v, x: "t", win: isSeq ? "med" : "60" }));
      resetResult();
      // Si falló apenas empezó (por ejemplo, el puerto no abre), igual se avisa.
      if (st.terminado && !live.endedOnArrival) onEnd();
      return;
    }
    const p = prev.st;
    if (!p) return;
    if (isSeq && p.fase !== "NORMAL" && st.fase === "NORMAL") toast(`Medición ${st.medicion} iniciada`, GREEN);
    if (isSeq && p.fase === "RECOVERY" && st.fase !== "RECOVERY" && !st.detenido && !st.error) {
      toast(`Medición ${p.medicion} de ${st.total} completada`, GREEN);
    }
    if (!p.terminado && st.terminado) onEnd();
  }, [s, st, toast, live.endedOnArrival]);

  // ---------- Acciones ----------
  const start = async () => {
    if (!cfg) return;
    if (cfg.src === "serial" && !String(cfg.port || "").trim()) {
      setCfgErr({ field: "port", msg: "Selecciona un puerto serial." });
      return;
    }
    const invalid =
      cfg.proto === "seq" ? SEQ_FIELDS.some(([k, , a, b, int]) => fieldError(cfg[k], a, b, int)) : !!durError(cfg.duracion);
    if (invalid || (cfg.src === "serial" && baudError(cfg.baud))) {
      setCfgErr({ field: "range", msg: "Revisa los campos marcados." });
      return;
    }
    setStarting(true);
    try {
      const meta = await api.start(cfg, finalFileName(file, cfg.proto, stamp));
      toast(`Adquisición iniciada · ${meta.path}`);
      setCfgErr(null);
      setModal(false);
      setTab("adq");
    } catch (e) {
      setCfgErr({ field: e.field, msg: e.message });
    } finally {
      setStarting(false);
    }
  };

  const onStop = useCallback(() => api.stop().catch((e) => toast(e.message, RED)), [toast]);
  // Un 409 aquí es un Enter repetido cuando la medición ya empezó: no es un error.
  const onConfirm = useCallback(() => api.confirm().catch((e) => e.status !== 409 && toast(e.message, RED)), [toast]);
  const t0Wall = st?.t0_wall;
  const onMark = useCallback(async () => {
    try {
      const mk = await api.marker();
      const where = seq && mk.medicion ? ` · medición ${mk.medicion}, ${(PH[mk.fase]?.name || mk.fase).toLowerCase()}` : "";
      toast(`Marca ${mk.label} agregada${where} · t = ${fmt(mk.t)} s · ${clockAt(t0Wall, mk.t)}`, INK);
    } catch (e) {
      toast(e.message, RED);
    }
  }, [seq, t0Wall, toast]);

  // Teclado: Enter confirma (en ESPERA) y M marca (en fases que se graban).
  useEffect(() => {
    const onKey = (e) => {
      if (tab !== "adq" || screen !== "live" || !st || st.terminado || modal || e.repeat) return;
      const tag = e.target?.tagName || "";
      const inField = /INPUT|SELECT|TEXTAREA/.test(tag);
      if ((e.key === "m" || e.key === "M") && !inField && !e.metaKey && !e.ctrlKey && !e.altKey && st.recording) {
        e.preventDefault();
        onMark();
      }
      if (e.key === "Enter" && !inField && tag !== "BUTTON" && st.fase === "ESPERA" && st.esperando_usuario) {
        e.preventDefault();
        onConfirm();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, screen, st, modal, onMark, onConfirm]);

  // ---------- Datos para los gráficos ----------
  const data = useMemo(() => {
    const store = live.store;
    return {
      bw: expandBW(store.bwFrames),
      hr: store.hr.slice(),
      br: store.br.slice(),
      marks: store.phaseMarks.slice(),
      markers: store.markers.slice(),
      dist: store.dist.slice(),
      nEnd: store.nEnd,
      noBW: store.bwFrames.length === 0,
    };
    // live.version cambia cada vez que llegan registros nuevos
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.version]);

  const chartData = useMemo(() => {
    if (!s || !st) return null;
    const segsAll = segmentsFrom(data.marks, st.t);
    const partial = data.noBW && data.hr.length > 0;
    const base = { t0Wall: st.t0_wall, partial, version: live.version };
    if (screen === "live") {
      const w = liveWindow({ win: lv.win, status: st, params: s.params, proto: s.proto, segs: segsAll });
      const f = w.filter;
      const series = f ? [data.bw.filter(f), data.hr.filter(f), data.br.filter(f)] : [data.bw, data.hr, data.br];
      const emptyMsg = st.error ? "No hay datos para graficar." : w.emptyMsg;
      return { ...base, series, dom: w.dom, segs: w.segs, now: st.t, markers: data.markers, emptyMsg };
    }
    const med = seq && rv.med !== "todas" ? +rv.med : null;
    const f = med != null ? (p) => p.m === med : null;
    const series = f ? [data.bw.filter(f), data.hr.filter(f), data.br.filter(f)] : [data.bw, data.hr, data.br];
    const any = series.some((x) => x.length);
    return {
      ...base,
      series,
      dom: dataDomain(series),
      segs: med != null ? segsAll.filter((x) => x.m === med) : segsAll,
      now: null,
      markers: data.markers,
      emptyMsg: any ? "Sin datos en esta ventana." : "No hay datos para graficar.",
    };
  }, [data, screen, lv.win, rv.med, s, st, seq, live.version]);

  const chartTitle = !s || !st
    ? ""
    : screen === "live"
      ? seq ? `Medición ${st.medicion || 1} — MR60BHA1` : "Captura continua — MR60BHA1"
      : seq ? (rv.med === "todas" ? "Todas las mediciones — MR60BHA1" : `Medición ${rv.med} — MR60BHA1`) : "Captura continua — MR60BHA1";

  const maxM = Math.max(1, ...data.marks.map((p) => p.m || 0));
  const medOptions = useMemo(
    () => [{ v: "todas", label: "Todas" }].concat(Array.from({ length: maxM }, (_, i) => ({ v: String(i + 1), label: `Medición ${i + 1}` }))),
    [maxM],
  );
  const setLiveView = useCallback((patch) => setLv((v) => ({ ...v, ...patch })), []);
  const setResultView = useCallback((patch) => setRv((v) => ({ ...v, ...patch })), []);

  // ---------- Resumen por fase ----------
  useEffect(() => {
    if (screen !== "result" || resTab !== "table" || !s || summary.id === s.id || !seq) return;
    setSummary({ id: s.id, rows: null, loading: true, error: null });
    api
      .summary()
      .then((r) => setSummary({ id: s.id, rows: r.rows, loading: false, error: null }))
      .catch((e) => setSummary({ id: s.id, rows: null, loading: false, error: e.message }));
  }, [screen, resTab, s, summary.id, seq]);

  // ---------- Exportar imágenes ----------
  const onGenerate = async () => {
    const dpi = Math.round(+exp.dpi);
    if (!(dpi >= 72 && dpi <= 600)) {
      toast("El DPI debe estar entre 72 y 600.", RED);
      return;
    }
    setExp((e) => ({ ...e, state: "running", blob: null }));
    try {
      const { blob, n } = await api.exportZip({ dpi, sgWindow: rv.sg ? rv.sgw : null, sgOrder: rv.sgo });
      setExp((e) => ({ ...e, state: "done", blob, n: n || 1, dpi }));
      toast("Imágenes listas: graficos_mediciones.zip", GREEN);
    } catch (e) {
      setExp((x) => ({ ...x, ...NO_EXPORT }));
      toast(e.message, RED);
    }
  };
  const onDownload = () => {
    if (!exp.blob) return;
    const url = URL.createObjectURL(exp.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "graficos_mediciones.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast("Descarga iniciada: graficos_mediciones.zip");
  };

  // ---------- Animación al cambiar de pantalla ----------
  const mainRef = useAnimateOnChange(`${tab}-${screen}`, [{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "none" }], { duration: 380, easing: EASE });

  const cfgSummary = cfg
    ? [
        { k: "Fuente", v: sourceLabel(cfg.src, cfg.port, cfg.baud) },
        {
          k: "Protocolo",
          v: cfg.proto === "seq"
            ? `Secuencia · ${cfg.n} mediciones · ${cfg.tn}/${cfg.th}/${cfg.tr} s${cfg.esperar ? " · con confirmación" : ""}`
            : `Continua · ${+cfg.duracion ? mmss(+cfg.duracion) : "hasta detener"}`,
        },
        { k: "Archivo", v: finalFileName(file, cfg.proto, stamp) },
      ]
    : [];

  const form = cfg && (
    <ConfigForm cfg={cfg} setCfg={setCfg} ports={ports.list} scannedAt={ports.scannedAt} onRefreshPorts={refreshPorts}
      fileValue={file || defaultFileName(cfg.proto, stamp)} setFile={(v) => { setFile(v); setCfgErr(null); }}
      onStart={start} error={cfgErr} starting={starting} />
  );

  let content = null;
  if (tab === "ana") {
    content = <AnalysisPage live={live} liveActive={liveActive} onBack={() => setTab("adq")} />;
  } else if (loadError) {
    content = (
      <div className="alert" role="alert" style={{ border: `1px solid ${RED}`, background: "oklch(0.96 0.02 27)", color: "oklch(0.38 0.12 27)" }}>
        {loadError} Ejecuta <code>uvicorn backend.main:app --port 8000</code> desde la raíz del repositorio y recarga la página.
      </div>
    );
  } else if (!cfg || !live.loaded) {
    content = <div style={{ padding: "32px 0", color: "var(--color-neutral-700)" }}>Conectando con el backend…</div>;
  } else if (screen === "config") {
    content = (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, minHeight: 0 }}>
        <section role="region" aria-label="Nueva adquisición" style={{ display: "flex", flexDirection: "column", gap: 14, width: "100%", maxWidth: 1400, maxHeight: "100%", overflow: "auto", margin: "0 auto" }}>
          <h2 style={{ fontSize: 28, margin: 0 }}>Nueva adquisición</h2>
          {form}
        </section>
      </div>
    );
  } else if (screen === "live") {
    content = (
      <>
        <Banner status={st} session={s} receivedAt={live.receivedAt} nMarkers={st.n_markers} onConfirm={onConfirm} onMark={onMark}
          onSeeResult={() => setErrAck((a) => ({ ...a, [s.id]: true }))} />
        <div style={grid}>
          <div style={leftCol}>
            <Metrics status={st} receivedAt={live.receivedAt} />
            <DistanceCard status={st} receivedAt={live.receivedAt} dist={data.dist} zone={cfg.zone} onZone={onZone} />
          </div>
          <ChartsCard isLive proto={s.proto} title={chartTitle} data={chartData} view={lv} setView={setLiveView} zoomKey={s.id} />
        </div>
      </>
    );
  } else {
    content = (
      <div style={grid}>
        <div style={leftCol}>
          <ResultPanel session={s} status={st} nEnd={data.nEnd} cfgSummary={cfgSummary} onStart={start} onEdit={() => setModal(true)}
            startError={modal ? null : cfgErr} starting={starting} exp={exp} onDpi={(v) => setExp((e) => ({ ...e, dpi: v }))}
            onGenerate={onGenerate} onDownload={onDownload} exportProgress={exp.state === "running" ? live.exportProgress : null} />
        </div>
        <ChartsCard isResult proto={s.proto} title={chartTitle} data={chartData} view={rv} setView={setResultView} medOptions={medOptions}
          tab={resTab} setTab={setResTab} zoomKey={s.id}
          table={<SummaryTable proto={s.proto} rows={summary.rows} loading={summary.loading} error={summary.error} unit={cfg.zone.unit} />} />
      </div>
    );
  }

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--color-bg)", color: "var(--color-text)", fontFamily: "var(--font-body)" }}>
      <Header tab={tab} setTab={setTab} live={live} liveActive={liveActive} screen={screen} onStop={onStop}
        sourceText={s ? sourceLabel(s.source.kind, s.source.port, s.source.baud) : ""} startedClock={s ? clock(new Date(s.started_at)) : ""} />
      <main ref={mainRef} style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 12, padding: "12px 20px", width: "100%", maxWidth: 1680, margin: "0 auto", boxSizing: "border-box" }}>
        {live.loaded && !live.connected && (
          <div role="alert" className="alert mb-0 py-2" style={{ border: `1px solid ${AMBER}`, background: "oklch(0.97 0.03 85)", color: "oklch(0.40 0.09 62)", fontSize: 14 }}>
            Se perdió la conexión con el backend. Reintentando…
          </div>
        )}
        {content}
      </main>
      <Modal show={modal && screen === "result" && tab === "adq"} onHide={() => setModal(false)} dialogClassName="cfg-modal" backdropClassName="cfg-backdrop" centered animation={false} aria-labelledby="cfg-modal-title">
        <div className="enter-up" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h2 id="cfg-modal-title" style={{ fontSize: 24, margin: 0, flex: 1 }}>Editar siguiente adquisición</h2>
            <button type="button" className="btn-close" aria-label="Cerrar" onClick={() => setModal(false)} />
          </div>
          {form}
        </div>
      </Modal>
      <Toasts toasts={toasts} onClose={closeToast} />
    </div>
  );
}
