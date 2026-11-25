# ============================================================
# BACKEND DEL DASHBOARD MR60BHA1 (FastAPI)
#
# Ejecutar desde la raíz del repositorio:
#   uvicorn backend.main:app --port 8000
#
# - REST para listar puertos, iniciar, detener y confirmar la
#   adquisición, ver el resultado y exportar imágenes.
# - WebSocket /ws/live: al conectarse envía el historial completo
#   de la adquisición y después, ~1 vez por segundo (o apenas cambia
#   la fase), el estado y solo los datos nuevos.
# - /api/cmae/* y /ws/cmae: placa CMAE (backend/cmae/servicio.py), solo si
#   está habilitada (MMWAVE_CMAE=1, ver backend/features.py).
# - Si existe frontend/dist (npm run build) también sirve la interfaz.
#
# Hay una sola adquisición a la vez, compartida por todas las
# pestañas: si se recarga la página se vuelve a ver la que está en curso.
# ============================================================

from __future__ import annotations

import asyncio
import hashlib
import itertools
import math
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .acquisition import (
    WAVE_COLS,
    AcquisitionManager,
    AcquisitionSession,
    ApneaProtocol,
    ContinuousProtocol,
    RetentionProtocol,
    SerialSource,
    SimulatedSource,
    list_serial_ports_info,
)
from .features import CMAE_HABILITADA
from .config import ConfigStore, normalize, resolve_filename, validate_start
from .data_io import FORMATO_SECUENCIA, load_csv, phase_summary, records_to_long, start_wall
from .plots import SavgolConfig, export_zip

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "datos"
FRONTEND_DIST = ROOT / "frontend" / "dist"

STATUS_EVERY_S = 1.0   # envío periódico del estado
POLL_S = 0.1           # cada cuánto se revisa si hay datos nuevos o cambió la fase

class FrontendFiles(StaticFiles):
    """Archivos de frontend/dist. index.html se revalida siempre para tomar cada compilación nueva."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.media_type == "text/html":
            response.headers["Cache-Control"] = "no-cache"
        return response


CMAE_CSV = re.compile(r"_cmae(_\d+)?\.csv$", re.IGNORECASE)
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ANALYSIS_CACHE_SIZE = 4  # archivos abiertos en Análisis que se conservan para exportar


# ============================================================
# CONVERSIÓN A JSON
# ============================================================

def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(value, digits)


def record_json(r: dict) -> dict:
    """Registro en formato largo -> {t, m, f, k, v} compacto para el frontend."""
    tipo = r["tipo"]
    if tipo == "BW":
        value: Any = [_num(r[c]) for c in WAVE_COLS]
    elif tipo in ("HR", "BR", "DIST"):
        value = _num(r["valor_1"])
    elif tipo in ("EVENT", "MARK"):
        value = r["evento"]
    else:
        value = None
    medicion = r["medicion"] if isinstance(r["medicion"], int) else None
    return {"t": round(float(r["t"]), 3), "m": medicion, "f": r["fase"], "k": tipo, "v": value}


def dist_json(points: list[tuple[float, float]]) -> list[list[float]]:
    return [[round(t, 3), v] for t, v in points if _num(v) is not None]


def _text(value: Any) -> Optional[str]:
    return None if value is None or pd.isna(value) else str(value)


def long_json(df: pd.DataFrame) -> list[dict]:
    """Formato largo de un CSV -> los mismos {t, m, f, k, v} que record_json."""
    out = []
    for r in df.itertuples(index=False):
        t = _num(r.t)
        tipo = _text(r.tipo)
        if t is None or tipo is None:
            continue
        if tipo == "BW":
            value: Any = [_num(getattr(r, c)) for c in WAVE_COLS]
        elif tipo in ("HR", "BR", "DIST"):
            value = _num(r.valor_1)
        elif tipo in ("EVENT", "MARK"):
            value = _text(r.evento)
        else:
            value = None
        medicion = None if pd.isna(r.medicion) else int(r.medicion)
        out.append({"t": round(t, 3), "m": medicion, "f": _text(r.fase), "k": tipo, "v": value})
    return out


def summary_rows(df: pd.DataFrame) -> list[dict]:
    table = phase_summary(df)
    rows = []
    if table.empty:
        return rows
    for (medicion, fase), row in table.iterrows():
        if pd.isna(medicion):
            continue
        item = {"medicion": int(medicion), "fase": str(fase)}
        for tipo in ("HR", "BR", "DIST"):
            n = row.get(f"{tipo} n")
            n = 0 if n is None or (isinstance(n, float) and math.isnan(n)) else int(n)
            item[tipo] = {
                "media": _num(row.get(f"{tipo} media")) if n else None,
                "desv": _num(row.get(f"{tipo} desv")) if n else None,
                "n": n,
            }
        rows.append(item)
    return rows


def status_json(session: AcquisitionSession) -> dict:
    st = session.status
    now = time.monotonic()
    t = session.elapsed()

    latest = {}
    for key in ("HR", "BR", "EVENT", "DIST"):
        value = session.latest.get(key)
        t_key = session.latest_t.get(key)
        if value is None:
            latest[key] = None
        else:
            latest[key] = {
                "v": value if key == "EVENT" else _num(value),
                "age": None if t_key is None else round(max(0.0, t - t_key), 2),
            }

    remaining = None
    if st.fase_fin is not None and not st.terminado:
        remaining = max(0.0, st.fase_fin - now)
    phase_elapsed = None
    if st.fase_inicio is not None and not st.terminado:
        phase_elapsed = max(0.0, now - st.fase_inicio)

    return {
        "fase": st.fase or "CONECTANDO",
        "estado": st.estado,
        "medicion": st.medicion,
        "total": st.total,
        "remaining_s": _round(remaining),
        "phase_elapsed_s": _round(phase_elapsed),
        "cuenta": st.cuenta,
        "esperando_usuario": st.esperando_usuario,
        "recording": bool(session.ctx.recording and not st.terminado),
        "terminado": st.terminado,
        "detenido": st.detenido,
        "error": st.error,
        "t": round(t, 3),
        "t0_wall": session.t0_wall.isoformat(timespec="milliseconds"),
        "latest": latest,
        "n_lines": session.n_lines,
        "n_lines_saved": session.n_lines_saved,
        "n_saved": session.n_saved,
        "n_markers": len(session.markers),
    }


def status_signature(session: AcquisitionSession) -> tuple:
    """Lo que, si cambia, se envía de inmediato sin esperar al envío periódico."""
    st = session.status
    return (st.fase, st.medicion, st.estado, st.cuenta, st.esperando_usuario,
            st.terminado, st.error, session.ctx.recording, len(session.markers))


# ============================================================
# APLICACIÓN
# ============================================================

def create_app(data_dir: Optional[Path] = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("MMWAVE_DATA_DIR") or DEFAULT_DATA_DIR)
    # Placa CMAE (ECG, oxímetro, presión): conexión propia, independiente del radar.
    # Aislada por defecto (backend/features.py): sin ella no se importa backend/cmae/.
    cmae = None
    if CMAE_HABILITADA:
        from .cmae.servicio import ServicioCMAE
        cmae = ServicioCMAE(data_dir)

    def cmae_datos(session: AcquisitionSession, cursor: Optional[dict] = None) -> tuple[dict, dict]:
        """Muestras de la placa en la escala de la adquisición ({} si está deshabilitada)."""
        return cmae.datos_sesion(session, cursor) if cmae is not None else ({}, {})

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if cmae is not None:
            await cmae.iniciar()
        try:
            yield
        finally:
            if cmae is not None:
                await cmae.cerrar()

    app = FastAPI(title="Dashboard mmWave MR60BHA1", lifespan=lifespan)
    manager = AcquisitionManager()
    if cmae is not None:
        app.include_router(cmae.router)
        cmae.sesion_radar = lambda: manager.session

    @app.get("/api/features")
    def features():
        """Funciones opcionales activas; la interfaz oculta lo que esté apagado."""
        return {"cmae": cmae is not None}

    def status_of(session: AcquisitionSession) -> dict:
        """Estado de la adquisición, con el CSV de la placa CMAE si se está grabando."""
        st = status_json(session)
        st["cmae"] = cmae.resumen_sesion(session) if cmae is not None else None
        return st
    config_store = ConfigStore(data_dir / ".dashboard_config.json")
    session_ids = itertools.count(1)
    export_lock = threading.Lock()
    export_state: dict = {"running": False, "done": 0, "total": 0, "file": None}

    def current() -> Optional[AcquisitionSession]:
        return manager.session

    def require_session() -> AcquisitionSession:
        session = current()
        if session is None:
            raise HTTPException(404, "Todavía no hay una adquisición.")
        return session

    def session_meta(session: Optional[AcquisitionSession]) -> Optional[dict]:
        return getattr(session, "meta", None) if session is not None else None

    # --------------------------------------------------------
    # Puertos y archivos
    # --------------------------------------------------------

    @app.get("/api/ports")
    def ports():
        return {
            "ports": list_serial_ports_info(),
            "scanned_at": datetime.now().isoformat(timespec="seconds"),
        }

    @app.get("/api/files")
    def files():
        if not data_dir.exists():
            return {"files": []}
        # Los CSV de la placa CMAE (<archivo>_cmae.csv) acompañan al del radar: no se listan solos.
        found = sorted((p for p in data_dir.glob("*.csv") if not CMAE_CSV.search(p.name)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return {"files": [
            {"name": p.name, "size": p.stat().st_size,
             "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
            for p in found
        ]}

    # --------------------------------------------------------
    # Configuración persistente
    # --------------------------------------------------------

    @app.get("/api/config")
    def get_config():
        return config_store.load()

    @app.put("/api/config")
    def put_config(payload: dict = Body(...)):
        # Acepta cambios parciales, por ejemplo {"zone": {...}} desde el medidor de distancia.
        return config_store.update(payload)

    # --------------------------------------------------------
    # Adquisición
    # --------------------------------------------------------

    @app.get("/api/acquisition")
    def acquisition_state():
        session = current()
        return {
            "busy": manager.busy,
            "session": session_meta(session),
            "status": status_of(session) if session is not None else None,
        }

    @app.post("/api/acquisition")
    def start(payload: dict = Body(...)):
        raw = payload.get("config")
        name, error = resolve_filename(payload.get("filename"))
        if error:
            raise HTTPException(400, {"field": "file", "msg": error})
        output_path = data_dir / name
        if output_path.exists():
            raise HTTPException(400, {"field": "file", "msg": f"El archivo {name} ya existe. Elige otro nombre."})
        problem = validate_start(raw)
        if problem:
            field, msg = problem
            raise HTTPException(400, {"field": field, "msg": msg})
        if manager.busy:
            raise HTTPException(409, {"field": None, "msg": "Ya hay una adquisición en curso."})

        # Se guarda la configuración usada (sin el nombre de archivo) para la siguiente.
        # La zona de distancia no viene en la petición: se conserva la guardada.
        cfg = config_store.update({k: v for k, v in raw.items() if k != "zone"})
        if cfg["proto"] == "seq":
            protocol = RetentionProtocol(
                n_mediciones=int(cfg["n"]), t_normal=float(cfg["tn"]), t_hold=float(cfg["th"]),
                t_recovery=float(cfg["tr"]), t_countdown=int(cfg["cd"]), t_pausa=float(cfg["tp"]),
                esperar_usuario=bool(cfg["esperar"]),
            )
            params = {k: cfg[k] for k in ("n", "tn", "th", "tr", "cd", "tp", "esperar")}
        elif cfg["proto"] == "apnea":
            protocol = ApneaProtocol(
                t_normal=float(cfg["a_tn"]), t_countdown=int(cfg["a_cd"]), t_hold=float(cfg["a_th"]),
                t_monitor=float(cfg["a_tm"]) or None, esperar_usuario=bool(cfg["esperar"]),
            )
            # Mismas claves que la secuencia para que la interfaz planifique las fases igual.
            params = {"n": 1, "tn": cfg["a_tn"], "cd": cfg["a_cd"], "th": cfg["a_th"], "tm": cfg["a_tm"],
                      "esperar": cfg["esperar"]}
        else:
            protocol = ContinuousProtocol(duracion=float(cfg["duracion"]) or None)
            params = {"duracion": cfg["duracion"]}

        if cfg["src"] == "serial":
            port, baud = cfg["port"], int(cfg["baud"])
            factory = lambda: SerialSource(port, baud)
            label = f"el puerto {port}"
            source = {"kind": "serial", "port": port, "baud": baud}
        else:
            factory = SimulatedSource
            label = "el simulador"
            source = {"kind": "sim", "port": None, "baud": None}

        try:
            session = manager.start(factory, protocol, output_path, source_label=label)
        except RuntimeError as exc:
            raise HTTPException(409, {"field": None, "msg": str(exc)})
        session.meta = {
            "id": next(session_ids),
            "file": name,
            "path": f"datos/{name}",
            "proto": cfg["proto"],
            "params": params,
            "source": source,
            "started_at": session.started_at.isoformat(timespec="seconds"),
        }
        return session.meta

    @app.post("/api/acquisition/stop")
    def stop():
        session = require_session()
        if not session.running:
            raise HTTPException(409, "La adquisición ya terminó.")
        session.stop()
        return {"ok": True}

    @app.post("/api/acquisition/confirm")
    def confirm():
        session = require_session()
        if not session.status.esperando_usuario:
            raise HTTPException(409, "La adquisición no está esperando confirmación.")
        session.confirm_ready()
        return {"ok": True}

    @app.post("/api/acquisition/marker")
    def marker():
        session = require_session()
        added = session.add_marker() if session.running else None
        if added is None:
            raise HTTPException(409, "Las marcas solo se agregan durante las fases que se graban.")
        medicion = added["medicion"] if isinstance(added["medicion"], int) else None
        return {"label": added["label"], "t": round(added["t"], 3),
                "medicion": medicion, "fase": added["fase"]}

    @app.get("/api/acquisition/last")
    def last():
        session = require_session()
        if session.running:
            raise HTTPException(409, "La adquisición todavía está en curso.")
        records, _ = session.snapshot()
        return {
            "session": session_meta(session),
            "status": status_of(session),
            "records": [record_json(r) for r in records],
            "dist": dist_json(list(session.dist_history)),
            "cmae": cmae_datos(session)[0],
        }

    @app.get("/api/acquisition/summary")
    def summary():
        session = require_session()
        records, _ = session.snapshot()
        return {"rows": summary_rows(records_to_long(records))}

    # --------------------------------------------------------
    # Análisis de archivos guardados o subidos
    # --------------------------------------------------------

    analysis_cache: "OrderedDict[str, pd.DataFrame]" = OrderedDict()

    def analysis_payload(key: str, name: str, origin: str, data: bytes) -> dict:
        try:
            fmt, raw, long = load_csv(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(400, f"No se pudo leer {name}: {exc}")

        analysis_cache[key] = long
        analysis_cache.move_to_end(key)
        while len(analysis_cache) > ANALYSIS_CACHE_SIZE:
            analysis_cache.popitem(last=False)

        records = long_json(long)
        seq = fmt == FORMATO_SECUENCIA
        mediciones = sorted({r["m"] for r in records if r["m"] is not None})
        t_values = [r["t"] for r in records]
        apnea = seq and any(r["k"] == "PHASE" and r["f"] == "MONITOREO" for r in records)
        return {
            "key": key,
            "file": name,
            "origin": origin,
            "proto": "apnea" if apnea else "seq" if seq else "cont",
            "n_rows": int(len(raw)),
            "mediciones": mediciones if seq else [],
            "n_end": sum(1 for r in records if r["k"] == "END"),
            "t_total": max(t_values) if t_values else 0.0,
            "t0_wall": start_wall(raw, fmt),
            "records": records,
            "dist": [[r["t"], r["v"]] for r in records if r["k"] == "DIST" and r["v"] is not None],
            "summary": summary_rows(long) if seq else [],
        }

    @app.get("/api/files/{name}")
    def open_file(name: str):
        path = data_dir / name
        if Path(name).name != name or path.suffix.lower() != ".csv" or not path.is_file():
            raise HTTPException(404, f"No se encontró {name} en la carpeta de datos.")
        stat = path.stat()
        return analysis_payload(f"datos:{name}:{stat.st_mtime_ns}", name, "datos", path.read_bytes())

    @app.post("/api/analysis/upload")
    async def upload(request: Request, name: str = "archivo.csv"):
        data = await request.body()
        if not data:
            raise HTTPException(400, "El archivo está vacío.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "El archivo supera los 200 MB.")
        key = f"upload:{hashlib.sha1(data).hexdigest()[:16]}"
        return await run_in_threadpool(analysis_payload, key, Path(name).name, "upload", data)

    # --------------------------------------------------------
    # Exportar imágenes
    # --------------------------------------------------------

    def run_export(df: pd.DataFrame, dpi: int, sg_window: Optional[float], sg_order: Optional[int]) -> Response:
        if not 72 <= dpi <= 600:
            raise HTTPException(400, "El DPI debe estar entre 72 y 600.")
        savgol = None
        if sg_window is not None:
            if not 0.1 <= sg_window <= 3.0 or sg_order not in (2, 3, 4, 5):
                raise HTTPException(400, "Revisa la ventana (0,1–3 s) y el orden (2–5) del filtro.")
            savgol = SavgolConfig(ventana_s=sg_window, orden=sg_order)

        n_images = int(df["medicion"].dropna().nunique())
        if not n_images:
            raise HTTPException(400, "No hay datos para exportar.")

        with export_lock:
            if export_state["running"]:
                raise HTTPException(409, "Ya se están generando imágenes.")
            export_state.update(running=True, done=0, total=0, file=None)

        def progress(done: int, total: int, file: Optional[str]) -> None:
            export_state.update(done=done, total=total, file=file)

        try:
            data = export_zip(df, dpi=dpi, savgol=savgol, progress=progress)
        finally:
            export_state["running"] = False
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="graficos_mediciones.zip"',
                "X-Image-Count": str(n_images),
            },
        )

    @app.post("/api/export")
    def export(dpi: int = 300, sg_window: Optional[float] = None, sg_order: Optional[int] = None):
        session = require_session()
        if session.running:
            raise HTTPException(409, "Espera a que termine la adquisición.")
        records, _ = session.snapshot()
        return run_export(records_to_long(records), dpi, sg_window, sg_order)

    @app.post("/api/analysis/export")
    def analysis_export(key: str, dpi: int = 300, sg_window: Optional[float] = None, sg_order: Optional[int] = None):
        df = analysis_cache.get(key)
        if df is None:
            raise HTTPException(404, "El archivo ya no está en memoria. Vuelve a abrirlo.")
        return run_export(df, dpi, sg_window, sg_order)

    # --------------------------------------------------------
    # En vivo
    # --------------------------------------------------------

    def snapshot_message(session: AcquisitionSession) -> tuple[dict, int, int, dict]:
        with session.lock:
            records = list(session.records)
            dist = list(session.dist_history)
        cmae_data, cmae_cursor = cmae_datos(session)
        message = {
            "type": "snapshot",
            "session": session_meta(session),
            "status": status_of(session),
            "records": [record_json(r) for r in records],
            "dist": dist_json(dist),
            # Placa CMAE en la escala de tiempo de la adquisición: {señal: [[t...], [v...]]}
            "cmae": cmae_data,
        }
        return message, len(records), len(dist), cmae_cursor

    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        await ws.accept()
        sent_id: Any = -1      # id de la adquisición cuyo historial ya se envió
        n_records = n_dist = 0
        cmae_cursor: dict = {}
        last_signature = None
        last_status = 0.0
        last_export = None
        try:
            while True:
                session = current()
                meta = session_meta(session)
                now = time.monotonic()
                if session is not None and meta is None:
                    # Recién creada: todavía no tiene sus datos de cabecera.
                    await asyncio.sleep(POLL_S)
                    continue
                current_id = meta["id"] if meta else None

                if current_id != sent_id:
                    if session is None:
                        await ws.send_json({"type": "snapshot", "session": None, "status": None,
                                            "records": [], "dist": [], "cmae": {}})
                    else:
                        message, n_records, n_dist, cmae_cursor = snapshot_message(session)
                        await ws.send_json(message)
                        last_signature = status_signature(session)
                    sent_id = current_id
                    last_status = now
                elif session is not None:
                    signature = status_signature(session)
                    cmae_new, cmae_next = cmae_datos(session, cmae_cursor)
                    has_new = (len(session.records) > n_records or len(session.dist_history) > n_dist
                               or bool(cmae_new))
                    if has_new or signature != last_signature or now - last_status >= STATUS_EVERY_S:
                        message: dict = {"type": "update", "status": status_of(session)}
                        records, dist = session.data_since(n_records, n_dist)
                        if records or dist or cmae_new:
                            message["data"] = {
                                "records": [record_json(r) for r in records],
                                "dist": dist_json(dist),
                                "cmae": cmae_new,
                            }
                            n_records += len(records)
                            n_dist += len(dist)
                            cmae_cursor = cmae_next
                        await ws.send_json(message)
                        last_signature = signature
                        last_status = now

                exported = dict(export_state)
                if exported != last_export:
                    if last_export is not None or exported["running"]:
                        await ws.send_json({"type": "export", **exported})
                    last_export = exported

                await asyncio.sleep(POLL_S)
        except Exception:
            # El navegador cerró la conexión (o se recargó la página).
            return

    # --------------------------------------------------------
    # Interfaz compilada
    # --------------------------------------------------------

    if FRONTEND_DIST.is_dir():
        app.mount("/", FrontendFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_frontend():
            return (
                "<p style='font-family:sans-serif'>El backend está funcionando, pero la interfaz "
                "no está compilada. En la carpeta <code>frontend/</code> ejecuta "
                "<code>npm install</code> y <code>npm run build</code>, o usa "
                "<code>npm run dev</code> durante el desarrollo.</p>"
            )

    app.state.manager = manager
    app.state.cmae = cmae
    app.state.data_dir = data_dir
    return app


app = create_app()
