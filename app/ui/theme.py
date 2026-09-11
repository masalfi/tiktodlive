"""Tema gelap yang konsisten untuk seluruh aplikasi.

Tanpa ini tampilan mengikuti tema OS, sehingga warna kustom (mis. teks abu
untuk keterangan) bisa jadi tidak terbaca di mode terang.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Panah spinbox/combobox dimuat dari file SVG. Data-URI di dalam stylesheet
# global tidak dirender oleh Qt, jadi pakai path file sungguhan.
_ASSETS = Path(__file__).resolve().parent / "assets"


def _arrow(name: str) -> str:
    return (_ASSETS / name).as_posix()


# --------------------------------------------------------------- platform

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


def ui_font_family() -> str:
    """Font antarmuka yang paling pas untuk OS ini.

    Tanpa ini Qt memakai "Sans Serif" generik yang tampak berbeda (dan lebih
    buruk) di tiap OS. Daftar dicoba berurutan, yang pertama tersedia dipakai.
    """
    from PySide6.QtGui import QFontDatabase

    if IS_MAC:
        preferred = [".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Helvetica"]
    elif IS_WINDOWS:
        preferred = ["Segoe UI Variable Text", "Segoe UI", "Tahoma"]
    else:
        preferred = ["Inter", "Ubuntu", "Cantarell", "DejaVu Sans"]

    families = set(QFontDatabase.families())
    for name in preferred:
        if name in families:
            return name
    return preferred[-1]


def mono_font_family() -> str:
    """Font monospace untuk pratinjau perintah scrcpy."""
    from PySide6.QtGui import QFontDatabase

    if IS_MAC:
        preferred = ["SF Mono", "Menlo", "Monaco"]
    elif IS_WINDOWS:
        preferred = ["Cascadia Mono", "Consolas", "Lucida Console"]
    else:
        preferred = ["JetBrains Mono", "DejaVu Sans Mono", "monospace"]

    families = set(QFontDatabase.families())
    for name in preferred:
        if name in families:
            return name
    return "monospace"


def base_point_size() -> int:
    """Ukuran font dasar.

    macOS merender teks lebih besar pada point size yang sama dibanding
    Windows, jadi Windows dinaikkan sedikit supaya terbaca setara.
    """
    return 13 if IS_MAC else 9


def repolish(widget) -> None:
    """Terapkan ulang stylesheet setelah properti berubah.

    Qt tidak otomatis mengevaluasi ulang selector [class="..."] ketika
    properti diubah saat runtime, jadi harus dipicu manual.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_font(app) -> None:
    """Pasang font aplikasi. Panggil sebelum setStyleSheet."""
    from PySide6.QtGui import QFont

    font = QFont(ui_font_family(), base_point_size())
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

# Palet
BG = "#1e1f26"
BG_ALT = "#252732"
BG_INPUT = "#2b2d38"
BORDER = "#3a3d4a"
TEXT = "#e4e6ef"
TEXT_DIM = "#9aa0b4"
ACCENT = "#4dd2ff"
DANGER = "#e04b4b"
WARN = "#e0a52e"
OK = "#57c98a"

_arrow_up = _arrow("arrow-up.svg")
_arrow_down = _arrow("arrow-down.svg")
_arrow_up_h = _arrow("arrow-up-hover.svg")
_arrow_down_h = _arrow("arrow-down-hover.svg")
_arrow_up_off = _arrow("arrow-up-off.svg")
_arrow_down_off = _arrow("arrow-down-off.svg")
_arrow_combo = _arrow("arrow-combo.svg")
_arrow_combo_h = _arrow("arrow-combo-hover.svg")

# Qt stylesheet TIDAK mendukung satuan "em" - diam-diam diabaikan. Jadi
# ukuran turunan dihitung dalam pt relatif terhadap ukuran dasar OS ini.
def build_stylesheet() -> str:
    """Bangun stylesheet dengan ukuran font sesuai platform saat ini.

    Dibuat sebagai fungsi (bukan konstanta) supaya ukuran dihitung saat
    dipanggil - penting agar bisa diuji untuk macOS maupun Windows.
    """
    _BASE_PT = base_point_size()
    _HINT_PT = _BASE_PT - 1
    _BIG_PT = _BASE_PT + 3
    _MONO_PT = _BASE_PT - 2
    _MONO = "Menlo" if IS_MAC else ("Consolas" if IS_WINDOWS else "monospace")

    return f"""
QWidget {{
    background: {BG};
    color: {TEXT};
}}

QGroupBox {{
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    font-size: {_HINT_PT}pt;
    color: {ACCENT};
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 9px;
    min-height: 27px;
    selection-background-color: {ACCENT};
    selection-color: #10121a;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {TEXT_DIM};
    background: {BG};
}}
/* Spinbox: tombol naik/turun perlu ukuran eksplisit, kalau tidak Qt
   menyusutkannya mengikuti tinggi field dan jadi nyaris tak bisa diklik. */
QSpinBox, QDoubleSpinBox {{
    padding-right: 22px;                 /* ruang untuk tombol naik/turun */
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: padding;
    width: 20px;
    background: {BG_ALT};
    border-left: 1px solid {BORDER};
    margin: 0;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 4px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-top: 1px solid {BORDER};
    border-bottom-right-radius: 4px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {ACCENT};
}}
/* Panah digambar sebagai SVG: Qt tidak mendukung trik segitiga border-CSS,
   hasilnya jadi kotak putih. */
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{_arrow_up}");
    width: 9px; height: 6px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{_arrow_down}");
    width: 9px; height: 6px;
}}
QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {{
    image: url("{_arrow_up_h}");
}}
QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {{
    image: url("{_arrow_down_h}");
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
    image: url("{_arrow_up_off}");
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
    image: url("{_arrow_down_off}");
}}

/* Combobox: panah juga perlu digambar sendiri. */
QComboBox {{ padding-right: 22px; }}
QComboBox::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: center right;
    width: 20px;
    border: none;
    border-left: 1px solid {BORDER};
}}
QComboBox::down-arrow {{
    image: url("{_arrow_combo}");
    width: 9px; height: 6px;
}}
QComboBox::down-arrow:hover {{
    image: url("{_arrow_combo_h}");
}}
QComboBox QAbstractItemView {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #10121a;
    outline: none;
}}

QPushButton {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 15px;
    min-height: 27px;
    font-weight: 500;
}}
QPushButton:hover {{ background: #343747; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #2a2c38; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {BG}; border-color: {BORDER}; }}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    top: -1px;
    background: {BG};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 7px 18px;
    margin-right: 2px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {BG_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-bottom: none;
}}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QTableWidget, QListWidget {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    outline: none;
}}
QTableWidget::item, QListWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected, QListWidget::item:selected {{
    background: #31506b;
    color: {TEXT};
}}
QHeaderView::section {{
    background: {BG_ALT};
    color: {TEXT_DIM};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
}}

QCheckBox {{ spacing: 8px; min-height: 24px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #4d5163; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 5px; min-width: 28px;
}}

/* Label harus transparan; tanpa ini QLabel mewarisi background QWidget
   dan muncul sebagai kotak gelap di atas panel. */
QLabel {{ background: transparent; }}

/* Kelas bantu: dipakai lewat setProperty("class", ...) supaya ukuran teks
   mengikuti font aplikasi, bukan piksel tetap yang salah di DPI berbeda. */
QLabel[class="hint"] {{
    color: {TEXT_DIM};
    font-size: {_HINT_PT}pt;
}}
QLabel[class="status-big"] {{
    font-size: {_BIG_PT}pt;
    font-weight: 600;
}}
QLabel[class="mono"] {{
    color: {TEXT_DIM};
    font-family: "{_MONO}";
    font-size: {_MONO_PT}pt;
}}

QStatusBar {{
    background: {BG_ALT};
    border-top: 1px solid {BORDER};
}}
QStatusBar QLabel {{ padding: 0 8px; }}

/* Fokus keyboard harus terlihat - penting untuk aksesibilitas dan
   sama-sama berlaku di macOS maupun Windows. */
QPushButton:focus {{
    border-color: {ACCENT};
}}
QTableWidget:focus, QListWidget:focus {{
    border-color: {ACCENT};
}}

/* Tabel: baris belang supaya mudah dibaca saat isinya panjang. */
QTableWidget {{
    alternate-background-color: {BG_ALT};
}}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}

QDialog {{ background: {BG}; }}
QToolTip {{
    background: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px;
    border-radius: 4px;
}}
"""


# Kompatibilitas: modul lama mengimpor STYLESHEET langsung.
STYLESHEET = build_stylesheet()

