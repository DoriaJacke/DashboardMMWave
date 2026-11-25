"""
Protocolo de la placa CMAE.

Reúne en un solo lugar lo que en el receptor original estaba repetido en varios
archivos:

  - cómo viene una trama (TransportFrame: AA 55 ... CRC),
  - cómo se arma una trama a partir de los fragmentos que llegan por BLE,
  - cómo se lee el contenido de cada tipo de paquete.

Los nombres de las tablas y de las columnas son los mismos del receptor
original (receivers/cmae_ble_reciever.py y cmae_uart0_receiver_ECG_FILTRADO_ONLY.py),
para que los CSV que genera esta app sean idénticos a los de siempre.

Formato de una trama:
    AA 55 | versión u8 | cantidad u8 | reloj del orquestador u32 | paquetes... | CRC16
Formato de cada paquete:
    tipo u16 | secuencia u32 | tiempo de la placa (ms) u32 | largo u16 | contenido
"""
from __future__ import annotations

import binascii
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

BLE = "BLE"
UART = "UART"

# ==================================================
# Tipos de paquete (source id)
# ==================================================
SRC_I2C0_ICM42670P = 0x0101
SRC_I2C0_QMC5883P = 0x0102
SRC_I2C0_SDP810 = 0x0103
SRC_I2C0_ORIENTATION = 0x0110

SRC_I2C1_BME680 = 0x0201
SRC_I2C1_SCD40 = 0x0202
SRC_I2C1_MAX30102_RAW = 0x0203
SRC_I2C1_MAX30102_RESULT = 0x0204

SRC_GPS_MAXM10S_PVT = 0x0301
SRC_GPS_MAXM10S_POS_AVG = 0x0302
SRC_GPS_MAXM10S_ALT_REF = 0x0303

SRC_SPI_ADS1220_ECG = 0x0401
SRC_ONEWIRE_DS18B20 = 0x0501

# Por BLE las señales rápidas llegan agrupadas en bloques de varias muestras.
SRC_BLE_BLOCK_ICM42670P = 0x8101
SRC_BLE_BLOCK_ORIENTATION = 0x8110
SRC_BLE_BLOCK_MAX30102_RAW = 0x8203
SRC_BLE_BLOCK_ADS1220_ECG = 0x8401

# Igual que en el receptor original: los bloques BLE no tienen nombre propio y
# en los CSV aparecen como UNKNOWN_0x8xxx.
NOMBRES_FUENTE: Dict[int, str] = {
    SRC_I2C0_ICM42670P: "ICM42670P",
    SRC_I2C0_QMC5883P: "QMC5883P",
    SRC_I2C0_SDP810: "SDP810",
    SRC_I2C0_ORIENTATION: "ORIENTATION",
    SRC_I2C1_BME680: "BME680",
    SRC_I2C1_SCD40: "SCD40",
    SRC_I2C1_MAX30102_RAW: "MAX30102_RAW",
    SRC_I2C1_MAX30102_RESULT: "MAX30102_RESULT",
    SRC_GPS_MAXM10S_PVT: "GPS_PVT",
    SRC_GPS_MAXM10S_POS_AVG: "GPS_POS_AVG",
    SRC_GPS_MAXM10S_ALT_REF: "GPS_ALT_REF",
    SRC_SPI_ADS1220_ECG: "ADS1220_ECG",
    SRC_ONEWIRE_DS18B20: "DS18B20",
}

FUENTES_BLOQUE = (
    SRC_BLE_BLOCK_ICM42670P,
    SRC_BLE_BLOCK_ORIENTATION,
    SRC_BLE_BLOCK_MAX30102_RAW,
    SRC_BLE_BLOCK_ADS1220_ECG,
)

MAGIC = b"\xAA\x55"
VERSION_TRAMA = 1
MAX_PAQUETES_POR_TRAMA = 20
MAX_LARGO_CONTENIDO = 1000

FRAG_MAGIC = b"\xCB\x1E"
FRAG_CABECERA = 18

# ==================================================
# Formatos binarios ("<" = sin relleno, little endian)
# ==================================================
_S_PAQUETE = struct.Struct("<HIIH")
_S_BLOQUE = struct.Struct("<HHHHIIIIB")
TAM_CABECERA_BLOQUE = _S_BLOQUE.size

_S_ECG_BLOQUE = struct.Struct("<ifB")
_S_PPG_BLOQUE = struct.Struct("<IIB")
_S_IMU_BLOQUE = struct.Struct("<ffffffh")
_S_ORI_BLOQUE = struct.Struct("<fffB")

_S_ICM = struct.Struct("<hhhhhhhhffffff")
_S_QMC = struct.Struct("<hhhfffB")
_S_SDP810 = struct.Struct("<ff")
_S_ORIENTACION = struct.Struct("<fffffffffffffffB")
_S_DS18B20 = struct.Struct("<ffHBBBBII")
_S_BME680 = struct.Struct("<ffffffffIBB")
_S_SCD40 = struct.Struct("<HffB")
_S_MAX_CRUDO = struct.Struct("<IIBB")
_S_MAX_RESULTADO = struct.Struct("<IIffffffhBBBBB")
_S_ECG = struct.Struct("<iffffBBBB")
_S_GPS_PVT = struct.Struct("<ddfffffffHBBBBBBBBBB")
_S_GPS_POS_AVG = struct.Struct("<ddffHBBII")
_S_GPS_ALT_REF = struct.Struct("<ffffHBBBBIIIII")


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (polinomio 0x1021, inicio 0xFFFF), el que usa la placa."""
    return binascii.crc_hqx(data, 0xFFFF)


# ==================================================
# Tramas
# ==================================================

def _fin_de_trama(buf: Any, i: int, n: int) -> Tuple[str, int]:
    """
    Revisa la trama que empieza en buf[i] (ya se sabe que ahí hay AA 55).
    Devuelve ("ok", posición del CRC), ("falta", 0) si aún no llegó completa,
    o ("mala", 0) si el encabezado no tiene sentido.
    """
    if n - i < 8:
        return "falta", 0
    cantidad = buf[i + 3]
    if buf[i + 2] != VERSION_TRAMA or cantidad == 0 or cantidad > MAX_PAQUETES_POR_TRAMA:
        return "mala", 0
    pos = i + 8
    for _ in range(cantidad):
        if n < pos + 12:
            return "falta", 0
        largo = buf[pos + 10] | (buf[pos + 11] << 8)
        pos += 12
        if largo > MAX_LARGO_CONTENIDO:
            return "mala", 0
        if n < pos + largo:
            return "falta", 0
        pos += largo
    if n < pos + 2:
        return "falta", 0
    return "ok", pos


class LectorTramas:
    """
    Saca tramas completas de un flujo de bytes (lo que llega por USB/UART).

    Lleva la cuenta de lo que descarta, para poder decir "llegan datos pero no
    son tramas" (por ejemplo, cuando la placa solo manda texto de arranque).
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.bytes_recibidos = 0
        self.bytes_descartados = 0
        self.tramas_ok = 0
        self.crc_malos = 0

    def alimentar(self, data: bytes) -> List[bytes]:
        self.bytes_recibidos += len(data)
        buf = self._buf
        buf += data
        n = len(buf)
        i = 0
        tramas: List[bytes] = []

        while True:
            j = buf.find(MAGIC, i)
            if j < 0:
                # Se guarda el último byte por si es el AA de un AA 55 partido en dos.
                guardar = 1 if n > i and buf[n - 1] == 0xAA else 0
                self.bytes_descartados += n - i - guardar
                i = n - guardar
                break
            self.bytes_descartados += j - i
            i = j

            estado, pos = _fin_de_trama(buf, i, n)
            if estado == "falta":
                break
            if estado == "mala":
                i += 1
                self.bytes_descartados += 1
                continue

            esperado = buf[pos] | (buf[pos + 1] << 8)
            if crc16(bytes(buf[i:pos])) != esperado:
                # Se avanza un solo byte para volver a sincronizar.
                i += 1
                self.bytes_descartados += 1
                self.crc_malos += 1
                continue

            tramas.append(bytes(buf[i:pos + 2]))
            self.tramas_ok += 1
            i = pos + 2

        del buf[:i]
        return tramas


def iter_tramas_archivo(data: bytes) -> Iterator[Tuple[int, int]]:
    """Recorre un .bin grabado y entrega (inicio, fin) de cada trama válida."""
    for inicio, fin, _estado in recorrer_archivo(data):
        if fin:
            yield inicio, fin


def recorrer_archivo(data: bytes) -> Iterator[Tuple[int, int, str]]:
    """
    Recorre un .bin y entrega (inicio, fin, estado) de cada cosa que encuentra.

    estado es "ok" para una trama válida (fin > 0). Para lo que no sirve, fin = 0
    y estado dice por qué: "magic" (basura antes de un AA 55), "truncada" o "crc".
    Sigue las mismas reglas que iter_frames_from_bin() del receptor original.
    """
    n = len(data)
    i = 0
    while i + 10 <= n:
        j = data.find(MAGIC, i)
        if j < 0:
            break
        if j != i:
            yield j, 0, "magic"
            i = j
        if i + 8 > n:
            yield i, 0, "truncada"
            break

        cantidad = data[i + 3]
        if data[i + 2] != VERSION_TRAMA or cantidad == 0 or cantidad > MAX_PAQUETES_POR_TRAMA:
            i += 1
            continue

        pos = i + 8
        ok = True
        for _ in range(cantidad):
            if pos + 12 > n:
                ok = False
                break
            largo = data[pos + 10] | (data[pos + 11] << 8)
            pos += 12
            if largo > MAX_LARGO_CONTENIDO or pos + largo + 2 > n:
                ok = False
                break
            pos += largo

        if not ok or pos + 2 > n:
            yield i, 0, "truncada"
            i += 1
            continue

        esperado = data[pos] | (data[pos + 1] << 8)
        if crc16(data[i:pos]) != esperado:
            yield i, 0, "crc"
            i += 1
            continue

        yield i, pos + 2, "ok"
        i = pos + 2


def iter_paquetes(trama: bytes) -> List[Tuple[int, int, int, bytes]]:
    """Devuelve [(tipo, secuencia, tiempo_ms, contenido), ...] de una trama."""
    paquetes: List[Tuple[int, int, int, bytes]] = []
    if len(trama) < 10 or trama[:2] != MAGIC:
        return paquetes
    cantidad = trama[3]
    if trama[2] != VERSION_TRAMA or cantidad == 0 or cantidad > MAX_PAQUETES_POR_TRAMA:
        return paquetes

    pos = 8
    for _ in range(cantidad):
        if pos + 12 > len(trama):
            return []
        tipo, seq, t_ms, largo = _S_PAQUETE.unpack_from(trama, pos)
        pos += 12
        if largo > MAX_LARGO_CONTENIDO or pos + largo + 2 > len(trama):
            return []
        paquetes.append((tipo, seq, t_ms, trama[pos:pos + largo]))
        pos += largo
    return paquetes


def reloj_orquestador_ms(trama: bytes) -> int:
    """Reloj de la placa al armar la trama. Sirve para reproducir un .bin a su ritmo real."""
    return struct.unpack_from("<I", trama, 4)[0]


# ==================================================
# Fragmentos BLE (CMAE-FRAG)
# ==================================================

@dataclass
class _TramaEnArmado:
    largo: int
    crc: int
    cantidad: int
    creada_s: float = field(default_factory=time.time)
    partes: List[Optional[bytes]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.partes = [None] * self.cantidad


class ReensambladorBLE:
    """Arma tramas AA 55 a partir de los fragmentos que la placa envía por BLE."""

    def __init__(self) -> None:
        self._en_armado: Dict[int, _TramaEnArmado] = {}
        self.fragmentos = 0
        self.errores = 0
        self.saltos = 0  # tramas que faltaron según su número de secuencia
        self._ultima_seq: Optional[int] = None

    def limpiar_viejas(self, max_edad_s: float = 3.0) -> None:
        ahora = time.time()
        viejas = [seq for seq, t in self._en_armado.items() if ahora - t.creada_s > max_edad_s]
        for seq in viejas:
            del self._en_armado[seq]
            self.errores += 1

    def alimentar(self, data: bytes) -> Optional[bytes]:
        """Devuelve la trama completa cuando llega su último fragmento; si no, None."""
        self.fragmentos += 1
        try:
            if len(data) < FRAG_CABECERA or data[:2] != FRAG_MAGIC:
                raise ValueError("fragmento sin marca CMAE")
            if data[2] != 1:
                raise ValueError(f"versión de fragmento no soportada: {data[2]}")

            seq, largo, crc, indice, cantidad, largo_frag = struct.unpack_from("<IHHHHH", data, 4)
            contenido = data[FRAG_CABECERA:]

            if indice == 0:
                if self._ultima_seq is not None and seq != ((self._ultima_seq + 1) & 0xFFFFFFFF):
                    self.saltos += 1
                self._ultima_seq = seq

            if len(contenido) != largo_frag:
                raise ValueError("el largo del fragmento no coincide")

            trama = self._en_armado.get(seq)
            if trama is None:
                trama = _TramaEnArmado(largo=largo, crc=crc, cantidad=cantidad)
                self._en_armado[seq] = trama
            if indice >= trama.cantidad:
                raise ValueError("índice de fragmento fuera de rango")
            trama.partes[indice] = contenido

            if any(p is None for p in trama.partes):
                return None

            del self._en_armado[seq]
            completa = b"".join(p or b"" for p in trama.partes)
            if len(completa) != trama.largo:
                raise ValueError("largo reconstruido inválido")
            if crc16(completa) != trama.crc:
                raise ValueError("CRC inválido")
            if completa[:2] != MAGIC:
                raise ValueError("la trama reconstruida no empieza con AA 55")
            return completa
        except Exception:
            self.errores += 1
            return None


# ==================================================
# Bloques BLE
# ==================================================

def leer_cabecera_bloque(contenido: bytes) -> Dict[str, int]:
    if len(contenido) < TAM_CABECERA_BLOQUE:
        raise ValueError("payload de bloque demasiado corto")
    claves = (
        "original_source_id", "sample_count", "sample_stride_bytes", "nominal_rate_hz",
        "t0_ms", "t_last_ms", "first_sequence", "last_sequence", "flags",
    )
    return dict(zip(claves, _S_BLOQUE.unpack_from(contenido, 0)))


def tiempo_muestra_ms(cab: Dict[str, int], idx: int) -> float:
    """Reparte las muestras del bloque entre el tiempo de la primera y el de la última."""
    cantidad = max(int(cab["sample_count"]), 1)
    t0 = float(cab["t0_ms"])
    t1 = float(cab["t_last_ms"])
    if cantidad <= 1 or t1 <= t0:
        ritmo = float(cab.get("nominal_rate_hz", 0) or 0)
        if ritmo > 0:
            return t0 + 1000.0 * idx / ritmo
        return t0
    return t0 + (t1 - t0) * idx / (cantidad - 1)


# ==================================================
# Lectura de cada paquete -> filas (las mismas columnas que los CSV originales)
# ==================================================

Fila = Dict[str, Any]


def fila_base(indice_trama: int, tipo: int, seq: int, t_ms: float) -> Fila:
    return {
        "frame_index": indice_trama,
        "t_ms": t_ms,
        "sequence": seq,
        "source_id": f"0x{tipo:04X}",
        "source_name": NOMBRES_FUENTE.get(tipo, f"UNKNOWN_0x{tipo:04X}"),
    }


def _bloque_ecg(indice_trama: int, tipo: int, seq: int, contenido: bytes) -> List[Fila]:
    cab = leer_cabecera_bloque(contenido)
    paso = int(cab["sample_stride_bytes"])
    filas: List[Fila] = []
    off = TAM_CABECERA_BLOQUE
    for idx in range(int(cab["sample_count"])):
        if off + _S_ECG_BLOQUE.size > len(contenido):
            break
        raw24, filtrado_uv, flags = _S_ECG_BLOQUE.unpack_from(contenido, off)
        off += paso
        fila = fila_base(indice_trama, tipo, seq, tiempo_muestra_ms(cab, idx))
        fila.update({
            "block_seq": seq,
            "sample_idx": idx,
            "first_sequence": cab["first_sequence"],
            "last_sequence": cab["last_sequence"],
            "raw24": raw24,
            "filtered_input_uV": filtrado_uv,
            "drdy_ok": bool(flags & 0x01),
            "electrodes_ok": bool(flags & 0x02),
            "lod_raw": bool(flags & 0x04),
            "lod_filtered": bool(flags & 0x08),
        })
        filas.append(fila)
    return filas


def _bloque_ppg(indice_trama: int, tipo: int, seq: int, contenido: bytes) -> List[Fila]:
    cab = leer_cabecera_bloque(contenido)
    paso = int(cab["sample_stride_bytes"])
    filas: List[Fila] = []
    off = TAM_CABECERA_BLOQUE
    for idx in range(int(cab["sample_count"])):
        if off + _S_PPG_BLOQUE.size > len(contenido):
            break
        red, ir, flags = _S_PPG_BLOQUE.unpack_from(contenido, off)
        off += paso
        fila = fila_base(indice_trama, tipo, seq, tiempo_muestra_ms(cab, idx))
        fila.update({
            "block_seq": seq,
            "sample_idx": idx,
            "red": red,
            "ir": ir,
            "finger_detected": bool(flags & 0x01),
            "sample_valid": bool(flags & 0x02),
        })
        filas.append(fila)
    return filas


def _bloque_imu(indice_trama: int, tipo: int, seq: int, contenido: bytes) -> List[Fila]:
    cab = leer_cabecera_bloque(contenido)
    paso = int(cab["sample_stride_bytes"])
    filas: List[Fila] = []
    off = TAM_CABECERA_BLOQUE
    for idx in range(int(cab["sample_count"])):
        if off + _S_IMU_BLOQUE.size > len(contenido):
            break
        ax, ay, az, gx, gy, gz, temp_x100 = _S_IMU_BLOQUE.unpack_from(contenido, off)
        off += paso
        fila = fila_base(indice_trama, tipo, seq, tiempo_muestra_ms(cab, idx))
        fila.update({
            "block_seq": seq,
            "sample_idx": idx,
            "ax_g": ax,
            "ay_g": ay,
            "az_g": az,
            "gx_dps": gx,
            "gy_dps": gy,
            "gz_dps": gz,
            "icm42670p_temperature_c": temp_x100 / 100.0,
        })
        filas.append(fila)
    return filas


def _bloque_orientacion(indice_trama: int, tipo: int, seq: int, contenido: bytes) -> List[Fila]:
    cab = leer_cabecera_bloque(contenido)
    paso = int(cab["sample_stride_bytes"])
    filas: List[Fila] = []
    off = TAM_CABECERA_BLOQUE
    for idx in range(int(cab["sample_count"])):
        if off + _S_ORI_BLOQUE.size > len(contenido):
            break
        pitch, roll, yaw, mag_valid = _S_ORI_BLOQUE.unpack_from(contenido, off)
        off += paso
        fila = fila_base(indice_trama, tipo, seq, tiempo_muestra_ms(cab, idx))
        fila.update({
            "block_seq": seq,
            "sample_idx": idx,
            "pitch_x_deg": pitch,
            "roll_y_deg": roll,
            "yaw_z_deg": yaw,
            "mag_valid": bool(mag_valid),
        })
        filas.append(fila)
    return filas


_BLOQUES = {
    SRC_BLE_BLOCK_ADS1220_ECG: ("ecg_block", _bloque_ecg),
    SRC_BLE_BLOCK_MAX30102_RAW: ("ppg_block", _bloque_ppg),
    SRC_BLE_BLOCK_ICM42670P: ("imu_block", _bloque_imu),
    SRC_BLE_BLOCK_ORIENTATION: ("orientation_block", _bloque_orientacion),
}


def _paquete_simple(tipo: int, contenido: bytes, protocolo: str, fila: Fila) -> Optional[str]:
    """Completa la fila con el contenido del paquete y devuelve el nombre de su tabla."""
    n = len(contenido)

    if tipo == SRC_ONEWIRE_DS18B20 and n >= _S_DS18B20.size:
        avg_c, last_c, muestras, conectado, valido, crc_ok, bits, descon, recon = _S_DS18B20.unpack_from(contenido, 0)
        fila.update({
            "temperature_c_avg": avg_c,
            "temperature_c_last": last_c,
            "samples_used": muestras,
            "connected": bool(conectado),
            "valid": bool(valido),
            "crc_ok": bool(crc_ok),
            "resolution_bits": bits,
            "disconnect_count": descon,
            "reconnect_count": recon,
        })
        return "ds18b20"

    if tipo == SRC_I2C1_BME680 and n >= _S_BME680.size:
        claves = (
            "bme680_temperature_c", "humidity_pct", "pressure_hpa", "gas_kohms",
            "altitude_m", "sea_level_hpa", "gps_ref_altitude_m", "gps_ref_age_s",
            "gps_ref_commit_id", "gas_valid", "altitude_source",
        )
        fila.update(dict(zip(claves, _S_BME680.unpack_from(contenido, 0))))
        fila["gas_valid"] = bool(fila["gas_valid"])
        return "bme680"

    if tipo == SRC_I2C1_SCD40 and n >= _S_SCD40.size:
        co2, temp, hum, listo = _S_SCD40.unpack_from(contenido, 0)
        fila.update({
            "co2_ppm": co2,
            "scd40_temperature_c": temp,
            "humidity_pct": hum,
            "data_ready": bool(listo),
        })
        return "scd40"

    if tipo == SRC_I2C0_SDP810 and n >= _S_SDP810.size:
        dp, temp = _S_SDP810.unpack_from(contenido, 0)
        fila.update({
            "differential_pressure_pa": dp,
            "sdp810_temperature_c": temp,
        })
        return "sdp810"

    if tipo == SRC_I2C0_QMC5883P and n >= _S_QMC.size:
        rx, ry, rz, gx, gy, gz, overflow = _S_QMC.unpack_from(contenido, 0)
        fila.update({
            "raw_x": rx,
            "raw_y": ry,
            "raw_z": rz,
            "mx_gauss": gx,
            "my_gauss": gy,
            "mz_gauss": gz,
            "overflow": bool(overflow),
        })
        return "qmc5883p"

    if tipo == SRC_I2C1_MAX30102_RESULT and n >= _S_MAX_RESULTADO.size:
        claves = (
            "raw_red", "raw_ir", "filtered_red", "filtered_ir", "current_diff", "r_ratio",
            "spo2", "bpm_float", "bpm", "finger_detected", "bpm_valid", "spo2_valid",
            "beat_detected", "algorithm_reset",
        )
        fila.update(dict(zip(claves, _S_MAX_RESULTADO.unpack_from(contenido, 0))))
        for k in ("finger_detected", "bpm_valid", "spo2_valid", "beat_detected", "algorithm_reset"):
            fila[k] = bool(fila[k])
        return "max30102_result"

    if tipo == SRC_I2C0_ICM42670P and n >= _S_ICM.size:
        v = _S_ICM.unpack_from(contenido, 0)
        fila.update({
            "accel_raw_x": v[0], "accel_raw_y": v[1], "accel_raw_z": v[2],
            "gyro_raw_x": v[3], "gyro_raw_y": v[4], "gyro_raw_z": v[5],
            "temp_raw": v[6],
            "icm42670p_temperature_c": v[7] / 100.0,
            "ax_g": v[8], "ay_g": v[9], "az_g": v[10],
            "gx_dps": v[11], "gy_dps": v[12], "gz_dps": v[13],
        })
        return "icm42670p"

    if tipo == SRC_I2C1_MAX30102_RAW and n >= _S_MAX_CRUDO.size:
        red, ir, dedo, valido = _S_MAX_CRUDO.unpack_from(contenido, 0)
        fila.update({
            "red": red,
            "ir": ir,
            "finger_detected": bool(dedo),
            "sample_valid": bool(valido),
        })
        return "max30102_raw"

    if tipo == SRC_SPI_ADS1220_ECG and n >= _S_ECG.size:
        raw24, out_ref, input_uv, lp40_mv, lp40_input_uv, drdy, lod_raw, lod_filt, elec_ok = _S_ECG.unpack_from(contenido, 0)
        fila.update({
            "raw24": raw24,
            "out_minus_ref_mV": out_ref,
            "ecg_input_est_uV": input_uv,
            "ecg_lp40_mV": lp40_mv,
            "ecg_lp40_input_est_uV": lp40_input_uv,
            "drdy_ok": bool(drdy),
            "lod_raw": bool(lod_raw),
            "lod_filtered": bool(lod_filt),
            "electrodes_ok": bool(elec_ok),
        })
        # El receptor BLE y el UART guardaban esta tabla con nombres distintos.
        return "ecg_passthrough" if protocolo == BLE else "ads1220_ecg"

    if tipo == SRC_GPS_MAXM10S_POS_AVG and n >= _S_GPS_POS_AVG.size:
        lat, lon, hacc, pdop, muestras, fill, en_psram, aceptadas, rechazadas = _S_GPS_POS_AVG.unpack_from(contenido, 0)
        fila.update({
            "lat_avg_deg": lat,
            "lon_avg_deg": lon,
            "avg_hacc_m": hacc,
            "avg_pdop": pdop,
            "samples": muestras,
            "fill_pct": fill,
            "buffer_in_psram": bool(en_psram),
            "total_accepted": aceptadas,
            "total_rejected": rechazadas,
        })
        return "gps_pos_avg"

    if tipo == SRC_GPS_MAXM10S_ALT_REF and n >= _S_GPS_ALT_REF.size:
        # El formato trae 14 valores; como en el original, la última clave queda sin usar.
        claves = (
            "altitude_msl_m", "avg_hacc_m", "avg_vacc_m", "avg_pdop", "samples",
            "ready", "fill_pct", "commit_progress_pct", "buffer_in_psram", "commit_id",
            "commit_age_ms", "total_accepted", "total_rejected", "rejected_by_quality",
            "rejected_by_interval",
        )
        fila.update(dict(zip(claves, _S_GPS_ALT_REF.unpack_from(contenido, 0))))
        fila["ready"] = bool(fila["ready"])
        fila["buffer_in_psram"] = bool(fila["buffer_in_psram"])
        return "gps_alt_ref"

    if tipo == SRC_GPS_MAXM10S_PVT and n >= _S_GPS_PVT.size:
        claves = (
            "lat_deg", "lon_deg", "height_ellipsoid_m", "height_msl_m", "hacc_m", "vacc_m",
            "ground_speed_kmh", "speed_acc_kmh", "pdop", "year", "month", "day", "hour",
            "minute", "second", "fix_type", "flags", "num_sv", "gnss_fix_ok", "quality_ok",
        )
        fila.update(dict(zip(claves, _S_GPS_PVT.unpack_from(contenido, 0))))
        fila["gnss_fix_ok"] = bool(fila["gnss_fix_ok"])
        fila["quality_ok"] = bool(fila["quality_ok"])
        return "gps_pvt"

    # La orientación completa (un paquete por muestra) solo viaja por UART.
    if tipo == SRC_I2C0_ORIENTATION and protocolo == UART and n >= _S_ORIENTACION.size:
        claves = (
            "pitch_x_deg", "roll_y_deg", "yaw_z_deg",
            "accel_pitch_x_deg", "accel_yaw_z_deg", "mag_roll_y_deg",
            "ax_g", "ay_g", "az_g",
            "gx_dps", "gy_dps", "gz_dps",
            "mx_gauss", "my_gauss", "mz_gauss",
            "mag_valid",
        )
        fila.update(dict(zip(claves, _S_ORIENTACION.unpack_from(contenido, 0))))
        fila["mag_valid"] = bool(fila["mag_valid"])
        return "orientation"

    return None


def leer_paquete(indice_trama: int, tipo: int, seq: int, t_ms: int, contenido: bytes,
                 protocolo: str) -> Tuple[str, List[Fila]]:
    """
    Convierte un paquete en filas. Devuelve (tabla, filas).

    Lo que no se reconoce o viene dañado queda en la tabla "raw_passthrough",
    igual que en el receptor original.
    """
    bloque = _BLOQUES.get(tipo) if protocolo == BLE else None
    if bloque is not None:
        tabla, leer = bloque
        try:
            return tabla, leer(indice_trama, tipo, seq, contenido)
        except Exception as exc:
            fila = fila_base(indice_trama, tipo, seq, float(t_ms))
            fila.update({"payload_len": len(contenido), "decode_error": f"{type(exc).__name__}: {exc}"})
            return "raw_passthrough", [fila]

    fila = fila_base(indice_trama, tipo, seq, float(t_ms))
    try:
        tabla = _paquete_simple(tipo, contenido, protocolo, fila)
    except Exception as exc:
        fila = fila_base(indice_trama, tipo, seq, float(t_ms))
        fila["decode_error"] = f"{type(exc).__name__}: {exc}"
        return "raw_passthrough", [fila]
    if tabla is not None:
        return tabla, [fila]

    fila["payload_len"] = len(contenido)
    fila["payload_hex_prefix"] = contenido[:24].hex()
    return "raw_passthrough", [fila]


def adivinar_protocolo(data: bytes, limite_tramas: int = 400) -> str:
    """Un .bin es BLE si trae bloques (tipos 0x8xxx). Si no, se toma como UART."""
    vistas = 0
    for inicio, fin in iter_tramas_archivo(data):
        for tipo, _seq, _t, _c in iter_paquetes(data[inicio:fin]):
            if tipo in FUENTES_BLOQUE:
                return BLE
        vistas += 1
        if vistas >= limite_tramas:
            break
    return UART
