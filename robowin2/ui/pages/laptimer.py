"""Lap Timer: control de sesión, crono, vueltas en vivo y nota FS de skidpad.

Sin popups modales: al finalizar, el resumen va a la fila de estado y al
historial (y queda persistido en el .db si hay log activo).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from robowin2.core.lapstore import (
    MODE_AUTOCROSS,
    MODE_ENDURANCE,
    MODE_SKIDPAD,
    format_lap_time,
)

from .. import theme as thm

MODES = [MODE_SKIDPAD, MODE_AUTOCROSS, MODE_ENDURANCE]


class LapTimerPage(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Control de sesión ---
        control_group = QGroupBox("CONTROL DE SESION")
        control_layout = QHBoxLayout(control_group)
        control_layout.setContentsMargins(8, 8, 8, 8)
        control_layout.setSpacing(6)

        self.mode_selector = QComboBox()
        self.mode_selector.addItems(MODES)
        control_layout.addWidget(self.mode_selector)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("NOMBRE DE SESION (EJ: TEST 1)")
        control_layout.addWidget(self.name_input, 1)

        self.start_stop_btn = QPushButton("INICIAR")
        self.start_stop_btn.setStyleSheet(thm.action_button_style("#1b7a4a"))
        self.start_stop_btn.clicked.connect(self.toggle_session)
        control_layout.addWidget(self.start_stop_btn)

        self.session_status = QLabel("LISTO — PENDIENTE DE INICIAR")
        self.session_status.setProperty("class", "chip")
        control_layout.addWidget(self.session_status, 1)
        layout.addWidget(control_group)

        # --- Métricas grandes ---
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(6)

        self.crono_label = self._stat_label("timer-big", "00:00.000")
        self.last_label = self._stat_label("stat-total", "--:--.---")
        self.best_label = self._stat_label("stat-best", "--:--.---")
        self.avg_label = self._stat_label("stat-avg", "--:--.---")
        self.fs_label = self._stat_label("stat-fs", "--:--.---")

        for widget, caption in [
            (self.crono_label, "CRONO SESION"),
            (self.last_label, "ULTIMA VUELTA"),
            (self.best_label, "MEJOR VUELTA"),
            (self.avg_label, "MEDIA"),
            (self.fs_label, "SKIDPAD FS"),
        ]:
            metrics_row.addWidget(self._captioned(widget, caption), 1)
        layout.addLayout(metrics_row)

        # --- Vueltas + historial ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        laps_group = QGroupBox("VUELTAS DE LA SESION")
        laps_layout = QVBoxLayout(laps_group)
        self.laps_table = QTableWidget(0, 4)
        self.laps_table.setHorizontalHeaderLabels(["VUELTA", "TIEMPO", "DELTA", "ESTADO"])
        self.laps_table.verticalHeader().setVisible(False)
        self.laps_table.setAlternatingRowColors(True)
        self.laps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.laps_table.horizontalHeader()
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        laps_layout.addWidget(self.laps_table)
        splitter.addWidget(laps_group)

        history_group = QGroupBox("HISTORIAL DE SESIONES")
        history_layout = QVBoxLayout(history_group)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["#", "NOMBRE", "MODO", "VUELTAS", "TOTAL", "MEJOR", "FS"]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h_header = self.history_table.horizontalHeader()
        h_header.setSectionResizeMode(1, h_header.ResizeMode.Stretch)
        history_layout.addWidget(self.history_table)
        splitter.addWidget(history_group)

        splitter.setSizes([600, 700])
        layout.addWidget(splitter, 1)

    @staticmethod
    def _stat_label(css_class: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("class", css_class)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    @staticmethod
    def _captioned(widget: QWidget, caption: str) -> QWidget:
        box = QWidget()
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)
        caption_label = QLabel(caption)
        caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption_label.setProperty("class", "muted-small")
        vbox.addWidget(caption_label)
        vbox.addWidget(widget)
        return box

    # --- acciones ---

    def toggle_session(self) -> None:
        sessions = self.ctx.sessions
        if sessions.is_running:
            self._finalize()
            return
        mode = self.mode_selector.currentText()
        sessions.start(self.name_input.text().strip(), mode)
        self.start_stop_btn.setText("DETENER")
        self.start_stop_btn.setStyleSheet(thm.action_button_style("#8f2c2c"))
        self.session_status.setText(f"{mode} ARMADO — el crono arranca con el primer ESPACIO o trigger")
        self.setFocus()  # que el foco no quede en un botón: ESPACIO = vuelta

    def _finalize(self) -> None:
        summary = self.ctx.sessions.stop()
        self.start_stop_btn.setText("INICIAR")
        self.start_stop_btn.setStyleSheet(thm.action_button_style("#1b7a4a"))
        if summary is None:
            self.session_status.setText("LISTO — PENDIENTE DE INICIAR")
            return

        fs = summary.get("fs_skidpad_s")
        resumen = (
            f"FINALIZADA: {summary['name']} | {summary['laps']} vueltas"
            + (f" | FS {format_lap_time(fs)}" if fs is not None else "")
            + (f" | mejor {format_lap_time(summary['best_s'])}" if summary.get("best_s") else "")
        )
        self.session_status.setText(resumen)
        self._append_history(summary)

    def _append_history(self, summary: dict) -> None:
        row = self.history_table.rowCount()
        self.history_table.insertRow(row)
        values = [
            str(row + 1),
            summary["name"],
            summary["mode"],
            str(summary["laps"]),
            format_lap_time(summary.get("total_s")),
            format_lap_time(summary.get("best_s")),
            format_lap_time(summary.get("fs_skidpad_s")) if summary.get("fs_skidpad_s") else "—",
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 6 and value != "—":
                item.setForeground(QColor(thm.theme()["accent"]))
            self.history_table.setItem(row, col, item)

    # --- refresco ---

    def refresh(self) -> None:
        sessions = self.ctx.sessions

        # Skidpad completo (4 vueltas): finalizar automáticamente
        if sessions.should_auto_finalize():
            self._finalize()

        stats = sessions.live_stats()
        elapsed = sessions.elapsed_s()
        self.crono_label.setText(format_lap_time(elapsed) if elapsed is not None else "00:00.000")

        if not stats["running"]:
            return

        if sessions.has_started:
            self.session_status.setText(f"{stats['mode']} EN CURSO — ESPACIO = vuelta manual")

        self.last_label.setText(format_lap_time(stats["last_s"]))
        self.best_label.setText(format_lap_time(stats["best_s"]))
        self.avg_label.setText(format_lap_time(stats["avg_s"]))
        self.fs_label.setText(
            format_lap_time(stats["fs_skidpad_s"]) if stats["fs_skidpad_s"] is not None else "--:--.---"
        )

        times = stats["laps"]
        best = min(times) if times else None
        self.laps_table.setRowCount(len(times))
        for idx, lap_time in enumerate(times):
            delta = lap_time - best if best is not None else 0.0
            state = "BEST" if abs(delta) < 1e-9 else ("LAST" if idx == len(times) - 1 else "")
            cells = [
                str(idx + 1),
                format_lap_time(lap_time),
                f"+{delta:.3f}s" if delta > 0 else "0.000s",
                state,
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if state == "BEST":
                    item.setForeground(QColor(thm.theme()["good"]))
                    if col == 1:
                        item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                self.laps_table.setItem(idx, col, item)

    def apply_theme(self) -> None:
        if not self.ctx.sessions.is_running:
            self.start_stop_btn.setStyleSheet(thm.action_button_style("#1b7a4a"))
