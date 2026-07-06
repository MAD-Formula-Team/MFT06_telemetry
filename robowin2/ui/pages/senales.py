"""Señales: lista con buscador; cada señal activa = tarjeta + gráfica en fila."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from .. import theme as thm
from ..widgets import MetricCard, SignalPlot


class SenalesPage(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._catalog = {info.key: info for info in ctx.decoder.signal_catalog()}
        self._color_index = 0
        self._colors: dict[str, str] = {}

        # fila activa por señal: (row_widget, card, plot)
        self.rows: dict[str, tuple[QWidget, MetricCard, SignalPlot]] = {}
        self.checkboxes: dict[str, QCheckBox] = {}

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
            chk = QCheckBox(key)
            chk.toggled.connect(lambda checked, k=key: self.toggle_signal(k, checked))
            self._list_layout.addWidget(chk)
            self.checkboxes[key] = chk
        self._list_layout.addStretch()

        scroll.setWidget(list_container)
        left_layout.addWidget(scroll)
        splitter.addWidget(left)

        # --- Panel derecho: filas [tarjeta | gráfica] ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

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
        for key, chk in self.checkboxes.items():
            chk.setVisible(needle in key.lower())

    def toggle_signal(self, key: str, checked: bool) -> None:
        if checked and key not in self.rows:
            info = self._catalog[key]
            color = self._color_for(key)

            card = MetricCard(title=info.label, unit=info.unit, color=color)
            card.setFixedWidth(150)
            plot = SignalPlot([(key, info.label, color)], unit=info.unit, y_range=info.y_range)

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

    def refresh(self) -> None:
        for key, (_row, card, plot) in self.rows.items():
            latest = self.ctx.datastore.latest(key)
            card.set_value(latest[1] if latest else None)
            plot.refresh(self.ctx.datastore)

    def apply_theme(self) -> None:
        for _row, _card, plot in self.rows.values():
            plot.apply_theme()
