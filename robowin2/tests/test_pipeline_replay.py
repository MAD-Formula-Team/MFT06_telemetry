"""Integración end-to-end: frames sintéticos codificados con el DBC real
pasan por ReplaySource -> Pipeline -> (rawlog, bus_stats, datastore, laptimer),
y el log en disco se puede reproducir de nuevo con resultados idénticos.
"""
import cantools
import pytest

from robowin2.core.bus_stats import BusStats
from robowin2.core.datastore import DataStore
from robowin2.core.decoder import DbcDecoder
from robowin2.core.frames import RawFrame
from robowin2.core.lapstore import LapTimer
from robowin2.core.pipeline import Pipeline
from robowin2.core.rawlog import RawLogReader, RawLogWriter
from robowin2.core.sources import ReplaySource


@pytest.fixture()
def synthetic_frames(dbc_path):
    """60 s simulados: engine_temp a 1 Hz, un ID desconocido, y 5 pasadas
    de laptimer con pulso fantasma."""
    db = cantools.database.load_file(dbc_path)
    frames = []

    for i in range(60):
        t_us = i * 1_000_000
        payload = db.encode_message(929, {"iat": 25 + i % 3, "ect": 80 + i, "oil_temp": 90 + i})
        frames.append(RawFrame(t_us=t_us, can_id=929, data=payload))

    # ID que no está en el DBC
    frames.append(RawFrame(t_us=500_000, can_id=0x666, data=b"\xde\xad"))

    # Laptimer: pasadas en t=5,15,26,38,50 s (device time) + fantasma a +0.4 s
    for pass_s in [5, 15, 26, 38, 50]:
        device_us = pass_s * 1_000_000
        for offset_us in (0, 400_000):  # pulso real + fantasma
            frames.append(
                RawFrame(
                    t_us=pass_s * 1_000_000 + offset_us,
                    can_id=0x777,
                    data=(device_us + offset_us).to_bytes(8, "little"),
                )
            )

    frames.sort(key=lambda f: f.t_us)
    return frames


def _run_pipeline(frames, dbc_path, db_file):
    decoder = DbcDecoder(dbc_path)
    datastore = DataStore()
    stats = BusStats()
    laptimer = LapTimer()
    rawlog = RawLogWriter(db_file) if db_file else None
    pipeline = Pipeline(decoder, datastore, stats, rawlog=rawlog, laptimer=laptimer)

    source = ReplaySource(frames, on_frame=pipeline.on_frame, realtime=False)
    source.start()
    assert source.join(timeout=10.0), "el replay no terminó"
    source.stop()
    pipeline.flush()
    if rawlog:
        rawlog.close()
    return pipeline, datastore, stats, laptimer


def test_end_to_end(synthetic_frames, dbc_path, tmp_path):
    db_file = tmp_path / "e2e.db"
    pipeline, datastore, stats, laptimer = _run_pipeline(synthetic_frames, dbc_path, db_file)

    # Todos los frames procesados, ninguno perdido
    assert pipeline.frames_processed == len(synthetic_frames)

    # Señales decodificadas: 60 muestras de ect con la rampa correcta
    t, v = datastore.snapshot("ect")
    assert len(v) == 60
    assert v[0] == 80.0 and v[-1] == 139.0

    # Laptimer: 5 pasadas -> 4 vueltas (fantasmas filtrados)
    assert [round(x, 3) for x in laptimer.lap_times()] == [10.0, 11.0, 12.0, 12.0]

    # Bus stats: el ID desconocido aparece marcado
    views = {view.can_id: view for view in stats.snapshot(now_us=60_000_000)}
    assert views[0x666].name is None and views[0x666].count == 1
    assert views[929].count == 60
    assert views[0x777].name == "laptimer" and views[0x777].count == 10

    # El log crudo contiene exactamente lo que entró
    reader = RawLogReader(db_file)
    run_id = reader.runs()[0]["id"]
    assert reader.frame_count(run_id) == len(synthetic_frames)
    assert len(reader.laps(run_id)) == 4
    reader.close()


def test_replay_from_disk_is_identical(synthetic_frames, dbc_path, tmp_path):
    """Grabar -> releer el .db -> re-procesar: mismos resultados exactos."""
    db_file = tmp_path / "first.db"
    _run_pipeline(synthetic_frames, dbc_path, db_file)

    reader = RawLogReader(db_file)
    run_id = reader.runs()[0]["id"]
    recorded = list(reader.frames(run_id))
    reader.close()

    _, datastore2, _, laptimer2 = _run_pipeline(recorded, dbc_path, None)
    t2, v2 = datastore2.snapshot("ect")
    assert len(v2) == 60 and v2[-1] == 139.0
    assert [round(x, 3) for x in laptimer2.lap_times()] == [10.0, 11.0, 12.0, 12.0]
