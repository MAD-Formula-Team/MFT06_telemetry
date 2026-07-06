"""Log crudo append-only en SQLite: nada se pierde, todo es regenerable.

Cada frame se registra ANTES de decodificar: un DBC incorrecto o un bug de
decodificación nunca cuesta datos. WAL + inserts por lotes para no bloquear.

La conexión SQLite se crea perezosamente en el primer write(), de modo que
pertenece al hilo del pipeline (sqlite3 exige usar la conexión desde el hilo
que la creó).
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .frames import RawFrame

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_utc TEXT NOT NULL,
    dbc_sha1 TEXT,
    app_version TEXT
);
CREATE TABLE IF NOT EXISTS frames (
    run_id INTEGER NOT NULL,
    t_us INTEGER NOT NULL,
    can_id INTEGER NOT NULL,
    len INTEGER NOT NULL,
    data BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_frames_run_t ON frames(run_id, t_us);
CREATE TABLE IF NOT EXISTS laps (
    run_id INTEGER NOT NULL,
    session_id INTEGER,
    lap_no INTEGER NOT NULL,
    t_us INTEGER NOT NULL,
    lap_time_s REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'laptimer'
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_utc TEXT,
    ended_utc TEXT,
    fs_time_s REAL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_FLUSH_INTERVAL_S = 0.25
_FLUSH_BATCH = 200


class RawLogWriter:
    def __init__(self, db_path: str | Path, dbc_sha1: str = "", app_version: str = ""):
        self._db_path = str(db_path)
        self._dbc_sha1 = dbc_sha1
        self._app_version = app_version
        self._conn: sqlite3.Connection | None = None
        self.run_id: int | None = None
        self._pending: list[tuple] = []
        self._last_flush = time.monotonic()

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False: la conexión se crea en el hilo de la
            # fuente (primer write) pero flush()/close() finales llegan del
            # hilo principal tras parar la fuente. El acceso está serializado
            # por diseño (nunca dos hilos a la vez), así que es seguro.
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            cur = self._conn.execute(
                "INSERT INTO runs (started_utc, dbc_sha1, app_version) VALUES (?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), self._dbc_sha1, self._app_version),
            )
            self.run_id = cur.lastrowid
            self._conn.commit()
        return self._conn

    def write(self, frame: RawFrame) -> None:
        self._ensure_conn()
        self._pending.append((self.run_id, frame.t_us, frame.can_id, len(frame.data), frame.data))
        now = time.monotonic()
        if len(self._pending) >= _FLUSH_BATCH or (now - self._last_flush) >= _FLUSH_INTERVAL_S:
            self.flush()

    def write_lap(self, lap_no: int, t_us: int, lap_time_s: float, session_id: int | None = None) -> None:
        conn = self._ensure_conn()
        conn.execute(
            "INSERT INTO laps (run_id, session_id, lap_no, t_us, lap_time_s) VALUES (?, ?, ?, ?, ?)",
            (self.run_id, session_id, lap_no, t_us, lap_time_s),
        )
        conn.commit()

    def begin_session(self, name: str, mode: str) -> int:
        conn = self._ensure_conn()
        cur = conn.execute(
            "INSERT INTO sessions (run_id, name, mode, started_utc) VALUES (?, ?, ?, ?)",
            (self.run_id, name, mode, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return int(cur.lastrowid)

    def end_session(self, session_id: int, fs_time_s: float | None = None) -> None:
        conn = self._ensure_conn()
        conn.execute(
            "UPDATE sessions SET ended_utc = ?, fs_time_s = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), fs_time_s, session_id),
        )
        conn.commit()

    def flush(self) -> None:
        if not self._pending:
            return
        conn = self._ensure_conn()
        conn.executemany(
            "INSERT INTO frames (run_id, t_us, can_id, len, data) VALUES (?, ?, ?, ?, ?)",
            self._pending,
        )
        conn.commit()
        self._pending.clear()
        self._last_flush = time.monotonic()

    def close(self) -> None:
        if self._conn is not None:
            self.flush()
            self._conn.close()
            self._conn = None


class RawLogReader:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row

    def runs(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def frames(self, run_id: int, t0_us: int | None = None, t1_us: int | None = None) -> Iterator[RawFrame]:
        query = "SELECT t_us, can_id, data FROM frames WHERE run_id = ?"
        params: list = [run_id]
        if t0_us is not None:
            query += " AND t_us >= ?"
            params.append(t0_us)
        if t1_us is not None:
            query += " AND t_us <= ?"
            params.append(t1_us)
        query += " ORDER BY t_us"
        for row in self._conn.execute(query, params):
            yield RawFrame(t_us=row["t_us"], can_id=row["can_id"], data=bytes(row["data"]))

    def frame_count(self, run_id: int) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM frames WHERE run_id = ?", (run_id,)).fetchone()
        return int(row["n"])

    def laps(self, run_id: int, session_id: int | None = None) -> list[dict]:
        if session_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM laps WHERE run_id = ? AND session_id = ? ORDER BY lap_no",
                (run_id, session_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM laps WHERE run_id = ? ORDER BY lap_no", (run_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def sessions(self, run_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
