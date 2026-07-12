"""Señales: lista con buscador; cada señal activa = tarjeta + gráfica en fila."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from .. import theme as thm
from ..widgets import MetricCard, SignalPlot
from .offline import WINDOW_PRESETS

# Umbrales de edad del dato, mismos que la página Bus CAN
_AGE_GOOD_S = 2.0
_AGE_STALE_S = 10.0


class SignalListCard(QFrame):
    """Tarjeta compacta y clicable de la lista de señales.

    Muestra nombre, valor en vivo y unidad. El borde indica la edad del
    último dato (verde/ámbar/rojo, gris sin datos) y el fondo marca si la
    señal está seleccionada. Click en cualquier punto alterna la selección.
    """

    toggled = Signal(str, bool)

    def __init__(self, key: str, unit: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.selected = False
        self._border_key = "border"
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.name_label = QLabel(key)
        layout.addWidget(self.name_label)
        layout.addStretch()
        self.value_label = QLabel("--")
        layout.addWidget(self.value_label)
        self.unit_label = QLabel(unit)
        layout.addWidget(self.unit_label)

        self.apply_theme()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
        super().mousePressEvent(event)

    def toggle(self) -> None:
        self.set_selected(not self.selected)
        self.toggled.emit(self.key, self.selected)

    def set_selected(self, selected: bool) -> None:
        if selected != self.selected:
            self.selected = selected
            self.apply_theme()

    def update_value(self, value: float | None, age_s: float | None) -> None:
        if value is None:
            text = "--"
        elif abs(value) < 10_000:
            text = f"{value:.1f}"
        else:
            text = f"{value:.0f}"
        if text != self.value_label.text():
            self.value_label.setText(text)

        if age_s is None:
            border_key = "border"
        elif age_s < _AGE_GOOD_S:
            border_key = "good"
        elif age_s < _AGE_STALE_S:
            border_key = "stale"
        else:
            border_key = "danger"
        if border_key != self._border_key:
            self._border_key = border_key
            self.apply_theme()

    def apply_theme(self) -> None:
        t = thm.theme()
        bg = t["selection"] if self.selected else t["card"]
        self.setStyleSheet(
            f"SignalListCard {{ background-color: {bg}; border: 1px solid {t[self._border_key]}; }}"
        )
        common = "background: transparent; border: none;"
        self.name_label.setStyleSheet(f"color: {t['text']}; font-size: 9pt; font-weight: 600; {common}")
        self.value_label.setStyleSheet(f"color: {t['text']}; font-size: 9pt; font-weight: 800; {common}")
        self.unit_label.setStyleSheet(f"color: {t['muted']}; font-size: 8pt; {common}")


class SenalesPage(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._catalog = {info.key: info for info in ctx.decoder.signal_catalog()}
        self._color_index = 0
        self._colors: dict[str, str] = {}
        self._window_s: float | None = 15.0  # ventana deslizante; None = todo

        # fila activa por señal: (row_widget, card, plot)
        self.rows: dict[str, tuple[QWidget, MetricCard, SignalPlot]] = {}
        self.cards: dict[str, SignalListCard] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        # --- Panel izquierdo: buscador + checkboxes ---
        left = QGroupBox("SEÑALES")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("BUSCAR SEÑAL...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        left_layout.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        list_container = QWidget()
        self._list_layout = QVBoxLayout(list_container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(2)

        for key in sorted(self._catalog):
            card = SignalListCard(key, self._catalog[key].unit)
            card.toggled.connect(self.toggle_signal)
            self._list_layout.addWidget(card)
            self.cards[key] = card
        self._list_layout.addStretch()

        scroll.setWidget(list_container)
        left_layout.addWidget(scroll)
        splitter.addWidget(left)

        # --- Panel derecho: filas [tarjeta | gráfica] ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Ventana temporal visible, mismos presets que Offline
        window_row = QHBoxLayout()
        window_label = QLabel("VENTANA:")
        window_label.setProperty("class", "muted")
        window_row.addWidget(window_label)

        self.window_selector = QComboBox()
        for label, seconds in WINDOW_PRESETS:
            self.window_selector.addItem(label.removeprefix("VENTANA: "), seconds)
        self.window_selector.setCurrentIndex(1)  # 15 s, la ventana por defecto
        self.window_selector.activated.connect(self._on_window_changed)
        window_row.addWidget(self.window_selector)
        window_row.addStretch()
        right_layout.addLayout(window_row)

        self.hint = QLabel("MARCA UNA SEÑAL PARA VERLA EN VIVO")
        self.hint.setProperty("class", "hint")
        right_layout.addWidget(self.hint)

        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_container = QWidget()
        self._rows_layout = QVBoxLayout(rows_container)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch()
        rows_scroll.setWidget(rows_container)
        right_layout.addWidget(rows_scroll)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([260, 1000])

    def _color_for(self, key: str) -> str:
        if key not in self._colors:
            self._colors[key] = thm.GRAPH_COLORS[self._color_index % len(thm.GRAPH_COLORS)]
            self._color_index += 1
        return self._colors[key]

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for key, card in self.cards.items():
            card.setVisible(needle in key.lower())

    def toggle_signal(self, key: str, checked: bool) -> None:
        if checked and key not in self.rows:
            info = self._catalog[key]
            color = self._color_for(key)

            card = MetricCard(title=info.label, unit=info.unit, color=color)
            card.setFixedWidth(150)
            plot = SignalPlot(
                [(key, info.label, color)], unit=info.unit, y_range=info.y_range,
                sliding_s=self._window_s,
            )

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            row_layout.addWidget(card)
            row_layout.addWidget(plot, 1)

            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
            self.rows[key] = (row, card, plot)

        elif not checked and key in self.rows:
            row, _card, _plot = self.rows.pop(key)
            self._rows_layout.removeWidget(row)
            row.deleteLater()

        self._relink_axes()
        self.hint.setVisible(not self.rows)

    def _relink_axes(self) -> None:
        anchor = None
        for _row, _card, plot in self.rows.values():
            if anchor is None:
                anchor = plot
                plot.plot_widget.setXLink(None)
            else:
                plot.plot_widget.setXLink(anchor.plot_widget)

    def _on_window_changed(self, index: int) -> None:
        self._window_s = self.window_selector.itemData(index)
        for _row, _card, plot in self.rows.values():
            plot.sliding_s = self._window_s
        if self._window_s is None:
            self._show_all_data()

    def _show_all_data(self) -> None:
        """Ajusta el eje X al rango completo de todas las señales activas."""
        bounds = [
            b for _row, _card, plot in self.rows.values()
            if (b := plot.data_bounds()) is not None
        ]
        if not bounds:
            return
        x0 = min(b[0] for b in bounds)
        x1 = max(b[1] for b in bounds)
        # Basta con fijar una gráfica: los ejes X están enlazados
        first_plot = next(iter(self.rows.values()))[2]
        first_plot.plot_widget.setXRange(x0, x1, padding=0.02)

    def refresh(self) -> None:
        now_s = self.ctx.now_us() / 1_000_000.0
        for key, list_card in self.cards.items():
            latest = self.ctx.datastore.latest(key)
            if latest is None:
                list_card.update_value(None, None)
            else:
                list_card.update_value(latest[1], max(0.0, now_s - latest[0]))

        for key, (_row, card, plot) in self.rows.items():
            latest = self.ctx.datastore.latest(key)
            card.set_value(latest[1] if latest else None)
            plot.refresh(self.ctx.datastore)
        if self._window_s is None and self.rows:
            self._show_all_data()

    def apply_theme(self) -> None:
        for card in self.cards.values():
            card.apply_theme()
        for _row, _card, plot in self.rows.values():
            plot.apply_theme()
