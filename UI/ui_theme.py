"""Centralized theme and style helpers for Robowin UI."""

BORDER_COLOR = "#3a3a3a"
NAV_ACTIVE_BG = "#00e676"
NAV_ACTIVE_HOVER_BG = "#00ff8c"
NAV_INACTIVE_BG = "#444"
NAV_INACTIVE_HOVER_BG = "#555"
NAV_INACTIVE_TEXT = "#aaa"

STATUS_DEFAULT_BG = "#1a1a1a"
POPUP_ON_BG = "#00e676"
POPUP_OFF_BG = "#555"

APP_STYLESHEET = """
    QMainWindow { background-color: #1e1e1e; color: #ffffff; }
    QLabel { color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }
    QGroupBox {
        border: 1px solid #444;
        border-radius: 0px;
        margin-top: 10px;
        font-weight: bold;
        color: #00acc1;
        background-color: #252525;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
    QPushButton { border-radius: 0px; }
    QLineEdit, QComboBox {
        border: 1px solid #444;
        border-radius: 0px;
        background-color: #1f1f1f;
        color: #e0e0e0;
    }
    QTableWidget {
        border: 1px solid #3a3a3a;
        border-radius: 0px;
        gridline-color: #3a3a3a;
        selection-background-color: #2e3f56;
    }
    QHeaderView::section {
        background-color: #222;
        color: #e6edf7;
        border: 1px solid #3a3a3a;
        border-radius: 0px;
        padding: 6px 8px;
        font-weight: 700;
    }
    QCheckBox { color: #aaa; spacing: 7px; }
    QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #666; border-radius: 0px; }
    QCheckBox::indicator:checked { background-color: #00e676; border-color: #00e676; }
"""


def nav_button_style(active):
    if active:
        bg = NAV_ACTIVE_BG
        fg = "#000"
        hover = NAV_ACTIVE_HOVER_BG
    else:
        bg = NAV_INACTIVE_BG
        fg = NAV_INACTIVE_TEXT
        hover = NAV_INACTIVE_HOVER_BG

    return (
        f"QPushButton {{ background-color: {bg}; color: {fg}; padding: 8px 16px; "
        f"border-radius: 0px; font-weight: bold; font-size: 10pt; border: 1px solid {BORDER_COLOR}; }} "
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )


def status_label_style(background_color=STATUS_DEFAULT_BG):
    return (
        f"background-color: {background_color}; color: white; padding: 6px 12px; "
        f"border: 1px solid {BORDER_COLOR}; border-radius: 0px; font-size: 9pt;"
    )


def popup_button_style(enabled):
    if enabled:
        return (
            f"background-color: {POPUP_ON_BG}; color: #000; padding: 6px 12px; "
            f"border: 1px solid {BORDER_COLOR}; border-radius: 0px; font-weight: bold;"
        )
    return (
        f"background-color: {POPUP_OFF_BG}; color: #aaa; padding: 6px 12px; "
        f"border: 1px solid {BORDER_COLOR}; border-radius: 0px; font-weight: bold;"
    )


def action_button_style(background_color, font_size_pt=9):
    return (
        f"background-color: {background_color}; color: white; padding: 8px 12px; font-weight: bold; "
        f"font-size: {font_size_pt}pt; border: 1px solid {BORDER_COLOR}; border-radius: 0px;"
    )
