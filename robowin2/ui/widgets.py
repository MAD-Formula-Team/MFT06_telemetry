"""Widgets reutilizables: eje mm:ss, tarjeta de métrica y gráfica de señales."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

import pyqtgraph as pg

from . import theme as thm


class TimeAxisItem(pg.AxisItem):
    """Eje X en formato mm:ss (décimas con zoom fino)."""

    def tickStrings(self, values, scale, spacing):
        strings = []
        for value in values:
            if value < 0:
                strings.append("")
                continue
            if spacing < 1.0:
                total_ds = int(round(value * 10))
                strings.append(f"{total_ds // 600:02d}:{(total_ds % 600) / 10.0:04.1f}")
            else:
                total_s = int(round(value))
                strings.append(f"{total_s // 60:02d}:{total_s % 60:02d}")
        return strings


class MetricCard(QFrame):
    """Tarjeta de valor en vivo (título, valor grande, unidad)."""

    def __init__(self, title: str, unit: str, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.base_color = color
        self.setProperty("class", "metric-card")
        self.setStyleSheet(f'QFrame[class="metric-card"] {{ border: 1px solid {color}; }}')
        self.setMinimumSize(120, 96)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setProperty("class", "card-title")
        layout.addWidget(title_label)

        self.value_label = QLabel("--")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet(thm.metric_value_style(color))
        layout.addWidget(self.value_label, 1)

        unit_label = QLabel(unit)
        unit_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        unit_label.setProperty("class", "muted-small")
        layout.addWidget(unit_label)

    def set_value(self, value: float | None, color: str | None = None) -> None:
        if value is None:
            self.value_label.setText("--")
            self.value_label.setStyleSheet(thm.metric_value_style(self.base_color))
            return
        self.value_label.setText(f"{value:.1f}" if abs(value) < 10_000 else f"{value:.0f}")
        self.value_label.setStyleSheet(thm.metric_value_style(color or self.base_color))


class SignalPlot(QWidget):
    """Gráfica multi-serie alimentada por snapshots del DataStore.

    - El eje Y se autoajusta SOLO a los datos visibles: al hacer zoom en X
      se ve siempre la imagen completa del tramo (setAutoVisibleOnly).
    - Zoom/pan de ratón solo en X (el Y lo gestiona el autoajuste).
    - Crosshair con lectura de valores bajo el cursor; emite crosshair_moved
      para que la página sincronice las demás gráficas y el popup.
    """

    crosshair_moved = Signal(float)
    crosshair_left = Signal()

    def __init__(
        self,
        series: list[tuple[str, str, str]],
        unit: str = "",
        y_range: tuple[float, float] | None = None,
        sliding_s: float | None = 15.0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.series = series
        self.unit_suffix = f" {unit}" if unit else ""
        self.y_range = y_range
        self.sliding_s = sliding_s
        self._series_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._latest: dict[str, float] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 10pt; font-weight: 600; padding: 1px;")
        layout.addWidget(self.title_label)

        self.plot_widget = pg.PlotWidget(axisItems={"bottom": TimeAxisItem(orientation="bottom")})
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setDownsampling(mode="peak")
        self.plot_widget.setClipToView(True)
        self.plot_widget.setMinimumHeight(140)
        self.plot_widget.setLabel("bottom", "Tiempo (mm:ss)")

        viewbox = self.plot_widget.getViewBox()
        viewbox.setMouseEnabled(x=True, y=False)
        if y_range is not None:
            self.plot_widget.setYRange(y_range[0], y_range[1], padding=0)
        else:
            viewbox.enableAutoRange(y=True)
            viewbox.setAutoVisible(y=True)  # Y se ajusta SOLO a los datos visibles en X

        self.curves = {}
        for key, _label, color in series:
            self.curves[key] = self.plot_widget.plot(pen=pg.mkPen(color=color, width=3))

        # Crosshair
        self._vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(thm.theme()["accent"], width=1.5, style=Qt.PenStyle.DashLine),
        )
        self._vline.setVisible(False)
        self.plot_widget.addItem(self._vline)
        self._proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved
        )
        self.plot_widget.leaveEvent = self._on_mouse_leave  # type: ignore[assignment]

        layout.addWidget(self.plot_widget)
        self.apply_theme()
        self._set_title({})

    # --- título ---

    def _set_title(self, values: dict[str, float], at_time: float | None = None) -> None:
        parts = []
        for key, label, color in self.series:
            value_text = f"{values[key]:.1f}{self.unit_suffix}" if key in values else "---"
            parts.append(f"<span style='color:{color};'><b>{label}</b>: {value_text}</span>")
        title = " | ".join(parts)
        if at_time is not None:
            title += f" @ {at_time:.2f}s"
        self.title_label.setText(title)

    # --- datos ---

    def refresh(self, datastore) -> None:
        latest: dict[str, float] = {}
        newest_t: float | None = None
        for key, _label, _color in self.series:
            t, v = datastore.snapshot(key)
            if len(t) == 0:
                continue
            self.curves[key].setData(t, v)
            self._series_cache[key] = (t, v)
            latest[key] = float(v[-1])
            if newest_t is None or t[-1] > newest_t:
                newest_t = float(t[-1])

        self._latest = latest
        self._set_title(latest)
        if newest_t is not None and self.sliding_s is not None:
            self.plot_widget.setXRange(max(0.0, newest_t - self.sliding_s), newest_t, padding=0)

    def values_at(self, x: float) -> dict[str, float]:
        """Valor de cada serie en el timestamp más cercano a x."""
        values: dict[str, float] = {}
        for key, _label, _color in self.series:
            cached = self._series_cache.get(key)
            if cached is None or len(cached[0]) == 0:
                continue
            t, v = cached
            idx = int(np.searchsorted(t, x))
            if idx >= len(t):
                idx = len(t) - 1
            elif idx > 0 and abs(t[idx - 1] - x) < abs(t[idx] - x):
                idx -= 1
            values[key] = float(v[idx])
        return values

    def data_bounds(self) -> tuple[float, float] | None:
        """(t_min, t_max) de los datos cargados."""
        bounds = [
            (t[0], t[-1]) for t, _v in self._series_cache.values() if len(t)
        ]
        if not bounds:
            return None
        return min(b[0] for b in bounds), max(b[1] for b in bounds)

    # --- crosshair ---

    def _on_mouse_moved(self, evt) -> None:
        pos = evt[0]
        if not self.plot_widget.sceneBoundingRect().contains(pos):
            return
        x = self.plot_widget.getViewBox().mapSceneToView(pos).x()
        self.set_crosshair(x)
        self.crosshair_moved.emit(x)

    def _on_mouse_leave(self, _event) -> None:
        self.hide_crosshair()
        self.crosshair_left.emit()

    def set_crosshair(self, x: float) -> None:
        self._vline.setPos(x)
        self._vline.setVisible(True)
        values = self.values_at(x)
        if values:
            self._set_title(values, at_time=x)

    def hide_crosshair(self) -> None:
        self._vline.setVisible(False)
        self._set_title(self._latest)

    # --- ventana temporal ---

    def set_x_window(self, start_s: float, duration_s: float) -> None:
        self.plot_widget.setXRange(start_s, start_s + duration_s, padding=0)

    def show_full_range(self) -> None:
        bounds = self.data_bounds()
        if bounds is not None:
            self.plot_widget.setXRange(bounds[0], bounds[1], padding=0.02)

    def view_x_range(self) -> tuple[float, float]:
        (x0, x1), _y = self.plot_widget.getViewBox().viewRange()
        return float(x0), float(x1)

    def show_lap_region(self, t0: float, t1: float) -> None:
        """Resalta el rango de una vuelta y enfoca la vista en él."""
        self._hide_compare_regions()
        if getattr(self, "_lap_region", None) is None:
            self._lap_region = pg.LinearRegionItem(movable=False, brush=pg.mkBrush(255, 79, 0, 45))
            self._lap_region.setZValue(-10)
            self.plot_widget.addItem(self._lap_region)
        self._lap_region.setRegion([t0, t1])
        self._lap_region.setVisible(True)
        pad = max(0.5, (t1 - t0) * 0.1)
        self.plot_widget.setXRange(t0 - pad, t1 + pad, padding=0)

    # Colores del comparador A/B (mismos que ROBOWIN 1: rojo vs azul)
    COMPARE_COLORS = ("#ff6b6b", "#4dabf7")

    def show_compare_regions(self, a: tuple[float, float], b: tuple[float, float]) -> None:
        """Resalta dos vueltas (A roja, B azul) y abarca ambas en la vista."""
        if getattr(self, "_lap_region", None) is not None:
            self._lap_region.setVisible(False)
        if getattr(self, "_compare_regions", None) is None:
            self._compare_regions = []
            for color in self.COMPARE_COLORS:
                region = pg.LinearRegionItem(movable=False, brush=pg.mkBrush(color + "2d"))
                region.setZValue(-10)
                self.plot_widget.addItem(region)
                self._compare_regions.append(region)
        for region, (t0, t1) in zip(self._compare_regions, (a, b)):
            region.setRegion([t0, t1])
            region.setVisible(True)
        lo = min(a[0], b[0])
        hi = max(a[1], b[1])
        pad = max(0.5, (hi - lo) * 0.05)
        self.plot_widget.setXRange(lo - pad, hi + pad, padding=0)

    def _hide_compare_regions(self) -> None:
        for region in getattr(self, "_compare_regions", None) or []:
            region.setVisible(False)

    def apply_theme(self) -> None:
        t = thm.theme()
        self.plot_widget.setBackground(t["plot_bg"])
        for axis_name in ("bottom", "left"):
            axis = self.plot_widget.getAxis(axis_name)
            axis.setPen(pg.mkPen(t["axis"]))
            axis.setTextPen(pg.mkPen(t["axis"]))
        self._vline.setPen(pg.mkPen(t["accent"], width=1.5, style=Qt.PenStyle.DashLine))
