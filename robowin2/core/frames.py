"""Frame CAN crudo y parseo del protocolo serie del receptor.

Protocolo (sin cambios respecto a ROBOWIN 1, compatible con las placas ya
flasheadas): una línea de texto por frame, ID en hex seguido de los bytes de
datos en hex separados por comas. Ejemplo: ``3A1,00,1F,5A,00,64,00``.
"""
from __future__ import annotations

from dataclasses import dataclass

# ID del laptimer (fuera del DBC): payload = timestamp uint64 little-endian en µs
LAPTIMER_CAN_ID = 0x777

# Pseudo-ID reservado (fuera del DBC, no es una trama CAN real): RSSI/SNR del
# último paquete LoRa recibido por la base. Ver LORA_METRICS_ID en
# include/common_config.hpp — mismo pseudo-ID en ambos lados.
# Payload: int16 LE rssi_dBm×10, int16 LE snr_dB×10.
LORA_METRICS_CAN_ID = 0x7F1

# Máximo ID CAN extendido (29 bits)
_MAX_CAN_ID = 0x1FFF_FFFF


@dataclass(frozen=True, slots=True)
class RawFrame:
    """Frame CAN crudo con timestamp de recepción.

    t_us es un timestamp monotónico en microsegundos asignado por la fuente
    (reloj local para serie, timestamp original para replay).
    """

    t_us: int
    can_id: int
    data: bytes

    @property
    def t_s(self) -> float:
        return self.t_us / 1_000_000.0


def parse_line(line: str, t_us: int) -> RawFrame | None:
    """Parsea una línea del protocolo serie. Devuelve None si es basura.

    Tolerante por diseño: el enlace radio/serie puede corromper líneas y
    eso no debe romper el pipeline ni perder los frames siguientes.
    """
    parts = line.strip().split(",")
    if not parts or not parts[0]:
        return None

    try:
        can_id = int(parts[0], 16)
        data = bytes(int(byte_text, 16) for byte_text in parts[1:] if byte_text)
    except ValueError:
        return None

    # Nota: bytes fuera de rango ("1FF") ya hicieron fallar bytes() arriba.
    if not (0 <= can_id <= _MAX_CAN_ID) or len(data) > 8:
        return None

    return RawFrame(t_us=t_us, can_id=can_id, data=data)


def format_line(frame: RawFrame) -> str:
    """Formatea un frame al protocolo serie (simétrico de parse_line)."""
    head = f"{frame.can_id:X}"
    if not frame.data:
        return head
    return head + "," + ",".join(f"{b:02X}" for b in frame.data)


def laptimer_timestamp_s(frame: RawFrame) -> float | None:
    """Extrae el timestamp del laptimer (segundos) de un frame 0x777."""
    if frame.can_id != LAPTIMER_CAN_ID or len(frame.data) < 8:
        return None
    return int.from_bytes(frame.data[:8], byteorder="little", signed=False) / 1_000_000.0


def lora_metrics(frame: RawFrame) -> tuple[float, float] | None:
    """Extrae (rssi_dBm, snr_dB) de un frame del pseudo-ID de métricas LoRa."""
    if frame.can_id != LORA_METRICS_CAN_ID or len(frame.data) < 4:
        return None
    rssi_x10 = int.from_bytes(frame.data[0:2], byteorder="little", signed=True)
    snr_x10 = int.from_bytes(frame.data[2:4], byteorder="little", signed=True)
    return rssi_x10 / 10.0, snr_x10 / 10.0
