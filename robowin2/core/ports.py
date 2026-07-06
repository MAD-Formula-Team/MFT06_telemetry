"""Descubrimiento y apertura de puertos serie, portable Windows/Linux.

Lecciones de ROBOWIN 1 aplicadas aquí:
- Detección por USB VID (determinista) en lugar de adivinar por nombre.
- Apertura SIN tocar DTR/RTS: el auto-reset del ESP32 está cableado a esas
  líneas y pyserial las activa por defecto al abrir, reiniciando la placa.
- Este módulo NUNCA cierra un puerto por silencio; eso es decisión de la UI
  (mostrar staleness), no del enlace.
"""
from __future__ import annotations

from dataclasses import dataclass

import serial
import serial.tools.list_ports

# VIDs USB de los adaptadores serie que puede llevar el receptor
PREFERRED_VIDS = {
    0x303A: "Espressif (USB nativo)",
    0x10C4: "Silicon Labs CP210x",
    0x1A86: "WCH CH340",
    0x0403: "FTDI",
}

DEFAULT_BAUDRATE = 1_000_000


@dataclass(frozen=True, slots=True)
class PortInfo:
    device: str
    description: str
    vid: int | None
    pid: int | None
    preferred: bool
    bluetooth: bool

    @property
    def label(self) -> str:
        chip = PREFERRED_VIDS.get(self.vid or -1)
        suffix = f" — {chip}" if chip else (f" — {self.description}" if self.description else "")
        return f"{self.device}{suffix}"


def classify_port(device: str, description: str, vid: int | None, pid: int | None) -> PortInfo:
    desc_lower = (description or "").lower()
    return PortInfo(
        device=device,
        description=description or "",
        vid=vid,
        pid=pid,
        preferred=vid in PREFERRED_VIDS,
        bluetooth="bluetooth" in desc_lower,
    )


def sort_candidates(ports: list[PortInfo]) -> list[PortInfo]:
    """Orden: adaptadores conocidos primero, Bluetooth al final."""

    def rank(p: PortInfo) -> tuple:
        if p.preferred:
            return (0, p.device)
        if p.bluetooth:
            return (2, p.device)
        return (1, p.device)

    return sorted(ports, key=rank)


def list_candidate_ports() -> list[PortInfo]:
    infos = [
        classify_port(p.device, p.description or "", getattr(p, "vid", None), getattr(p, "pid", None))
        for p in serial.tools.list_ports.comports()
    ]
    return sort_candidates(infos)


def open_port_no_reset(device: str, baudrate: int = DEFAULT_BAUDRATE, timeout: float = 0.1) -> serial.Serial:
    """Abre el puerto con DTR/RTS fijados a False ANTES de open().

    Sin transición en esas líneas no hay auto-reset del ESP32, ni con
    puentes CP210x/CH340 ni con USB-CDC nativo.
    """
    ser = serial.Serial()
    ser.port = device
    ser.baudrate = baudrate
    ser.timeout = timeout
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser
