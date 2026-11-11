"""Dark theme with the accent colour the project settled on."""
from __future__ import annotations

BG = "#0F1115"
SIDEBAR = "#151821"
PANEL = "#151821"
PANEL_ALT = "#1B1F2A"
HOVER = "#222838"
SELECTED = "#26324A"
TEXT = "#E6E8EB"
TEXT_DIM = "#8A8F98"
TEXT_FAINT = "#5A6070"
ACCENT = "#2E7BE7"
ACCENT_DIM = "#1F5CB8"
DIVIDER = "#232833"

QUALITY_COLORS = {
    "hires": "#C79A3A",
    "lossless": "#2E7BE7",
    "exhigh": "#3FA07A",
    "higher": "#3FA07A",
    "standard": "#6B7280",
}

STATE_COLORS = {
    "downloaded": "#3FA07A",
    "none": "#8A8F98",
    "pending_review": "#C79A3A",
    "invalid": "#5A6070",
    "match_failed": "#B4544C",
    "removed_cloud": "#5A6070",
}

QUALITY_LABELS = {
    "hires": "Hi-Res",
    "lossless": "SQ",
    "exhigh": "320K",
    "higher": "192K",
    "standard": "128K",
}


def quality_label(value: str | None) -> str:
    if not value:
        return ""
    return QUALITY_LABELS.get(value.lower(), value.upper())


def quality_color(value: str | None) -> str:
    if not value:
        return TEXT_FAINT
    return QUALITY_COLORS.get(value.lower(), TEXT_FAINT)


STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}}
/* Without this every label paints its own dark rectangle over panels. */
QLabel {{
    background-color: transparent;
}}
QCheckBox, QRadioButton {{
    background: transparent;
}}
QFrame#Sidebar {{
    background-color: {SIDEBAR};
    border-right: 1px solid {DIVIDER};
}}
QFrame#QueuePanel {{
    background-color: {PANEL};
    border-left: 1px solid {DIVIDER};
}}
QFrame#Header {{
    background-color: {BG};
    border-bottom: 1px solid {DIVIDER};
}}
QFrame#PlayerBar {{
    background-color: {PANEL};
    border-top: 1px solid {DIVIDER};
}}
QLabel#Brand {{
    font-size: 16px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#BrandSub {{
    font-size: 11px;
    color: {TEXT_FAINT};
}}
QLabel#PlaylistTitle {{
    font-size: 18px;
    font-weight: 700;
}}
QLabel#Cover {{
    background-color: {PANEL_ALT};
    border-radius: 16px;
}}
QListWidget#LyricList {{
    background: transparent;
    border: none;
    outline: none;
}}
QLabel#NowTitle {{
    font-size: 26px;
    font-weight: 700;
}}
QLabel#PlaylistMeta {{
    font-size: 12px;
    color: {TEXT_DIM};
}}
QListView {{
    background-color: {BG};
    border: none;
    outline: none;
}}
QPushButton {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {DIVIDER};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: {HOVER};
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
}}
QPushButton#Accent {{
    background-color: {ACCENT};
    border: none;
    font-weight: 600;
}}
QPushButton#Accent:hover {{
    background-color: {ACCENT_DIM};
}}
QPushButton#PlayerTitle {{
    background: transparent;
    border: none;
    text-align: left;
    padding: 0;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton#PlayerTitle:hover {{
    color: {ACCENT};
}}
QPushButton#AccountCard {{
    background-color: {PANEL_ALT};
    border: 1px solid {DIVIDER};
    border-radius: 8px;
    padding: 8px 12px;
    text-align: left;
    color: {TEXT};
    font-size: 12px;
}}
QPushButton#AccountCard:hover {{
    background-color: {HOVER};
    border-color: {ACCENT};
}}
QPushButton#NavItem {{
    background: transparent;
    border: none;
    text-align: left;
    padding: 9px 14px;
    border-radius: 6px;
    color: {TEXT_DIM};
}}
QPushButton#NavItem:hover {{
    background-color: {HOVER};
    color: {TEXT};
}}
QPushButton#NavItem:checked {{
    background-color: {SELECTED};
    color: {TEXT};
    font-weight: 600;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {PANEL_ALT};
    border: 1px solid {DIVIDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 3px;
    background: {DIVIDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 10px;
    height: 10px;
    margin: -4px 0;
    border-radius: 5px;
    background: {TEXT};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {DIVIDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_FAINT};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {DIVIDER};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {TEXT_FAINT};
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QPlainTextEdit, QTextEdit, QTextBrowser, QTextBrowser#Lyrics {{
    background-color: {PANEL_ALT};
    border: 1px solid {DIVIDER};
    border-radius: 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QTableWidget, QListWidget {{
    background-color: {PANEL};
    alternate-background-color: {PANEL_ALT};
    border: 1px solid {DIVIDER};
    border-radius: 8px;
    gridline-color: {DIVIDER};
    outline: none;
}}
QHeaderView::section {{
    background-color: {PANEL_ALT};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {DIVIDER};
    padding: 6px 8px;
}}
QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: {SELECTED};
    color: {TEXT};
}}
QDialog, QMessageBox {{
    background-color: {BG};
}}
QTabWidget::pane {{
    border: 1px solid {DIVIDER};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 8px 16px;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QProgressBar#DownloadProgress {{
    background-color: {DIVIDER};
    border: none;
    border-radius: 3px;
}}
QProgressBar#DownloadProgress::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}
QLabel#Brand {{
    font-size: 15px;
    font-weight: 700;
    font-style: italic;
    color: {TEXT};
    padding: 2px 4px;
}}
QLabel#PlayerSubtitle {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}
QPushButton#PlayerTitle {{
    text-align: left;
    font-weight: 600;
    border: none;
    background: transparent;
    padding: 0;
}}
QLabel#PlayerTime {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
QPushButton#TransportButton, QPushButton#VolumeButton {{
    border: none;
    background: transparent;
}}
QSlider#Progress, QSlider#Volume {{
    background: transparent;
    border: none;
}}
QSlider#Progress::groove:horizontal {{
    height: 4px;
    background: {DIVIDER};
    border: none;
    border-radius: 2px;
}}
QSlider#Progress::sub-page:horizontal {{
    background: {ACCENT};
    border: none;
    border-radius: 2px;
}}
QSlider#Progress::handle:horizontal {{
    width: 10px;
    height: 10px;
    margin: -3px 0;
    border: none;
    border-radius: 5px;
    background: {TEXT};
}}
QSlider#Volume::groove:horizontal {{
    height: 3px;
    background: {DIVIDER};
    border: none;
    border-radius: 2px;
}}
QSlider#Volume::sub-page:horizontal {{
    background: {TEXT_DIM};
    border: none;
    border-radius: 2px;
}}
QSlider#Volume::handle:horizontal {{
    width: 8px;
    height: 8px;
    margin: -3px 0;
    border: none;
    border-radius: 4px;
    background: {TEXT};
}}
QToolTip {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {DIVIDER};
    padding: 4px;
}}
"""
