"""Contexto de aplicación: instancia y conecta el núcleo, gestiona fuentes.

Es el único punto donde la UI toca el core. Sin imports de Qt: también lo
usan los tests headless.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from robowin2 import __version__, paths
from robowin2.core.bus_stats import BusStats
from robowin2.core.datastore import DataStore
from robowin2.core.decoder import DbcDecoder
from robowin2.core.frames import RawFrame
from robowin2.core.lapstore import LapTimer
from robowin2.core.pipeline import Pipeline
from robowin2.core.rawlog import RawLogReader, RawLogWriter
from robowin2.core.sessions import SessionManager
from robowin2.core.sources import ReplaySource, SerialSource


class AppContext:
    def __init__(self, dbc_path: str):
        self.decoder = DbcDecoder(dbc_path)
        self.datastore = DataStore()
        self.bus_stats = BusStats()
        self.laptimer = LapTimer()
        self.sessions = SessionManager(self.laptimer, writer_provider=lambda: self._rawlog)

        self.source: SerialSource | ReplaySource | None = None
        self.pipeline: Pipeline | None = None
        self._rawlog: RawLogWriter | None = None
        self._replay_mode = False
        self._status_lock = threading.Lock()
        self._status: tuple[str, str] = ("Sin conexión", "warn")

    # --- estado ---

    def _set_status(self, msg: str, level: str) -> None:
        with self._status_lock:
            self._status = (msg, level)

    def status(self) -> tuple[str, str]:
        with self._status_lock:
            return self._status

    def frames_processed(self) -> int:
        return self.pipeline.frames_processed if self.pipeline else 0

    def now_us(self) -> int:
        """Reloj de referencia para staleness en Bus CAN.

        En vivo: monotónico local (mismo reloj que SerialSource). En replay:
        el timestamp más reciente visto, para que las edades sean coherentes
        con el log y no con el reloj de hoy.
        """
        if self._replay_mode:
            views = self.bus_stats.snapshot(now_us=0)
            return max((v.last_t_us for v in views), default=0)
        return time.monotonic_ns() // 1_000

    # --- fuentes ---

    def connect_serial(self, device: str) -> None:
        self.stop_source()
        self._replay_mode = False
        self._rawlog = RawLogWriter(
            paths.default_db_path(), dbc_sha1="", app_version=__version__
        )
        self.pipeline = Pipeline(
            self.decoder, self.datastore, self.bus_stats,
            rawlog=self._rawlog, laptimer=self.laptimer,
            on_lap=self.sessions.on_lap,
            session_id_provider=lambda: self.sessions.active_db_id,
        )
        self.source = SerialSource(device, on_frame=self.pipeline.on_frame, on_status=self._set_status)
        self.source.start()

    def open_replay_frames(self, frames: list[RawFrame], realtime: bool = True, speed: float = 1.0) -> None:
        """Reproduce frames por el pipeline (sin re-loguear a disco)."""
        self.stop_source()
        self._replay_mode = True
        self.datastore.clear()
        self.bus_stats.clear()
        self.laptimer.reset()
        self.pipeline = Pipeline(
            self.decoder, self.datastore, self.bus_stats,
            rawlog=None, laptimer=self.laptimer,
            on_lap=self.sessions.on_lap,
        )
        self.source = ReplaySource(
            frames, on_frame=self.pipeline.on_frame, on_status=self._set_status,
            realtime=realtime, speed=speed,
        )
        self.source.start()

    def open_replay_db(self, db_path: str | Path, realtime: bool = True, speed: float = 1.0) -> int:
        """Carga el último run de un .db y lo reproduce. Devuelve nº de frames."""
        reader = RawLogReader(db_path)
        runs = reader.runs()
        if not runs:
            reader.close()
            raise ValueError("El log no contiene ningún run")
        run_id = runs[-1]["id"]
        frames = list(reader.frames(run_id))
        reader.close()
        self.open_replay_frames(frames, realtime=realtime, speed=speed)
        return len(frames)

    def stop_source(self) -> None:
        if self.source is not None:
            self.source.stop()
            self.source = None
        if self.pipeline is not None:
            self.pipeline.flush()
        if self._rawlog is not None:
            self._rawlog.close()
            self._rawlog = None
        self._set_status("Sin conexión", "warn")

    def shutdown(self) -> None:
        self.stop_source()
