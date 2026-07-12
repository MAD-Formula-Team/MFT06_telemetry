"""Ventana principal: navbar de marca, control de fuente y stack de páginas."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from robowin2.core import ports as core_ports

from . import theme as thm
from .pages.bus_can import BusCanPage
from .pages.dashboard import DashboardPage
from .pages.laptimer import LapTimerPage
from .pages.offline import OfflinePage
from .pages.senales import SenalesPage

REFRESH_MS = 100

# Índices de página donde ESPACIO cuenta como trigger manual de vuelta
SPACE_TRIGGER_PAGES = (0, 2)  # DASHBOARD y LAP TIMER


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("ROBOWIN 2 · MFT06")
        self.resize(1366, 800)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Navbar ---
        navbar = QWidget()
        navbar.setObjectName("navbar")
        navbar.setMaximumHeight(44)
        nav_layout = QHBoxLayout(navbar)
        nav_layout.setContentsMargins(8, 0, 8, 0)
        nav_layout.setSpacing(2)

        brand = QLabel("MFT06")
        brand.setProperty("class", "brand")
        brand.setContentsMargins(4, 0, 14, 0)
        nav_layout.addWidget(brand)

        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(["DASHBOARD", "SEÑALES", "LAP TIMER", "BUS CAN", "OFFLINE"]):
            btn = QPushButton(label)
            btn.setMaximumHeight(30)
            btn.clicked.connect(lambda _=False, i=index: self.switch_page(i))
            nav_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        nav_layout.addStretch()

        # Fuente de datos: receptor ESP32 (CSV por radio) o Robotell USB-CAN (cable)
        self.source_mode = "esp32"
        self.source_btn = QPushButton("FUENTE: ESP32")
        self.source_btn.setMaximumHeight(30)
        self.source_btn.setToolTip(
            "Alterna la fuente CAN: receptor ESP32 (radio) o adaptador Robotell USB-CAN (cable).\n"
            "Se aplica al pulsar CONECTAR."
        )
        self.source_btn.clicked.connect(self.toggle_source_mode)
        nav_layout.addWidget(self.source_btn)

        self.port_selector = QComboBox()
        self.port_selector.setMinimumWidth(200)
        self.port_selector.setMaximumHeight(30)
        self.refresh_ports()
        nav_layout.addWidget(self.port_selector)

        refresh_btn = QPushButton("⟳")
        refresh_btn.setMaximumWidth(30)
        refresh_btn.setMaximumHeight(30)
        refresh_btn.setToolTip("Actualizar lista de puertos")
        refresh_btn.clicked.connect(self.refresh_ports)
        nav_layout.addWidget(refresh_btn)
        self._tool_buttons = [self.source_btn, refresh_btn]

        self.connect_btn = QPushButton("CONECTAR")
        self.connect_btn.setMaximumHeight(30)
        self.connect_btn.clicked.connect(self.toggle_connection)
        nav_layout.addWidget(self.connect_btn)

        replay_btn = QPushButton("ABRIR LOG")
        replay_btn.setMaximumHeight(30)
        replay_btn.clicked.connect(self.open_replay)
        nav_layout.addWidget(replay_btn)
        self._tool_buttons.append(replay_btn)

        self.theme_btn = QPushButton("MODO CLARO")
        self.theme_btn.setMaximumHeight(30)
        self.theme_btn.clicked.connect(self.toggle_theme)
        nav_layout.addWidget(self.theme_btn)
        self._tool_buttons.append(self.theme_btn)

        self.status_label = QLabel("Sin conexión")
        self.status_label.setMaximumWidth(340)
        nav_layout.addWidget(self.status_label)

        root.addWidget(navbar)

        # --- Páginas ---
        self.stack = QStackedWidget()
        self.pages = [
            DashboardPage(ctx), SenalesPage(ctx), LapTimerPage(ctx), BusCanPage(ctx), OfflinePage(ctx),
        ]
        for page in self.pages:
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.apply_theme()
        self.switch_page(0)

        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        # ESPACIO = trigger manual de vuelta (filtro global: los botones
        # con foco se comerían la tecla si se dejara llegar hasta ellos)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
            and not event.isAutoRepeat()
            and self.ctx.sessions.is_running
            and self.stack.currentIndex() in SPACE_TRIGGER_PAGES
            and not isinstance(QApplication.focusWidget(), QLineEdit)
        ):
            self.ctx.manual_lap_trigger()
            return True
        return super().eventFilter(obj, event)

    # --- fuente de datos ---

    def refresh_ports(self) -> None:
        current = self.port_selector.currentData()
        self.port_selector.blockSignals(True)
        self.port_selector.clear()
        for info in core_ports.list_candidate_ports():
            self.port_selector.addItem(info.label[:52], info.device)
        if current:
            idx = self.port_selector.findData(current)
            if idx >= 0:
                self.port_selector.setCurrentIndex(idx)
        self.port_selector.blockSignals(False)

    def toggle_source_mode(self) -> None:
        self.source_mode = "robotell" if self.source_mode == "esp32" else "esp32"
        self.source_btn.setText(f"FUENTE: {self.source_mode.upper()}")
        if self.ctx.source is not None:
            self.statusBar().showMessage("La nueva fuente se aplicará al reconectar", 5000)

    def toggle_connection(self) -> None:
        if self.ctx.source is not None:
            self.ctx.stop_source()
            self.connect_btn.setText("CONECTAR")
            return
        device = self.port_selector.currentData()
        if not device:
            QMessageBox.warning(self, "Sin puerto", "No hay ningún puerto serie seleccionado.")
            return
        if self.source_mode == "robotell":
            self.ctx.connect_robotell(device)
        else:
            self.ctx.connect_serial(device)
        self.connect_btn.setText("DESCONECTAR")

    def open_replay(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir log ROBOWIN", "", "Logs ROBOWIN (*.db);;Todos (*)"
        )
        if not filename:
            return
        try:
            n = self.ctx.open_replay_db(filename, realtime=True, speed=1.0)
        except Exception as exc:
            QMessageBox.critical(self, "Error abriendo log", str(exc))
            return
        self.connect_btn.setText("DETENER REPLAY")
        self.statusBar().showMessage(f"Replay: {n} frames", 5000)

    # --- refresco ---

    def _tick(self) -> None:
        page = self.stack.currentWidget()
        if page is not None:
            page.refresh()
        msg, level = self.ctx.status()
        frames = self.ctx.frames_processed()
        self.status_label.setText(f"{msg} | {frames} frames")
        self.status_label.setStyleSheet(thm.status_chip_style(level))
        if self.ctx.source is None and self.connect_btn.text() != "CONECTAR":
            self.connect_btn.setText("CONECTAR")

    # --- tema / navegación ---

    def switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setStyleSheet(thm.nav_button_style(i == index))

    def toggle_theme(self) -> None:
        thm.toggle_theme()
        self.apply_theme()

    def apply_theme(self) -> None:
        self.setStyleSheet(thm.app_stylesheet())
        self.theme_btn.setText("MODO CLARO" if thm.is_dark() else "MODO OSCURO")
        for btn in [self.connect_btn, *self._tool_buttons]:
            btn.setStyleSheet(thm.tool_button_style())
        self.switch_page(self.stack.currentIndex())
        for page in self.pages:
            page.apply_theme()

    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        self.timer.stop()
        self.ctx.shutdown()
        event.accept()
