"""The white slide-in Main Menu (Views/Screens/MainMenu.xaml) and its pages."""

import os
import platform
import time

from .qt import QtCore, QtGui, QtWidgets, Qt, QT_API
from . import __version__, envfile, paths, theme
from .widgets import (MenuItem, OptionItem, PanelHeader, SlideOverlay, ToggleItem,
                      KeyValue, button, label, scaled)

SUPPORT_URL = "https://openziti.discourse.group/"
DOCS_URL = "https://netfoundry.io/docs/openziti/reference/tunnelers/linux/"
PROJECT_URL = "https://github.com/openziti/ziti-tunnel-sdk-c"


def _page():
    w = QtWidgets.QWidget()
    w.setProperty("panel", "light")
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    return w, lay


def _scroll(inner):
    sa = QtWidgets.QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    sa.setWidget(inner)
    inner.setProperty("panel", "light")
    inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    sa.setStyleSheet("QScrollArea { background: white; }")
    return sa


class MainMenu(SlideOverlay):
    def __init__(self, parent, app):
        super(MainMenu, self).__init__(parent, direction="left")
        self.app = app
        self.setProperty("panel", "light")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget()
        outer.addWidget(self.stack)
        self._history = []
        self.pages = {}
        self._build_main()
        self._build_identities()
        self._build_advanced()
        self._build_tunnel_config()
        self._build_log_level()
        self._build_app_settings()
        self._build_logs()
        self._build_about()
        app.model.statusChanged.connect(self._refresh_status)
        app.model.identitiesChanged.connect(self._refresh_identities)
        app.service.stateChanged.connect(self._refresh_service)

    # -- navigation -------------------------------------------------------------
    def _add(self, key, title, body, back_to=None):
        page, lay = _page()
        hdr = PanelHeader(title, "Back")
        hdr.back.connect(self.go_back)
        lay.addWidget(hdr)
        lay.addWidget(body, 1)
        self.stack.addWidget(page)
        self.pages[key] = page
        page.header = hdr
        return page

    def show_page(self, key):
        cur = self.stack.currentWidget()
        if cur is not None and cur is not self.pages.get(key):
            self._history.append(cur)
        self.stack.setCurrentWidget(self.pages[key])
        hook = getattr(self, "_on_show_" + key, None)
        if hook:
            hook()
        if not self.isVisible():
            self.open()

    def go_back(self):
        if self._history:
            self.stack.setCurrentWidget(self._history.pop())
        else:
            self.dismiss()

    def open_menu(self):
        self._history = []
        self.stack.setCurrentWidget(self.pages["main"])
        self.open()

    # -- pages ------------------------------------------------------------------
    def _build_main(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(0)
        items = [
            ("Identities", "identities.png", lambda: self.show_page("identities")),
            ("Advanced Settings", "advanced.png", lambda: self.show_page("advanced")),
            ("About", "about.png", lambda: self.show_page("about")),
            ("Feedback", "feedback.png", self.app.collect_feedback),
            ("Support", "support.png", lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(SUPPORT_URL))),
        ]
        for text, icon, fn in items:
            mi = MenuItem(text, icon)
            mi.clicked.connect(fn)
            lay.addWidget(mi)
        lay.addStretch(1)
        self.version_label = label("", role="muted", size=9.5, align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.version_label)
        lay.addSpacing(10)
        quit_btn = button("Quit Ziti Desktop Edge", "primary", self.app.quit)
        quit_btn.setToolTip("Closes the app. The ziti-edge-tunnel service keeps running.")
        wrap = QtWidgets.QHBoxLayout()
        wrap.setContentsMargins(40, 0, 40, 24)
        wrap.addWidget(quit_btn)
        lay.addLayout(wrap)
        page = self._add("main", "Main Menu", body)
        page.header.back_btn.findChildren(QtWidgets.QLabel)[1].setText("Close")
        self._refresh_version()

    def _refresh_version(self):
        tv = (self.app.model.version or "").lstrip("vV")
        self.version_label.setText("App v%s%s" % (__version__, ("  •  Tunnel v%s" % tv) if tv else ""))

    def _build_identities(self):
        inner = QtWidgets.QWidget()
        self.ident_lay = QtWidgets.QVBoxLayout(inner)
        self.ident_lay.setContentsMargins(0, 0, 0, 0)
        self.ident_lay.setSpacing(0)
        self.ident_lay.addStretch(1)
        self._add("identities", "Identities", _scroll(inner))

    def _refresh_identities(self):
        lay = self.ident_lay
        while lay.count() > 1:
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        ids = self.app.model.sorted_identities()
        if not ids:
            lay.insertWidget(0, label("No identities yet. Use ADD IDENTITY on the main screen.",
                                      role="muted", wrap=True, align=Qt.AlignmentFlag.AlignCenter))
        for i, ident in enumerate(ids):
            mi = MenuItem(ident.name, "identities.png", detail=ident.status_text())
            mi.clicked.connect(lambda ident=ident: self.app.window.open_identity(ident.identifier))
            lay.insertWidget(i, mi)

    def _build_advanced(self):
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for text, icon, key in (("Tunnel Config", "wrench.png", "tunnel"),
                                ("Service Logs", "logs.png", "service_logs"),
                                ("Application Logs", "logs.png", "app_logs"),
                                ("Set Logging Level", "advanced.png", "loglevel"),
                                ("App Settings", "dashboard.png", "app_settings")):
            mi = MenuItem(text, icon, tint=theme.BLUE_TEXT if icon == "dashboard.png" else None)
            if key in ("service_logs", "app_logs"):
                mi.clicked.connect(lambda k=key: self.show_logs(k))
            else:
                mi.clicked.connect(lambda k=key: self.show_page(k))
            lay.addWidget(mi)
        self.boot_toggle = ToggleItem("Start tunnel at boot",
                                      "systemctl enable/disable %s" % paths.SERVICE_UNIT)
        self.boot_toggle.toggle.toggled.connect(self.app.service.set_enabled)
        lay.addWidget(self.boot_toggle)
        restart = MenuItem("Restart Tunnel Service", "wrench.png", arrow=False)
        restart.clicked.connect(self.app.restart_tunnel)
        lay.addWidget(restart)
        lay.addStretch(1)
        self.service_info = label("", role="muted", size=8.5, wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        self.service_info.setContentsMargins(24, 0, 24, 16)
        lay.addWidget(self.service_info)
        self._add("advanced", "Advanced Settings", _scroll(inner))

    def _refresh_service(self, st):
        self.boot_toggle.toggle.set_checked_silent(st.enabled)
        self.boot_toggle.setEnabled(st.installed)
        self.service_info.setText("%s: %s (%s)" % (paths.SERVICE_UNIT, st.active_state,
                                                    st.unit_file_state or "n/a"))

    def _build_tunnel_config(self):
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(24, 4, 24, 20)
        lay.setSpacing(0)
        lay.addWidget(label("Live values", role="key", size=10))
        self.cfg_ip = KeyValue("IPv4 Address:")
        self.cfg_subnet = KeyValue("Subnet Mask:")
        self.cfg_mtu = KeyValue("MTU:")
        self.cfg_dns = KeyValue("DNS Server:")
        self.cfg_loglevel = KeyValue("Log Level:")
        self.cfg_iddir = KeyValue("Identity Dir:")
        for w in (self.cfg_ip, self.cfg_subnet, self.cfg_mtu, self.cfg_dns, self.cfg_loglevel, self.cfg_iddir):
            lay.addWidget(w)
        lay.addSpacing(16)
        lay.addWidget(label("Service settings (%s)" % os.path.basename(paths.ENV_FILE), role="key", size=10))
        lay.addSpacing(6)
        lay.addWidget(label("DNS IP range (the tunnel address and intercept pool)", role="muted", size=8.5))
        self.ed_range = QtWidgets.QLineEdit()
        self.ed_range.setPlaceholderText(paths.DEFAULT_DNS_IP_RANGE)
        self.ed_range.textChanged.connect(self._validate_range)
        lay.addWidget(self.ed_range)
        lay.addSpacing(10)
        lay.addWidget(label("Upstream DNS (optional, re-applied each time the tunnel starts)",
                            role="muted", size=8.5, wrap=True))
        self.ed_upstream = QtWidgets.QLineEdit()
        self.ed_upstream.setPlaceholderText("e.g. 1.1.1.1 or dns.example.com:53")
        lay.addWidget(self.ed_upstream)
        lay.addSpacing(16)
        self.save_cfg = button("Save and Restart Tunnel", "primary", self._save_config)
        lay.addWidget(self.save_cfg)
        lay.addSpacing(8)
        note = label("Saving the DNS IP range needs administrator rights and restarts "
                     "ziti-edge-tunnel. The tunnel unit itself is never modified.",
                     role="muted", size=8.5, wrap=True)
        lay.addWidget(note)
        lay.addStretch(1)
        self._add("tunnel", "Tunnel Configuration", _scroll(inner))

    def _validate_range(self, text):
        ok = True
        if text.strip():
            try:
                envfile.validate_dns_ip_range(text)
            except ValueError as e:
                ok = False
                self.ed_range.setToolTip(str(e))
        self.ed_range.setProperty("invalid", "false" if ok else "true")
        self.ed_range.style().unpolish(self.ed_range)
        self.ed_range.style().polish(self.ed_range)
        self.save_cfg.setEnabled(ok)

    def _on_show_tunnel(self):
        env = envfile.read(paths.ENV_FILE)
        self._env_range = env.get("ZITI_DNS_IP_RANGE", "")
        self.ed_range.setText(self._env_range or paths.DEFAULT_DNS_IP_RANGE)
        self.ed_upstream.setText(self.app.settings.value("upstream_dns", "") or "")
        self._refresh_status()

    def _save_config(self):
        rng = self.ed_range.text().strip() or paths.DEFAULT_DNS_IP_RANGE
        upstream = self.ed_upstream.text().strip()
        self.app.save_tunnel_config(rng, upstream, range_changed=(rng != getattr(self, "_env_range", None)))

    def _refresh_status(self):
        m = self.app.model
        ip = m.ip_info
        self.cfg_ip.set(ip.get("Ip", "-"))
        self.cfg_subnet.set(ip.get("Subnet", "-"))
        self.cfg_mtu.set(str(ip.get("MTU", "-")))
        self.cfg_dns.set(ip.get("DNS", "-"))
        self.cfg_loglevel.set(m.log_level or "-")
        self.cfg_iddir.set(m.status.get("ConfigDir") or paths.IDENTITY_DIR)
        for lvl, item in self.level_items.items():
            item.set_selected(lvl == m.log_level)
        self._refresh_version()

    def _build_log_level(self):
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.level_items = {}
        for lvl in paths.LOG_LEVELS:
            it = OptionItem(lvl.capitalize())
            it.clicked.connect(lambda l=lvl: self.app.set_log_level(l))
            self.level_items[lvl] = it
            lay.addWidget(it)
        lay.addStretch(1)
        lay.addWidget(label("Applied immediately over IPC and remembered by the tunnel.",
                            role="muted", size=8.5, wrap=True, align=Qt.AlignmentFlag.AlignCenter))
        lay.addSpacing(16)
        self._add("loglevel", "Logging Level", _scroll(inner))

    def _build_app_settings(self):
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.t_login = ToggleItem("Start at login", "Run in the background (system tray) when you log in")
        self.t_login.toggle.toggled.connect(self.app.set_autostart)
        self.t_min = ToggleItem("Start minimized", "Start in the background without opening the window")
        self.t_min.toggle.toggled.connect(lambda on: self.app.settings.setValue("start_minimized", on))
        self.t_close = ToggleItem("Keep running when closed",
                                  "Closing the window keeps the app running in the background")
        self.t_close.toggle.toggled.connect(lambda on: self.app.settings.setValue("close_to_tray", on))
        self.t_notify = ToggleItem("Desktop notifications", "MFA prompts, timeouts and connection changes")
        self.t_notify.toggle.toggled.connect(lambda on: self.app.settings.setValue("notifications", on))
        for w in (self.t_login, self.t_min, self.t_close, self.t_notify):
            lay.addWidget(w)
        self.tray_item = MenuItem("Show icon in top bar", "dashboard.png", arrow=True,
                                  tint=theme.BLUE_TEXT, detail="GNOME")
        self.tray_item.clicked.connect(self.app.fix_tray)
        lay.addWidget(self.tray_item)
        lay.addStretch(1)
        self._add("app_settings", "App Settings", _scroll(inner))

    def _on_show_app_settings(self):
        s = self.app.settings
        self.t_login.toggle.set_checked_silent(self.app.autostart_enabled())
        self.t_min.toggle.set_checked_silent(_bool(s.value("start_minimized", True)))
        self.t_close.toggle.set_checked_silent(_bool(s.value("close_to_tray", True)))
        self.t_notify.toggle.set_checked_silent(_bool(s.value("notifications", True)))
        self.tray_item.setVisible(self.app.tray is None and bool(self.app.tray_hint))

    def _build_logs(self):
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.log_view, 1)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 12)
        self.log_refresh = button("Refresh", "secondary", self._reload_logs)
        self.log_copy = button("Copy", "secondary",
                               lambda: QtWidgets.QApplication.clipboard().setText(self.log_view.toPlainText()))
        self.log_save = button("Save...", "secondary", self._save_logs)
        for b in (self.log_refresh, self.log_copy, self.log_save):
            bar.addWidget(b)
        lay.addLayout(bar)
        self._add("logs", "Logs", body)
        self._log_kind = "service_logs"

    def show_logs(self, kind):
        self._log_kind = kind
        self.pages["logs"].header.title.setText("Service Logs" if kind == "service_logs" else "Application Logs")
        self.show_page("logs")
        self._reload_logs()

    def _reload_logs(self):
        self.log_view.setPlainText("Loading...")
        if self._log_kind == "app_logs":
            self.app.read_app_log(self._show_log_text)
        else:
            self.app.read_service_log(self._show_log_text)

    def _show_log_text(self, text):
        self.log_view.setPlainText(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _save_logs(self):
        name = "ziti-edge-tunnel-%s.log" % time.strftime("%Y%m%d-%H%M%S")
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save log", os.path.expanduser("~/" + name))
        if fn:
            with open(fn, "w") as f:
                f.write(self.log_view.toPlainText())

    def _build_about(self):
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(24, 10, 24, 20)
        logo = QtWidgets.QLabel()
        logo.setPixmap(scaled("Ziti-Green.png", 96))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        t = label("Ziti Desktop Edge for Linux", size=14, align=Qt.AlignmentFlag.AlignCenter,
                  family=theme.FONT_TITLE)
        lay.addWidget(t)
        lay.addSpacing(12)
        self.ab_app = KeyValue("App version", __version__)
        self.ab_tunnel = KeyValue("ziti-edge-tunnel", "-")
        self.ab_rev = KeyValue("Tunnel revision", "-")
        self.ab_qt = KeyValue("Toolkit", "%s / Qt %s" % (QT_API, QtCore.qVersion()))
        self.ab_os = KeyValue("System", platform.platform(terse=True))
        for w in (self.ab_app, self.ab_tunnel, self.ab_rev, self.ab_qt, self.ab_os):
            lay.addWidget(w)
        lay.addSpacing(12)
        blurb = label("A desktop front end for the OpenZiti ziti-edge-tunnel service. "
                      "It controls the existing systemd service and its IPC sockets and does "
                      "not include or replace the tunneler. Community project, not affiliated with NetFoundry.",
                      role="muted", size=8.5, wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(blurb)
        lay.addSpacing(8)
        for text, url in (("Linux tunneler documentation", DOCS_URL),
                          ("ziti-edge-tunnel source", PROJECT_URL),
                          ("Community support", SUPPORT_URL)):
            l = label('<a href="%s" style="color:%s;">%s</a>' % (url, theme.BLUE_TEXT, text),
                      align=Qt.AlignmentFlag.AlignCenter)
            l.setOpenExternalLinks(True)
            lay.addWidget(l)
        lay.addStretch(1)
        self._add("about", "About", _scroll(inner))

    def _on_show_about(self):
        v = self.app.model.status.get("ServiceVersion") or {}
        self.ab_tunnel.set(v.get("Version") or "not connected")
        rev = v.get("Revision") or "-"
        if v.get("BuildDate"):
            rev += " (%s)" % v["BuildDate"]
        self.ab_rev.set(rev)


def _bool(v):
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)
