"""Tema MAD Formula Team para ROBOWIN 2 (portado de ROBOWIN 1).

Marca: negro #1a1a19, azul #1c93d8, naranja #ff4f00, blanco roto #ebebeb.
Widgets estáticos via clases QSS (widget.setProperty("class", "chip"));
estilos runtime leen theme().
"""

TEAM_BLUE = "#1c93d8"
TEAM_ORANGE = "#ff4f00"
TEAM_DARK = "#1a1a19"
TEAM_LIGHT = "#ebebeb"

GRAPH_COLORS = [
    "#1c93d8",  # Azul MFT
    "#ff4f00",  # Naranja MFT
    "#00b34a",  # Verde
    "#d9a400",  # Ambar
    "#b026c9",  # Violeta
    "#0091ea",  # Cyan
    "#e91e63",  # Rosa
    "#78786f",  # Gris piedra
]

DARK_PALETTE = {
    "name": "dark",
    "bg": TEAM_DARK,
    "surface": "#222221",
    "surface_alt": "#2a2a29",
    "card": "#20201f",
    "border": "#3a3a38",
    "text": TEAM_LIGHT,
    "muted": "#a8a8a4",
    "primary": TEAM_BLUE,
    "primary_hover": "#3fa9e6",
    "accent": TEAM_ORANGE,
    "selection": "#155a85",
    "good": "#39ff9b",
    "warn": "#ffb300",
    "danger": "#ff1744",
    "stale": "#ffb74d",
    "plot_bg": "#161615",
    "axis": "#8f8f8b",
    "scroll_handle": "#3f3f3d",
    "timer_text": "#5cb8ea",
    "stat_best_text": "#39ff9b",
    "stat_best_bg": "#072b1f",
    "stat_best_border": "#1aff8c",
}

LIGHT_PALETTE = {
    "name": "light",
    "bg": TEAM_LIGHT,
    "surface": "#ffffff",
    "surface_alt": "#dcdcda",
    "card": "#f6f6f5",
    "border": "#c2c2bf",
    "text": TEAM_DARK,
    "muted": "#5f5f5b",
    "primary": TEAM_BLUE,
    "primary_hover": "#3fa9e6",
    "accent": TEAM_ORANGE,
    "selection": "#bfe0f3",
    "good": "#0a7a45",
    "warn": "#b45309",
    "danger": "#d50000",
    "stale": "#b45309",
    "plot_bg": "#ffffff",
    "axis": "#55554f",
    "scroll_handle": "#bdbdb9",
    "timer_text": "#0f6ba3",
    "stat_best_text": "#0a7a45",
    "stat_best_bg": "#dcf2e6",
    "stat_best_border": "#0a7a45",
}

_PALETTES = {"dark": DARK_PALETTE, "light": LIGHT_PALETTE}
_current = "dark"


def theme() -> dict:
    return _PALETTES[_current]


def set_theme(name: str) -> str:
    global _current
    if name in _PALETTES:
        _current = name
    return _current


def toggle_theme() -> str:
    return set_theme("light" if _current == "dark" else "dark")


def is_dark() -> bool:
    return _current == "dark"


def app_stylesheet() -> str:
    t = theme()
    sel_text = t["text"] if t["name"] == "light" else "#ffffff"
    return f"""
    QMainWindow {{ background-color: {t['bg']}; color: {t['text']}; }}
    QWidget {{ font-family: 'Segoe UI', sans-serif; }}
    QWidget#navbar {{ background-color: {t['surface']}; border-bottom: 2px solid {t['accent']}; }}
    QStackedWidget > QWidget {{ background-color: {t['bg']}; }}
    QLabel {{ color: {t['text']}; }}
    QGroupBox {{
        border: 1px solid {t['border']}; border-radius: 0px; margin-top: 10px;
        font-weight: bold; color: {t['primary']}; background-color: {t['surface']};
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QPushButton {{ border-radius: 0px; }}
    QLineEdit, QComboBox {{
        border: 1px solid {t['border']}; border-radius: 0px;
        background-color: {t['surface']}; color: {t['text']}; padding: 5px 8px;
    }}
    QComboBox::drop-down {{ border: 0px; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {t['surface']}; color: {t['text']};
        selection-background-color: {t['selection']}; selection-color: {sel_text};
    }}
    QTableWidget {{
        background-color: {t['surface']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 0px;
        gridline-color: {t['border']};
        selection-background-color: {t['selection']}; selection-color: {sel_text};
        alternate-background-color: {t['card']}; font-size: 10pt;
    }}
    QHeaderView::section {{
        background-color: {t['surface_alt']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 0px;
        padding: 4px 8px; font-weight: 700;
    }}
    QCheckBox {{ color: {t['muted']}; spacing: 7px; font-size: 9pt; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t['muted']}; border-radius: 0px; }}
    QCheckBox::indicator:checked {{ background-color: {t['primary']}; border-color: {t['primary']}; }}
    QSplitter::handle {{ background-color: {t['border']}; }}
    QScrollArea {{ border: 1px solid {t['border']}; background-color: {t['bg']}; }}
    QScrollBar:vertical {{ background: {t['bg']}; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['scroll_handle']}; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['primary']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: {t['bg']}; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t['scroll_handle']}; min-width: 30px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QLabel[class="muted"] {{ color: {t['muted']}; font-size: 10pt; }}
    QLabel[class="muted-small"] {{ color: {t['muted']}; font-size: 9pt; }}
    QLabel[class="hint"] {{ color: {t['muted']}; font-size: 9pt; font-style: italic; }}
    QLabel[class="card-title"] {{ color: {t['muted']}; font-size: 10pt; font-weight: 700; }}
    QLabel[class="accent-title"] {{ color: {t['accent']}; font-size: 12pt; font-weight: 800; }}
    QLabel[class="brand"] {{ color: {t['accent']}; font-size: 13pt; font-weight: 900; letter-spacing: 2px; }}
    QLabel[class="chip"] {{
        color: {t['text']}; background-color: {t['surface_alt']};
        border: 1px solid {t['border']}; border-radius: 0px;
        padding: 5px 10px; font-size: 10pt;
    }}
    QFrame[class="metric-card"] {{ background-color: {t['card']}; }}
    QLabel[class="value-popup"] {{
        background-color: {t['surface']}; color: {t['text']};
        border: 2px solid {t['primary']}; border-radius: 0px;
        padding: 6px; font-family: 'Consolas', monospace; font-size: 10pt;
    }}
    QLabel[class="timer-big"] {{
        background-color: {t['card']}; color: {t['timer_text']};
        border: 2px solid {t['primary']}; border-radius: 0px;
        font-size: 28px; font-weight: 800; padding: 12px;
    }}
    QLabel[class="stat-total"] {{
        background-color: {t['card']}; color: {t['text']};
        border: 2px solid {t['border']}; border-radius: 0px;
        font-size: 18px; font-weight: 700; padding: 10px 12px;
    }}
    QLabel[class="stat-best"] {{
        background-color: {t['stat_best_bg']}; color: {t['stat_best_text']};
        border: 2px solid {t['stat_best_border']}; border-radius: 0px;
        font-size: 18px; font-weight: 800; padding: 10px 12px;
    }}
    QLabel[class="stat-avg"] {{
        background-color: {t['card']}; color: {t['timer_text']};
        border: 2px solid {t['primary']}; border-radius: 0px;
        font-size: 18px; font-weight: 700; padding: 10px 12px;
    }}
    QLabel[class="stat-fs"] {{
        background-color: {t['card']}; color: {t['accent']};
        border: 2px solid {t['accent']}; border-radius: 0px;
        font-size: 18px; font-weight: 800; padding: 10px 12px;
    }}
    """


def nav_button_style(active: bool) -> str:
    t = theme()
    if active:
        return (
            f"QPushButton {{ background-color: {t['primary']}; color: #ffffff; padding: 6px 14px; "
            f"border-radius: 0px; font-weight: bold; font-size: 10pt; border: 1px solid {t['primary']}; }} "
            f"QPushButton:hover {{ background-color: {t['primary_hover']}; }}"
        )
    return (
        f"QPushButton {{ background-color: transparent; color: {t['muted']}; padding: 6px 14px; "
        f"border-radius: 0px; font-weight: bold; font-size: 10pt; border: 1px solid transparent; }} "
        f"QPushButton:hover {{ background-color: {t['surface_alt']}; color: {t['text']}; }}"
    )


def tool_button_style() -> str:
    t = theme()
    return (
        f"background-color: transparent; color: {t['muted']}; padding: 6px 10px; "
        f"border: 1px solid {t['border']}; border-radius: 0px; font-weight: bold; font-size: 9pt;"
    )


def action_button_style(background_color: str, font_size_pt: int = 9) -> str:
    return (
        f"background-color: {background_color}; color: white; padding: 8px 12px; font-weight: bold; "
        f"font-size: {font_size_pt}pt; border: 1px solid rgba(0, 0, 0, 60); border-radius: 0px;"
    )


def status_chip_style(level: str) -> str:
    t = theme()
    colors = {"info": "#2e7d32", "warn": "#f57c00", "error": "#c62828"}
    bg = colors.get(level, t["surface_alt"])
    return (
        f"background-color: {bg}; color: #ffffff; padding: 6px 12px; "
        f"border: 1px solid {t['border']}; border-radius: 0px; font-size: 9pt;"
    )


def metric_value_style(color: str) -> str:
    return f"color: {color}; font-size: 24px; font-weight: 800;"
