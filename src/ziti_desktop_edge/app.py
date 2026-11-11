"""Application controller: wires IPC, systemd, model, window and tray."""
import argparse
import io
import json
import logging
import logging.handlers
import os
import re
import shlex
import subprocess
import sys
import tarfile
import time

from .qt import QtCore, QtGui, QtNetwork, QtWidgets, QT_API, exec_
from . import __version__, desktop, envfile, paths, theme
from .ipc import CommandClient, EventClient, IpcResult
from .main_window import MainWindow
from .tray import Tray
from .updater import Updater, is_newer
from .model import TunnelModel
from .service import (HelperRunner, ServiceController, user_in_ziti_group,
                      user_listed_in_ziti_group)

log = logging.getLogger("ziti_desktop_edge")


def _bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)


def setup_logging(debug=False):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(os.path.join(paths.state_dir(), "app.log"),
                                                  maxBytes=1024 * 1024, backupCount=2)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.DEBUG if debug else logging.WARNING)
    root.addHandler(sh)


AUTOSTART_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Ziti Desktop Edge
Comment=OpenZiti tunnel control (runs in the system tray)
Exec=ziti-edge-tunnel-gui --minimized
Icon=ziti-edge-tunnel-gui
Terminal=false
Categories=Network;
X-GNOME-Autostart-enabled=true
Hidden=%s
"""


class App(QtCore.QObject):
    def __init__(self, qapp, args):
        super(App, self).__init__()
        self.qapp = qapp
        self.args = args
        self.settings = QtCore.QSettings(paths.ORG_NAME, paths.APP_ID)
        self.model = TunnelModel(self)
        self.cmd = CommandClient(parent=self)
        self.events = EventClient(parent=self)
        self.service = ServiceController(self)
        self.helper = HelperRunner(self)
        self.perm_ok = None
        self.listed_in_group = False
        self._last_running = None
        self._pending_restart = False
        self.tray = None
        self.tray_hint = None
        self._check_permissions()

        self.server = None
        self.updater = Updater(self)
        self.window = MainWindow(self)
        self.tray = None
        self.model.notification.connect(self._notify)
        # GNOME without the AppIndicator extension has no tray. Keep checking, so
        # the icon appears as soon as the extension is enabled - no restart needed.
        self._tray_timer = QtCore.QTimer(self)
        self._tray_timer.setInterval(4000)
        self._tray_timer.timeout.connect(self._ensure_tray)
        self._ensure_tray()
        if self.tray is None:
            self.tray_hint = self.tray_fix_state()
            log.info("no system tray available (desktop: %s); running without a tray icon",
                     os.environ.get("XDG_CURRENT_DESKTOP", "?"))
            self._tray_timer.start()

        self.events.received.connect(self.model.handle_event)
        self.events.connectedChanged.connect(self._events_connected)
        self.service.stateChanged.connect(self._service_state)
        self.service.actionFinished.connect(self._action_finished)
        self.model.identitiesChanged.connect(self._update_tray)
        self.model.statusChanged.connect(self._update_tray)

        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.setInterval(1500)
        self._ui_timer.timeout.connect(self._update_tray)
        self._ui_timer.start()
        self.service.start_polling()

        self.updater.available.connect(self._update_available)
        self.updater.upToDate.connect(self._update_none)
        self.updater.failed.connect(self._update_failed)
        self.updater.progress.connect(lambda t: self.message(t) if self._manual_check else log.info("%s", t))
        self.updater.downloaded.connect(lambda f: self.install_update_file(f, confirm=False))
        self._manual_check = False
        self._update_timer = QtCore.QTimer(self)
        self._update_timer.setInterval(24 * 3600 * 1000)
        self._update_timer.timeout.connect(lambda: self.check_updates(manual=False))
        if self.updater.enabled():
            self._update_timer.start()
            QtCore.QTimer.singleShot(20000, lambda: self.check_updates(manual=False))

    # -- startup ------------------------------------------------------------------
    def show_initial(self):
        if not self.args.minimized:
            self.window.show_and_raise()
        elif self.tray is None and not _bool(self.settings.value("bg_hint_shown", False)):
            # started at login with no tray: say once where the app went
            self.settings.setValue("bg_hint_shown", True)
            desktop.notify("Ziti Desktop Edge is running in the background",
                           "Open it from your app menu to connect or manage identities. "
                           "Enable top bar icons to get a tray icon.")

    def _ensure_tray(self):
        if self.tray is not None or not desktop.tray_available():
            return
        self.tray = Tray(self)
        self.tray.show()
        self._tray_timer.stop()
        self.tray_hint = None
        self._update_tray()
        log.info("system tray available; tray icon shown")
        self.window.refresh_connection()

    # -- GNOME top-bar icon support ------------------------------------------------
    def tray_fix_state(self):
        """What the 'show icon in the top bar' notice should offer, or None."""
        if self.tray is not None or not desktop.is_gnome():
            return None
        return desktop.appindicator_state()

    def fix_tray(self):
        state = desktop.appindicator_state()
        if state == "missing":
            self.message("Installing top bar icon support...")

            def done(ok, out):
                try:
                    self.helper.finished.disconnect(done)
                except TypeError:
                    pass
                if not ok:
                    self.message("Could not install %s: %s" % (desktop.APPINDICATOR_PACKAGE, out or "cancelled"),
                                 error=True)
                    return
                desktop.enable_appindicator()
                self._after_enable(newly_installed=True)
            self.helper.finished.connect(done)
            self.helper.run(["install-tray-extension"])
        elif state in ("disabled", "blocked"):
            ok, err = desktop.enable_appindicator()
            self.tray_hint = self.tray_fix_state()
            if not ok:
                self.message("Could not enable the extension: %s" % err, error=True)
                return
            self._after_enable(newly_installed=False)
        elif state == "enabled":
            self.message("Top bar icon support is enabled but not running yet. Log out and back in.")
        self.window.refresh_connection()

    def _after_enable(self, newly_installed):
        self._tray_timer.start()

        def check():
            self.tray_hint = self.tray_fix_state()
            if self.tray is None:
                self.message("Almost done: log out and back in to show the Ziti icon in the top bar.")
            else:
                self.message("The Ziti icon is now in the top bar")
            self.window.refresh_connection()
        if newly_installed:
            check()
        else:
            QtCore.QTimer.singleShot(5000, check)

    def dismiss_tray_hint(self):
        self.settings.setValue("tray_hint_dismissed", True)
        self.window.refresh_connection()

    def _check_permissions(self):
        g = user_in_ziti_group()
        self.listed_in_group = user_listed_in_ziti_group()
        if g is True:
            self.perm_ok = True
        elif g is False:
            # custom setups may relax the socket dir permissions; trust real access
            sd = paths.SOCKET_DIR
            self.perm_ok = True if (os.path.isdir(sd) and os.access(sd, os.R_OK | os.X_OK)) else False
        else:
            self.perm_ok = None
        if os.environ.get("ZDE_SKIP_GROUP_CHECK"):
            self.perm_ok = True

    # -- service / event plumbing ---------------------------------------------
    def _service_state(self, st):
        running = st.running
        if running and self.perm_ok is not False:
            self.events.start()
        if not running and not st.transitioning:
            if self.events.is_connected():
                self.events.stop()
            if self.model.connected:
                self.model.clear()
        if self._last_running is not None and running != self._last_running:
            self._notify("Ziti Desktop Edge", "Tunnel connected" if running else "Tunnel disconnected", "info")
        self._last_running = running
        self.window.refresh_connection()
        self._update_tray()

    def _events_connected(self, on):
        if on:
            self.request_status()
            self._apply_upstream_dns()
        else:
            self.model.clear()
        self.window.refresh_connection()
        self.window.refresh_identities()
        self._update_tray()

    def _action_finished(self, action, ok, msg):
        if ok:
            if action == "enable":
                self.message("The tunnel will start at boot")
            elif action == "disable":
                self.message("The tunnel will no longer start at boot")
            elif action == "restart":
                self.message("Tunnel service restarted")
        else:
            nice = {"start": "connect", "stop": "disconnect"}.get(action, action)
            self.message("Could not %s: %s" % (nice, (msg or "unknown error").splitlines()[-1]), error=True)
        self.window.refresh_connection()

    def _update_tray(self):
        if self.tray is not None:
            self.tray.update_state()

    def _notify(self, title, text, severity="info"):
        if not _bool(self.settings.value("notifications", True), True):
            return
        if self.tray is None:
            desktop.notify(title, text, "critical" if severity == "critical" else "normal")
            return
        Icon = QtWidgets.QSystemTrayIcon.MessageIcon
        icon = Icon.Critical if severity == "critical" else (
            Icon.Warning if severity in ("major", "minor") else Icon.Information)
        self.tray.showMessage(title, text, icon, 6000)

    def message(self, text, error=False, action=None):
        (log.warning if error else log.info)("%s", text)
        self.window.show_message(text, error=error, action=action)

    # -- IPC helpers ----------------------------------------------------------
    def ipc_call(self, command, data=None, callback=None):
        if not self.events.is_connected() and not self.service.state.running:
            res = IpcResult(False, "The tunnel is not connected. Tap the power button first.")
            if callback:
                callback(res)
            else:
                self.message(res.error, error=True)
            return
        self.cmd.send(command, data, callback)

    def _report(self, what):
        def cb(res):
            if res.success:
                if what:
                    self.message(what)
            else:
                self.message(res.error or "Command failed", error=True)
            self.request_status()
        return cb

    def request_status(self):
        def cb(res):
            if res.success and isinstance(res.data, dict):
                self.model.apply_status(res.data)
        if self.cmd.is_connected() or self.events.is_connected():
            self.cmd.send("Status", None, cb)

    # -- user actions -----------------------------------------------------------
    def toggle_connection(self):
        st = self.service.state
        if not st.installed and st.load_state != "unknown":
            self.message("ziti-edge-tunnel is not installed", error=True)
            return
        if self.perm_ok is False:
            self.message("Add your account to the '%s' group first" % paths.ZITI_GROUP, error=True)
            return
        if st.running or st.active_state == "activating":
            self.service.stop()
        else:
            self.service.start()
        self.window.refresh_connection()

    def restart_tunnel(self):
        self.service.restart()
        self.window.refresh_connection()

    def set_identity_enabled(self, identifier, on):
        ident = self.model.identity(identifier)

        def cb(res):
            if not res.success:
                self.message(res.error or "Could not change the identity", error=True)
            elif ident is not None:
                ident.raw["Active"] = on
                self.model.identitiesChanged.emit()
            self.request_status()
        self.ipc_call("IdentityOnOff", {"Identifier": identifier, "OnOff": bool(on)}, cb)

    def forget_identity(self, identifier):
        ident = self.model.identity(identifier)
        name = ident.name if ident else identifier
        self.ipc_call("RemoveIdentity", {"Identifier": identifier}, self._report("Forgot %s" % name))

    def refresh_identity(self, identifier):
        self.ipc_call("RefreshIdentity", {"Identifier": identifier}, self._report("Identity refreshed"))

    def set_log_level(self, level):
        self.ipc_call("SetLogLevel", {"Level": level}, self._report("Log level set to %s" % level))

    @staticmethod
    def _identity_filename(name):
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "identity"
        return name[:120]

    def add_identity_jwt(self, path):
        try:
            with open(path, "r") as f:
                jwt = f.read().strip()
        except (IOError, OSError) as e:
            self.message("Cannot read %s: %s" % (path, e), error=True)
            return
        if jwt.count(".") < 2:
            self.message("%s does not look like an enrollment token" % os.path.basename(path), error=True)
            return
        name = self._identity_filename(os.path.splitext(os.path.basename(path))[0])
        self.message("Enrolling %s..." % name)
        self.ipc_call("AddIdentity", {"JwtContent": jwt, "IdentityFilename": name, "UseKeychain": False},
                      self._report("Identity %s added" % name))

    def add_identity_url(self, url, name):
        fn = self._identity_filename(name)
        self.message("Adding %s..." % fn)

        def cb(res):
            if not res.success:
                self.message(res.error or "Could not add the identity", error=True)
            else:
                self.message("Identity %s added. Authenticate with your provider to finish." % fn)
            self.request_status()
        self.ipc_call("AddIdentity", {"ControllerURL": url, "IdentityFilename": fn}, cb)

    def external_auth(self, identifier):
        ident = self.model.identity(identifier)
        providers = ident.ext_auth_providers if ident else []
        provider = None
        if len(providers) > 1:
            provider, ok = QtWidgets.QInputDialog.getItem(self.window, "Choose provider",
                                                          "Identity provider:", providers, 0, False)
            if not ok:
                return
        elif providers:
            provider = providers[0]
        data = {"Identifier": identifier}
        if provider:
            data["Provider"] = provider

        def cb(res):
            url = (res.data or {}).get("url") if isinstance(res.data, dict) else None
            if res.success and url:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
                self.message("Continue signing in with your browser")
            else:
                self.message(res.error or "External authentication failed", error=True)
        self.ipc_call("ExternalAuth", data, cb)

    def _apply_upstream_dns(self):
        up = (self.settings.value("upstream_dns", "") or "").strip()
        if not up:
            return
        hosts = []
        for part in re.split(r"[,\s]+", up):
            if not part:
                continue
            host, _, port = part.rpartition(":") if part.count(":") == 1 else (part, "", "")
            entry = {"host": host}
            if port.isdigit():
                entry["port"] = int(port)
            hosts.append(entry)
        if hosts:
            self.cmd.send("SetUpstreamDNS", hosts,
                          lambda r: None if r.success else self.message("Upstream DNS: %s" % r.error, error=True))

    def save_tunnel_config(self, dns_range, upstream, range_changed):
        try:
            dns_range = envfile.validate_dns_ip_range(dns_range)
        except ValueError as e:
            self.message(str(e), error=True)
            return
        self.settings.setValue("upstream_dns", upstream)
        if not range_changed:
            if self.events.is_connected():
                self._apply_upstream_dns()
            self.message("Settings saved")
            return

        def done(ok, out):
            try:
                self.helper.finished.disconnect(done)
            except TypeError:
                pass
            if ok:
                self.message("Saved. Restarting the tunnel...")
                self.service.restart()
            else:
                self.message("Could not save: %s" % (out or "permission denied"), error=True)
        self.helper.finished.connect(done)
        self.helper.run(["set-env", "ZITI_DNS_IP_RANGE=%s" % dns_range])

    def join_group(self):
        def done(ok, out):
            try:
                self.helper.finished.disconnect(done)
            except TypeError:
                pass
            if ok:
                self.listed_in_group = True
                self.message("Added. Log out and back in for the change to take effect.")
            else:
                self.message("Could not change group membership: %s" % (out or "cancelled"), error=True)
            self.window.refresh_connection()
        self.helper.finished.connect(done)
        self.helper.run(["join-group"])

    # -- logs & feedback ------------------------------------------------------
    def _journal_cmd(self, lines=2000):
        override = os.environ.get("ZDE_JOURNAL_CMD")
        if override:
            return shlex.split(override)
        return ["journalctl", "--unit", paths.SERVICE_UNIT, "--no-pager", "--output", "short-iso",
                "--lines", str(lines)]

    def read_service_log(self, cb):
        proc = QtCore.QProcess(self)
        proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        cmd = self._journal_cmd()

        def done(*_):
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            proc.deleteLater()
            if not out.strip() or "-- No entries --" in out or "insufficient permissions" in out.lower():
                out += ("\n\nNo journal entries are visible to your account. Members of the "
                        "'systemd-journal' or 'adm' group can read system logs:\n"
                        "  sudo usermod -aG systemd-journal $USER   (then log in again)")
            cb(out)

        def failed(err):
            if err == QtCore.QProcess.ProcessError.FailedToStart:
                cb("Could not run journalctl: %s" % proc.errorString())
                proc.deleteLater()

        proc.finished.connect(done)
        proc.errorOccurred.connect(failed)
        proc.start(cmd[0], cmd[1:])

    def read_app_log(self, cb):
        fn = os.path.join(paths.state_dir(), "app.log")
        try:
            with open(fn, "r") as f:
                cb(f.read()[-400000:])
        except (IOError, OSError) as e:
            cb("No application log yet (%s)" % e)

    def collect_feedback(self):
        name = "ziti-desktop-edge-feedback-%s.tar.gz" % time.strftime("%Y%m%d-%H%M%S")
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self.window, "Save diagnostic bundle",
                                                      os.path.expanduser("~/" + name),
                                                      "Archive (*.tar.gz)")
        if not fn:
            return

        def run(cmd):
            try:
                return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      timeout=20).stdout
            except Exception as e:  # pragma: no cover
                return ("%s: %s" % (" ".join(cmd), e)).encode()

        files = {
            "status.json": json.dumps(self.model.status, indent=2, default=str).encode(),
            "service-log.txt": run(self._journal_cmd(10000)),
            "systemctl-status.txt": run(["systemctl", "status", "--no-pager", paths.SERVICE_UNIT]),
            "versions.txt": ("app %s\n%s %s\nqt %s\npython %s\n" % (
                __version__, QT_API, "", QtCore.qVersion(), sys.version)).encode(),
        }
        try:
            with open(paths.ENV_FILE, "rb") as f:
                files["ziti-edge-tunnel.env"] = f.read()
        except (IOError, OSError):
            pass
        try:
            with open(os.path.join(paths.state_dir(), "app.log"), "rb") as f:
                files["app.log"] = f.read()
        except (IOError, OSError):
            pass
        try:
            with tarfile.open(fn, "w:gz") as tar:
                for n, data in files.items():
                    ti = tarfile.TarInfo(n)
                    ti.size = len(data)
                    ti.mtime = int(time.time())
                    tar.addfile(ti, io.BytesIO(data))
            self.message("Saved %s (it contains identity names and logs; no keys)" % os.path.basename(fn))
        except (IOError, OSError) as e:
            self.message("Could not write %s: %s" % (fn, e), error=True)

    # -- desktop integration --------------------------------------------------
    def autostart_enabled(self):
        user = paths.autostart_file()
        if os.path.exists(user):
            with open(user) as f:
                txt = f.read()
            return not re.search(r"^Hidden\s*=\s*true", txt, re.M | re.I)
        return os.path.exists("/etc/xdg/autostart/%s.desktop" % paths.APP_ID)

    def set_autostart(self, on):
        fn = paths.autostart_file()
        try:
            os.makedirs(os.path.dirname(fn), exist_ok=True)
            with open(fn, "w") as f:
                f.write(AUTOSTART_TEMPLATE % ("false" if on else "true"))
        except OSError as e:
            self.message("Could not update autostart: %s" % e, error=True)

    def close_to_tray(self):
        """Closing the window keeps the app running in the background (with or without a tray)."""
        return _bool(self.settings.value("close_to_tray", True), True)

    def first_hide_hint(self):
        key = "hide_hint_shown" if self.tray is not None else "hide_hint_notray_shown"
        if not _bool(self.settings.value(key, False)):
            self.settings.setValue(key, True)
            if self.tray is not None:
                self._notify("Ziti Desktop Edge is still running",
                             "It stays in the system tray. Quit it from the tray menu; "
                             "the tunnel service is not affected.")
            else:
                desktop.notify("Ziti Desktop Edge is still running",
                               "Open it again from your app menu. Quit from Main Menu \u203a Quit. "
                               "The tunnel service is not affected.")

    # -- updates ------------------------------------------------------------------
    def check_updates(self, manual=True):
        if not manual and not _bool(self.settings.value("auto_update_check", True), True):
            return
        self._manual_check = manual  # background checks stay quiet unless an update exists
        self.updater.check()

    def _update_available(self, version, rel):
        self.window.menu.set_update_status("Version %s is available" % version)
        if not self._manual_check and self.settings.value("update_notified") == version:
            return
        self.settings.setValue("update_notified", version)
        self._notify("Ziti Desktop Edge %s is available" % version,
                     "Open the app and click the update message to install it.")
        def install():
            self._manual_check = True  # from here on the user is watching
            self.updater.download(rel)
        self.window.show_message("Version %s is available. Click to install." % version,
                                 action=install, timeout_ms=0)

    def _update_none(self, latest):
        self.window.menu.set_update_status("You have the latest version (%s)" % latest)
        if self._manual_check:
            self.message("You have the latest version")

    def _update_failed(self, msg):
        self.window.menu.set_update_status(msg)
        if self._manual_check:
            self.message(msg, error=True)
        else:
            log.warning("background update check: %s", msg)

    @staticmethod
    def read_package_version(path):
        try:
            if path.endswith(".deb"):
                out = subprocess.run(["dpkg-deb", "--field", path, "Package", "Version"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout.decode()
                f = dict(l.split(":", 1) for l in out.splitlines() if ":" in l)
                return f.get("Package", "").strip(), f.get("Version", "").strip()
            out = subprocess.run(["rpm", "-qp", "--nosignature", "--qf", "%{NAME} %{VERSION}-%{RELEASE}", path],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15).stdout.decode()
            name, _, ver = out.strip().partition(" ")
            return name, ver
        except (OSError, subprocess.SubprocessError):
            return "", ""

    def install_update_file(self, path, confirm=True):
        name, version = self.read_package_version(path)
        if name != paths.APP_ID:
            self.message("%s is not a Ziti Desktop Edge package" % os.path.basename(path), error=True)
            return
        if confirm:
            if is_newer(version):
                q = "Install Ziti Desktop Edge %s? (installed: %s)\n\nThe app restarts afterwards; " \
                    "the tunnel keeps running." % (version, __version__)
            else:
                q = "%s is not newer than the installed version (%s). Reinstall it anyway?" % (version, __version__)
            r = QtWidgets.QMessageBox.question(self.window, "Install update", q)
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.message("Installing %s %s..." % (name, version))

        def done(ok, out):
            try:
                self.helper.finished.disconnect(done)
            except TypeError:
                pass
            if ok:
                log.info("update installed: %s", out.splitlines()[-1] if out else "")
                self.message("Update installed. Restarting...")
                QtCore.QTimer.singleShot(800, self.restart_app)
            else:
                last = [l for l in (out or "").splitlines() if l.strip()]
                self.message("Update failed: %s" % (last[-1] if last else "cancelled"), error=True)
        self.helper.finished.connect(done)
        self.helper.run(["install-update", os.path.abspath(path)])

    def restart_app(self):
        args = [] if self.window.isVisible() else ["--minimized"]
        if self.server is not None:
            self.server.close()  # let the new instance become the single instance
        launcher = "/usr/bin/ziti-edge-tunnel-gui"
        if os.path.exists(launcher) and os.path.dirname(os.path.abspath(__file__)).startswith("/usr/lib/"):
            QtCore.QProcess.startDetached(launcher, args)
        else:
            QtCore.QProcess.startDetached(sys.executable, ["-m", "ziti_desktop_edge"] + args)
        self.quit()

    def quit(self):
        self.events.stop()
        self.cmd.close()
        if self.tray is not None:
            self.tray.hide()
        self.qapp.quit()


def _single_instance(name):
    """Return a QLocalServer if we are the first instance, else None."""
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return None
    QtNetwork.QLocalServer.removeServer(name)
    server = QtNetwork.QLocalServer()
    server.listen(name)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ziti-edge-tunnel-gui",
                                     description="Desktop GUI for the OpenZiti ziti-edge-tunnel service")
    parser.add_argument("--minimized", action="store_true", help="start hidden in the system tray")
    parser.add_argument("--debug", action="store_true", help="verbose logging to stderr")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    setup_logging(args.debug)
    if hasattr(QtCore.Qt, "HighDpiScaleFactorRoundingPolicy"):
        QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QT_API == "pyqt5":
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    qapp = QtWidgets.QApplication([sys.argv[0]] + qt_args)
    qapp.setApplicationName(paths.APP_ID)
    qapp.setApplicationDisplayName(paths.APP_NAME)
    qapp.setOrganizationName(paths.ORG_NAME)
    qapp.setDesktopFileName(paths.APP_ID)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(QtGui.QIcon(paths.asset("images", "Ziti-Green.png")))

    server = _single_instance("%s-%d" % (paths.APP_ID, os.getuid()))
    if server is None:
        log.info("another instance is running; asked it to show itself")
        return 0

    theme.apply(qapp)
    log.info("starting %s %s (%s, Qt %s)", paths.APP_ID, __version__, QT_API, QtCore.qVersion())

    app = App(qapp, args)
    app.server = server

    def on_conn():
        c = server.nextPendingConnection()
        if c is not None:
            c.readyRead.connect(lambda: app.window.show_and_raise())
    server.newConnection.connect(on_conn)

    app.show_initial()
    return exec_(qapp)
