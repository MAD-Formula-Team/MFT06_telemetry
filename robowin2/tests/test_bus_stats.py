from robowin2.core.bus_stats import BusStats


def _feed(stats, t_us, can_id, data, name=None):
    stats.on_frame(t_us, can_id, data, name)


def test_frequency_and_count():
    stats = BusStats()
    # 10 Hz durante 2 s
    for i in range(20):
        _feed(stats, i * 100_000, 0x3A1, b"\x01\x02", "engine_temp")

    views = stats.snapshot(now_us=1_900_000)
    assert len(views) == 1
    v = views[0]
    assert v.count == 20
    assert v.name == "engine_temp"
    assert 9.0 <= v.freq_hz <= 11.0
    assert abs(v.period_ms - 100.0) < 5.0


def test_rolling_window_prunes_old_frames():
    stats = BusStats()
    _feed(stats, 0, 0x100, b"\x00")
    _feed(stats, 100_000, 0x100, b"\x00")
    # 60 s después: la ventana de 5 s debe estar vacía -> 0 Hz, count se conserva
    views = stats.snapshot(now_us=60_000_000)
    v = views[0]
    assert v.count == 2
    assert v.freq_hz == 0.0
    assert v.age_s > 50


def test_changed_byte_mask():
    stats = BusStats()
    _feed(stats, 0, 0x200, bytes([0xAA, 0xBB, 0xCC]))
    _feed(stats, 1000, 0x200, bytes([0xAA, 0xFF, 0xCC]))
    v = stats.snapshot(now_us=2000)[0]
    assert v.changed_mask == 0b010  # solo cambió el byte 1


def test_unknown_id_and_bandwidth_share():
    stats = BusStats()
    _feed(stats, 0, 0x3A1, b"\x00" * 6, "engine_temp")
    _feed(stats, 1000, 0x666, b"\x00" * 2, None)  # desconocido
    views = {v.can_id: v for v in stats.snapshot(now_us=2000)}
    assert views[0x666].name is None
    assert abs(views[0x3A1].bandwidth_share - 6 / 8) < 1e-9
    assert abs(views[0x666].bandwidth_share - 2 / 8) < 1e-9
