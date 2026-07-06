"""Sesiones: colección de vueltas, auto-completado skidpad y persistencia .db."""
from robowin2.core.bus_stats import BusStats
from robowin2.core.datastore import DataStore
from robowin2.core.decoder import DbcDecoder
from robowin2.core.frames import RawFrame
from robowin2.core.lapstore import MODE_AUTOCROSS, MODE_SKIDPAD, LapTimer
from robowin2.core.pipeline import Pipeline
from robowin2.core.rawlog import RawLogReader, RawLogWriter
from robowin2.core.sessions import SessionManager


def _trigger_frame(device_s: float) -> RawFrame:
    us = int(device_s * 1_000_000)
    return RawFrame(t_us=us, can_id=0x777, data=us.to_bytes(8, "little"))


def _build(dbc_path, writer):
    laptimer = LapTimer()
    sessions = SessionManager(laptimer, writer_provider=lambda: writer)
    pipeline = Pipeline(
        DbcDecoder(dbc_path), DataStore(), BusStats(),
        rawlog=writer, laptimer=laptimer,
        on_lap=sessions.on_lap,
        session_id_provider=lambda: sessions.active_db_id,
    )
    return sessions, pipeline


def test_skidpad_session_full_cycle_with_persistence(dbc_path, tmp_path):
    writer = RawLogWriter(tmp_path / "sesion.db")
    sessions, pipeline = _build(dbc_path, writer)

    sessions.start("SKIDPAD TEST", MODE_SKIDPAD)
    assert sessions.is_running and sessions.active_db_id is not None

    # 5 pasadas -> 4 vueltas: 10, 11, 12, 9 s (FS = (10+9)/2 = 9.5)
    for t in [100.0, 110.0, 121.0, 133.0, 142.0]:
        pipeline.on_frame(_trigger_frame(t))

    assert sessions.should_auto_finalize()
    stats = sessions.live_stats()
    assert stats["laps"] == [10.0, 11.0, 12.0, 9.0]
    assert stats["fs_skidpad_s"] == 9.5

    summary = sessions.stop()
    assert summary["fs_skidpad_s"] == 9.5
    assert not sessions.is_running
    writer.close()

    # Persistencia: sesión con FS y 4 vueltas colgando de ella
    reader = RawLogReader(tmp_path / "sesion.db")
    run_id = reader.runs()[0]["id"]
    stored_sessions = reader.sessions(run_id)
    assert len(stored_sessions) == 1
    sess = stored_sessions[0]
    assert sess["name"] == "SKIDPAD TEST"
    assert sess["fs_time_s"] == 9.5
    assert sess["ended_utc"] is not None

    laps = reader.laps(run_id, session_id=sess["id"])
    assert [lap["lap_time_s"] for lap in laps] == [10.0, 11.0, 12.0, 9.0]
    reader.close()


def test_laps_outside_session_have_no_session_id(dbc_path, tmp_path):
    writer = RawLogWriter(tmp_path / "libre.db")
    _sessions, pipeline = _build(dbc_path, writer)

    # Sin sesión activa: las vueltas se registran igualmente (session_id NULL)
    for t in [10.0, 20.0]:
        pipeline.on_frame(_trigger_frame(t))
    writer.close()

    reader = RawLogReader(tmp_path / "libre.db")
    run_id = reader.runs()[0]["id"]
    laps = reader.laps(run_id)
    assert len(laps) == 1 and laps[0]["session_id"] is None
    reader.close()


def test_autocross_no_auto_finalize_and_no_writer(dbc_path):
    laptimer = LapTimer()
    sessions = SessionManager(laptimer, writer_provider=lambda: None)  # replay: sin log
    sessions.start("", MODE_AUTOCROSS)
    assert sessions.active_db_id is None
    assert sessions.active.name.startswith(MODE_AUTOCROSS)  # nombre autogenerado

    for t in [0.0, 50.0, 101.0, 155.0, 203.0]:
        lap = laptimer.on_trigger(t)
        if lap:
            sessions.on_lap(lap)

    assert not sessions.should_auto_finalize()  # solo skidpad auto-completa
    summary = sessions.stop()
    assert summary["laps"] == 4
    assert summary["fs_skidpad_s"] is None
    assert sessions.history[-1] is summary
