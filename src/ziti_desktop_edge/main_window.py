"""Main window, laid out like MainWindow.xaml of Ziti Desktop Edge for Windows."""

from .qt import QtCore, QtGui, QtWidgets, Qt, exec_
from . import paths, theme
from .identity_panel import IdentityDetails, MfaScreen
from .main_menu import MainMenu
from .widgets import (Blurb, Clickable, ConnectButton, IdentityRow, ImageButton, SpeedStat,
                      button, hline, label, pixmap, scaled)


class SortHeader(Clickable):
    def __init__(self, text, key, parent=None):
        super(SortHeader, self).__init__(parent)
        self.key = key
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.lb = label(text, role="header")
        self.arrow = label("", role="header")
        lay.addWidget(self.lb)
        lay.addWidget(self.arrow)

    def set_active(self, on):
        self.arrow.setText("▾" if on else "")
        self.lb.setStyleSheet("color: white;" if on else "")


class MainWindow(QtWidgets.QWidget):
    def __init__(self, app):
        super(MainWindow, self).__init__()
        self.app = app
        self.setWindowTitle(paths.APP_NAME)
        self.setWindowIcon(QtGui.QIcon(paths.asset("images", "Ziti-Green.png")))
        self.setMinimumSize(380, 600)
        self.resize(430, 760)
        self.setAcceptDrops(True)
        self._rows = {}
        self._bg = pixmap("background.png")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        view = QtWidgets.QWidget()
        view.setObjectName("MainView")
        root.addWidget(view)
        lay = QtWidgets.QVBoxLayout(view)
        lay.setContentsMargins(10, 4, 10, 0)
        lay.setSpacing(0)

        # header -----------------------------------------------------------
        header = QtWidgets.QHBoxLayout()
        self.menu_btn = ImageButton("hamburger.png", "MAIN", "MENU")
        self.menu_btn.setToolTip("Main menu")
        self.menu_btn.clicked.connect(lambda: self.menu.open_menu())
        header.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignTop)
        center = QtWidgets.QVBoxLayout()
        center.setContentsMargins(0, 12, 0, 0)
        center.setSpacing(2)
        logo = QtWidgets.QLabel()
        logo.setPixmap(scaled("z.png", 25, 40))
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center.addWidget(logo)
        self.connect_label = label("Tap to Connect", align=Qt.AlignmentFlag.AlignHCenter)
        self.connect_label.setFont(theme.font(12, family=theme.FONT_TITLE))
        center.addWidget(self.connect_label)
        header.addLayout(center, 1)
        self.add_btn = ImageButton("identity.png", "ADD", "IDENTITY", align=Qt.AlignmentFlag.AlignRight)
        self.add_btn.setToolTip("Add an identity")
        self.add_btn.clicked.connect(self._add_menu)
        header.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(header)

        # connect button + stats -------------------------------------------
        self.connect_btn = ConnectButton()
        self.connect_btn.clicked.connect(self.app.toggle_connection)
        lay.addSpacing(4)
        lay.addWidget(self.connect_btn)

        self.stats = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(self.stats)
        sl.setContentsMargins(0, 6, 0, 8)
        self.down = SpeedStat("Download Speed", "down.png", theme.BLUE_TEXT)
        self.up = SpeedStat("Upload Speed", "up.png", theme.UPLOAD_RED)
        sl.addWidget(self.down)
        sl.addWidget(self.up)
        lay.addWidget(self.stats)

        # problem notice (service missing / permissions) --------------------
        self.notice = QtWidgets.QWidget()
        self.notice.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.notice.setStyleSheet("QWidget#Notice { background: rgba(43,48,70,0.85); border-radius: 10px; }")
        self.notice.setObjectName("Notice")
        nl = QtWidgets.QVBoxLayout(self.notice)
        nl.setContentsMargins(14, 12, 14, 12)
        self.notice_text = label("", wrap=True, size=9.5, align=Qt.AlignmentFlag.AlignCenter)
        self.notice_text.setOpenExternalLinks(True)
        nl.addWidget(self.notice_text)
        self.notice_btn = button("", "primary")
        nl.addWidget(self.notice_btn)
        self.notice_btn.clicked.connect(self._notice_action)
        self.notice_dismiss = button("Not now", "flat")
        self.notice_dismiss.setStyleSheet("color: #7d8faf; font-size: 11px;")
        self.notice_dismiss.clicked.connect(self.app.dismiss_tray_hint)
        nl.addWidget(self.notice_dismiss, 0, Qt.AlignmentFlag.AlignHCenter)
        self._notice_fn = None
        lay.addWidget(self.notice)
        lay.addSpacing(8)

        # identity list ----------------------------------------------------
        hdr = QtWidgets.QHBoxLayout()
        hdr.setContentsMargins(14, 0, 22, 4)
        self.sort_status = SortHeader("Status", "status")
        self.sort_name = SortHeader("Name", "name")
        self.sort_services = SortHeader("Services", "services")
        self.sort_status.setFixedWidth(64)
        hdr.addWidget(self.sort_status)
        hdr.addWidget(self.sort_name, 1)
        hdr.addWidget(self.sort_services)
        for h in (self.sort_status, self.sort_name, self.sort_services):
            h.clicked.connect(lambda h=h: self._sort(h.key))
        lay.addLayout(hdr)
        lay.addWidget(hline())
        self.list_area = QtWidgets.QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        self.list_lay = QtWidgets.QVBoxLayout(inner)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(0)
        self.list_lay.addStretch(1)
        self.list_area.setWidget(inner)
        lay.addWidget(self.list_area, 1)
        self.empty_hint = Clickable()
        el = QtWidgets.QVBoxLayout(self.empty_hint)
        self.empty_label = label("No identities yet — click ADD IDENTITY or drop a .jwt file here",
                                 color=theme.BLUE_TEXT, align=Qt.AlignmentFlag.AlignCenter, wrap=True, size=9.5)
        el.addWidget(self.empty_label)
        self.empty_hint.clicked.connect(self.add_jwt)
        lay.addWidget(self.empty_hint)
        lay.addSpacing(10)

        # overlays ---------------------------------------------------------
        self.blurb = Blurb(self)
        self.menu = MainMenu(self, app)
        self.details = IdentityDetails(self, app)
        self.mfa = MfaScreen(self, app)

        self._sort_key = app.settings.value("sort", "name") or "name"
        self._sort(self._sort_key, save=False)
        app.model.identitiesChanged.connect(self.refresh_identities)
        app.model.metricsChanged.connect(self._metrics)
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self.refresh_connection)
        self._tick.start()
        self.refresh_identities()
        self.refresh_connection()

    # -- painting & geometry -------------------------------------------------
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        if not self._bg.isNull():
            p.drawPixmap(self.rect(), self._bg)
        else:
            g = QtGui.QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QtGui.QColor("#262b45"))
            g.setColorAt(1, QtGui.QColor("#0f1124"))
            p.fillRect(self.rect(), g)

    def resizeEvent(self, e):
        super(MainWindow, self).resizeEvent(e)
        self._place_blurb()

    def _place_blurb(self):
        h = max(44, self.blurb.sizeHint().height())
        self.blurb.setGeometry(0, self.height() - h, self.width(), h)

    def show_message(self, text, error=False, action=None, timeout_ms=6000):
        self.blurb.show_message(text, error, action, timeout_ms)
        self._place_blurb()

    # -- state ------------------------------------------------------------------
    def refresh_connection(self):
        a = self.app
        st = a.service.state
        connected = st.running and a.events.is_connected()
        busy = st.transitioning or a.service.busy() or (st.running and not a.events.is_connected()
                                                         and a.perm_ok is not False)
        self.connect_btn.set_state(st.running, busy, st.uptime())
        if not st.installed and st.load_state != "unknown":
            text = "Not Installed"
        elif st.active_state == "activating" or (st.running and not a.events.is_connected() and busy):
            text = "Connecting..."
        elif st.active_state == "deactivating":
            text = "Disconnecting..."
        elif connected:
            text = "Connected"
        elif st.running:
            text = "Running"
        elif st.active_state == "failed":
            text = "Service Failed"
        else:
            text = "Tap to Connect"
        self.connect_label.setText(text)
        self.stats.setVisible(connected)
        self._update_notice()

    def _update_notice(self):
        a = self.app
        st = a.service.state
        msg, btn, fn = None, None, None
        dismissable = False
        if not st.installed and st.load_state != "unknown":
            msg = ("The <b>ziti-edge-tunnel</b> service was not found.<br>Install it from "
                   '<a style="color:#7EB4EA" href="https://netfoundry.io/docs/openziti/downloads/?os=Linux">'
                   "OpenZiti downloads</a>, then reopen this app.")
        elif a.perm_ok is False:
            if a.listed_in_group:
                msg = ("You were added to the <b>%s</b> group, but this login session started before that. "
                       "Log out and back in to control the tunnel." % paths.ZITI_GROUP)
            else:
                msg = ("Your account is not in the <b>%s</b> group, so the app cannot talk to the "
                       "tunnel service." % paths.ZITI_GROUP)
                btn, fn = "Add me to the %s group" % paths.ZITI_GROUP, a.join_group
        elif st.running and not a.events.is_connected() and a.events.last_error and st.uptime() and st.uptime() > 15:
            msg = "Waiting for the tunnel's IPC socket: %s" % a.events.last_error
        elif st.active_state == "failed":
            msg = "ziti-edge-tunnel failed to start. See Main Menu › Advanced Settings › Service Logs."
            btn, fn = "View Service Logs", lambda: (self.menu.open_menu(), self.menu.show_logs("service_logs"))
        elif a.tray_hint and str(a.settings.value("tray_hint_dismissed", "false")).lower() != "true":
            dismissable = True
            if a.tray_hint == "enabled":
                msg = "Log out and back in to show the Ziti icon in the top bar."
            else:
                msg = ("GNOME does not show tray icons by default, so Ziti Desktop Edge runs in the "
                       "background without one. Turn on top bar icons to control the tunnel from there.")
                btn = ("Show icon in top bar" if a.tray_hint == "missing" else "Enable top bar icon")
                fn = a.fix_tray
        self.notice.setVisible(bool(msg))
        if msg:
            self.notice_text.setText(msg)
        self.notice_btn.setVisible(bool(btn))
        if btn:
            self.notice_btn.setText(btn)
        self.notice_dismiss.setVisible(dismissable)
        self._notice_fn = fn

    def _notice_action(self):
        if self._notice_fn:
            self._notice_fn()

    def _metrics(self, up, down):
        self.up.set_rate(up)
        self.down.set_rate(down)

    def _sort(self, key, save=True):
        self._sort_key = key
        for h in (self.sort_status, self.sort_name, self.sort_services):
            h.set_active(h.key == key)
        if save:
            self.app.settings.setValue("sort", key)
            self.refresh_identities()

    def refresh_identities(self):
        ids = self.app.model.sorted_identities(self._sort_key)
        keep = set(i.identifier for i in ids)
        for ident in list(self._rows):
            if ident not in keep:
                self._rows.pop(ident).deleteLater()
        for idx, ident in enumerate(ids):
            row = self._rows.get(ident.identifier)
            if row is None:
                row = IdentityRow(ident)
                row.toggled.connect(self.app.set_identity_enabled)
                row.opened.connect(self.open_identity)
                self._rows[ident.identifier] = row
            else:
                row.refresh(ident)
            self.list_lay.insertWidget(idx, row)
        connected = self.app.events.is_connected()
        self.empty_hint.setVisible(connected and not ids)
        if not connected:
            self.empty_hint.setVisible(False)

    def open_identity(self, identifier):
        if self.menu.isVisible():
            self.menu.dismiss()
        self.details.show_identity(identifier)

    # -- add identity ---------------------------------------------------------
    def _add_menu(self):
        m = QtWidgets.QMenu(self)
        m.addAction("With JWT", self.add_jwt)
        m.addAction("With URL", self.add_url)
        exec_(m, self.add_btn.mapToGlobal(QtCore.QPoint(0, self.add_btn.height())))

    def add_jwt(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select an enrollment token", QtCore.QDir.homePath(),
            "Ziti enrollment token (*.jwt);;All files (*)")
        if fn:
            self.app.add_identity_jwt(fn)

    def add_url(self):
        dlg = AddByUrlDialog(self)
        if exec_(dlg) == QtWidgets.QDialog.DialogCode.Accepted:
            self.app.add_identity_url(dlg.url.text().strip(), dlg.name.text().strip())

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().endswith((".jwt", ".deb", ".rpm"))
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            f = u.toLocalFile()
            if f.endswith(".jwt"):
                self.app.add_identity_jwt(f)
            elif f.endswith((".deb", ".rpm")):
                self.app.install_update_file(f)

    # -- window behaviour -----------------------------------------------------
    def closeEvent(self, e):
        if self.app.close_to_tray():
            e.ignore()
            self.hide()
            self.app.first_hide_hint()
        else:
            e.accept()
            self.app.quit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            for ov in (self.mfa, self.details, self.menu):
                if ov.isVisible():
                    ov.dismiss()
                    return
        super(MainWindow, self).keyPressEvent(e)

    def toggle_visible(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_and_raise()

    def show_and_raise(self):
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()


class AddByUrlDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(AddByUrlDialog, self).__init__(parent)
        self.setWindowTitle("Add identity with URL")
        self.setProperty("panel", "light")
        self.setStyleSheet("QDialog { background: white; } QLabel { color: %s; }" % theme.TEXT_DARK)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(label("Join a network that uses an external identity provider.",
                            wrap=True, size=9.5, color=theme.TEXT_DARK))
        lay.addWidget(label("Controller URL", bold=True, size=9.5, color=theme.TEXT_DARK))
        self.url = QtWidgets.QLineEdit()
        self.url.setPlaceholderText("https://controller.example.com:443")
        lay.addWidget(self.url)
        lay.addWidget(label("Identity Name", bold=True, size=9.5, color=theme.TEXT_DARK))
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("my-laptop")
        lay.addWidget(self.name)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", "secondary", self.reject))
        self.ok = button("Join Network", "primary", self._accept)
        row.addWidget(self.ok)
        lay.addSpacing(8)
        lay.addLayout(row)
        self.resize(380, 0)

    def _accept(self):
        u = QtCore.QUrl(self.url.text().strip())
        if u.scheme() not in ("https", "http") or not u.host():
            self.url.setProperty("invalid", "true")
            self.url.style().polish(self.url)
            return
        if not self.name.text().strip():
            self.name.setText(u.host())
        self.accept()
