"""Análisis offline: abrir .db propios o CSV de ROBOWIN 1, vincular
vueltas con telemetría y exportar CSV compatible.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from robowin2.core.lapstore import format_lap_time
from robowin2.io_ import offline as offline_io

from .. import theme as thm
from ..widgets import SignalPlot

# Ventanas temporales predefinidas (etiqueta, segundos); None = todo el rango
WINDOW_PRESETS: list[tuple[str, float | None]] = [
    ("VENTANA: TODO", None),
    ("15 s", 15.0),
    ("30 s", 30.0),
    ("1 min", 60.0),
    ("3 min", 180.0),
    ("5 min", 300.0),
    ("10 min", 600.0),
]


def parse_window_text(text: str) -> float | None:
    """'45' -> 45 s; '3:15' -> 195 s; '1:05:00' -> 3900 s. None si no parsea."""
    parts = text.strip().split(":")
    if not text.strip() or len(parts) > 3:
        return None
    try:
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60.0 + float(part)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


class OfflinePage(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.dataset: offline_io.OfflineDataset | None = None
        self.plots: dict[str, SignalPlot] = {}
        self.checkboxes: dict[str, QCheckBox] = {}
        self._color_index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Barra de acciones ---
        toolbar = QHBoxLayout()
        open_db_btn = QPushButton("ABRIR .DB")
        open_db_btn.setStyleSheet(thm.action_button_style("#1c93d8"))
        open_db_btn.clicked.connect(self._open_db)
        toolbar.addWidget(open_db_btn)

        open_csv_btn = QPushButton("IMPORTAR CSV")
        open_csv_btn.setToolTip("CSV combinado de ROBOWIN 1 o CSV del data logger (detección automática)")
        open_csv_btn.setStyleSheet(thm.action_button_style("#1c93d8"))
        open_csv_btn.clicked.connect(self._open_csv)
        toolbar.addWidget(open_csv_btn)

        export_btn = QPushButton("EXPORTAR CSV")
        export_btn.setStyleSheet(thm.action_button_style("#ff4f00"))
        export_btn.clicked.connect(self._export_csv)
        toolbar.addWidget(export_btn)

        self.dataset_label = QLabel("SIN DATOS CARGADOS")
        self.dataset_label.setProperty("class", "chip")
        toolbar.addWidget(self.dataset_label, 1)
        layout.addLayout(toolbar)

        # --- Ventana temporal + popup ---
        window_row = QHBoxLayout()
        window_label = QLabel("VENTANA:")
        window_label.setProperty("class", "muted")
        window_row.addWidget(window_label)

        self.window_selector = QComboBox()
        for label, seconds in WINDOW_PRESETS:
            self.window_selector.addItem(label, seconds)
        self.window_selector.activated.connect(self._on_window_preset)
        window_row.addWidget(self.window_selector)

        self.window_custom = QLineEdit()
        self.window_custom.setPlaceholderText("PERSONALIZADA: mm:ss (ej. 3:15)")
        self.window_custom.setMaximumWidth(220)
        self.window_custom.returnPressed.connect(self._apply_custom_window)
        window_row.addWidget(self.window_custom)

        apply_window_btn = QPushButton("APLICAR")
        apply_window_btn.setStyleSheet(thm.tool_button_style())
        apply_window_btn.clicked.connect(self._apply_custom_window)
        window_row.addWidget(apply_window_btn)

        self.popup_btn = QPushButton("POPUP ON")
        self.popup_btn.setStyleSheet(thm.tool_button_style())
        self.popup_btn.setToolTip("Popup con los valores de todas las señales bajo el cursor")
        self.popup_btn.clicked.connect(self._toggle_popup)
        window_row.addWidget(self.popup_btn)
        window_row.addStretch()
        layout.addLayout(window_row)

        # Popup flotante de valores (sigue al cursor sobre las gráficas)
        self.popup_enabled = True
        self.value_popup = QLabel(self)
        self.value_popup.setProperty("class", "value-popup")
        self.value_popup.setVisible(False)
        self.value_popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # --- Contenido ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        signals_group = QGroupBox("SEÑALES")
        signals_layout = QVBoxLayout(signals_group)
        self.search = QLineEdit()
        self.search.setPlaceholderText("BUSCAR SEÑAL...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        signals_layout.addWidget(self.search)

        signals_scroll = QScrollArea()
        signals_scroll.setWidgetResizable(True)
        self._signals_container = QWidget()
        self._signals_layout = QVBoxLayout(self._signals_container)
        self._signals_layout.setContentsMargins(4, 4, 4, 4)
        self._signals_layout.setSpacing(2)
        self._signals_layout.addStretch()
        signals_scroll.setWidget(self._signals_container)
        signals_layout.addWidget(signals_scroll)
        left_layout.addWidget(signals_group, 1)

        laps_group = QGroupBox("VUELTAS")
        laps_layout = QVBoxLayout(laps_group)
        self.laps_table = QTableWidget(0, 4)
        self.laps_table.setHorizontalHeaderLabels(["V", "TIEMPO", "SESION", "MODO"])
        self.laps_table.verticalHeader().setVisible(False)
        self.laps_table.setAlternatingRowColors(True)
        self.laps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.laps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.laps_table.currentCellChanged.connect(self._on_lap_selected)
        header = self.laps_table.horizontalHeader()
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        laps_layout.addWidget(self.laps_table)

        self.lap_hint = QLabel("SELECCIONA UNA VUELTA PARA ENFOCAR LA TELEMETRIA")
        self.lap_hint.setProperty("class", "hint")
        self.lap_hint.setWordWrap(True)
        laps_layout.addWidget(self.lap_hint)

        # Comparador A/B (como en ROBOWIN 1)
        compare_row = QHBoxLayout()
        compare_row.setSpacing(4)
        self.compare_a = QComboBox()
        self.compare_a.setToolTip("Vuelta A (roja)")
        compare_row.addWidget(self.compare_a, 1)
        self.compare_b = QComboBox()
        self.compare_b.setToolTip("Vuelta B (azul)")
        compare_row.addWidget(self.compare_b, 1)
        compare_btn = QPushButton("COMPARAR")
        compare_btn.setStyleSheet(thm.action_button_style("#455a64"))
        compare_btn.clicked.connect(self._compare_laps)
        compare_row.addWidget(compare_btn)
        laps_layout.addLayout(compare_row)
        left_layout.addWidget(laps_group, 1)

        splitter.addWidget(left)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        plots_container = QWidget()
        self._plots_layout = QVBoxLayout(plots_container)
        self._plots_layout.setContentsMargins(4, 4, 4, 4)
        self._plots_layout.setSpacing(8)
        self._plots_layout.addStretch()
        right_scroll.setWidget(plots_container)
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([320, 1000])
        layout.addWidget(splitter, 1)

    # --- carga de datos ---

    def _open_db(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Abrir log ROBOWIN", "", "Logs (*.db);;Todos (*)")
        if not filename:
            return
        try:
            dataset = offline_io.load_db(filename, self.ctx.decoder)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el log:\n{exc}")
            return
        self.load_dataset(dataset)

    def _open_csv(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Importar CSV (ROBOWIN 1 o data logger)", "", "CSV (*.csv);;Todos (*)"
        )
        if not filename:
            return
        try:
            dataset = offline_io.load_csv_auto(filename)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo importar el CSV:\n{exc}")
            return
        self.load_dataset(dataset)

    def _export_csv(self) -> None:
        if self.dataset is None:
            QMessageBox.information(self, "Exportar", "Carga primero un dataset.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Exportar CSV combinado", "", "CSV (*.csv)")
        if not filename:
            return
        try:
            rows = offline_io.export_csv(self.dataset, filename)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Fallo exportando:\n{exc}")
            return
        QMessageBox.information(self, "Exportar", f"Exportadas {rows} filas.")

    def load_dataset(self, dataset: offline_io.OfflineDataset) -> None:
        """Puebla la página con un dataset (también usado por los tests)."""
        self.dataset = dataset
        self.dataset_label.setText(
            f"{dataset.description} | {len(dataset.signal_keys)} señales | {len(dataset.laps)} vueltas"
        )

        # Reset de señales y gráficas
        for chk in self.checkboxes.values():
            chk.deleteLater()
        self.checkboxes.clear()
        for plot in self.plots.values():
            plot.deleteLater()
        self.plots.clear()
        self._color_index = 0

        for key in dataset.signal_keys:
            chk = QCheckBox(key)
            chk.toggled.connect(lambda checked, k=key: self._toggle_signal(k, checked))
            self._signals_layout.insertWidget(self._signals_layout.count() - 1, chk)
            self.checkboxes[key] = chk
        self._apply_filter(self.search.text())

        # Vueltas
        self.laps_table.blockSignals(True)
        self.laps_table.setRowCount(len(dataset.laps))
        for row, lap in enumerate(dataset.laps):
            cells = [str(lap.number), format_lap_time(lap.lap_time_s), lap.session_name, lap.session_mode]
            for col, value in enumerate(cells):
                self.laps_table.setItem(row, col, QTableWidgetItem(value))
        self.laps_table.blockSignals(False)

        # Selectores del comparador A/B (índice del dataset como data:
        # los números de vuelta pueden repetirse entre sesiones)
        for combo in (self.compare_a, self.compare_b):
            combo.blockSignals(True)
            combo.clear()
            for idx, lap in enumerate(dataset.laps):
                label = f"V{lap.number}" + (f" · {lap.session_name}" if lap.session_name else "")
                combo.addItem(label, idx)
            combo.blockSignals(False)
        if len(dataset.laps) > 1:
            self.compare_b.setCurrentIndex(len(dataset.laps) - 1)
        self.lap_hint.setText("SELECCIONA UNA VUELTA PARA ENFOCAR LA TELEMETRIA")

        # Auto-activar hasta 3 señales con datos
        for key in dataset.signal_keys:
            if len(self.plots) >= 3:
                break
            _t, v = dataset.datastore.snapshot(key)
            if len(v) and (v != 0).any():
                self.checkboxes[key].setChecked(True)

    # --- señales y vueltas ---

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for key, chk in self.checkboxes.items():
            chk.setVisible(needle in key.lower())

    def _toggle_signal(self, key: str, checked: bool) -> None:
        if checked and key not in self.plots and self.dataset is not None:
            color = thm.GRAPH_COLORS[self._color_index % len(thm.GRAPH_COLORS)]
            self._color_index += 1
            plot = SignalPlot([(key, key.replace("_", " ").upper(), color)], sliding_s=None)
            plot.refresh(self.dataset.datastore)
            plot.crosshair_moved.connect(lambda x, sender=plot: self._on_crosshair(x, sender))
            plot.crosshair_left.connect(self._on_crosshair_left)
            self._plots_layout.insertWidget(self._plots_layout.count() - 1, plot)
            self.plots[key] = plot
        elif not checked and key in self.plots:
            plot = self.plots.pop(key)
            self._plots_layout.removeWidget(plot)
            plot.deleteLater()
        self._relink_axes()

    def _relink_axes(self) -> None:
        anchor = None
        for plot in self.plots.values():
            if anchor is None:
                anchor = plot
                plot.plot_widget.setXLink(None)
            else:
                plot.plot_widget.setXLink(anchor.plot_widget)

    def _compare_laps(self) -> None:
        if self.dataset is None:
            return
        idx_a = self.compare_a.currentData()
        idx_b = self.compare_b.currentData()
        if idx_a is None or idx_b is None:
            return
        lap_a = self.dataset.laps[idx_a]
        lap_b = self.dataset.laps[idx_b]
        for plot in self.plots.values():
            plot.show_compare_regions(
                (lap_a.t_start_s, lap_a.t_end_s), (lap_b.t_start_s, lap_b.t_end_s)
            )
        delta = lap_b.lap_time_s - lap_a.lap_time_s
        sign = "+" if delta >= 0 else "-"
        color_a, color_b = SignalPlot.COMPARE_COLORS
        self.lap_hint.setText(
            f"COMPARANDO <span style='color:{color_a};'><b>V{lap_a.number}</b></span>"
            f" vs <span style='color:{color_b};'><b>V{lap_b.number}</b></span>: "
            f"{format_lap_time(lap_a.lap_time_s)} vs {format_lap_time(lap_b.lap_time_s)}"
            f" | Δ={sign}{abs(delta):.3f}s"
        )

    def _on_lap_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        if self.dataset is None or not (0 <= row < len(self.dataset.laps)):
            return
        lap = self.dataset.laps[row]
        for plot in self.plots.values():
            plot.show_lap_region(lap.t_start_s, lap.t_end_s)
        self.lap_hint.setText(
            f"VUELTA {lap.number}: {format_lap_time(lap.lap_time_s)}"
            + (f" | {lap.session_name}" if lap.session_name else "")
        )

    # --- crosshair + popup ---

    def _toggle_popup(self) -> None:
        self.popup_enabled = not self.popup_enabled
        self.popup_btn.setText("POPUP ON" if self.popup_enabled else "POPUP OFF")
        if not self.popup_enabled:
            self.value_popup.setVisible(False)

    def _on_crosshair(self, x: float, sender: SignalPlot | None) -> None:
        # Sincronizar el crosshair en el resto de gráficas
        for plot in self.plots.values():
            if plot is not sender:
                plot.set_crosshair(x)

        if not self.popup_enabled or not self.plots:
            return

        lines = [f"TIEMPO: {x:.2f}s", "=" * 24]
        for key in sorted(self.plots):
            values = self.plots[key].values_at(x)
            for series_key, value in values.items():
                lines.append(f"{series_key}: {value:.2f}")
        if len(lines) <= 2:
            return

        self.value_popup.setText("\n".join(lines))
        self.value_popup.adjustSize()
        cursor = self.mapFromGlobal(QCursor.pos())
        popup_x = min(cursor.x() + 20, max(0, self.width() - self.value_popup.width() - 10))
        popup_y = max(cursor.y() - self.value_popup.height() - 20, 10)
        self.value_popup.move(popup_x, popup_y)
        self.value_popup.setVisible(True)
        self.value_popup.raise_()

    def _on_crosshair_left(self) -> None:
        self.value_popup.setVisible(False)
        for plot in self.plots.values():
            plot.hide_crosshair()

    # --- ventana temporal ---

    def _on_window_preset(self, index: int) -> None:
        self._apply_window(self.window_selector.itemData(index))

    def _apply_custom_window(self) -> None:
        seconds = parse_window_text(self.window_custom.text())
        if seconds is None:
            QMessageBox.information(
                self, "Ventana", "Formato no válido. Ejemplos: 45, 3:15, 1:05:00"
            )
            return
        self._apply_window(seconds)

    def _apply_window(self, seconds: float | None) -> None:
        """Aplica una ventana temporal a todas las gráficas (None = todo).

        Mantiene el borde izquierdo actual de la vista, de modo que se puede
        elegir la anchura y luego desplazarse arrastrando.
        """
        if not self.plots:
            return
        anchor = next(iter(self.plots.values()))
        if seconds is None:
            for plot in self.plots.values():
                plot.show_full_range()
            return

        bounds = anchor.data_bounds()
        start = anchor.view_x_range()[0]
        if bounds is not None:
            start = min(max(start, bounds[0]), max(bounds[0], bounds[1] - seconds))
        for plot in self.plots.values():
            plot.set_x_window(start, seconds)

    # --- interfaz de página ---

    def refresh(self) -> None:
        pass  # datos estáticos: se dibujan al cargar/seleccionar

    def apply_theme(self) -> None:
        for plot in self.plots.values():
            plot.apply_theme()
