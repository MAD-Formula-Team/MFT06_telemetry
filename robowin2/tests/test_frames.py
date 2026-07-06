from robowin2.core.frames import RawFrame, format_line, laptimer_timestamp_s, parse_line


def test_parse_valid_line():
    frame = parse_line("3A1,00,1F,5A,00,64,00", t_us=123)
    assert frame is not None
    assert frame.can_id == 0x3A1
    assert frame.data == bytes([0x00, 0x1F, 0x5A, 0x00, 0x64, 0x00])
    assert frame.t_us == 123


def test_parse_lowercase_and_id_only():
    assert parse_line("3a1,ff", 0).data == b"\xff"
    frame = parse_line("777", 0)
    assert frame.can_id == 0x777 and frame.data == b""


def test_parse_garbage_returns_none():
    for garbage in ["", ",", "XYZ,00", "3A1,GG", "hola mundo", "3A1,1FF"]:
        assert parse_line(garbage, 0) is None, garbage


def test_parse_tolerates_trailing_comma():
    # El enlace puede cortar una línea justo tras una coma: los bytes ya
    # recibidos siguen siendo válidos.
    frame = parse_line("3A1,00,", 0)
    assert frame is not None and frame.data == b"\x00"


def test_parse_rejects_oversize():
    assert parse_line("3A1," + ",".join(["00"] * 9), 0) is None  # >8 bytes
    assert parse_line("FFFFFFFF,00", 0) is None  # ID > 29 bits


def test_roundtrip_format_parse():
    original = RawFrame(t_us=5, can_id=0x3A4, data=bytes(range(8)))
    assert parse_line(format_line(original), 5) == original


def test_laptimer_timestamp_extraction():
    ts_us = 12_345_678
    frame = RawFrame(t_us=0, can_id=0x777, data=ts_us.to_bytes(8, "little"))
    assert laptimer_timestamp_s(frame) == ts_us / 1e6
    assert laptimer_timestamp_s(RawFrame(0, 0x3A1, b"\x00" * 8)) is None
    assert laptimer_timestamp_s(RawFrame(0, 0x777, b"\x00" * 4)) is None
