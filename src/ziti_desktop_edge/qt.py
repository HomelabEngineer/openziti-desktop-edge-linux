"""Qt binding shim.

Prefers PyQt6 and falls back to PyQt5 so the same code runs on current
distributions (Debian 12+/Ubuntu 22.04+/Fedora/RHEL 9 EPEL) and on older ones
that only ship Qt5. Everything else in the application imports Qt from here.
"""
import os

_forced = os.environ.get("ZDE_QT_API", "").lower()
_order = ["pyqt6", "pyqt5"]
if _forced in _order:
    _order.remove(_forced)
    _order.insert(0, _forced)

QT_API = None
_err = None
for _api in _order:
    try:
        if _api == "pyqt6":
            from PyQt6 import QtCore, QtGui, QtWidgets, QtNetwork  # noqa: F401
            from PyQt6.QtCore import pyqtSignal as Signal, pyqtSlot as Slot  # noqa: F401
            QAction = QtGui.QAction
        else:
            from PyQt5 import QtCore, QtGui, QtWidgets, QtNetwork  # noqa: F401,F811
            from PyQt5.QtCore import pyqtSignal as Signal, pyqtSlot as Slot  # noqa: F401,F811
            QAction = QtWidgets.QAction
        QT_API = _api
        break
    except ImportError as e:  # pragma: no cover - depends on host
        _err = e

if QT_API is None:  # pragma: no cover
    raise ImportError(
        "ziti-edge-tunnel-gui needs PyQt6 or PyQt5 "
        "(apt install python3-pyqt6 | dnf install python3-pyqt6): %s" % _err)

Qt = QtCore.Qt
QT6 = QT_API == "pyqt6"


def exec_(obj, *args):
    """Call exec()/exec_() on dialogs, menus and the application."""
    fn = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return fn(*args)
