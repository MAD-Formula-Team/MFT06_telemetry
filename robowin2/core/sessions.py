"""Gestión de sesiones de cronometraje (vivo) y su persistencia en el .db.

La sesión colecciona las vueltas que produce el LapTimer mientras está
activa. En skidpad se marca auto-completada a las 4 vueltas (la nota FS
solo existe con exactamente 4). La UI decide cuándo finalizar.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime

from .lapstore import MODE_SKIDPAD, Lap, LapTimer, Session, fs_skidpad_score


class SessionManager:
    def __init__(self, laptimer: LapTimer, writer_provider: Callable[[], object | None]):
        self._laptimer = laptimer
        self._writer_provider = writer_provider
        self._lock = threading.Lock()
        self.active: Session | None = None
        self.active_db_id: int | None = None
        self._started_monotonic: float | None = None
        self._auto_complete = False
        self.history: list[dict] = []

    # --- ciclo de vida ---

    def start(self, name: str, mode: str) -> None:
        with self._lock:
            self._laptimer.reset()
            self.active = Session(name=name or f"{mode}_{datetime.now():%H%M%S}", mode=mode)
            self._started_monotonic = time.monotonic()
            self._auto_complete = False

            writer = self._writer_provider()
            self.active_db_id = None
            if writer is not None:
                try:
                    self.active_db_id = writer.begin_session(self.active.name, mode)
                except Exception:
                    self.active_db_id = None  # sin persistencia, la sesión sigue

    def on_lap(self, lap: Lap) -> None:
        """Callback del pipeline: una vuelta válida cerrada."""
        with self._lock:
            if self.active is None:
                return
            self.active.laps.append(lap)
            if self.active.mode == MODE_SKIDPAD and len(self.active.laps) >= 4:
                self._auto_complete = True

    def stop(self) -> dict | None:
        """Finaliza la sesión activa. Devuelve el resumen (o None si no había)."""
        with self._lock:
            if self.active is None:
                return None
            summary = self.active.summary()
            summary["ended_utc"] = datetime.now().isoformat(timespec="seconds")
            summary["lap_times"] = [lap.lap_time_s for lap in self.active.laps]

            writer = self._writer_provider()
            if writer is not None and self.active_db_id is not None:
                try:
                    writer.end_session(self.active_db_id, fs_time_s=summary.get("fs_skidpad_s"))
                except Exception:
                    pass

            self.history.append(summary)
            self.active = None
            self.active_db_id = None
            self._started_monotonic = None
            self._auto_complete = False
            return summary

    # --- estado para la UI ---

    @property
    def is_running(self) -> bool:
        return self.active is not None

    def should_auto_finalize(self) -> bool:
        return self._auto_complete

    def elapsed_s(self) -> float | None:
        """Crono de sesión (desde INICIAR, reloj local)."""
        if self._started_monotonic is None:
            return None
        return time.monotonic() - self._started_monotonic

    def live_stats(self) -> dict:
        """Snapshot para el refresco de la página."""
        with self._lock:
            if self.active is None:
                return {"running": False, "laps": []}
            times = [lap.lap_time_s for lap in self.active.laps]
            return {
                "running": True,
                "name": self.active.name,
                "mode": self.active.mode,
                "laps": times,
                "best_s": min(times) if times else None,
                "avg_s": (sum(times) / len(times)) if times else None,
                "last_s": times[-1] if times else None,
                "total_s": sum(times) if times else None,
                "fs_skidpad_s": fs_skidpad_score(times) if self.active.mode == MODE_SKIDPAD else None,
            }
