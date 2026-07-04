"""Tema centralizado Robowin — colores corporativos MAD Formula Team.

Marca: negro #1a1a19, azul #1c93d8, naranja #ff4f00, blanco roto #ebebeb.

Soporta modo oscuro y claro. Los widgets estáticos se estilizan con clases QSS
(`widget.setProperty("class", "chip")`) resueltas por `app_stylesheet()`; los
estilos calculados en runtime leen `theme()` para tomar la paleta activa.
Para cambiar de modo: `set_theme('light')` y reaplicar `app_stylesheet()`.
"""

TEAM_BLUE = "#1c93d8"
TEAM_ORANGE = "#ff4f00"
TEAM_DARK = "#1a1a19"
TEAM_LIGHT = "#ebebeb"

DARK_PALETTE = {
    'name': 'dark',
    'bg': TEAM_DARK,
    'surface': '#222221',
    'surface_alt': '#2a2a29',
    'card': '#20201f',
    'border': '#3a3a38',
    'text': TEAM_LIGHT,
    'muted': '#a8a8a4',
    'primary': TEAM_BLUE,
    'primary_hover': '#3fa9e6',
    'accent': TEAM_ORANGE,
    'selection': '#155a85',
    'timer_text': '#5cb8ea',
    'stat_best_text': '#39ff9b',
    'stat_best_bg': '#072b1f',
    'stat_best_border': '#1aff8c',
    'stat_avg_text': '#5cb8ea',
    'good': '#39ff9b',
    'delta': '#ffad66',
    'live': '#00e676',
    'stale': '#ffb74d',
    'disabled': '#4a4a47',
    'track': '#262625',
    'plot_bg': '#161615',
    'axis': '#8f8f8b',
    'scroll_handle': '#3f3f3d',
}

LIGHT_PALETTE = {
    'name': 'light',
    'bg': TEAM_LIGHT,
    'surface': '#ffffff',
    'surface_alt': '#dcdcda',
    'card': '#f6f6f5',
    'border': '#c2c2bf',
    'text': TEAM_DARK,
    'muted': '#5f5f5b',
    'primary': TEAM_BLUE,
    'primary_hover': '#3fa9e6',
    'accent': TEAM_ORANGE,
    'selection': '#bfe0f3',
    'timer_text': '#0f6ba3',
    'stat_best_text': '#0a7a45',
    'stat_best_bg': '#dcf2e6',
    'stat_best_border': '#0a7a45',
    'stat_avg_text': '#0f6ba3',
    'good': '#0a7a45',
    'delta': '#b45309',
    'live': '#0a8a3c',
    'stale': '#b45309',
    'disabled': '#b5b5b1',
    'track': '#d5d5d2',
    'plot_bg': '#ffffff',
    'axis': '#55554f',
    'scroll_handle': '#bdbdb9',
}

_PALETTES = {'dark': DARK_PALETTE, 'light': LIGHT_PALETTE}
_current_theme = 'dark'


def theme():
    """Paleta activa (dict de colores)."""
    return _PALETTES[_current_theme]


def set_theme(name):
    global _current_theme
    if name in _PALETTES:
        _current_theme = name
    return _current_theme


def toggle_theme():
    """Alterna oscuro/claro y devuelve el nombre del modo activo."""
    return set_theme('light' if _current_theme == 'dark' else 'dark')


def is_dark():
    return _current_theme == 'dark'


# Compatibilidad con codigo existente
BORDER_COLOR = DARK_PALETTE['border']
STATUS_DEFAULT_BG = DARK_PALETTE['bg']


def app_stylesheet():
    t = theme()
    sel_text = t['text'] if t['name'] == 'light' else '#ffffff'
    return f"""
    QMainWindow {{ background-color: {t['bg']}; color: {t['text']}; }}
    QWidget {{ font-family: 'Segoe UI', sans-serif; }}
    QWidget#navbar {{ background-color: {t['surface']}; border-bottom: 2px solid {t['accent']}; }}
    QStackedWidget > QWidget {{ background-color: {t['bg']}; }}
    QLabel {{ color: {t['text']}; }}
    QGroupBox {{
        border: 1px solid {t['border']};
        border-radius: 0px;
        margin-top: 10px;
        font-weight: bold;
        color: {t['primary']};
        background-color: {t['surface']};
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QPushButton {{ border-radius: 0px; }}
    QLineEdit, QComboBox {{
        border: 1px solid {t['border']};
        border-radius: 0px;
        background-color: {t['surface']};
        color: {t['text']};
        padding: 5px 8px;
    }}
    QComboBox::drop-down {{ border: 0px; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {t['surface']};
        color: {t['text']};
        selection-background-color: {t['selection']};
        selection-color: {sel_text};
    }}
    QTableWidget {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 0px;
        gridline-color: {t['border']};
        selection-background-color: {t['selection']};
        selection-color: {sel_text};
        alternate-background-color: {t['card']};
        font-size: 10pt;
    }}
    QHeaderView::section {{
        background-color: {t['surface_alt']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 0px;
        padding: 4px 8px;
        font-weight: 700;
    }}
    QCheckBox {{ color: {t['muted']}; spacing: 7px; font-size: 9pt; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t['muted']}; border-radius: 0px; }}
    QCheckBox::indicator:checked {{ background-color: {t['primary']}; border-color: {t['primary']}; }}
    QRadioButton {{ color: {t['muted']}; spacing: 7px; }}
    QTabWidget::pane {{ border: 1px solid {t['border']}; background-color: {t['bg']}; }}
    QTabBar::tab {{
        background: {t['surface']};
        color: {t['muted']};
        padding: 6px 16px;
        border: 1px solid {t['border']};
        border-radius: 0px;
    }}
    QTabBar::tab:selected {{ background: {t['surface_alt']}; color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
    QSplitter::handle {{ background-color: {t['border']}; }}
    QScrollArea {{ border: 1px solid {t['border']}; background-color: {t['bg']}; }}
    QScrollBar:vertical {{ background: {t['bg']}; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['scroll_handle']}; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['primary']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: {t['bg']}; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t['scroll_handle']}; min-width: 30px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* Lista de señales offline: fondo blanco fijo en ambos temas */
    QScrollArea#offlineSignalsScroll {{ background-color: #ffffff; border: 1px solid {t['border']}; }}
    QScrollArea#offlineSignalsScroll > QWidget > QWidget {{ background-color: #ffffff; }}
    QScrollArea#offlineSignalsScroll QCheckBox {{ color: {TEAM_DARK}; }}

    /* --- Clases semanticas --- */
    QLabel[class="muted"] {{ color: {t['muted']}; font-size: 10pt; }}
    QLabel[class="muted-small"] {{ color: {t['muted']}; font-size: 9pt; }}
    QLabel[class="hint"] {{ color: {t['muted']}; font-size: 9pt; font-style: italic; }}
    QLabel[class="footer"] {{ color: {t['muted']}; font-size: 9pt; }}
    QLabel[class="label-strong"] {{ color: {t['text']}; font-size: 10pt; font-weight: 700; }}
    QLabel[class="card-title"] {{ color: {t['muted']}; font-size: 10pt; font-weight: 700; }}
    QLabel[class="accent-title"] {{ color: {t['accent']}; font-size: 12pt; font-weight: 800; }}
    QLabel[class="page-title"] {{ color: {t['accent']}; font-size: 22px; font-weight: 800; letter-spacing: 1px; }}
    QLabel[class="brand"] {{ color: {t['accent']}; font-size: 13pt; font-weight: 900; letter-spacing: 2px; }}
    QLabel[class="chip"] {{
        color: {t['text']};
        background-color: {t['surface_alt']};
        border: 1px solid {t['border']};
        border-radius: 0px;
        padding: 5px 10px;
        font-size: 10pt;
    }}
    QLabel[class="timer-big"] {{
        background-color: {t['card']};
        color: {t['timer_text']};
        border: 2px solid {t['primary']};
        border-radius: 0px;
        font-size: 28px;
        font-weight: 800;
        padding: 12px;
    }}
    QLabel[class="stat-total"] {{
        background-color: {t['card']};
        color: {t['text']};
        border: 2px solid {t['border']};
        border-radius: 0px;
        font-size: 18px;
        font-weight: 700;
        padding: 10px 12px;
    }}
    QLabel[class="stat-best"] {{
        background-color: {t['stat_best_bg']};
        color: {t['stat_best_text']};
        border: 2px solid {t['stat_best_border']};
        border-radius: 0px;
        font-size: 18px;
        font-weight: 800;
        padding: 10px 12px;
    }}
    QLabel[class="stat-avg"] {{
        background-color: {t['card']};
        color: {t['stat_avg_text']};
        border: 2px solid {t['primary']};
        border-radius: 0px;
        font-size: 18px;
        font-weight: 700;
        padding: 10px 12px;
    }}
    QFrame[class="metric-card"] {{ background-color: {t['card']}; }}
    QLabel[class="value-popup"] {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 2px solid {t['primary']};
        border-radius: 0px;
        padding: 6px;
        font-family: 'Consolas', monospace;
        font-size: 10pt;
    }}
    """


def nav_button_style(active):
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


def status_label_style(background_color=None):
    t = theme()
    bg = background_color or t['surface_alt']
    fg = "#ffffff" if background_color else t['text']
    return (
        f"background-color: {bg}; color: {fg}; padding: 6px 12px; "
        f"border: 1px solid {t['border']}; border-radius: 0px; font-size: 9pt;"
    )


def popup_button_style(enabled):
    t = theme()
    if enabled:
        return (
            f"background-color: {t['primary']}; color: #ffffff; padding: 6px 12px; "
            f"border: 1px solid {t['primary']}; border-radius: 0px; font-weight: bold;"
        )
    return (
        f"background-color: {t['surface_alt']}; color: {t['muted']}; padding: 6px 12px; "
        f"border: 1px solid {t['border']}; border-radius: 0px; font-weight: bold;"
    )


def theme_button_style():
    t = theme()
    return (
        f"background-color: transparent; color: {t['muted']}; padding: 6px 10px; "
        f"border: 1px solid {t['border']}; border-radius: 0px; font-weight: bold; font-size: 9pt;"
    )


def action_button_style(background_color, font_size_pt=9):
    return (
        f"background-color: {background_color}; color: white; padding: 8px 12px; font-weight: bold; "
        f"font-size: {font_size_pt}pt; border: 1px solid rgba(0, 0, 0, 60); border-radius: 0px;"
    )


def metric_value_style(color):
    """Valor grande de una tarjeta de metrica (dashboard / señales)."""
    return f"color: {color}; font-size: 24px; font-weight: 800;"
