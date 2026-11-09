"""Identity details card and MFA screens (IdentityDetails.xaml / MFAScreen.xaml)."""
from .qt import QtCore, QtGui, QtWidgets, Qt
from . import theme
from .widgets import (Clickable, KeyValue, QrView, SlideOverlay, Toggler, button,
                      label, scaled, hline)


class _Card(SlideOverlay):
    """Dimmed backdrop with a white rounded card rising from the bottom."""

    def __init__(self, parent):
        super(_Card, self).__init__(parent, direction="up")
        self.setStyleSheet("_Card { background: rgba(7,8,38,0.55); }")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 26, 10, 0)
        self.card = QtWidgets.QWidget()
        self.card.setProperty("panel", "light")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setStyleSheet("QWidget#Card { background: white; border-top-left-radius: 14px;"
                                " border-top-right-radius: 14px; }")
        self.card.setObjectName("Card")
        outer.addWidget(self.card)
        self.body = QtWidgets.QVBoxLayout(self.card)
        self.body.setContentsMargins(18, 14, 18, 14)
        self.body.setSpacing(4)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(7, 8, 38, 140))

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.pos()):
            self.dismiss()


class IdentityDetails(_Card):
    def __init__(self, parent, app):
        super(IdentityDetails, self).__init__(parent)
        self.app = app
        self.identifier = None

        top = QtWidgets.QHBoxLayout()
        self.toggle = Toggler()
        self.toggle.toggled.connect(self._toggle)
        top.addWidget(self.toggle)
        self.title = label("", role="title", align=Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.title, 1)
        x = Clickable()
        xl = QtWidgets.QHBoxLayout(x)
        xl.setContentsMargins(0, 0, 0, 0)
        xi = QtWidgets.QLabel()
        xi.setPixmap(scaled("closeBlack.png", 18))
        xl.addWidget(xi)
        x.clicked.connect(self.dismiss)
        top.addWidget(x)
        self.body.addLayout(top)
        self.body.addWidget(hline("#E5E7EB"))

        self.kv_name = KeyValue("Name")
        self.body.addWidget(self.kv_name)
        mfa_row = QtWidgets.QHBoxLayout()
        mfa_row.setContentsMargins(0, 5, 0, 5)
        mfa_row.addWidget(label("Multi Factor Auth", role="key", size=9.5))
        mfa_row.addStretch(1)
        self.mfa_lock = QtWidgets.QLabel()
        self.mfa_lock.setPixmap(scaled("mfaoff.png", 28))
        mfa_row.addWidget(self.mfa_lock)
        self.mfa_toggle = Toggler()
        self.mfa_toggle.toggled.connect(self._mfa_toggled)
        mfa_row.addWidget(self.mfa_toggle)
        self.body.addLayout(mfa_row)
        self.kv_network = KeyValue("Network")
        self.kv_status = KeyValue("Status")
        self.kv_file = KeyValue("Identity File")
        for w in (self.kv_network, self.kv_status, self.kv_file):
            self.body.addWidget(w)

        self.auth_box = QtWidgets.QWidget()
        al = QtWidgets.QVBoxLayout(self.auth_box)
        al.setContentsMargins(0, 8, 0, 4)
        self.auth_msg = label("You must authenticate to access services", bold=True, size=9.5,
                              align=Qt.AlignmentFlag.AlignCenter, wrap=True)
        al.addWidget(self.auth_msg)
        self.auth_btn = button("Authenticate", "primary", self._authenticate)
        al.addWidget(self.auth_btn)
        self.body.addWidget(self.auth_box)

        svc_row = QtWidgets.QHBoxLayout()
        svc_row.setContentsMargins(0, 8, 0, 4)
        self.svc_count = label("0 Services", role="key", size=9.5)
        svc_row.addWidget(self.svc_count)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("search")
        self.search.textChanged.connect(self._fill_services)
        svc_row.addWidget(self.search, 1)
        self.body.addLayout(svc_row)

        self.svc_list = QtWidgets.QListWidget()
        self.svc_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.svc_list.setStyleSheet(
            "QListWidget { background: white; color: %s; border: none; }"
            "QListWidget::item { border-bottom: 1px solid #EDEFF3; padding: 6px 2px; }"
            "QListWidget::item:selected { background: #E5F0FF; color: %s; }" % (theme.TEXT_DARK, theme.TEXT_DARK))
        self.svc_list.itemDoubleClicked.connect(self._copy_service)
        self.body.addWidget(self.svc_list, 1)
        self.empty = QtWidgets.QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setPixmap(scaled("No_Services.png", 150))
        self.body.addWidget(self.empty, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.codes_btn = button("Recovery Codes", "secondary", self._recovery_codes)
        bottom.addWidget(self.codes_btn)
        self.refresh_btn = button("Refresh", "secondary", lambda: self.app.refresh_identity(self.identifier))
        bottom.addWidget(self.refresh_btn)
        self.body.addLayout(bottom)
        forget = button("Forget This Identity", "danger", self._forget)
        self.body.addWidget(forget, 0, Qt.AlignmentFlag.AlignHCenter)

        app.model.identitiesChanged.connect(self.refresh)

    def show_identity(self, identifier):
        self.identifier = identifier
        self.search.clear()
        self.refresh()
        self.open()

    def refresh(self):
        if not self.isVisible() and self.identifier is None:
            return
        ident = self.app.model.identity(self.identifier)
        if ident is None:
            if self.isVisible():
                self.dismiss()
            return
        self.toggle.set_checked_silent(ident.active)
        self.title.setText(ident.name)
        self.kv_name.set(ident.name)
        self.mfa_toggle.set_checked_silent(ident.mfa_enabled)
        self.mfa_toggle.setEnabled(ident.active and ident.loaded and not ident.needs_ext_auth)
        self.mfa_lock.setVisible(ident.mfa_enabled and ident.mfa_needed)
        net = ident.controller
        if ident.controller_version:
            net += " at " + ident.controller_version
        self.kv_network.set(net)
        self.kv_status.set(ident.status_text())
        self.kv_file.set(ident.identifier)
        needs = ident.active and (ident.mfa_needed or ident.needs_ext_auth)
        self.auth_box.setVisible(needs)
        if ident.needs_ext_auth:
            self.auth_btn.setText("Authenticate With Provider")
        else:
            self.auth_btn.setText("Authenticate")
        self.codes_btn.setVisible(ident.mfa_enabled and not ident.mfa_needed)
        self._fill_services()

    def _fill_services(self, *_):
        ident = self.app.model.identity(self.identifier)
        self.svc_list.clear()
        if ident is None:
            return
        q = self.search.text().strip().lower()
        svcs = sorted(ident.services, key=lambda s: (s.get("Name") or "").lower())
        n = 0
        for s in svcs:
            addrs = []
            for a in s.get("Addresses") or []:
                if a.get("IsHost"):
                    addrs.append(a.get("HostName") or "")
                else:
                    ip = a.get("IP") or ""
                    pre = a.get("Prefix")
                    addrs.append("%s/%s" % (ip, pre) if pre not in (None, 32) else ip)
            ports = []
            for pr in s.get("Ports") or []:
                lo, hi = pr.get("Low"), pr.get("High")
                ports.append(str(lo) if lo == hi else "%s-%s" % (lo, hi))
            protos = ",".join(s.get("Protocols") or [])
            name = s.get("Name") or "(unnamed)"
            blob = " ".join([name] + addrs + ports).lower()
            if q and q not in blob:
                continue
            n += 1
            perms = s.get("Permissions") or {}
            role = "host" if perms.get("Bind") and not perms.get("Dial") else (
                "dial+host" if perms.get("Bind") else "")
            line2 = ", ".join(a for a in addrs if a) or "-"
            if ports:
                line2 += "  :" + ",".join(ports)
            if protos:
                line2 += "  (" + protos.lower() + ")"
            access = "" if s.get("IsAccessible", True) else "  ⚠ posture check failing"
            item = QtWidgets.QListWidgetItem("%s%s%s\n%s" % (name, ("  [" + role + "]") if role else "",
                                                             access, line2))
            item.setToolTip("Double-click to copy the address")
            item.setData(Qt.ItemDataRole.UserRole, addrs[0] if addrs else name)
            self.svc_list.addItem(item)
        total = len(svcs)
        self.svc_count.setText("%d Service%s" % (total, "" if total == 1 else "s"))
        self.svc_list.setVisible(n > 0)
        self.empty.setVisible(n == 0)
        self.search.setVisible(total > 0)

    def _copy_service(self, item):
        QtWidgets.QApplication.clipboard().setText(item.data(Qt.ItemDataRole.UserRole) or "")
        self.app.message("Copied %s" % item.data(Qt.ItemDataRole.UserRole))

    def _toggle(self, on):
        self.app.set_identity_enabled(self.identifier, on)

    def _authenticate(self):
        ident = self.app.model.identity(self.identifier)
        if ident is None:
            return
        if ident.needs_ext_auth:
            self.app.external_auth(self.identifier)
        else:
            self.app.window.mfa.authenticate(self.identifier)

    def _mfa_toggled(self, on):
        ident = self.app.model.identity(self.identifier)
        self.mfa_toggle.set_checked_silent(ident.mfa_enabled if ident else False)
        if on:
            self.app.window.mfa.setup(self.identifier)
        else:
            self.app.window.mfa.remove(self.identifier)

    def _recovery_codes(self):
        self.app.window.mfa.show_codes_prompt(self.identifier)

    def _forget(self):
        ident = self.app.model.identity(self.identifier)
        if ident is None:
            return
        r = QtWidgets.QMessageBox.question(
            self, "Forget identity",
            "Forget “%s”?\n\nThe identity file is deleted from the tunnel and cannot be "
            "recovered; you would need a new enrollment token to rejoin." % ident.name)
        if r == QtWidgets.QMessageBox.StandardButton.Yes:
            self.app.forget_identity(self.identifier)
            self.dismiss()


class MfaScreen(_Card):
    """MFA setup (QR + verify), authentication and recovery codes."""

    def __init__(self, parent, app):
        super(MfaScreen, self).__init__(parent)
        self.app = app
        self.identifier = None
        self.mode = None
        self.secret_url = ""
        top = QtWidgets.QHBoxLayout()
        self.title = label("", role="title", align=Qt.AlignmentFlag.AlignCenter)
        top.addSpacing(18)
        top.addWidget(self.title, 1)
        x = Clickable()
        xl = QtWidgets.QHBoxLayout(x)
        xl.setContentsMargins(0, 0, 0, 0)
        xi = QtWidgets.QLabel()
        xi.setPixmap(scaled("closeBlack.png", 18))
        xl.addWidget(xi)
        x.clicked.connect(self.dismiss)
        top.addWidget(x)
        self.body.addLayout(top)
        self.body.addWidget(hline("#E5E7EB"))
        self.subtitle = label("", role="muted", wrap=True, align=Qt.AlignmentFlag.AlignCenter, size=9.5)
        self.body.addWidget(self.subtitle)
        self.qr = QrView()
        self.body.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignHCenter)
        self.secret = label("", size=9, wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        self.secret.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(self.secret)
        links = QtWidgets.QHBoxLayout()
        self.link_btn = button("Open Link", "secondary", self._open_link)
        self.copy_btn = button("Copy Secret", "secondary", self._copy_secret)
        links.addWidget(self.link_btn)
        links.addWidget(self.copy_btn)
        self.body.addLayout(links)
        self.codes = QtWidgets.QPlainTextEdit()
        self.codes.setReadOnly(True)
        self.codes.setFont(QtGui.QFont("monospace", 11))
        self.body.addWidget(self.codes, 1)
        self.code_edit = QtWidgets.QLineEdit()
        self.code_edit.setPlaceholderText("Authentication or recovery code")
        self.code_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_edit.setFont(theme.font(14))
        self.code_edit.returnPressed.connect(self._submit)
        self.body.addWidget(self.code_edit)
        self.error = label("", color=theme.RED, wrap=True, align=Qt.AlignmentFlag.AlignCenter, size=9)
        self.body.addWidget(self.error)
        self.go = button("Authenticate", "primary", self._submit)
        self.body.addWidget(self.go)
        row = QtWidgets.QHBoxLayout()
        self.regen_btn = button("Regenerate", "secondary", self._regen)
        self.save_btn = button("Save Codes", "secondary", self._save_codes)
        row.addWidget(self.regen_btn)
        row.addWidget(self.save_btn)
        self.body.addLayout(row)
        self.body.addStretch(1)

    def _layout(self, mode):
        self.mode = mode
        setup = mode == "setup"
        codes = mode == "codes"
        self.qr.setVisible(setup and QrView.available())
        self.secret.setVisible(setup)
        self.link_btn.setVisible(setup)
        self.copy_btn.setVisible(setup)
        self.codes.setVisible(codes)
        self.code_edit.setVisible(not codes)
        self.go.setVisible(not codes)
        self.regen_btn.setVisible(codes)
        self.save_btn.setVisible(codes)
        self.error.setText("")
        self.code_edit.clear()
        self.go.setEnabled(True)

    def _name(self):
        ident = self.app.model.identity(self.identifier)
        return ident.name if ident else ""

    # -- entry points ---------------------------------------------------------
    def setup(self, identifier):
        self.identifier = identifier
        self._layout("setup")
        self.title.setText("Setup MFA")
        self.subtitle.setText("Starting MFA enrollment for %s..." % self._name())
        self.secret.setText("")
        self.open()
        self.app.ipc_call("EnableMFA", {"Identifier": identifier}, self._enrolled)

    def _enrolled(self, res):
        if not res.success:
            self.error.setText(res.error or "MFA enrollment failed")
            return
        data = res.data or {}
        self.secret_url = data.get("ProvisioningUrl") or ""
        self.pending_codes = data.get("RecoveryCodes") or []
        q = QtCore.QUrlQuery(QtCore.QUrl(self.secret_url).query())
        secret = q.queryItemValue("secret") or ""
        self.subtitle.setText("Scan the QR code with an authenticator app (or add the secret "
                              "manually), then enter the code below to finish setup.")
        if QrView.available():
            self.qr.set_data(self.secret_url)
        self.secret.setText("Secret: <b>%s</b>" % secret if secret else self.secret_url)
        self.go.setText("Verify")
        self.code_edit.setFocus()

    def authenticate(self, identifier):
        self.identifier = identifier
        self._layout("auth")
        self.title.setText("Authorize MFA")
        self.subtitle.setText("Enter the code from your authenticator app (or a recovery code) for %s"
                              % self._name())
        self.go.setText("Authenticate")
        self.open()
        self.code_edit.setFocus()

    def remove(self, identifier):
        self.identifier = identifier
        self._layout("remove")
        self.title.setText("Remove MFA")
        self.subtitle.setText("Enter an authentication code to turn off MFA for %s" % self._name())
        self.go.setText("Remove MFA")
        self.open()
        self.code_edit.setFocus()

    def show_codes_prompt(self, identifier):
        self.identifier = identifier
        self._layout("codes_prompt")
        self.title.setText("MFA Recovery Codes")
        self.subtitle.setText("Enter an authentication code to view the recovery codes")
        self.go.setText("Show Codes")
        self.open()
        self.code_edit.setFocus()

    def _show_codes(self, codes, note):
        self._layout("codes")
        self.title.setText("MFA Recovery Codes")
        self.subtitle.setText(note)
        rows = [" ".join(codes[i:i + 2]) for i in range(0, len(codes), 2)]
        self.codes.setPlainText("\n".join(rows))

    # -- actions --------------------------------------------------------------
    def _submit(self):
        code = self.code_edit.text().strip()
        if not code:
            self.error.setText("Please enter a code")
            return
        self.go.setEnabled(False)
        self.error.setText("")
        payload = {"Identifier": self.identifier, "Code": code}
        self._last_code = code
        cmd = {"setup": "VerifyMFA", "auth": "SubmitMFA", "remove": "RemoveMFA",
               "codes_prompt": "GetMFACodes"}[self.mode]
        self.app.ipc_call(cmd, payload, lambda res, c=cmd: self._after(c, res))

    def _after(self, cmd, res):
        self.go.setEnabled(True)
        if not res.success:
            self.error.setText(res.error or "The code was not accepted")
            self.code_edit.selectAll()
            return
        if cmd == "VerifyMFA":
            codes = getattr(self, "pending_codes", []) or []
            self.app.message("MFA is now enabled for %s" % self._name())
            if codes:
                self._show_codes(codes, "MFA is enabled. Save these recovery codes somewhere safe; "
                                        "each can be used once instead of an authenticator code.")
            else:
                self.dismiss()
        elif cmd == "SubmitMFA":
            self.app.message("Authenticated %s" % self._name())
            self.dismiss()
        elif cmd == "RemoveMFA":
            self.app.message("MFA removed from %s" % self._name())
            self.dismiss()
        elif cmd in ("GetMFACodes", "GenerateMFACodes"):
            data = res.data or {}
            self._show_codes(data.get("RecoveryCodes") or [], "Each code can be used once.")
        self.app.request_status()

    def _regen(self):
        code, ok = QtWidgets.QInputDialog.getText(self, "Regenerate codes",
                                                  "Authentication code (old recovery codes stop working):")
        if ok and code.strip():
            self.app.ipc_call("GenerateMFACodes", {"Identifier": self.identifier, "Code": code.strip()},
                              lambda res: self._after("GenerateMFACodes", res) if res.success
                              else self.app.message(res.error or "Failed", error=True))

    def _save_codes(self):
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save recovery codes",
                                                      QtCore.QDir.homePath() + "/%s-recovery-codes.txt"
                                                      % (self._name() or "ziti"))
        if fn:
            with open(fn, "w") as f:
                f.write(self.codes.toPlainText() + "\n")

    def _open_link(self):
        if self.secret_url:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.secret_url))

    def _copy_secret(self):
        q = QtCore.QUrlQuery(QtCore.QUrl(self.secret_url).query())
        QtWidgets.QApplication.clipboard().setText(q.queryItemValue("secret") or self.secret_url)
        self.app.message("Secret copied")
