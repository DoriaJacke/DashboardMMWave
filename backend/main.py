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
# - Si existe frontend/dist (npm run build) también sirve la interfaz.
#
# Hay una sola adquisición a la vez, compartida por todas las
# pestañas: si se recarga la página se vuelve a ver la que está en curso.
# ============================================================

from __future__ import annotations

import asyncio
import itertools
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .acquisition import (
    WAVE_COLS,
    AcquisitionManager,
    AcquisitionSession,
    ContinuousProtocol,
    RetentionProtocol,
    SerialSource,
    SimulatedSource,
    list_serial_ports_info,
)
from .config import ConfigStore, normalize, resolve_filename, validate_start
from .data_io import phase_summary, records_to_long
from .plots import SavgolConfig, export_zip

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "datos"
FRONTEND_DIST = ROOT / "frontend" / "dist"

STATUS_EVERY_S = 1.0   # envío periódico del estado
POLL_S = 0.1           # cada cuánto se revisa si cambió la fase


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
    app = FastAPI(title="Dashboard mmWave MR60BHA1")
    manager = AcquisitionManager()
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
        found = sorted(data_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
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
            "status": status_json(session) if session is not None else None,
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
            "status": status_json(session),
            "records": [record_json(r) for r in records],
            "dist": dist_json(list(session.dist_history)),
        }

    @app.get("/api/acquisition/summary")
    def summary():
        session = require_session()
        records, _ = session.snapshot()
        table = phase_summary(records_to_long(records))
        rows = []
        if not table.empty:
            for (medicion, fase), row in table.iterrows():
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
        return {"rows": rows}

    # --------------------------------------------------------
    # Exportar imágenes
    # --------------------------------------------------------

    @app.post("/api/export")
    def export(dpi: int = 300, sg_window: Optional[float] = None, sg_order: Optional[int] = None):
        session = require_session()
        if session.running:
            raise HTTPException(409, "Espera a que termine la adquisición.")
        if not 72 <= dpi <= 600:
            raise HTTPException(400, "El DPI debe estar entre 72 y 600.")
        savgol = None
        if sg_window is not None:
            if not 0.1 <= sg_window <= 3.0 or sg_order not in (2, 3, 4, 5):
                raise HTTPException(400, "Revisa la ventana (0,1–3 s) y el orden (2–5) del filtro.")
            savgol = SavgolConfig(ventana_s=sg_window, orden=sg_order)

        records, _ = session.snapshot()
        df = records_to_long(records)
        if df["medicion"].dropna().empty:
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
            headers={"Content-Disposition": 'attachment; filename="graficos_mediciones.zip"'},
        )

    # --------------------------------------------------------
    # En vivo
    # --------------------------------------------------------

    def snapshot_message(session: AcquisitionSession) -> tuple[dict, int, int]:
        with session.lock:
            records = list(session.records)
            dist = list(session.dist_history)
        message = {
            "type": "snapshot",
            "session": session_meta(session),
            "status": status_json(session),
            "records": [record_json(r) for r in records],
            "dist": dist_json(dist),
        }
        return message, len(records), len(dist)

    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        await ws.accept()
        sent_id: Any = -1      # id de la adquisición cuyo historial ya se envió
        n_records = n_dist = 0
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
                                            "records": [], "dist": []})
                    else:
                        message, n_records, n_dist = snapshot_message(session)
                        await ws.send_json(message)
                        last_signature = status_signature(session)
                    sent_id = current_id
                    last_status = now
                elif session is not None:
                    signature = status_signature(session)
                    if signature != last_signature or now - last_status >= STATUS_EVERY_S:
                        message: dict = {"type": "update", "status": status_json(session)}
                        records, dist = session.data_since(n_records, n_dist)
                        if records or dist:
                            message["data"] = {
                                "records": [record_json(r) for r in records],
                                "dist": dist_json(dist),
                            }
                            n_records += len(records)
                            n_dist += len(dist)
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
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
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
    app.state.data_dir = data_dir
    return app


app = create_app()
