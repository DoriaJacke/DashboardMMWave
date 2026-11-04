# ============================================================
# PROTOCOLO BLE DE LA PLACA BIOMÉDICA CMAE (PBM)
#
# Copia mínima del receptor original de la placa
# (CMAE_RECEPTOR_PORTABLE/receivers/cmae_ble_reciever.py):
#
#   1. Por BLE llegan fragmentos CMAE-FRAG; se rearman en una
#      trama AA 55 y se verifica su CRC16.
#   2. De cada trama se decodifican solo dos fuentes:
#        0x0204 resultado del MAX30102 -> BPM, SpO2 y su validez
#        0x8203 bloque crudo MAX30102  -> onda PPG (infrarroja)
# ============================================================

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

SRC_I2C1_MAX30102_RESULT = 0x0204
SRC_BLE_BLOCK_MAX30102_RAW = 0x8203

RESULT_FMT = "<IIffffffhBBBBB"
RESULT_SIZE = struct.calcsize(RESULT_FMT)
PPG_SAMPLE_FMT = "<IIB"
PPG_SAMPLE_SIZE = struct.calcsize(PPG_SAMPLE_FMT)

BLOCK_HEADER_FMT = "<HHHHIIIIB"
BLOCK_HEADER_SIZE = struct.calcsize(BLOCK_HEADER_FMT)

FRAG_MAGIC = b"\xCB\x1E"
FRAG_HEADER_LEN = 18


@dataclass
class Lectura:
    """Un resultado del MAX30102 (llega unas 7 veces por segundo)."""
    t_ms: float          # tiempo de la placa, ms desde que se encendió
    bpm: float           # NaN si la placa no tiene lectura
    spo2: float          # NaN si la placa no tiene lectura
    dedo: bool           # la placa detecta un dedo en el sensor
    bpm_valido: bool
    spo2_valido: bool

    @property
    def bpm_ok(self) -> bool:
        return self.dedo and self.bpm_valido and not math.isnan(self.bpm)

    @property
    def spo2_ok(self) -> bool:
        return self.dedo and self.spo2_valido and not math.isnan(self.spo2)


# ============================================================
# CRC Y REARMADO DE FRAGMENTOS BLE
# ============================================================

def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass
class ReassemblyBuffer:
    frame_len: int
    frame_crc: int
    frag_count: int
    created_s: float = field(default_factory=time.time)
    fragments: list[Optional[bytes]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fragments = [None] * self.frag_count

    def add(self, index: int, payload: bytes) -> bool:
        if index < 0 or index >= self.frag_count:
            return False
        self.fragments[index] = payload
        return True

    @property
    def complete(self) -> bool:
        return all(part is not None for part in self.fragments)

    def build(self) -> bytes:
        data = b"".join(part or b"" for part in self.fragments)
        if len(data) != self.frame_len:
            raise ValueError(f"largo reconstruido inválido: {len(data)} != {self.frame_len}")
        crc = crc16_ccitt_false(data)
        if crc != self.frame_crc:
            raise ValueError(f"CRC inválido: 0x{crc:04X} != 0x{self.frame_crc:04X}")
        if not data.startswith(b"\xAA\x55"):
            raise ValueError("la trama reconstruida no empieza con AA 55")
        return data


class FragmentReassembler:
    """Reconstruye tramas AA 55 desde los fragmentos CMAE-FRAG recibidos por BLE."""

    def __init__(self) -> None:
        self.buffers: dict[int, ReassemblyBuffer] = {}
        self.errors = 0

    def cleanup_old(self, max_age_s: float = 3.0) -> None:
        now = time.time()
        old = [seq for seq, buf in self.buffers.items() if now - buf.created_s > max_age_s]
        for seq in old:
            del self.buffers[seq]
            self.errors += 1

    def feed(self, data: bytes) -> Optional[bytes]:
        """Devuelve la trama completa cuando llega su último fragmento; si no, None."""
        try:
            if len(data) < FRAG_HEADER_LEN or data[:2] != FRAG_MAGIC:
                raise ValueError("fragmento sin magic CMAE")
            if data[2] != 1:
                raise ValueError(f"versión CMAE-FRAG no soportada: {data[2]}")

            frame_seq, frame_len, frame_crc, frag_index, frag_count, frag_len = struct.unpack_from(
                "<IHHHHH", data, 4
            )
            frag_payload = data[FRAG_HEADER_LEN:]
            if len(frag_payload) != frag_len:
                raise ValueError("el largo del fragmento no coincide")

            buf = self.buffers.get(frame_seq)
            if buf is None:
                buf = ReassemblyBuffer(frame_len=frame_len, frame_crc=frame_crc, frag_count=frag_count)
                self.buffers[frame_seq] = buf
            if not buf.add(frag_index, frag_payload):
                raise ValueError("frag_index fuera de rango")
            if not buf.complete:
                return None

            del self.buffers[frame_seq]
            return buf.build()
        except Exception:
            self.errors += 1
            return None


# ============================================================
# TRAMA AA 55 Y DECODIFICACIÓN
# ============================================================

def iter_transport_packets(frame: bytes) -> list[tuple[int, int, int, bytes]]:
    """Devuelve [(source_id, sequence, timestamp_ms, payload), ...] de una trama AA 55."""
    packets: list[tuple[int, int, int, bytes]] = []
    if len(frame) < 10 or not frame.startswith(b"\xAA\x55"):
        return packets
    version, count = frame[2], frame[3]
    if version != 1 or count == 0 or count > 20:
        return packets

    pos = 8
    for _ in range(count):
        if pos + 12 > len(frame):
            return []
        source_id, seq, ts_ms, payload_len = struct.unpack_from("<HIIH", frame, pos)
        pos += 12
        if payload_len > 1000 or pos + payload_len + 2 > len(frame):
            return []
        packets.append((source_id, seq, ts_ms, frame[pos:pos + payload_len]))
        pos += payload_len
    return packets


def parse_block_header(payload: bytes) -> dict[str, int]:
    if len(payload) < BLOCK_HEADER_SIZE:
        raise ValueError("payload de bloque demasiado corto")
    keys = [
        "original_source_id", "sample_count", "sample_stride_bytes", "nominal_rate_hz",
        "t0_ms", "t_last_ms", "first_sequence", "last_sequence", "flags",
    ]
    return dict(zip(keys, struct.unpack_from(BLOCK_HEADER_FMT, payload, 0)))


def sample_time_ms(header: dict[str, int], idx: int) -> float:
    """Tiempo de la muestra idx dentro de un bloque, repartido entre t0 y t_last."""
    count = max(int(header["sample_count"]), 1)
    t0 = float(header["t0_ms"])
    t1 = float(header["t_last_ms"])
    if count <= 1 or t1 <= t0:
        rate = float(header.get("nominal_rate_hz", 0) or 0)
        return t0 + 1000.0 * idx / rate if rate > 0 else t0
    return t0 + (t1 - t0) * idx / (count - 1)


def _decode_result(ts_ms: float, payload: bytes) -> Optional[Lectura]:
    if len(payload) < RESULT_SIZE:
        return None
    vals = struct.unpack_from(RESULT_FMT, payload, 0)
    # 6 spo2, 7 bpm_float, 9 finger_detected, 10 bpm_valid, 11 spo2_valid
    return Lectura(
        t_ms=ts_ms,
        bpm=float(vals[7]),
        spo2=float(vals[6]),
        dedo=bool(vals[9]),
        bpm_valido=bool(vals[10]),
        spo2_valido=bool(vals[11]),
    )


def _decode_ppg_block(payload: bytes) -> list[tuple[float, float]]:
    h = parse_block_header(payload)
    samples: list[tuple[float, float]] = []
    off = BLOCK_HEADER_SIZE
    for idx in range(int(h["sample_count"])):
        if off + PPG_SAMPLE_SIZE > len(payload):
            break
        _red, ir, _flags = struct.unpack_from(PPG_SAMPLE_FMT, payload, off)
        off += int(h["sample_stride_bytes"])
        samples.append((sample_time_ms(h, idx), float(ir)))
    return samples


def decode_frame(frame: bytes) -> tuple[list[Lectura], list[tuple[float, float]]]:
    """Devuelve (lecturas de BPM/SpO2, muestras PPG como (t_ms, ir)) de una trama."""
    lecturas: list[Lectura] = []
    ppg: list[tuple[float, float]] = []
    for source_id, _seq, ts_ms, payload in iter_transport_packets(frame):
        try:
            if source_id == SRC_I2C1_MAX30102_RESULT:
                lectura = _decode_result(float(ts_ms), payload)
                if lectura is not None:
                    lecturas.append(lectura)
            elif source_id == SRC_BLE_BLOCK_MAX30102_RAW:
                ppg.extend(_decode_ppg_block(payload))
        except Exception:
            continue
    return lecturas, ppg
