"""Control of the existing ziti-edge-tunnel systemd service.

The GUI never ships or replaces the unit; it only asks systemd to start,
stop, restart, enable or disable it. Authorisation is handled by polkit:
the package installs a rule letting active local members of the ``ziti``
group manage ``ziti-edge-tunnel.service`` without a password (matching the
Windows and Android clients, where any user can toggle the tunnel). On
systems where that rule does not apply, systemd/polkit prompts for admin
credentials, and as a last resort the pkexec helper is used.
"""
import logging
import os
import shlex
import shutil
import time

from .qt import QtCore, Signal
from . import paths

log = logging.getLogger(__name__)


def systemctl_cmd():
    if paths.MOCK_SYSTEMD:
        return shlex.split(paths.MOCK_SYSTEMD)
    return [shutil.which("systemctl") or "/bin/systemctl"]


def pkexec_cmd(args):
    if paths.USE_PKEXEC:
        return ["pkexec", paths.HELPER] + list(args)
    return [paths.HELPER] + list(args)


class ServiceState(object):
    def __init__(self, props=None):
        p = props or {}
        self.load_state = p.get("LoadState", "unknown")
        self.active_state = p.get("ActiveState", "unknown")
        self.sub_state = p.get("SubState", "")
        self.unit_file_state = p.get("UnitFileState", "")
        self.main_pid = int(p.get("MainPID", "0") or 0)
        mono = p.get("ActiveEnterTimestampMonotonic", "0") or "0"
        try:
            self.active_since_mono = int(mono) / 1e6
        except ValueError:
            self.active_since_mono = 0.0
        self.error = p.get("_error")

    @property
    def installed(self):
        return self.load_state not in ("not-found", "unknown", "")

    @property
    def running(self):
        return self.active_state == "active"

    @property
    def transitioning(self):
        return self.active_state in ("activating", "deactivating", "reloading")

    @property
    def enabled(self):
        return self.unit_file_state in ("enabled", "enabled-runtime", "static", "alias")

    def uptime(self):
        if not self.running or self.active_since_mono <= 0:
            return None
        return max(0.0, time.monotonic() - self.active_since_mono)

    def label(self):
        if not self.installed:
            return "ziti-edge-tunnel is not installed"
        if self.active_state == "active":
            return "Running"
        if self.active_state == "activating":
            return "Starting..."
        if self.active_state == "deactivating":
            return "Stopping..."
        if self.active_state == "failed":
            return "Failed"
        return "Stopped"


class ServiceController(QtCore.QObject):
    """Asynchronous systemctl wrapper. Emits ``stateChanged`` on every poll."""

    stateChanged = Signal(object)
    actionFinished = Signal(str, bool, str)  # action, ok, message

    PROPS = ("LoadState", "ActiveState", "SubState", "UnitFileState",
             "ActiveEnterTimestampMonotonic", "MainPID")

    def __init__(self, parent=None, poll_ms=3000):
        super(ServiceController, self).__init__(parent)
        self.unit = paths.SERVICE_UNIT
        self.state = ServiceState()
        self._busy = set()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self.refresh)
        self._show_proc = None

    def start_polling(self):
        self.refresh()
        self._timer.start()

    def busy(self):
        return bool(self._busy)

    # -- status ---------------------------------------------------------------
    def refresh(self):
        if self._show_proc is not None:
            return
        proc = QtCore.QProcess(self)
        self._show_proc = proc
        cmd = systemctl_cmd() + ["show", self.unit, "--no-pager",
                                 "--property=" + ",".join(self.PROPS)]

        def done(*_):
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            props = {}
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
            if proc.exitCode() != 0 and not props:
                props["_error"] = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            self._show_proc = None
            proc.deleteLater()
            self.state = ServiceState(props)
            self.stateChanged.emit(self.state)

        def failed(err):
            if err == QtCore.QProcess.ProcessError.FailedToStart and self._show_proc is proc:
                self._show_proc = None
                proc.deleteLater()
                self.state = ServiceState({"_error": "systemctl not available"})
                self.stateChanged.emit(self.state)

        proc.finished.connect(done)
        proc.errorOccurred.connect(failed)
        proc.start(cmd[0], cmd[1:])

    # -- actions --------------------------------------------------------------
    def start(self):
        self._action("start")

    def stop(self):
        self._action("stop")

    def restart(self):
        self._action("restart")

    def set_enabled(self, enabled):
        self._action("enable" if enabled else "disable")

    def _action(self, action):
        if action in self._busy:
            return
        self._busy.add(action)
        self._run(action, systemctl_cmd() + [action, self.unit], fallback=True)

    def _run(self, action, cmd, fallback):
        proc = QtCore.QProcess(self)
        proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        log.info("running %s", " ".join(cmd))

        def done(code, *_):
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").strip()
            proc.deleteLater()
            ok = code == 0
            denied = any(s in out.lower() for s in (
                "access denied", "interactive authentication required",
                "not authorized", "authentication is required"))
            if not ok and fallback and denied and not paths.MOCK_SYSTEMD:
                log.info("systemctl %s denied, retrying through pkexec helper", action)
                self._run(action, pkexec_cmd(["service", action]), fallback=False)
                return
            self._busy.discard(action)
            if not ok and code in (126, 127) and not fallback:
                out = out or "authorisation was cancelled"
            self.actionFinished.emit(action, ok, out)
            self.refresh()

        def failed(err):
            if err == QtCore.QProcess.ProcessError.FailedToStart:
                self._busy.discard(action)
                self.actionFinished.emit(action, False, proc.errorString())
                proc.deleteLater()

        proc.finished.connect(done)
        proc.errorOccurred.connect(failed)
        proc.start(cmd[0], cmd[1:])


class HelperRunner(QtCore.QObject):
    """Runs the pkexec helper asynchronously."""

    finished = Signal(bool, str)

    def run(self, args):
        proc = QtCore.QProcess(self)
        proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        cmd = pkexec_cmd(args)

        def done(code, *_):
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").strip()
            proc.deleteLater()
            if code in (126, 127) and paths.USE_PKEXEC:
                out = out or "authorisation was cancelled"
            self.finished.emit(code == 0, out)

        def failed(err):
            if err == QtCore.QProcess.ProcessError.FailedToStart:
                self.finished.emit(False, proc.errorString())
                proc.deleteLater()

        proc.finished.connect(done)
        proc.errorOccurred.connect(failed)
        proc.start(cmd[0], cmd[1:])


def user_in_ziti_group():
    """True if this process (or the login user) can use the ziti sockets."""
    import grp
    try:
        g = grp.getgrnam(paths.ZITI_GROUP)
    except KeyError:
        return None  # group missing: tunneler not installed
    if os.getuid() == 0 or g.gr_gid in os.getgroups() or os.getgid() == g.gr_gid:
        return True
    return False


def user_listed_in_ziti_group():
    """True if /etc/group lists the user but the session predates it (re-login needed)."""
    import grp
    import pwd
    try:
        g = grp.getgrnam(paths.ZITI_GROUP)
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return False
    return user in g.gr_mem
