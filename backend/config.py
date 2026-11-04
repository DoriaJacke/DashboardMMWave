# ============================================================
# CONFIGURACIÓN DE LA ADQUISICIÓN
#
# Valores por defecto, rangos y validación de la configuración
# que envía la interfaz al iniciar una adquisición.
# ============================================================

from __future__ import annotations

import copy
import json
import math
import threading
from pathlib import Path
from typing import Any, Optional

# Campos del protocolo de secuencia: (mínimo, máximo). Son los mismos de la interfaz.
SEQ_FIELDS = {
    "n": (1, 200),     # mediciones
    "tn": (1, 600),    # respiración normal (s)
    "th": (1, 120),    # retención (s)
    "tr": (1, 600),    # descanso (s)
    "cd": (0, 10),     # cuenta regresiva (s)
    "tp": (0, 60),     # pausa entre mediciones (s)
}
INT_FIELDS = {"n", "cd", "baud"}
DUR_RANGE = (0, 36000)  # captura continua (s, 0 = hasta detener)

DEFAULT_CONFIG: dict[str, Any] = {
    "src": "serial",       # "serial" | "sim"
    "port": "",
    "baud": 115200,
    "proto": "seq",        # "seq" | "cont"
    "n": 20,
    "tn": 20,
    "th": 10,
    "tr": 30,
    "cd": 3,
    "tp": 3,
    "esperar": True,
    "duracion": 0,
    # Zona adecuada del medidor de distancia.
    "zone": {"min": 40, "max": 150, "scale": 300, "unit": "cm"},
}

MSG_PORT = "Selecciona un puerto serial."
MSG_RANGE = "Revisa los campos marcados."


def to_number(value: Any) -> Optional[float]:
    """Número finito o None (acepta números y textos como "20")."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact(number: float) -> int | float:
    return int(number) if float(number).is_integer() else number


def normalize(raw: Any, base: Optional[dict] = None) -> dict:
    """
    Mezcla `raw` sobre `base` (por defecto, los valores por defecto).
    Ignora claves desconocidas y valores con tipo inválido, para que
    una configuración guardada nunca rompa la interfaz.
    """
    cfg = copy.deepcopy(base or DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return cfg
    if raw.get("src") in ("serial", "sim"):
        cfg["src"] = raw["src"]
    if raw.get("proto") in ("seq", "cont"):
        cfg["proto"] = raw["proto"]
    if isinstance(raw.get("port"), str):
        cfg["port"] = raw["port"].strip()[:64]
    if isinstance(raw.get("esperar"), bool):
        cfg["esperar"] = raw["esperar"]
    for key in ("baud", *SEQ_FIELDS, "duracion"):
        number = to_number(raw.get(key))
        if number is not None and number >= 0:
            cfg[key] = int(number) if key in INT_FIELDS else _compact(number)
    zone = raw.get("zone")
    if isinstance(zone, dict):
        for key in ("min", "max", "scale"):
            number = to_number(zone.get(key))
            if number is not None and number >= 0:
                cfg["zone"][key] = _compact(number)
        if isinstance(zone.get("unit"), str):
            cfg["zone"]["unit"] = zone["unit"].strip()[:12]
    return cfg


def validate_start(raw: Any) -> Optional[tuple[str, str]]:
    """
    Revisa la configuración con la que se quiere iniciar.
    Devuelve (campo, mensaje) con el primer problema, o None si está todo bien.
    """
    if not isinstance(raw, dict):
        return "range", MSG_RANGE
    if raw.get("src") not in ("serial", "sim") or raw.get("proto") not in ("seq", "cont"):
        return "range", MSG_RANGE
    if raw["src"] == "serial":
        if not str(raw.get("port") or "").strip():
            return "port", MSG_PORT
        baud = to_number(raw.get("baud"))
        if baud is None or baud <= 0 or not baud.is_integer():
            return "range", MSG_RANGE
    if raw["proto"] == "seq":
        for key, (low, high) in SEQ_FIELDS.items():
            number = to_number(raw.get(key))
            if number is None or not low <= number <= high:
                return "range", MSG_RANGE
            if key in INT_FIELDS and not number.is_integer():
                return "range", MSG_RANGE
    else:
        number = to_number(raw.get("duracion"))
        low, high = DUR_RANGE
        if number is None or not low <= number <= high:
            return "range", MSG_RANGE
    return None


class ConfigStore:
    """
    Última configuración usada, guardada en un JSON (datos/.dashboard_config.json).
    Así la siguiente adquisición no vuelve en silencio a los valores por defecto.
    No guarda el nombre de archivo: cada adquisición genera uno nuevo con su hora.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = None
            return normalize(raw)

    def update(self, raw: Any) -> dict:
        """Mezcla los cambios sobre lo guardado (acepta cambios parciales) y guarda."""
        with self._lock:
            try:
                current = normalize(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                current = normalize(None)
            cfg = normalize(raw, base=current)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return cfg


INVALID_CHARS = set('<>:"/\\|?*')


def resolve_filename(name: Any) -> tuple[Optional[str], Optional[str]]:
    """(nombre final con .csv, None) o (None, mensaje de error)."""
    name = str(name or "").strip()
    if not name:
        return None, "Escribe un nombre para el archivo."
    if any(c in INVALID_CHARS for c in name) or name.startswith("."):
        return None, 'El nombre no puede incluir carpetas ni los caracteres < > : " / \\ | ? *'
    if not name.lower().endswith(".csv"):
        name += ".csv"
    return name, None
