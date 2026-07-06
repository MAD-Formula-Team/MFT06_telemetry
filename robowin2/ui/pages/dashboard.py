"""Dashboard: variables críticas con umbrales + temperaturas combinadas + RPM."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QVBoxLayout, QWidget

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

        # --- Columna izquierda: tarjetas críticas ---
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

        # --- Columna derecha: gráficas ---
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
        for key, card in self.cards.items():
            latest = self.ctx.datastore.latest(key)
            if latest is None:
                card.set_value(None)
            else:
                _t, value = latest
                card.set_value(value, color=threshold_color(key, value))
        for plot in self.plots:
            plot.refresh(self.ctx.datastore)

    def apply_theme(self) -> None:
        for plot in self.plots:
            plot.apply_theme()
