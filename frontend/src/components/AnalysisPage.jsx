// Sección Análisis: abre un CSV de la carpeta de datos (también los antiguos,
// en formato de secuencia o continuo) o uno subido desde el equipo, y muestra
// los mismos gráficos, resumen por fase y exportación que el Resultado.

import { FileUp, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { clock, fmt, mmss, pad } from "../lib/format";
import { useNow } from "../lib/hooks";
import { RED, phaseOf } from "../lib/phases";
import { dataDomain, emptyStore, expandBW, ingest, segmentsFrom } from "../lib/series";
import { useExport } from "../lib/useExport";
import ChartsCard from "./ChartsCard";
import ExportCard from "./ExportCard";
import { indicatorDetail } from "./Header";
import SummaryTable from "./SummaryTable";

const VIEW = { med: "todas", x: "i", shade: true, sg: false, sgw: 0.8, sgo: 2 };

const grid = { flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "400px minmax(0,1fr)", gridTemplateRows: "minmax(0,1fr)", gap: 14 };
const leftCol = { display: "flex", flexDirection: "column", gap: 12, minHeight: 0, overflow: "auto", padding: 2, margin: -2 };
const card = { boxShadow: "var(--shadow-sm)", background: "#fff", flex: "none", padding: 16, gap: 10 };
const dl = { display: "grid", gridTemplateColumns: "auto minmax(0,1fr)", gap: "3px 12px", margin: 0, fontSize: 13 };
const dt = { fontWeight: 400, color: "var(--color-neutral-700)" };
const errorBox = { padding: "8px 10px", fontSize: 13, border: `1px solid ${RED}`, background: "oklch(0.96 0.02 27)", color: "oklch(0.38 0.12 27)" };

const sizeText = (b) => (b < 1048576 ? `${fmt(b / 1024, b < 10240 ? 1 : 0)} KB` : `${fmt(b / 1048576, 1)} MB`);
const dayText = (d) => `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`;
const FORMATS = { seq: "Secuencia (MEDICION20SEQRES)", cont: "Continuo (tomadatosSEPT)" };

export default function AnalysisPage({ live, liveActive, onBack, toast, unit }) {
  useNow(1000, liveActive);
  const [files, setFiles] = useState({ list: null, error: null });
  const [opening, setOpening] = useState(null);
  const [openError, setOpenError] = useState(null);
  const [ds, setDs] = useState(null);
  const [view, setViewState] = useState(VIEW);
  const [tab, setTab] = useState("charts");
  const { exp, setDpi, reset: resetExport, generate, download } = useExport(toast);
  const reqId = useRef(0);
  const uploadRef = useRef(null);

  const refresh = useCallback(() => {
    api
      .files()
      .then((r) => setFiles({ list: r.files, error: null }))
      .catch((e) => setFiles({ list: null, error: e.message }));
  }, []);
  useEffect(() => refresh(), [refresh]);

  // Solo vale la respuesta del último archivo pedido.
  const load = async (origin, name, fetcher) => {
    const id = ++reqId.current;
    setOpening({ origin, name });
    setOpenError(null);
    try {
      const d = await fetcher();
      if (id !== reqId.current) return;
      setDs(d);
      setViewState({ ...VIEW, med: d.proto === "seq" && d.mediciones.length ? String(d.mediciones[0]) : "todas" });
      setTab("charts");
      resetExport();
    } catch (e) {
      if (id === reqId.current) setOpenError(e.message);
    } finally {
      if (id === reqId.current) setOpening(null);
    }
  };
  const openSaved = (name) => load("datos", name, () => api.openFile(name));
  const onUpload = (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) load("upload", file.name, () => api.uploadFile(file));
  };

  // ---------- Datos para los gráficos (igual que el Resultado) ----------
  const seq = ds?.proto === "seq";
  const data = useMemo(() => {
    if (!ds) return null;
    const store = emptyStore();
    ingest(store, ds.records, ds.dist);
    return { bw: expandBW(store.bwFrames), hr: store.hr, br: store.br, marks: store.phaseMarks, markers: store.markers, noBW: !store.bwFrames.length };
  }, [ds]);

  const chartData = useMemo(() => {
    if (!data) return null;
    const med = seq && view.med !== "todas" ? +view.med : null;
    const f = med != null ? (p) => p.m === med : null;
    const series = f ? [data.bw.filter(f), data.hr.filter(f), data.br.filter(f)] : [data.bw, data.hr, data.br];
    const segsAll = segmentsFrom(data.marks, ds.t_total);
    const any = series.some((x) => x.length);
    return {
      series,
      dom: dataDomain(series),
      segs: med != null ? segsAll.filter((x) => x.m === med) : segsAll,
      now: null,
      markers: data.markers,
      emptyMsg: !ds.records.length ? "El archivo no tiene registros." : any ? "Sin datos en esta ventana." : "No hay datos para graficar.",
      t0Wall: ds.t0_wall,
      partial: data.noBW && data.hr.length > 0,
      version: ds.key,
    };
  }, [data, ds, seq, view.med]);

  const medOptions = useMemo(
    () => [{ v: "todas", label: "Todas" }].concat((ds?.mediciones || []).map((m) => ({ v: String(m), label: `Medición ${m}` }))),
    [ds],
  );
  const setView = useCallback((patch) => setViewState((v) => ({ ...v, ...patch })), []);
  const title = !ds
    ? ""
    : seq
      ? view.med === "todas" ? "Todas las mediciones — MR60BHA1" : `Medición ${view.med} — MR60BHA1`
      : "Captura continua — MR60BHA1";

  const exporting = exp.state === "running";
  const onGenerate = () =>
    generate({ key: ds.key, sgWindow: view.sg ? view.sgw : null, sgOrder: view.sgo }, `graficos_${ds.file.replace(/\.csv$/i, "")}.zip`);

  const recording = liveActive ? live.session?.file : null;
  const t0 = ds?.t0_wall ? new Date(ds.t0_wall) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1, minHeight: 0 }}>
      {liveActive && (
        <div className="card border-0" style={{ boxShadow: "var(--shadow-sm)", background: "#fff", flexDirection: "row", display: "flex", alignItems: "center", gap: 16, padding: "10px 16px", flex: "none" }}>
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

      <div style={grid}>
        <div style={leftCol}>
          <section className="card border-0" style={card} aria-label="Archivos de mediciones">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h2 style={{ fontSize: 20, margin: 0, flex: 1 }}>Archivos</h2>
              <button className="btn btn-sm btn-outline-secondary d-inline-flex align-items-center gap-1" onClick={refresh} title="Volver a leer la carpeta de datos">
                <RefreshCw size={14} strokeWidth={1.5} />
                Actualizar
              </button>
            </div>
            <p style={{ fontSize: 13, margin: 0, color: "var(--color-neutral-800)" }}>
              CSV de la carpeta de datos, incluidos los antiguos. Se reconocen los formatos de secuencia y continuo.
            </p>
            {files.error && <div role="alert" className="alert mb-0" style={errorBox}>{files.error}</div>}
            {files.list && !files.list.length && (
              <div style={{ fontSize: 13, color: "var(--color-neutral-700)" }}>La carpeta de datos no tiene archivos CSV.</div>
            )}
            {files.list?.length > 0 && (
              <div className="list-group" role="listbox" aria-label="CSV guardados" style={{ maxHeight: 300, overflow: "auto" }}>
                {files.list.map((f) => {
                  const active = ds?.origin === "datos" && ds.file === f.name;
                  const busy = opening?.origin === "datos" && opening.name === f.name;
                  return (
                    <button key={f.name} type="button" role="option" aria-selected={active} disabled={exporting}
                      className="list-group-item list-group-item-action"
                      onClick={() => openSaved(f.name)}
                      style={{ padding: "7px 10px", ...(active && { background: "var(--color-accent-100)", color: "var(--color-accent-800)", boxShadow: "inset 3px 0 0 var(--color-accent)" }) }}>
                      <div style={{ fontFamily: "ui-monospace,monospace", fontSize: 12, wordBreak: "break-all" }}>{f.name}</div>
                      <div style={{ fontSize: 12, opacity: 0.8, display: "flex", gap: 8 }}>
                        <span>{dayText(new Date(f.mtime))} {clock(new Date(f.mtime)).slice(0, 5)}</span>
                        <span>· {sizeText(f.size)}</span>
                        {recording === f.name && <span>· grabando ahora</span>}
                        {busy && <span>· abriendo…</span>}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
            <input ref={uploadRef} type="file" accept=".csv,text/csv" onChange={onUpload} style={{ display: "none" }} />
            <button className="btn btn-outline-secondary d-inline-flex align-items-center justify-content-center gap-2" disabled={exporting}
              onClick={() => uploadRef.current?.click()}>
              <FileUp size={16} strokeWidth={1.5} />
              {opening?.origin === "upload" ? `Subiendo ${opening.name}…` : "Subir CSV desde el equipo"}
            </button>
            {openError && <div role="alert" className="alert mb-0 enter-down" style={errorBox}>{openError}</div>}
          </section>

          {ds && (
            <section className="card border-0" style={card} aria-label="Archivo abierto">
              <h2 style={{ fontSize: 20, margin: 0 }}>Archivo abierto</h2>
              <dl style={dl}>
                <dt style={dt}>Archivo</dt>
                <dd style={{ margin: 0, fontFamily: "ui-monospace,monospace", fontSize: 12, wordBreak: "break-all" }}>{ds.file}</dd>
                <dt style={dt}>Origen</dt>
                <dd style={{ margin: 0 }}>{ds.origin === "datos" ? "Carpeta de datos" : "Subido desde el equipo"}</dd>
                <dt style={dt}>Formato</dt>
                <dd style={{ margin: 0 }}>{FORMATS[ds.proto]}</dd>
                <dt style={dt}>Filas</dt>
                <dd style={{ margin: 0, fontWeight: 500 }}>{fmt(ds.n_rows)}</dd>
                <dt style={dt}>Mediciones</dt>
                <dd style={{ margin: 0 }}>{seq ? `${ds.mediciones.length} · completas ${ds.n_end}` : "Captura continua"}</dd>
                <dt style={dt}>Duración</dt>
                <dd style={{ margin: 0 }}>{mmss(ds.t_total)}</dd>
                <dt style={dt}>Inicio</dt>
                <dd style={{ margin: 0 }}>{t0 ? `${dayText(t0)} ${clock(t0)}` : "—"}</dd>
              </dl>
              {recording === ds.file && ds.origin === "datos" && (
                <div style={{ fontSize: 12, color: "var(--color-neutral-700)" }}>
                  Este archivo se sigue grabando: lo que ves es lo guardado al abrirlo. Usa Actualizar y ábrelo de nuevo para ver más.
                </div>
              )}
            </section>
          )}

          {ds && ds.records.length > 0 && (
            <ExportCard exp={exp} nImages={seq ? Math.max(1, ds.mediciones.length) : 1} onDpi={setDpi} onGenerate={onGenerate} onDownload={download}
              exportProgress={exporting ? live.exportProgress : null} style={{ flex: "none" }} />
          )}
        </div>

        {ds ? (
          <ChartsCard isResult proto={ds.proto} title={title} data={chartData} view={view} setView={setView} medOptions={medOptions}
            tab={tab} setTab={setTab} zoomKey={ds.key}
            table={<SummaryTable proto={ds.proto} rows={ds.summary} loading={false} error={null} unit={unit} />} />
        ) : (
          <section className="card border-0" style={{ ...card, flex: 1, alignItems: "center", justifyContent: "center", textAlign: "center", color: "var(--color-neutral-700)" }}>
            <h2 style={{ fontSize: 22, margin: 0, color: "var(--color-text)" }}>Análisis de mediciones</h2>
            <p style={{ margin: 0, fontSize: 14, maxWidth: 460 }}>
              {opening ? `Abriendo ${opening.name}…` : "Elige un CSV de la lista o sube uno desde el equipo para ver sus gráficos, el resumen por fase y exportar las imágenes."}
            </p>
          </section>
        )}
      </div>
    </div>
  );
}
