# ============================================================
# ADQUISICIÓN MR60BHA1
#
# Fuentes de datos (puerto serial ESP32 o simulador), sesión de
# adquisición en segundo plano y los dos protocolos de toma de datos:
#
#   RetentionProtocol  -> basado en MEDICION20SEQRES.py
#   ContinuousProtocol -> basado en tomadatosSEPT.py
# ============================================================

from __future__ import annotations

import csv
import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import serial
from serial.tools import list_ports

WAVE_COLS = ["valor_1", "valor_2", "valor_3", "valor_4", "valor_5"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def list_serial_ports() -> list[str]:
    return [p.device for p in list_ports.comports()]


def list_serial_ports_info() -> list[dict]:
    """Puertos detectados con su descripción (por ejemplo, el chip USB-serial)."""
    ports = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        description = (p.description or "").replace(f"({p.device})", "").strip()
        if description in ("", "n/a", p.device):
            description = ""
        ports.append({"device": p.device, "description": description})
    return ports


# ============================================================
# FUENTES DE DATOS
# ============================================================

class SerialSource:
    """Lee líneas de texto del ESP32 por puerto serial."""

    def __init__(self, port: str, baudrate: int = 115200):
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=1)
        time.sleep(2)

    def readline(self) -> str:
        raw = self.ser.readline()
        if not raw:
            return ""
        return raw.decode("utf-8", errors="ignore").strip()

    def set_hold(self, hold: bool) -> None:
        pass

    def close(self) -> None:
        self.ser.close()


class SimulatedSource:
    """
    Genera líneas con el mismo formato que el ESP32
    (START, EVENT, DIST, HR, BR, BW) para probar el dashboard sin hardware.
    """

    PERIODS = {"BW": 0.2, "HR": 1.0, "BR": 1.0, "DIST": 2.0, "EVENT": 6.0}

    def __init__(self):
        self._t0 = time.monotonic()
        self._queue: list[str] = ["START"]
        self._next = {"BW": 0.0, "HR": 1.0, "BR": 1.5, "DIST": 0.5, "EVENT": 3.0}
        self._hold = False
        self._hr = 72.0
        self._br = 15.0
        self._dist = 55.0
        self._wave_phase = 0.0

    def set_hold(self, hold: bool) -> None:
        self._hold = hold

    def readline(self) -> str:
        while True:
            if self._queue:
                return self._queue.pop(0)
            now = time.monotonic() - self._t0
            due = [k for k, t in self._next.items() if t <= now]
            if not due:
                time.sleep(max(0.0, min(self._next.values()) - now))
                continue
            for kind in due:
                self._queue.append(self._make(kind))
                self._next[kind] += self.PERIODS[kind]

    def _make(self, kind: str) -> str:
        if kind == "BW":
            amp = 0.08 if self._hold else 1.0
            freq = self._br / 60.0
            dt = self.PERIODS["BW"] / 5
            values = []
            for _ in range(5):
                self._wave_phase += 2 * math.pi * freq * dt
                values.append(amp * math.sin(self._wave_phase) + random.gauss(0, 0.05))
            return "BW," + ",".join(f"{v:.3f}" for v in values)
        if kind == "HR":
            target = 66.0 if self._hold else 72.0
            self._hr += 0.3 * (target - self._hr) + random.gauss(0, 1.0)
            return f"HR,{self._hr:.0f}"
        if kind == "BR":
            target = 3.0 if self._hold else 15.0
            self._br += 0.3 * (target - self._br) + random.gauss(0, 0.5)
            self._br = max(self._br, 0.0)
            return f"BR,{self._br:.0f}"
        if kind == "DIST":
            self._dist += 0.1 * (55.0 - self._dist) + random.gauss(0, 1.0)
            return f"DIST,{self._dist:.1f}"
        return "EVENT," + random.choice(["QUIETO", "QUIETO", "QUIETO", "MOVIMIENTO"])

    def close(self) -> None:
        pass


# ============================================================
# ESTADO DE LA SESIÓN
# ============================================================

@dataclass
class Context:
    """Fase actual con la que se etiqueta cada línea recibida."""
    medicion: int | str = ""
    fase: str = ""
    condicion: str = ""
    flag_hold: int = 0
    recording: bool = False


@dataclass
class Status:
    """Estado que se muestra en la interfaz."""
    estado: str = "CONECTANDO"
    fase: str = ""
    medicion: int = 0
    total: int = 0
    fase_inicio: Optional[float] = None
    fase_fin: Optional[float] = None
    cuenta: Optional[int] = None
    esperando_usuario: bool = False
    terminado: bool = False
    detenido: bool = False
    error: Optional[str] = None


class AcquisitionSession:
    """
    Ejecuta un protocolo en un hilo, mientras otro hilo lee el sensor
    continuamente. Cada línea se etiqueta con la fase vigente, se escribe
    en el CSV (formato del protocolo) y se guarda en memoria para graficar.
    """

    def __init__(
        self,
        source_factory: Callable[[], object],
        protocol,
        output_path: str | Path,
        source_label: str = "la fuente de datos",
    ):
        self.protocol = protocol
        self.output_path = Path(output_path)
        self._source_factory = source_factory
        self.source_label = source_label
        self.source = None

        self.lock = threading.Lock()
        self.ctx = Context()
        self.status = Status(total=protocol.n_mediciones)
        self.records: list[dict] = []
        self.latest: dict = {"HR": None, "BR": None, "DIST": None, "EVENT": None}
        self.latest_t: dict = {}
        # (t, distancia) de todas las líneas DIST, también las de fases que no se graban.
        self.dist_history: list[tuple[float, float]] = []
        self.n_lines = 0
        self.n_saved = 0

        self.stop_event = threading.Event()
        self.user_ready = threading.Event()
        self.t0 = time.monotonic()
        self.started_at = datetime.now()
        # Hora del PC que corresponde a t = 0 (se fija al abrir la fuente).
        self.t0_wall = self.started_at
        # Segundos desde t0 en que terminó la adquisición.
        self.t_end: Optional[float] = None

        self._file = None
        self._writer = None
        self._thread = threading.Thread(target=self._main, daemon=True)

    # --------------------------------------------------------
    # Ciclo de vida
    # --------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.status.detenido = True
        self.stop_event.set()

    def confirm_ready(self) -> None:
        self.user_ready.set()

    @property
    def running(self) -> bool:
        return not self.status.terminado

    def _main(self) -> None:
        reader = None
        try:
            try:
                self.source = self._source_factory()
            except Exception as exc:
                raise RuntimeError(f"No se pudo abrir {self.source_label}: {exc}") from exc
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.output_path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(self.protocol.columns)
            self._file.flush()

            self.t0 = time.monotonic()
            self.t0_wall = datetime.now()
            reader = threading.Thread(target=self._reader_loop, daemon=True)
            reader.start()

            self.protocol.run(self)
            if not self.stop_event.is_set():
                self.set_status(estado="ADQUISICIÓN COMPLETADA", fase="FIN", fase_fin=None)
        except Exception as exc:
            self.status.error = str(exc)
        finally:
            self.stop_event.set()
            if reader is not None:
                reader.join(timeout=3)
            if self.source is not None:
                try:
                    self.source.close()
                except Exception:
                    pass
            if self._file is not None:
                self._file.close()
            if self.status.detenido:
                self.set_status(estado="ADQUISICIÓN DETENIDA MANUALMENTE", fase="FIN", fase_fin=None)
            self.status.esperando_usuario = False
            self.t_end = time.monotonic() - self.t0
            self.status.terminado = True

    # --------------------------------------------------------
    # Lectura del sensor
    # --------------------------------------------------------

    def _reader_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                line = self.source.readline()
            except Exception as exc:
                self.status.error = f"Error leyendo el sensor: {exc}"
                self.stop_event.set()
                break
            if line:
                self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        parts = [p.strip() for p in line.split(",")]
        tipo = parts[0]
        t = time.monotonic() - self.t0

        with self.lock:
            self.n_lines += 1
            self._update_latest(tipo, parts, t)

            ctx = self.ctx
            if not ctx.recording:
                return

            row = self.protocol.format_line(line, parts, ctx, self)
            if row is not None:
                self._write(row)

            record = parse_record(tipo, parts, t, ctx.medicion, ctx.fase)
            if record is not None:
                self.records.append(record)

    def _update_latest(self, tipo: str, parts: list[str], t: float) -> None:
        if len(parts) < 2:
            return
        if tipo == "EVENT":
            self.latest["EVENT"] = parts[1]
            self.latest_t["EVENT"] = t
        elif tipo in ("HR", "BR", "DIST"):
            value = to_float(parts[1])
            if value is not None:
                self.latest[tipo] = value
                self.latest_t[tipo] = t
                if tipo == "DIST":
                    self.dist_history.append((t, value))

    def _write(self, row: list) -> None:
        self._writer.writerow(row)
        self._file.flush()
        self.n_saved += 1

    # --------------------------------------------------------
    # Herramientas para los protocolos
    # --------------------------------------------------------

    def set_status(self, **kwargs) -> None:
        # Cada vez que se indica la fase, empieza a contar su tiempo transcurrido.
        if "fase" in kwargs and "fase_inicio" not in kwargs:
            kwargs["fase_inicio"] = time.monotonic()
        for key, value in kwargs.items():
            setattr(self.status, key, value)

    def wait(self, seconds: float) -> bool:
        """Espera; devuelve False si la adquisición fue detenida."""
        return not self.stop_event.wait(seconds)

    def wait_user(self) -> bool:
        self.user_ready.clear()
        self.status.esperando_usuario = True
        while not self.stop_event.is_set():
            if self.user_ready.wait(0.2):
                break
        self.status.esperando_usuario = False
        return not self.stop_event.is_set()

    def pause_recording(self, medicion: int | str, fase: str) -> None:
        with self.lock:
            self.ctx = Context(medicion=medicion, fase=fase, recording=False)

    def start_phase(self, medicion, fase, condicion, flag_hold, label, duration=None) -> None:
        t = time.monotonic() - self.t0
        with self.lock:
            self.ctx = Context(medicion, fase, condicion, flag_hold, recording=True)
            row = self.protocol.phase_row(self.ctx)
            if row is not None:
                self._write(row)
            self.records.append(_mark_record("PHASE", t, medicion, fase))
        if self.source is not None:
            self.source.set_hold(flag_hold == 1)
        self.set_status(
            estado=label,
            fase=fase,
            medicion=medicion if isinstance(medicion, int) else 0,
            fase_fin=(time.monotonic() + duration) if duration else None,
            cuenta=None,
        )

    def run_phase(self, medicion, fase, condicion, flag_hold, label, duration) -> bool:
        self.start_phase(medicion, fase, condicion, flag_hold, label, duration)
        return self.wait(duration)

    def end_measurement(self, medicion) -> None:
        t = time.monotonic() - self.t0
        with self.lock:
            row = self.protocol.end_row(medicion)
            if row is not None:
                self._write(row)
            self.records.append(_mark_record("END", t, medicion, "END"))
            self.ctx = Context(medicion=medicion, fase="END", recording=False)
        if self.source is not None:
            self.source.set_hold(False)

    def snapshot(self) -> tuple[list[dict], dict]:
        with self.lock:
            return list(self.records), dict(self.latest)

    def elapsed(self) -> float:
        """Segundos desde t0 (fijo al terminar la adquisición)."""
        if self.t_end is not None:
            return self.t_end
        return time.monotonic() - self.t0

    def data_since(self, n_records: int, n_dist: int) -> tuple[list[dict], list[tuple[float, float]]]:
        """Registros y distancias nuevos desde los índices indicados (para enviar en vivo)."""
        with self.lock:
            return self.records[n_records:], self.dist_history[n_dist:]


def parse_record(tipo: str, parts: list[str], t: float, medicion, fase) -> Optional[dict]:
    """Convierte una línea del sensor a un registro en formato largo para graficar."""
    record = {"t": t, "medicion": medicion, "fase": fase, "tipo": tipo, "evento": None}
    for col in WAVE_COLS:
        record[col] = None

    if tipo == "BW":
        if len(parts) < 6:
            return None
        for col, value in zip(WAVE_COLS, parts[1:6]):
            record[col] = to_float(value)
    elif tipo in ("HR", "BR", "DIST"):
        if len(parts) < 2:
            return None
        record["valor_1"] = to_float(parts[1])
    elif tipo == "EVENT":
        if len(parts) < 2:
            return None
        record["evento"] = parts[1]
    elif tipo != "START":
        return None
    return record


def _mark_record(tipo: str, t: float, medicion, fase: str) -> dict:
    record = {"t": t, "medicion": medicion, "fase": fase, "tipo": tipo, "evento": None}
    for col in WAVE_COLS:
        record[col] = None
    return record


# ============================================================
# PROTOCOLO 1: SECUENCIA CON RETENCIÓN (MEDICION20SEQRES.py)
# ============================================================

@dataclass
class RetentionProtocol:
    n_mediciones: int = 20
    t_normal: float = 20
    t_hold: float = 10
    t_recovery: float = 30
    t_countdown: int = 3
    t_pausa: float = 3
    esperar_usuario: bool = True

    nombre: str = "Secuencia con retención respiratoria"
    columns: list[str] = field(default_factory=lambda: [
        "timestamp", "medicion", "fase", "condicion", "flag_hold",
        "tipo", *WAVE_COLS,
    ])

    def _base(self, ctx: Context) -> list:
        return [now_iso(), ctx.medicion, ctx.fase, ctx.condicion, ctx.flag_hold]

    def format_line(self, line, parts, ctx, session) -> Optional[list]:
        tipo = parts[0]
        if tipo == "START":
            return self._base(ctx) + ["START", "", "", "", "", ""]
        if tipo in ("EVENT", "DIST", "HR", "BR") and len(parts) >= 2:
            return self._base(ctx) + [tipo, parts[1], "", "", "", ""]
        if tipo == "BW" and len(parts) >= 6:
            return self._base(ctx) + ["BW", *parts[1:6]]
        return None

    def phase_row(self, ctx: Context) -> list:
        return self._base(ctx) + ["PHASE", "", "", "", "", ""]

    def end_row(self, medicion) -> list:
        return [now_iso(), medicion, "END", "FIN", 0, "END", "", "", "", "", ""]

    def run(self, s: AcquisitionSession) -> None:
        for m in range(1, self.n_mediciones + 1):

            s.pause_recording(m, "ESPERA")
            s.set_status(estado="COLÓCATE EN POSICIÓN", fase="ESPERA", medicion=m, fase_fin=None)
            if self.esperar_usuario and not s.wait_user():
                return

            if not s.run_phase(m, "NORMAL", "RESPIRACION_NORMAL", 0,
                               "RESPIRACIÓN NORMAL", self.t_normal):
                return

            s.start_phase(m, "PREP", "PREPARACION", 0, "PREPÁRATE", 1 + self.t_countdown)
            if not s.wait(1):
                return
            for cuenta in range(self.t_countdown, 0, -1):
                s.set_status(cuenta=cuenta)
                if not s.wait(1):
                    return
            s.set_status(cuenta=None)

            if not s.run_phase(m, "HOLD", "RETENCION", 1,
                               "AGUANTA LA RESPIRACIÓN", self.t_hold):
                return

            if not s.run_phase(m, "RECOVERY", "RECUPERACION", 0,
                               "DESCANSO", self.t_recovery):
                return

            s.end_measurement(m)

            if m < self.n_mediciones:
                s.set_status(estado="DESCANSO ENTRE MEDICIONES", fase="PAUSA",
                             fase_fin=time.monotonic() + self.t_pausa)
                if not s.wait(self.t_pausa):
                    return


# ============================================================
# PROTOCOLO 2: CAPTURA CONTINUA (tomadatosSEPT.py)
# ============================================================

@dataclass
class ContinuousProtocol:
    duracion: Optional[float] = None

    n_mediciones: int = 0
    nombre: str = "Captura continua"
    columns: list[str] = field(default_factory=lambda: [
        "timestamp", "datetime", "HR", "BR", "distance", "movement", "raw",
    ])

    def format_line(self, line, parts, ctx, session) -> list:
        latest = session.latest
        return [
            f"{time.monotonic() - session.t0:.3f}",
            datetime.now().isoformat(),
            latest["HR"],
            latest["BR"],
            latest["DIST"],
            latest["EVENT"],
            line,
        ]

    def phase_row(self, ctx: Context) -> None:
        return None

    def end_row(self, medicion) -> None:
        return None

    def run(self, s: AcquisitionSession) -> None:
        s.start_phase(1, "CONTINUO", "CAPTURA_CONTINUA", 0, "CAPTURANDO", self.duracion)
        if self.duracion:
            s.wait(self.duracion)
        else:
            s.stop_event.wait()


# ============================================================
# GESTOR (una adquisición activa a la vez)
# ============================================================

class AcquisitionManager:
    def __init__(self):
        self.session: Optional[AcquisitionSession] = None

    @property
    def busy(self) -> bool:
        return self.session is not None and self.session.running

    def start(self, source_factory, protocol, output_path, source_label="la fuente de datos") -> AcquisitionSession:
        if self.busy:
            raise RuntimeError("Ya hay una adquisición en curso.")
        self.session = AcquisitionSession(source_factory, protocol, output_path, source_label)
        self.session.start()
        return self.session
