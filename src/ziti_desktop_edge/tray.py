"""System tray icon, like the Windows notification-area icon."""
from .qt import QtGui, QtWidgets, QAction
from . import paths


def _icon(name):
    return QtGui.QIcon(paths.asset("images", name))


class Tray(QtWidgets.QSystemTrayIcon):
    def __init__(self, app):
        super(Tray, self).__init__(app.qapp)
        self.app = app
        self._icons = {
            "on": _icon("Ziti-Green.png"),
            "off": _icon("Ziti-White.png"),
            "error": _icon("Ziti-Red.png"),
            "mfa_on": _icon("ziti-green-mfa.png"),
            "mfa_off": _icon("ziti-white-mfa.png"),
            "timer": _icon("ziti-green-timer.png"),
        }
        self.setIcon(self._icons["off"])
        self.setToolTip(paths.APP_NAME)
        menu = QtWidgets.QMenu()
        self.menu = menu
        self.a_show = QAction("Show Ziti Desktop Edge", menu)
        self.a_show.triggered.connect(app.window.show_and_raise)
        self.a_status = QAction("", menu)
        self.a_status.setEnabled(False)
        self.a_connect = QAction("Connect", menu)
        self.a_connect.triggered.connect(app.toggle_connection)
        self.a_restart = QAction("Restart Tunnel Service", menu)
        self.a_restart.triggered.connect(app.restart_tunnel)
        self.ids_menu = QtWidgets.QMenu("Identities", menu)
        self.a_quit = QAction("Quit", menu)
        self.a_quit.triggered.connect(app.quit)
        menu.addAction(self.a_show)
        menu.addSeparator()
        menu.addAction(self.a_status)
        menu.addAction(self.a_connect)
        menu.addAction(self.a_restart)
        menu.addMenu(self.ids_menu)
        menu.addSeparator()
        menu.addAction(self.a_quit)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        menu.aboutToShow.connect(self._fill_ids)

    def _activated(self, reason):
        R = QtWidgets.QSystemTrayIcon.ActivationReason
        if reason in (R.Trigger, R.DoubleClick):
            self.app.window.toggle_visible()

    def _fill_ids(self):
        self.ids_menu.clear()
        ids = self.app.model.sorted_identities()
        self.ids_menu.setEnabled(bool(ids))
        for ident in ids:
            a = self.ids_menu.addAction(ident.name)
            a.setCheckable(True)
            a.setChecked(ident.active)
            a.toggled.connect(lambda on, i=ident.identifier: self.app.set_identity_enabled(i, on))

    def update_state(self):
        a = self.app
        st = a.service.state
        connected = st.running and a.events.is_connected()
        mfa = a.model.any_mfa_needed()
        if st.active_state == "failed" or (not st.installed and st.load_state != "unknown"):
            key = "error"
        elif connected and a.model.any_timing_out():
            key = "timer"
        elif connected:
            key = "mfa_on" if mfa else "on"
        else:
            key = "mfa_off" if mfa else "off"
        self.setIcon(self._icons[key])
        status = a.window.connect_label.text()
        if status == "Tap to Connect":
            status = "Disconnected"
        self.a_status.setText("Status: %s" % status)
        self.setToolTip("%s - %s" % (paths.APP_NAME, status))
        self.a_connect.setText("Disconnect" if st.running else "Connect")
        self.a_connect.setEnabled(st.installed and not a.service.busy())
        self.a_restart.setEnabled(st.installed and st.running)
