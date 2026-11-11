"""Desktop-environment helpers: tray availability on GNOME and D-Bus notifications.

Stock GNOME (Fedora Workstation, Debian GNOME, RHEL) has no system tray.
Tray icons appear only when the "AppIndicator and KStatusNotifierItem Support"
extension is installed and enabled. Ubuntu ships it on by default, which is
why the icon shows there and not on Fedora.
"""
import logging
import os
import shutil
import subprocess

from .qt import QtWidgets

log = logging.getLogger(__name__)

APPINDICATOR_UUID = "appindicatorsupport@rgcjonas.gmail.com"
APPINDICATOR_PACKAGE = "gnome-shell-extension-appindicator"


def is_gnome():
    de = ":".join(os.environ.get(k, "") for k in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP",
                                                   "DESKTOP_SESSION")).lower()
    return "gnome" in de and "unity" not in de


def tray_available():
    if os.environ.get("ZDE_FORCE_TRAY"):
        return True
    if os.environ.get("ZDE_FORCE_NO_TRAY"):
        return False
    return QtWidgets.QSystemTrayIcon.isSystemTrayAvailable()


def _run(cmd, timeout=8):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def appindicator_state():
    """'missing', 'disabled', 'enabled', 'blocked' (all extensions off) or None if unknown."""
    if os.environ.get("ZDE_FAKE_EXT_STATE"):
        return os.environ["ZDE_FAKE_EXT_STATE"]
    if not shutil.which("gnome-extensions"):
        return None
    rc, out = _run(["gnome-extensions", "info", APPINDICATOR_UUID])
    if rc != 0:
        return "missing"
    state = ""
    enabled_line = ""
    for line in out.splitlines():
        s = line.strip().lower()
        if s.startswith("state:"):
            state = s.split(":", 1)[1].strip()
        elif s.startswith("enabled:"):
            enabled_line = s.split(":", 1)[1].strip()
    if _user_extensions_disabled():
        return "blocked"
    if state in ("active", "enabled") or enabled_line == "yes":
        return "enabled"
    return "disabled"


def _user_extensions_disabled():
    if not shutil.which("gsettings"):
        return False
    rc, out = _run(["gsettings", "get", "org.gnome.shell", "disable-user-extensions"], timeout=4)
    return rc == 0 and out.strip() == "true"


def enable_appindicator():
    """Enable the extension for this user. Returns (ok, message)."""
    if _user_extensions_disabled():
        _run(["gsettings", "set", "org.gnome.shell", "disable-user-extensions", "false"], timeout=4)
    rc, out = _run(["gnome-extensions", "enable", APPINDICATOR_UUID])
    if rc != 0:
        return False, out.strip() or "gnome-extensions enable failed"
    return True, ""


def _gv_str(text):
    """Quote text as a GVariant string literal for gdbus."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def notify(title, body, urgency="normal"):
    """Desktop notification without a tray icon (org.freedesktop.Notifications).

    Uses notify-send when present, otherwise gdbus (part of GLib, always on GNOME).
    Runs detached so the UI never waits on the notification daemon.
    """
    if os.environ.get("ZDE_NOTIFY_LOG"):
        with open(os.environ["ZDE_NOTIFY_LOG"], "a") as f:
            f.write("%s | %s\n" % (title, body))
        return True
    if shutil.which("notify-send"):
        cmd = ["notify-send", "--app-name=Ziti Desktop Edge", "--icon=ziti-edge-tunnel-gui",
               "--urgency=%s" % ("critical" if urgency == "critical" else "normal"), title, body]
    elif shutil.which("gdbus"):
        cmd = ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
               "--object-path", "/org/freedesktop/Notifications",
               "--method", "org.freedesktop.Notifications.Notify",
               _gv_str("Ziti Desktop Edge"), "uint32 0", _gv_str("ziti-edge-tunnel-gui"),
               _gv_str(title), _gv_str(body), "@as []",
               "{'desktop-entry': <'ziti-edge-tunnel-gui'>}", "int32 6000"]
    else:
        return False
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        log.debug("notification failed", exc_info=True)
        return False
