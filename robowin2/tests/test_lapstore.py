from robowin2.core.lapstore import (
    MODE_SKIDPAD,
    LapTimer,
    Session,
    format_lap_time,
    fs_skidpad_score,
)


def test_basic_laps():
    lt = LapTimer()
    assert lt.on_trigger(100.0) is None  # primera pasada: referencia
    lap = lt.on_trigger(110.0)
    assert lap.number == 1 and lap.lap_time_s == 10.0
    lap2 = lt.on_trigger(121.5)
    assert lap2.lap_time_s == 11.5
    assert lt.best_s == 10.0 and lt.last_s == 11.5


def test_double_ir_pulse_filtered():
    lt = LapTimer()
    lt.on_trigger(100.0)
    assert lt.on_trigger(100.4) is None          # pulso fantasma
    lap = lt.on_trigger(110.0)
    assert lap.lap_time_s == 10.0                # medida desde el PRIMER pulso
    assert lt.on_trigger(110.3) is None
    assert lt.on_trigger(120.0).lap_time_s == 10.0
    assert len(lt.laps) == 2


def test_non_monotonic_rejected():
    lt = LapTimer()
    lt.on_trigger(100.0)
    assert lt.on_trigger(99.0) is None
    assert lt.on_trigger(110.0).lap_time_s == 10.0


def test_fs_skidpad_score():
    assert fs_skidpad_score([10.0, 11.0, 12.0, 9.0]) == 9.5  # (10 + 9) / 2
    assert fs_skidpad_score([10.0, 11.0]) is None            # incompleta


def test_session_summary_skidpad():
    lt = LapTimer()
    for t in [0.0, 10.0, 21.0, 33.0, 42.0]:
        lt.on_trigger(t)
    sess = Session(name="TEST", mode=MODE_SKIDPAD, laps=list(lt.laps))
    summary = sess.summary()
    assert summary["laps"] == 4
    assert summary["fs_skidpad_s"] == (10.0 + 9.0) / 2.0
    assert summary["total_s"] == 42.0


def test_format_lap_time():
    assert format_lap_time(None) == "--:--.---"
    assert format_lap_time(69.5) == "01:09.500"
