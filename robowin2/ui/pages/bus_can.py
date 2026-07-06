"""Bus CAN: análisis en vivo por ID (la página nueva de ROBOWIN 2).

Por ID: nombre DBC (o DESCONOCIDO resaltado), contador, Hz, periodo, jitter,
edad con color de staleness, payload hex con bytes cambiados resaltados y
cuota de ancho de banda. Botón de pausa para inspeccionar sin que se mueva.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

from .. import theme as thm

COLUMNS = ["ID", "NOMBRE", "Hz", "PERIODO", "JITTER", "EDAD", "FRAMES", "% BUS", "DATA"]
_COL_ID, _COL_NAME, _COL_HZ, _COL_PERIOD, _COL_JITTER, _COL_AGE, _COL_COUNT, _COL_BW, _COL_DATA = range(9)


def _data_html(data: bytes, changed_mask: int, accent: str) -> str:
    parts = []
    for i, byte in enumerate(data):
        text = f"{byte:02X}"
        if changed_mask & (1 << i):
            parts.append(f"<b><span style='color:{accent};'>{text}</span></b>")
        else:
            parts.append(text)
    return "<span style='font-family:Consolas,monospace;'>" + " ".join(parts) + "</span>"


class BusCanPage(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.paused = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.pause_btn = QPushButton("PAUSAR")
        self.pause_btn.setStyleSheet(thm.tool_button_style())
        self.pause_btn.setMaximumWidth(110)
        self.pause_btn.clicked.connect(self._toggle_pause)
        controls.addWidget(self.pause_btn)

        self.summary = QLabel("SIN TRAFICO")
        self.summary.setProperty("class", "muted")
        controls.addWidget(self.summary)
        controls.addStretch()
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        for col in range(len(COLUMNS) - 1):
            header.setSectionResizeMode(col, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_DATA, header.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_btn.setText("REANUDAR" if self.paused else "PAUSAR")

    def refresh(self) -> None:
        if self.paused:
            return

        t = thm.theme()
        views = self.ctx.bus_stats.snapshot(now_us=self.ctx.now_us())
        total_hz = sum(v.freq_hz for v in views)
        self.summary.setText(
            f"{len(views)} IDs | {total_hz:.1f} frames/s en ventana de 5 s" if views else "SIN TRAFICO"
        )

        self.table.setRowCount(len(views))
        for row, view in enumerate(views):
            id_item = QTableWidgetItem(f"0x{view.can_id:03X}")
            id_item.setToolTip(str(view.can_id))

            if view.name:
                name_item = QTableWidgetItem(view.name)
            else:
                name_item = QTableWidgetItem("DESCONOCIDO")
                name_item.setForeground(QColor(t["accent"]))

            age_item = QTableWidgetItem(f"{view.age_s:.1f}s")
            if view.age_s < 2.0:
                age_item.setForeground(QColor(t["good"]))
            elif view.age_s < 10.0:
                age_item.setForeground(QColor(t["stale"]))
            else:
                age_item.setForeground(QColor(t["danger"]))

            cells = {
                _COL_ID: id_item,
                _COL_NAME: name_item,
                _COL_HZ: QTableWidgetItem(f"{view.freq_hz:.1f}"),
                _COL_PERIOD: QTableWidgetItem(f"{view.period_ms:.0f} ms"),
                _COL_JITTER: QTableWidgetItem(f"{view.jitter_ms:.0f} ms"),
                _COL_AGE: age_item,
                _COL_COUNT: QTableWidgetItem(str(view.count)),
                _COL_BW: QTableWidgetItem(f"{view.bandwidth_share * 100:.0f}%"),
            }
            for col, item in cells.items():
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

            data_label = QLabel(_data_html(view.last_data, view.changed_mask, t["accent"]))
            data_label.setContentsMargins(6, 0, 6, 0)
            self.table.setCellWidget(row, _COL_DATA, data_label)

    def apply_theme(self) -> None:
        self.pause_btn.setStyleSheet(thm.tool_button_style())
