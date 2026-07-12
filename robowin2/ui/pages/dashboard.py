"""Dashboard: laptime en vivo + variables críticas con umbrales + temperaturas y RPM."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from robowin2.core.lapstore import format_lap_time

from .. import theme as thm
from ..widgets import MetricCard, SignalPlot

# Umbrales de aviso. direction 'above': peligroso al superar (temperaturas);
# 'below': peligroso al caer (tensión de batería).
THRESHOLDS = {
    "ect": {"direction": "above", "warn": 100.0, "danger": 110.0},
    "oil_temp": {"direction": "above", "warn": 120.0, "danger": 135.0},
    "batt_volt": {"direction": "below", "warn": 12.2, "danger": 11.8},
}

CRITICAL_KEYS = ["ect", "oil_temp", "batt_volt"]


def threshold_color(key: str, value: float) -> str | None:
    rule = THRESHOLDS.get(key)
    if rule is None:
        return None
    t = thm.theme()
    if rule["direction"] == "below":
        if value <= rule["danger"]:
            return t["danger"]
        if value <= rule["warn"]:
            return t["warn"]
    else:
        if value >= rule["danger"]:
            return t["danger"]
        if value >= rule["warn"]:
            return t["warn"]
    return None


class DashboardPage(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        units = ctx.decoder.units()
        catalog = {info.key: info for info in ctx.decoder.signal_catalog()}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Columna 1: laptime en vivo (como en ROBOWIN 1) ---
        laptime_group = QGroupBox("LAPTIME")
        laptime_layout = QVBoxLayout(laptime_group)
        laptime_layout.setContentsMargins(8, 8, 8, 8)
        laptime_layout.setSpacing(8)

        self.session_mode_label = QLabel("SESION ACTUAL: --")
        self.session_mode_label.setProperty("class", "accent-title")
        laptime_layout.addWidget(self.session_mode_label)

        self.session_state_label = QLabel("ESTADO: LISTO")
        self.session_state_label.setProperty("class", "chip")
        laptime_layout.addWidget(self.session_state_label)

        self.total_time_label = QLabel("00:00.000")
        self.total_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_time_label.setProperty("class", "timer-big")
        laptime_layout.addWidget(self.total_time_label)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(6)
        self.laps_count_label = QLabel("VUELTAS: 0")
        self.last_lap_label = QLabel("ULTIMA: --:--.---")
        for label in (self.laps_count_label, self.last_lap_label):
            label.setProperty("class", "chip")
            summary_row.addWidget(label)
        laptime_layout.addLayout(summary_row)

        self.laps_table = QTableWidget(0, 4)
        self.laps_table.setHorizontalHeaderLabels(["VUELTA", "TIEMPO", "DELTA", "ESTADO"])
        self.laps_table.verticalHeader().setVisible(False)
        self.laps_table.setAlternatingRowColors(True)
        self.laps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.laps_table.horizontalHeader()
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        laptime_layout.addWidget(self.laps_table, 1)

        layout.addWidget(laptime_group, 1)

        # --- Columna 2: tarjetas críticas ---
        cards_group = QGroupBox("VARIABLES CRITICAS")
        cards_layout = QVBoxLayout(cards_group)
        cards_layout.setContentsMargins(8, 8, 8, 8)
        cards_layout.setSpacing(8)

        self.cards: dict[str, MetricCard] = {}
        for idx, key in enumerate(CRITICAL_KEYS):
            if key not in catalog:
                continue
            card = MetricCard(
                title=catalog[key].label,
                unit=units.get(key, ""),
                color=thm.GRAPH_COLORS[idx % len(thm.GRAPH_COLORS)],
            )
            self.cards[key] = card
            cards_layout.addWidget(card)
        cards_layout.addStretch()
        layout.addWidget(cards_group, 1)

        # --- Columna 3: gráficas ---
        plots_group = QGroupBox("GRAFICAS")
        plots_layout = QVBoxLayout(plots_group)
        plots_layout.setContentsMargins(8, 8, 8, 8)
        plots_layout.setSpacing(8)

        self.plots: list[SignalPlot] = []
        temp_series = [
            (key, catalog[key].label, thm.GRAPH_COLORS[i])
            for i, key in enumerate(["ect", "oil_temp"])
            if key in catalog
        ]
        if temp_series:
            temps_plot = SignalPlot(temp_series, unit=units.get("ect", "C"))
            self.plots.append(temps_plot)
            plots_layout.addWidget(temps_plot)

        if "engine_rpm" in catalog:
            rpm_info = catalog["engine_rpm"]
            rpm_plot = SignalPlot(
                [("engine_rpm", rpm_info.label, thm.GRAPH_COLORS[2])],
                unit=rpm_info.unit,
                y_range=rpm_info.y_range,
            )
            self.plots.append(rpm_plot)
            plots_layout.addWidget(rpm_plot)

        # Zoom/pan sincronizado entre gráficas
        for plot in self.plots[1:]:
            plot.plot_widget.setXLink(self.plots[0].plot_widget)

        plots_layout.addStretch()
        layout.addWidget(plots_group, 3)

    def refresh(self) -> None:
        self._refresh_laptime()
        for key, card in self.cards.items():
            latest = self.ctx.datastore.latest(key)
            if latest is None:
                card.set_value(None)
            else:
                _t, value = latest
                card.set_value(value, color=threshold_color(key, value))
        for plot in self.plots:
            plot.refresh(self.ctx.datastore)

    def _refresh_laptime(self) -> None:
        sessions = self.ctx.sessions
        stats = sessions.live_stats()

        if not stats["running"]:
            self.session_mode_label.setText("SESION ACTUAL: --")
            self.session_state_label.setText("ESTADO: LISTO")
            self.total_time_label.setText("00:00.000")
            self.laps_count_label.setText("VUELTAS: 0")
            self.last_lap_label.setText("ULTIMA: --:--.---")
            self.laps_table.setRowCount(0)
            return

        self.session_mode_label.setText(f"SESION ACTUAL: {stats['mode']}")
        self.session_state_label.setText(
            "ESTADO: EN CURSO — ESPACIO = VUELTA"
            if sessions.has_started
            else "ESTADO: ARMADO — ESPACIO ARRANCA EL CRONO"
        )
        elapsed = sessions.elapsed_s()
        self.total_time_label.setText(format_lap_time(elapsed) if elapsed is not None else "00:00.000")

        times = stats["laps"]
        self.laps_count_label.setText(f"VUELTAS: {len(times)}")
        last = stats["last_s"]
        self.last_lap_label.setText(f"ULTIMA: {format_lap_time(last)}" if last is not None else "ULTIMA: --:--.---")

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
        for plot in self.plots:
            plot.apply_theme()
