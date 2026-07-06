"""Smoke UI offscreen: ventana completa alimentada con frames sintéticos.

Sin hardware ni pantalla: los frames entran por el mismo pipeline que en vivo
(vía replay no-realtime) y las páginas se refrescan a mano.
"""
import os

import cantools
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from robowin2.app_context import AppContext  # noqa: E402
from robowin2.core.frames import RawFrame  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def ctx(dbc_path):
    context = AppContext(dbc_path)
    yield context
    context.shutdown()


@pytest.fixture()
def loaded_ctx(ctx, dbc_path):
    """Contexto con 30 s de datos sintéticos ya procesados."""
    db = cantools.database.load_file(dbc_path)
    frames = []
    for i in range(30):
        t_us = i * 1_000_000
        payload = db.encode_message(929, {"iat": 25, "ect": 85 + i, "oil_temp": 95 + i})
        frames.append(RawFrame(t_us=t_us, can_id=929, data=payload))
    frames.append(RawFrame(t_us=15_000_000, can_id=0x666, data=b"\x01\x02"))

    ctx.open_replay_frames(frames, realtime=False)
    assert ctx.source.join(timeout=10.0)
    ctx.stop_source()
    return ctx


def _make_window(qapp, context):
    from robowin2.ui.main_window import MainWindow

    window = MainWindow(context)
    window.timer.stop()  # refresco manual en tests
    return window


def test_window_builds_and_navigates(qapp, loaded_ctx):
    window = _make_window(qapp, loaded_ctx)
    assert window.stack.count() == 5
    for i in range(5):
        window.switch_page(i)
        assert window.stack.currentIndex() == i
        window._tick()
    window.close()


def test_dashboard_cards_show_values_and_thresholds(qapp, loaded_ctx):
    window = _make_window(qapp, loaded_ctx)
    window.switch_page(0)
    window._tick()
    dashboard = window.pages[0]
    # ect terminó en 114 -> zona danger (>=110)
    assert dashboard.cards["ect"].value_label.text() == "114.0"
    from robowin2.ui import theme as thm

    assert thm.theme()["danger"] in dashboard.cards["ect"].value_label.styleSheet()
    window.close()


def test_bus_can_table_lists_ids_and_unknown(qapp, loaded_ctx):
    window = _make_window(qapp, loaded_ctx)
    window.switch_page(3)
    window._tick()
    bus_page = window.pages[3]
    assert bus_page.table.rowCount() == 2  # 929 + 0x666

    names = [bus_page.table.item(r, 1).text() for r in range(2)]
    assert "engine_temp" in names and "DESCONOCIDO" in names

    counts = {bus_page.table.item(r, 0).text(): bus_page.table.item(r, 6).text() for r in range(2)}
    assert counts["0x3A1"] == "30"
    window.close()


def test_senales_row_lifecycle(qapp, loaded_ctx):
    window = _make_window(qapp, loaded_ctx)
    window.switch_page(1)
    senales = window.pages[1]

    senales.checkboxes["ect"].setChecked(True)
    assert "ect" in senales.rows
    window._tick()
    assert senales.rows["ect"][1].value_label.text() == "114.0"

    senales.search.setText("rpm")
    assert senales.checkboxes["ect"].isHidden()
    assert not senales.checkboxes["engine_rpm"].isHidden()

    senales.checkboxes["ect"].setChecked(False)
    assert "ect" not in senales.rows
    window.close()


def test_laptimer_page_session_flow(qapp, loaded_ctx):
    """INICIAR -> vueltas simuladas -> auto-finalize skidpad -> historial + FS."""
    window = _make_window(qapp, loaded_ctx)
    window.switch_page(2)
    page = window.pages[2]
    ctx = loaded_ctx

    page.mode_selector.setCurrentText("SKIDPAD")
    page.name_input.setText("SMOKE SKIDPAD")
    page.toggle_session()
    assert ctx.sessions.is_running
    assert page.start_stop_btn.text() == "DETENER"

    # Simular triggers del laptimer: 4 vueltas de 10, 11, 12, 9 s
    for t in [100.0, 110.0, 121.0, 133.0, 142.0]:
        lap = ctx.laptimer.on_trigger(t)
        if lap:
            ctx.sessions.on_lap(lap)

    page.refresh()  # detecta el auto-completado del skidpad y finaliza

    assert not ctx.sessions.is_running
    assert page.start_stop_btn.text() == "INICIAR"
    assert page.history_table.rowCount() == 1
    assert page.history_table.item(0, 1).text() == "SMOKE SKIDPAD"
    assert page.history_table.item(0, 6).text() == "00:09.500"  # FS = (10+9)/2
    assert "FS 00:09.500" in page.session_status.text()
    window.close()


def test_offline_page_dataset_and_lap_focus(qapp, loaded_ctx, dbc_path, tmp_path):
    """Cargar dataset en OFFLINE: señales, auto-plots y foco de vuelta."""
    import cantools

    from robowin2.core.decoder import DbcDecoder
    from robowin2.core.rawlog import RawLogWriter
    from robowin2.io_ import offline as offline_io

    db = cantools.database.load_file(dbc_path)
    writer = RawLogWriter(tmp_path / "ui_off.db")
    for i in range(20):
        payload = db.encode_message(929, {"iat": 25, "ect": 80 + i, "oil_temp": 90 + i})
        writer.write(RawFrame(t_us=i * 1_000_000, can_id=929, data=payload))
    sid = writer.begin_session("UI OFF", "AUTOCROSS")
    writer.write_lap(1, 15_000_000, 8.0, session_id=sid)
    writer.end_session(sid)
    writer.close()

    dataset = offline_io.load_db(tmp_path / "ui_off.db", DbcDecoder(dbc_path))

    window = _make_window(qapp, loaded_ctx)
    window.switch_page(4)
    page = window.pages[4]
    page.load_dataset(dataset)

    assert "ect" in page.checkboxes
    assert len(page.plots) > 0  # auto-activadas señales con datos
    assert page.laps_table.rowCount() == 1

    page.laps_table.setCurrentCell(0, 0)  # foco de vuelta
    assert "VUELTA 1" in page.lap_hint.text()
    for plot in page.plots.values():
        assert plot._lap_region is not None and plot._lap_region.isVisible()
    window.close()


def test_offline_zoom_popup_and_time_windows(qapp, loaded_ctx, dbc_path, tmp_path):
    """Auto-Y visible, crosshair+popup sincronizados y ventanas temporales."""
    import cantools

    from robowin2.core.decoder import DbcDecoder
    from robowin2.core.rawlog import RawLogWriter
    from robowin2.io_ import offline as offline_io
    from robowin2.ui.pages.offline import parse_window_text

    # parse de ventanas personalizadas
    assert parse_window_text("45") == 45.0
    assert parse_window_text("3:15") == 195.0
    assert parse_window_text("1:05:00") == 3900.0
    assert parse_window_text("abc") is None and parse_window_text("") is None

    # dataset de 10 minutos
    db = cantools.database.load_file(dbc_path)
    writer = RawLogWriter(tmp_path / "zoom.db")
    for i in range(600):
        payload = db.encode_message(929, {"iat": 25, "ect": 80 + (i % 40), "oil_temp": 90})
        writer.write(RawFrame(t_us=i * 1_000_000, can_id=929, data=payload))
    writer.close()
    dataset = offline_io.load_db(tmp_path / "zoom.db", DbcDecoder(dbc_path))

    window = _make_window(qapp, loaded_ctx)
    window.switch_page(4)
    page = window.pages[4]
    page.load_dataset(dataset)
    assert len(page.plots) >= 1
    plot = next(iter(page.plots.values()))

    # Auto-Y solo con datos visibles + zoom de ratón solo en X
    viewbox = plot.plot_widget.getViewBox()
    assert viewbox.state["autoVisibleOnly"][1] is True
    assert viewbox.state["mouseEnabled"][1] is False

    # Ventana preset de 1 min: la vista mide 60 s
    page._apply_window(60.0)
    x0, x1 = plot.view_x_range()
    assert abs((x1 - x0) - 60.0) < 1e-6

    # Ventana personalizada "3:15"
    page.window_custom.setText("3:15")
    page._apply_custom_window()
    x0, x1 = plot.view_x_range()
    assert abs((x1 - x0) - 195.0) < 1e-6

    # Crosshair sincronizado + popup con valores
    page._on_crosshair(100.0, sender=None)
    assert page.value_popup.isVisibleTo(page)
    assert "TIEMPO: 100.00s" in page.value_popup.text()
    assert "ect:" in page.value_popup.text()

    page._on_crosshair_left()
    assert not page.value_popup.isVisibleTo(page)

    # Toggle del popup
    page._toggle_popup()
    page._on_crosshair(100.0, sender=None)
    assert not page.value_popup.isVisibleTo(page)
    window.close()


def test_theme_toggle(qapp, loaded_ctx):
    from robowin2.ui import theme as thm

    thm.set_theme("dark")
    window = _make_window(qapp, loaded_ctx)
    assert "#1a1a19" in window.styleSheet()
    window.toggle_theme()
    assert "#ebebeb" in window.styleSheet()
    assert window.theme_btn.text() == "MODO OSCURO"
    window.toggle_theme()
    assert thm.is_dark()
    window.close()
