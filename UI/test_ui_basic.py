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

    def mkPen(*_args, **_kwargs):
        return None

    fake_pg.PlotWidget = PlotWidget
    fake_pg.InfiniteLine = InfiniteLine
    fake_pg.SignalProxy = SignalProxy
    fake_pg.mkPen = mkPen
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


if __name__ == "__main__":
    unittest.main()
