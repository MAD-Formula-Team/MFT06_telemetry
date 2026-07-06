"""Lógica de vueltas y sesiones, portada de ROBOWIN 1 (sin Qt).

Incluye las dos protecciones aprendidas en pista:
- vuelta mínima plausible (el sensor IR emite dos pulsos por pasada), y
- rechazo de timestamps no crecientes.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

# Cualquier "vuelta" más corta es el segundo pulso IR de la misma pasada
MIN_LAP_S = 3.0

MODE_SKIDPAD = "SKIDPAD"
MODE_AUTOCROSS = "AUTOCROSS"
MODE_ENDURANCE = "ENDURANCE"


@dataclass(frozen=True, slots=True)
class Lap:
    number: int
    lap_time_s: float
    trigger_t_s: float  # timestamp del dispositivo laptimer (fin de vuelta)


def fs_skidpad_score(lap_times: list[float]) -> float | None:
    """Nota FS de skidpad: media de la mejor vuelta derecha (1-2) y la mejor
    izquierda (3-4). Solo válida con exactamente 4 vueltas."""
    if len(lap_times) != 4:
        return None
    return (min(lap_times[0:2]) + min(lap_times[2:4])) / 2.0


class LapTimer:
    """Convierte triggers del laptimer (timestamps del dispositivo) en vueltas.

    El primer trigger arma la referencia; cada trigger posterior válido cierra
    una vuelta medida de primer pulso a primer pulso.
    """

    def __init__(self, min_lap_s: float = MIN_LAP_S):
        self._min_lap_s = min_lap_s
        self._lock = threading.Lock()
        self._reference_t_s: float | None = None
        self.laps: list[Lap] = []

    def on_trigger(self, t_device_s: float) -> Lap | None:
        with self._lock:
            if self._reference_t_s is None:
                self._reference_t_s = t_device_s
                return None

            lap_time = t_device_s - self._reference_t_s
            if lap_time <= 0:
                return None  # timestamp no creciente: descartar
            if lap_time < self._min_lap_s:
                # Pulso fantasma: ignorar SIN mover la referencia
                return None

            self._reference_t_s = t_device_s
            lap = Lap(number=len(self.laps) + 1, lap_time_s=lap_time, trigger_t_s=t_device_s)
            self.laps.append(lap)
            return lap

    def lap_times(self) -> list[float]:
        with self._lock:
            return [lap.lap_time_s for lap in self.laps]

    def reset(self) -> None:
        with self._lock:
            self._reference_t_s = None
            self.laps = []

    @property
    def best_s(self) -> float | None:
        times = self.lap_times()
        return min(times) if times else None

    @property
    def avg_s(self) -> float | None:
        times = self.lap_times()
        return sum(times) / len(times) if times else None

    @property
    def last_s(self) -> float | None:
        times = self.lap_times()
        return times[-1] if times else None


@dataclass
class Session:
    name: str
    mode: str
    laps: list[Lap] = field(default_factory=list)

    def summary(self) -> dict:
        times = [lap.lap_time_s for lap in self.laps]
        fs = fs_skidpad_score(times) if self.mode == MODE_SKIDPAD else None
        return {
            "name": self.name,
            "mode": self.mode,
            "laps": len(times),
            "total_s": sum(times) if times else None,
            "best_s": min(times) if times else None,
            "avg_s": (sum(times) / len(times)) if times else None,
            "last_s": times[-1] if times else None,
            "fs_skidpad_s": fs,
        }


def format_lap_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--.---"
    total_ms = int(round(seconds * 1000.0))
    return f"{total_ms // 60000:02d}:{(total_ms % 60000) // 1000:02d}.{total_ms % 1000:03d}"
