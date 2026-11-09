"""Visual style matching Ziti Desktop Edge for Windows / Android."""
from .qt import QtGui
from . import paths

DARK_BG = "#131429"
LIGHT_BG = "#2b3046"
NAVY = "#070826"
TEXT_DARK = "#0F0F23"
COLUMN_HEADER = "#7d8faf"
BLUE = "#0068F9"
BLUE_TEXT = "#0069FF"
BLUE_HOVER = "#1676FE"
RED = "#F4044D"
UPLOAD_RED = "#FF0047"
GREEN = "#34A22B"
TOGGLE_OFF = "#E5EAED"
MUTED = "#638190"
CARD_BG = "#FFFFFF"
SUBTLE = "#F3F4F6"

FONT_BODY = "Open Sans"
FONT_TITLE = "Russo One"

_loaded = False


def load_fonts():
    global _loaded
    if _loaded:
        return
    for f in ("open_sans.ttf", "russo_one.ttf"):
        QtGui.QFontDatabase.addApplicationFont(paths.asset("fonts", f))
    _loaded = True


def font(size=10, bold=False, family=FONT_BODY, weight=None):
    f = QtGui.QFont(family)
    f.setPointSizeF(size)
    if weight is not None:
        f.setWeight(weight)
    elif bold:
        f.setBold(True)
    return f


QSS = """
QWidget#MainView { background: transparent; color: white; }
QLabel { color: white; }
QLabel[role="muted"] { color: %(COLUMN_HEADER)s; }
QLabel[role="header"] { color: %(COLUMN_HEADER)s; font-size: 11px; }
QLabel[role="tiny"] { color: white; font-size: 10px; }

/* white slide-in panels (main menu, identity details, dialogs) */
QWidget[panel="light"] { background: %(CARD_BG)s; color: %(TEXT_DARK)s; }
QWidget[panel="light"] QLabel { color: %(TEXT_DARK)s; }
QWidget[panel="light"] QLabel[role="muted"] { color: %(MUTED)s; }
QWidget[panel="light"] QLabel[role="title"] { font-size: 15px; font-weight: 600; }
QWidget[panel="light"] QLabel[role="key"] { font-weight: 600; }
QWidget[panel="light"] QLabel[role="danger"] { color: %(RED)s; }
QWidget[panel="light"] QLabel[role="link"] { color: %(BLUE_TEXT)s; }

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: white; color: %(TEXT_DARK)s; border: 1px solid #D1D5DB;
    border-radius: 8px; padding: 6px 8px; selection-background-color: %(BLUE)s;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid %(BLUE)s; }
QLineEdit[invalid="true"] { border: 1px solid #FF860000; background: #FFECB5B5; }
QPlainTextEdit#LogView { background: %(DARK_BG)s; color: #E5E7EB; border: none;
    font-family: monospace; font-size: 11px; border-radius: 0px; }

QPushButton[kind="primary"] {
    background: %(BLUE)s; color: white; border: none; border-radius: 8px;
    padding: 9px 18px; font-size: 13px;
}
QPushButton[kind="primary"]:hover { background: %(BLUE_HOVER)s; }
QPushButton[kind="primary"]:disabled { background: #9FBCD9; }
QPushButton[kind="secondary"] {
    background: %(SUBTLE)s; color: %(TEXT_DARK)s; border: 1px solid #D1D5DB;
    border-radius: 8px; padding: 8px 16px; font-size: 13px;
}
QPushButton[kind="secondary"]:hover { background: #E5F0FF; }
QPushButton[kind="danger"] {
    background: transparent; color: %(RED)s; border: none; font-size: 13px; padding: 6px;
}
QPushButton[kind="danger"]:hover { text-decoration: underline; }
QPushButton[kind="flat"] { background: transparent; border: none; color: white; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(125,143,175,0.55); border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QMenu { background: %(DARK_BG)s; color: #C0C0C0; border: 2px solid gray; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 8px 22px; border-radius: 6px; }
QMenu::item:selected { background: %(LIGHT_BG)s; color: white; }
QMenu::separator { height: 1px; background: #3b4059; margin: 4px 8px; }

QToolTip { background: %(DARK_BG)s; color: white; border: 1px solid %(LIGHT_BG)s; padding: 4px; }
QMessageBox, QDialog[panel="light"] { background: white; }
QMessageBox QLabel { color: %(TEXT_DARK)s; }
QMessageBox QPushButton { background: %(BLUE)s; color: white; border: none; border-radius: 6px;
    padding: 6px 16px; min-width: 70px; }
""" % dict(globals())


def apply(qapp):
    """Install fonts, base font, style and stylesheet on the QApplication."""
    load_fonts()
    qapp.setStyle("Fusion")
    base = QtGui.QFont(FONT_BODY)
    base.setPointSizeF(9.5)
    qapp.setFont(base)
    qapp.setStyleSheet(QSS)
