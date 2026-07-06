from robowin2.core.frames import RawFrame
from robowin2.core.rawlog import RawLogReader, RawLogWriter


def test_write_read_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    writer = RawLogWriter(db, dbc_sha1="abc", app_version="test")

    frames = [RawFrame(t_us=i * 1000, can_id=0x3A1 + (i % 3), data=bytes([i % 256] * 6)) for i in range(500)]
    for f in frames:
        writer.write(f)
    writer.write_lap(lap_no=1, t_us=123456, lap_time_s=10.5)
    writer.close()

    reader = RawLogReader(db)
    runs = reader.runs()
    assert len(runs) == 1 and runs[0]["dbc_sha1"] == "abc"
    run_id = runs[0]["id"]

    assert reader.frame_count(run_id) == 500
    read_back = list(reader.frames(run_id))
    assert read_back == frames  # igualdad exacta, byte a byte

    laps = reader.laps(run_id)
    assert len(laps) == 1 and laps[0]["lap_time_s"] == 10.5
    reader.close()


def test_time_slicing(tmp_path):
    db = tmp_path / "slice.db"
    writer = RawLogWriter(db)
    for i in range(100):
        writer.write(RawFrame(t_us=i * 1_000_000, can_id=0x100, data=b"\x00"))
    writer.close()

    reader = RawLogReader(db)
    run_id = reader.runs()[0]["id"]
    window = list(reader.frames(run_id, t0_us=10_000_000, t1_us=19_000_000))
    assert len(window) == 10
    assert window[0].t_us == 10_000_000 and window[-1].t_us == 19_000_000
    reader.close()


def test_flush_on_close_never_loses_pending(tmp_path):
    db = tmp_path / "pending.db"
    writer = RawLogWriter(db)
    # Menos que el tamaño de lote: queda pendiente hasta close()
    writer.write(RawFrame(t_us=1, can_id=0x1, data=b"\x01"))
    writer.close()

    reader = RawLogReader(db)
    assert reader.frame_count(reader.runs()[0]["id"]) == 1
    reader.close()
