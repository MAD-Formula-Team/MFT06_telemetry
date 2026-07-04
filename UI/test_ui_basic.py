import os
import sys
import unittest
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

UI_DIR = Path(__file__).resolve().parent
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

if "cantools" not in sys.modules:
    fake_cantools = types.ModuleType("cantools")

    class _FakeDBC:
        def __init__(self):
            self.messages = []

        def get_message_by_frame_id(self, _frame_id):
            raise KeyError

        def decode_message(self, _frame_id, _data):
            return {}

    fake_cantools.database = types.SimpleNamespace(load_file=lambda _path: _FakeDBC())
    sys.modules["cantools"] = fake_cantools

from PyQt6.QtWidgets import QApplication, QWidget

if "pyqtgraph" not in sys.modules:
    fake_pg = types.ModuleType("pyqtgraph")

    class _DummySignal:
        def connect(self, _slot):
            return None

    class _DummyScene:
        def __init__(self):
            self.sigMouseMoved = _DummySignal()

    class _DummyAxis:
        def setStyle(self, **_kwargs):
            return None

    class _DummyVB:
        def mapSceneToView(self, _pos):
            class _Point:
                def x(self):
                    return 0.0

            return _Point()

    class _DummyPlotItem:
        def __init__(self):
            self.vb = _DummyVB()

    class _DummyCurve:
        def setData(self, *_args, **_kwargs):
            return None

    class _DummyViewBox:
        pass

    class PlotWidget(QWidget):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.plotItem = _DummyPlotItem()
            self._scene = _DummyScene()

        def setBackground(self, *_args, **_kwargs):
            return None

        def showGrid(self, *_args, **_kwargs):
            return None

        def setDownsampling(self, *_args, **_kwargs):
            return None

        def setClipToView(self, *_args, **_kwargs):
            return None

        def setMinimumHeight(self, *_args, **_kwargs):
            return None

        def setMaximumHeight(self, *_args, **_kwargs):
            return None

        def setLabel(self, *_args, **_kwargs):
            return None

        def getAxis(self, *_args, **_kwargs):
            return _DummyAxis()

        def plot(self, *_args, **_kwargs):
            return _DummyCurve()

        def addItem(self, *_args, **_kwargs):
            return None

        def removeItem(self, *_args, **_kwargs):
            return None

        def setXLink(self, *_args, **_kwargs):
            return None

        def scene(self):
            return self._scene

        def sceneBoundingRect(self):
            class _Rect:
                def contains(self, _pos):
                    return False

            return _Rect()

        def setXRange(self, *_args, **_kwargs):
            return None

        def setYRange(self, *_args, **_kwargs):
            return None

        def getViewBox(self):
            return _DummyViewBox()

        def clear(self):
            return None

        def setTitle(self, *_args, **_kwargs):
            return None

    class InfiniteLine:
        def __init__(self, *args, **kwargs):
            return None

        def setVisible(self, *_args, **_kwargs):
            return None

        def setPos(self, *_args, **_kwargs):
            return None

    class SignalProxy:
        def __init__(self, *_args, **_kwargs):
            return None

    class AxisItem:
        def __init__(self, *_args, **_kwargs):
            return None

    class LinearRegionItem:
        def __init__(self, *_args, **_kwargs):
            return None

        def setRegion(self, *_args, **_kwargs):
            return None

        def setVisible(self, *_args, **_kwargs):
            return None

        def setZValue(self, *_args, **_kwargs):
            return None

    def mkPen(*_args, **_kwargs):
        return None

    def mkBrush(*_args, **_kwargs):
        return None

    fake_pg.PlotWidget = PlotWidget
    fake_pg.InfiniteLine = InfiniteLine
    fake_pg.SignalProxy = SignalProxy
    fake_pg.LinearRegionItem = LinearRegionItem
    fake_pg.AxisItem = AxisItem
    fake_pg.mkPen = mkPen
    fake_pg.mkBrush = mkBrush
    sys.modules["pyqtgraph"] = fake_pg

import Robowin


class TestTelemetryUIBasic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

        cls._orig_worker_start = Robowin.CanWorker.start
        cls._orig_worker_stop = Robowin.CanWorker.stop

        # Evita hilos/IO real durante tests de UI.
        Robowin.CanWorker.start = lambda self: None
        Robowin.CanWorker.stop = lambda self: None

    @classmethod
    def tearDownClass(cls):
        Robowin.CanWorker.start = cls._orig_worker_start
        Robowin.CanWorker.stop = cls._orig_worker_stop

    def setUp(self):
        self.window = Robowin.TelemetryWindow()
        self.window.timer.stop()

    def tearDown(self):
        self.window.deleteLater()

    def test_page_count_and_navigation(self):
        self.assertEqual(self.window.pages_stack.count(), 5)

        self.window.switch_page(4)
        self.assertEqual(self.window.pages_stack.currentIndex(), 4)

        self.window.switch_page(0)
        self.assertEqual(self.window.pages_stack.currentIndex(), 0)

    def test_popup_toggle_changes_state_and_text(self):
        self.assertFalse(self.window.popup_enabled)
        self.assertEqual(self.window.popup_toggle_btn.text(), "POPUP OFF")

        self.window.toggle_popup()
        self.assertTrue(self.window.popup_enabled)
        self.assertEqual(self.window.popup_toggle_btn.text(), "POPUP ON")

        self.window.toggle_popup()
        self.assertFalse(self.window.popup_enabled)
        self.assertEqual(self.window.popup_toggle_btn.text(), "POPUP OFF")

    def test_status_label_behavior(self):
        self.window.update_status("conectado: /dev/ttyUSB0", "green")
        self.assertIn("PUERTO:", self.window.status_label.text())
        self.assertIn("#2e7d32", self.window.status_label.styleSheet())

        self.window.update_status("error", "red")
        self.assertEqual(self.window.status_label.text(), "BUSCANDO...")
        self.assertIn("#f57c00", self.window.status_label.styleSheet())

    def test_offline_session_selector_from_combined_rows(self):
        rows = [
            {
                "timestamp": 1.0,
                "name": "TEST_A",
                "mode": "SKIDPAD",
                "lap_number": 1,
                "lap_time_fmt": "00:10.000",
                "delta_fmt": "0.000s",
                "state": "BEST",
                "lap_time_s": 10.0,
                "delta_s": 0.0,
            },
            {
                "timestamp": 2.0,
                "name": "TEST_A",
                "mode": "SKIDPAD",
                "lap_number": 2,
                "lap_time_fmt": "00:10.500",
                "delta_fmt": "+0.500s",
                "state": "LAST",
                "lap_time_s": 10.5,
                "delta_s": 0.5,
            },
        ]

        self.window.update_offline_session_selector(rows)

        self.assertGreaterEqual(self.window.offline_session_selector.count(), 2)
        self.assertEqual(self.window.offline_session_selector.currentIndex(), 1)
        self.assertEqual(self.window.offline_session_laps_table.rowCount(), 2)

    def test_load_from_csv_combined_format(self):
        """El CSV combinado (telemetría + columnas laptime de texto) debe
        recargarse sin perder filas ni registrar las columnas laptime como señales."""
        import tempfile

        store = Robowin.TelemetryDataStore()
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, newline=""
        ) as f:
            f.write("timestamp,engine_rpm,ect,name,mode,lap_number,lap_time_s,lap_time_fmt,state\n")
            f.write("1.000,5000,80,,,,,,\n")
            f.write("2.000,5500,81,TEST,SKIDPAD,1,10.5,00:10.500,BEST\n")
            path = f.name

        try:
            ok, _msg, num_signals, num_rows = store.load_from_csv(path)
        finally:
            os.unlink(path)

        self.assertTrue(ok)
        self.assertEqual(num_rows, 2)
        self.assertEqual(num_signals, 2)
        self.assertEqual(sorted(store.get_all_signals()), ["ect", "engine_rpm"])
        _t, values = store.get_signal_data("engine_rpm")
        self.assertEqual(values, [5000.0, 5500.0])

    def test_history_table_has_total_column(self):
        headers = [
            self.window.laptimer_history_table.horizontalHeaderItem(i).text()
            for i in range(self.window.laptimer_history_table.columnCount())
        ]
        self.assertIn("TOTAL", headers)

    def test_offline_signal_checkboxes_and_lap_focus(self):
        """Cargar señales offline debe crear checkboxes, auto-activar gráficas
        y permitir enfocar la telemetría de una vuelta sin errores."""
        w = self.window
        w.data_store.clear()
        w.data_store.add_sample("engine_rpm", 5000, timestamp=1.0)
        w.data_store.add_sample("engine_rpm", 6000, timestamp=2.0)
        w.data_store.add_sample("ect", 80, timestamp=1.0)
        w.offline_unified_laptime_rows = [
            {"timestamp": 2.0, "lap_number": 1, "lap_time_s": 1.0}
        ]

        w.populate_offline_signal_checkboxes()

        self.assertEqual(sorted(w.offline_checkboxes), ["ect", "engine_rpm"])
        # Auto-check: señales con datos distintos de cero generan gráfica
        self.assertGreaterEqual(len(w.offline_plot_widgets), 1)

        w.focus_offline_lap({"timestamp": 2.0, "lap_time_s": 1.0}, switch_tab=True)
        self.assertEqual(w.offline_right_tabs.currentIndex(), 0)

    def test_theme_toggle_switches_palette(self):
        """El botón de tema debe alternar oscuro/claro y reaplicar estilos."""
        import ui_theme

        ui_theme.set_theme("dark")
        self.window.apply_theme()
        self.assertIn("#1a1a19", self.window.styleSheet())
        self.assertEqual(self.window.theme_toggle_btn.text(), "MODO CLARO")

        self.window.toggle_theme_mode()
        self.assertFalse(ui_theme.is_dark())
        self.assertIn("#ebebeb", self.window.styleSheet())
        self.assertEqual(self.window.theme_toggle_btn.text(), "MODO OSCURO")

        self.window.toggle_theme_mode()
        self.assertTrue(ui_theme.is_dark())

    def test_signal_cards_follow_active_graphs(self):
        """Activar una señal en SEÑALES crea su tarjeta de valor; desactivarla la quita."""
        w = self.window
        key = "test_signal"
        w.color_assignment[key] = "#1c93d8"

        w.toggle_graph(key, True)
        self.assertIn(key, w.signal_cards)
        self.assertIn(key, w.signal_card_value_labels)

        w.toggle_graph(key, False)
        self.assertNotIn(key, w.signal_cards)
        self.assertNotIn(key, w.signal_card_value_labels)

    def test_offline_signal_search_filters_checkboxes(self):
        """El buscador de señales offline oculta las que no coinciden."""
        w = self.window
        w.data_store.clear()
        w.data_store.add_sample("engine_rpm", 1.0, timestamp=0.1)
        w.data_store.add_sample("ect", 2.0, timestamp=0.1)
        w.populate_offline_signal_checkboxes()

        w.offline_signal_search.setText("rpm")
        self.assertTrue(w.offline_checkboxes["ect"].isHidden())
        self.assertFalse(w.offline_checkboxes["engine_rpm"].isHidden())

        w.offline_signal_search.setText("")
        self.assertFalse(w.offline_checkboxes["ect"].isHidden())
        self.assertFalse(w.offline_checkboxes["engine_rpm"].isHidden())

    def test_skidpad_history_total_uses_fs_time(self):
        """En skidpad, la columna TOTAL del historial debe mostrar el tiempo FS:
        media de la mejor vuelta derecha (1-2) y la mejor izquierda (3-4)."""
        w = self.window
        w.session_mode = "Skidpad"
        w.session_laps = [10.0, 11.0, 12.0, 9.0]

        summary = w.build_laptimer_summary(42.0)
        expected_fs = w.format_lap_time((10.0 + 9.0) / 2.0)  # 00:09.500
        self.assertEqual(summary["skidpad_time"], expected_fs)

        w.append_session_history(summary)
        row = w.laptimer_history_table.rowCount() - 1
        self.assertEqual(w.laptimer_history_table.item(row, 6).text(), expected_fs)

    def test_pause_before_first_trigger_does_not_crash(self):
        self.window.start_session()
        self.window.toggle_pause_session()  # antes: TypeError por started_at None
        self.assertTrue(self.window.session_paused)
        self.window.toggle_pause_session()
        self.assertFalse(self.window.session_paused)
        self.assertIsNone(self.window.session_started_at)


if __name__ == "__main__":
    unittest.main()
