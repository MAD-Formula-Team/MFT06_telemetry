"""Datasets offline: .db propio, CSV legado REAL de ROBOWIN 1 y export roundtrip."""
from pathlib import Path

import cantools
import pytest

from robowin2.core.decoder import DbcDecoder
from robowin2.core.frames import RawFrame
from robowin2.core.rawlog import RawLogWriter
from robowin2.io_ import offline as offline_io

LEGACY_CSV = Path(__file__).resolve().parents[2] / "telemetria_20260703_184024.csv"
DATALOGGER_CSV = Path(__file__).resolve().parents[2] / "run_cambio_1.csv"


@pytest.fixture()
def recorded_db(dbc_path, tmp_path):
    """Log .db con telemetría, sesión y vueltas (incluye pulso fantasma)."""
    db = cantools.database.load_file(dbc_path)
    writer = RawLogWriter(tmp_path / "off.db")

    for i in range(60):
        payload = db.encode_message(929, {"iat": 25, "ect": 80 + i, "oil_temp": 90 + i})
        writer.write(RawFrame(t_us=i * 1_000_000, can_id=929, data=payload))

    session_id = writer.begin_session("OFFLINE TEST", "SKIDPAD")
    lap_data = [(2, 10_000_000, 10.0), (3, 21_000_000, 11.0)]
    for lap_no, t_us, lap_s in lap_data:
        writer.write_lap(lap_no, t_us, lap_s, session_id=session_id)
        us = t_us
        writer.write(RawFrame(t_us=us, can_id=0x777, data=us.to_bytes(8, "little")))
    writer.end_session(session_id, fs_time_s=None)
    writer.close()
    return tmp_path / "off.db"


def test_load_db(recorded_db, dbc_path):
    dataset = offline_io.load_db(recorded_db, DbcDecoder(dbc_path))
    t, v = dataset.datastore.snapshot("ect")
    assert len(v) == 60 and v[-1] == 139.0

    assert len(dataset.laps) == 2
    lap = dataset.laps[0]
    assert lap.lap_time_s == 10.0 and lap.t_end_s == 10.0
    assert lap.t_start_s == 0.0
    assert lap.session_name == "OFFLINE TEST"
    assert len(dataset.sessions) == 1


def test_load_legacy_csv_real_file():
    """El CSV real exportado por ROBOWIN 1 se importa sin pérdidas."""
    assert LEGACY_CSV.exists(), "falta el CSV legado del repo"
    dataset = offline_io.load_legacy_csv(LEGACY_CSV)

    # 68 señales de telemetría, ninguna columna laptime colada
    assert len(dataset.signal_keys) == 68
    assert not set(dataset.signal_keys) & offline_io.LEGACY_LAPTIME_COLUMNS

    t, v = dataset.datastore.snapshot("engine_rpm")
    assert len(v) == 190  # todas las filas

    # 47 vueltas de la sesión Endurance 17
    assert len(dataset.laps) == 47
    assert dataset.laps[0].number == 1
    assert dataset.laps[-1].number == 47
    assert dataset.laps[-1].session_name == "Endurance 17"


def test_load_datalogger_csv_real_file():
    """El CSV real del data logger (filas dispersas, timestamps absolutos)
    se importa con tiempos relativos y sin filas de unidades coladas."""
    assert DATALOGGER_CSV.exists(), "falta run_cambio_1.csv en la raíz del repo"
    dataset = offline_io.load_datalogger_csv(DATALOGGER_CSV)

    keys = dataset.signal_keys
    assert "ect" in keys and "engine_rpm" in keys and "oil_temp" in keys
    assert dataset.laps == []  # el logger no registra vueltas

    t, v = dataset.datastore.snapshot("engine_rpm")
    assert len(v) > 1000  # datos abundantes
    assert t[0] >= 0.0 and t[-1] > t[0]  # timeline relativa y creciente
    # La fila de unidades ('rpm') no puede haber entrado como muestra
    assert all(x >= 0 for x in v[:100])

    # Los timestamps relativos empiezan cerca de 0 (primera fila = t0)
    first_ts = min(dataset.datastore.snapshot(k)[0][0] for k in keys if len(dataset.datastore.snapshot(k)[0]))
    assert first_ts < 1.0


def test_load_csv_auto_detects_both_formats(tmp_path):
    legacy = offline_io.load_csv_auto(LEGACY_CSV)
    assert len(legacy.laps) == 47

    logger = offline_io.load_csv_auto(DATALOGGER_CSV)
    assert "(data logger)" in logger.description

    bad = tmp_path / "malo.csv"
    bad.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError):
        offline_io.load_csv_auto(bad)


def test_export_roundtrip(recorded_db, dbc_path, tmp_path):
    """Exportar a CSV combinado y reimportarlo conserva señales y vueltas."""
    dataset = offline_io.load_db(recorded_db, DbcDecoder(dbc_path))
    out = tmp_path / "export.csv"
    rows = offline_io.export_csv(dataset, out)
    assert rows == 60

    reimported = offline_io.load_legacy_csv(out)
    t, v = reimported.datastore.snapshot("ect")
    assert len(v) == 60 and v[0] == 80.0 and v[-1] == 139.0
    assert [lap.lap_time_s for lap in reimported.laps] == [10.0, 11.0]


def test_load_db_filters_ghost_pulse(dbc_path, tmp_path):
    """Triggers crudos con pulso fantasma: el dataset no debe verse afectado
    (la referencia de vuelta no se mueve con el segundo pulso)."""
    writer = RawLogWriter(tmp_path / "ghost.db")
    for device_s in [10.0, 10.4, 20.0]:  # 10.4 = fantasma
        us = int(device_s * 1_000_000)
        writer.write(RawFrame(t_us=us, can_id=0x777, data=us.to_bytes(8, "little")))
    writer.close()

    dataset = offline_io.load_db(tmp_path / "ghost.db", DbcDecoder(dbc_path))
    # Sin filas en la tabla laps (no había sesión ni pipeline), pero la carga
    # no debe fallar ni contar el fantasma como señal
    assert dataset.laps == []
