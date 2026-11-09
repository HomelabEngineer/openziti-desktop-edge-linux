"""Reusable widgets styled after the Windows/Android Ziti Desktop Edge."""
from .qt import QtCore, QtGui, QtWidgets, Qt, Signal
from . import paths, theme

_pix_cache = {}


def pixmap(name):
    p = _pix_cache.get(name)
    if p is None:
        p = QtGui.QPixmap(paths.asset("images", name))
        _pix_cache[name] = p
    return p


def scaled(name, w, h=None, dpr=None):
    """Return a crisp, HiDPI-aware scaled pixmap."""
    pm = pixmap(name)
    if pm.isNull():
        return pm
    ratio = dpr or (QtWidgets.QApplication.instance().devicePixelRatio()
                    if QtWidgets.QApplication.instance() else 1.0)
    h = h or int(round(pm.height() * float(w) / pm.width()))
    out = pm.scaled(int(w * ratio), int(h * ratio),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(ratio)
    return out


def label(text="", role=None, size=None, bold=False, color=None, align=None, wrap=False, family=None):
    lb = QtWidgets.QLabel(text)
    if role:
        lb.setProperty("role", role)
    if size or bold or family:
        lb.setFont(theme.font(size or 10, bold, family or theme.FONT_BODY))
    if color:
        lb.setStyleSheet("color: %s;" % color)
    if align is not None:
        lb.setAlignment(align)
    if wrap:
        lb.setWordWrap(True)
    return lb


def button(text, kind="primary", slot=None):
    b = QtWidgets.QPushButton(text)
    b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def hline(color="rgba(255,255,255,0.1)"):
    f = QtWidgets.QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet("background: %s;" % color)
    return f


class Clickable(QtWidgets.QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super(Clickable, self).__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit()
        super(Clickable, self).mouseReleaseEvent(e)


class Toggler(QtWidgets.QAbstractButton):
    """35x20 pill switch (Views/Controls/Toggler.xaml)."""

    def __init__(self, parent=None, checked=False):
        super(Toggler, self).__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def _set_pos(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_checked_silent(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._anim.stop()
        self._set_pos(1.0 if on else 0.0)

    def sizeHint(self):
        return QtCore.QSize(38, 22)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(1.5, 1.5, 35, 19)
        off = QtGui.QColor(theme.TOGGLE_OFF)
        on = QtGui.QColor(theme.GREEN)
        t = self._pos
        col = QtGui.QColor(int(off.red() + (on.red() - off.red()) * t),
                           int(off.green() + (on.green() - off.green()) * t),
                           int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            col.setAlpha(120)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, 9.5, 9.5)
        knob = QtCore.QRectF(r.x() + 1 + t * 16, r.y() + 0.5, 18, 18)
        p.setBrush(QtGui.QColor("white"))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 30), 1))
        p.drawEllipse(knob)


class ImageButton(Clickable):
    """Icon over a two-line caption, e.g. MAIN/MENU and ADD/IDENTITY."""

    def __init__(self, image, line1, line2, align=Qt.AlignmentFlag.AlignLeft, parent=None):
        super(ImageButton, self).__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 16, 14, 8)
        lay.setSpacing(1)
        icon = QtWidgets.QLabel()
        icon.setPixmap(scaled(image, 26, 26))
        icon.setAlignment(align)
        lay.addWidget(icon)
        for t in (line1, line2):
            lb = label(t, role="tiny", align=align)
            lb.setFont(theme.font(7.5))
            lay.addWidget(lb)
        lay.addStretch(1)
        self.setFixedWidth(100)


class ConnectButton(Clickable):
    """Large power button; shows uptime and STOP while connected."""

    def __init__(self, parent=None):
        super(ConnectButton, self).__init__(parent)
        self.setFixedHeight(160)
        self._connected = False
        self._busy = False
        self._time = "00:00:00"
        self._angle = 0
        self._spin = QtCore.QTimer(self)
        self._spin.setInterval(40)
        self._spin.timeout.connect(self._tick)

    def _tick(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def set_state(self, connected, busy=False, elapsed=None):
        self._connected = connected
        self._busy = busy
        if busy and not self._spin.isActive():
            self._spin.start()
        elif not busy:
            self._spin.stop()
        if elapsed is not None:
            s = int(elapsed)
            self._time = "%02d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60)
        self.setToolTip("Disconnect (stop ziti-edge-tunnel)" if connected
                        else "Connect (start ziti-edge-tunnel)")
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        size = 140
        x = (self.width() - size) // 2
        rect = QtCore.QRect(x, 0, size, size)
        pm = pixmap("connected.png" if self._connected else "connect.png")
        p.drawPixmap(rect, pm)
        if self._busy:
            pen = QtGui.QPen(QtGui.QColor(theme.BLUE_TEXT), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect.adjusted(3, 3, -3, -3), -self._angle * 16, 90 * 16)
        if self._connected:
            p.setPen(QtGui.QColor("white"))
            p.setFont(theme.font(9))
            p.drawText(QtCore.QRect(x, 88, size, 18), Qt.AlignmentFlag.AlignHCenter, self._time)
            p.setFont(theme.font(8))
            p.drawText(QtCore.QRect(x, 104, size, 18), Qt.AlignmentFlag.AlignHCenter, "STOP")


class SpeedStat(QtWidgets.QWidget):
    def __init__(self, title, icon, color, parent=None):
        super(SpeedStat, self).__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(label(title, size=10.5))
        ic = QtWidgets.QLabel()
        ic.setPixmap(scaled(icon, 18, 18))
        row.addWidget(ic)
        row.addStretch(1)
        lay.addLayout(row)
        self.value = label("0", align=Qt.AlignmentFlag.AlignHCenter)
        self.value.setFont(theme.font(28))
        self.value.setStyleSheet("color: %s;" % color)
        lay.addWidget(self.value)
        self.unit = label("KBps", role="tiny", align=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.unit)

    def set_rate(self, bytes_per_sec):
        v = float(bytes_per_sec or 0)
        units = ["Bps", "KBps", "MBps", "GBps"]
        i = 1
        v = v / 1000.0
        while v >= 1000 and i < len(units) - 1:
            v /= 1000.0
            i += 1
        self.value.setText(("%.1f" % v) if v < 100 else ("%d" % v))
        self.unit.setText(units[i])


class IdentityRow(Clickable):
    """Row in the main identity list (Views/ItemRenderers/IdentityItem.xaml)."""

    toggled = Signal(str, bool)
    opened = Signal(str)

    def __init__(self, identity, parent=None):
        super(IdentityRow, self).__init__(parent)
        self.identifier = identity.identifier
        self.setFixedHeight(64)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(10, 4, 10, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)

        self.toggle = Toggler(checked=identity.active)
        self.toggle.toggled.connect(lambda on: self.toggled.emit(self.identifier, on))
        tbox = QtWidgets.QVBoxLayout()
        tbox.setSpacing(2)
        tbox.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignHCenter)
        self.toggle_label = label("", role="tiny", align=Qt.AlignmentFlag.AlignHCenter)
        tbox.addWidget(self.toggle_label)
        tw = QtWidgets.QWidget()
        tw.setLayout(tbox)
        tw.setFixedWidth(62)
        grid.addWidget(tw, 0, 0, 2, 1)

        self.name = label("", size=12)
        self.url = label("", role="tiny")
        grid.addWidget(self.name, 0, 1, Qt.AlignmentFlag.AlignBottom)
        grid.addWidget(self.url, 1, 1, Qt.AlignmentFlag.AlignTop)

        self.badge = QtWidgets.QLabel()
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedSize(46, 26)
        self.badge_label = label("services", role="tiny", align=Qt.AlignmentFlag.AlignHCenter)
        bbox = QtWidgets.QVBoxLayout()
        bbox.setSpacing(1)
        bbox.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)
        bbox.addWidget(self.badge_label)
        bw = QtWidgets.QWidget()
        bw.setLayout(bbox)
        bw.setFixedWidth(76)
        grid.addWidget(bw, 0, 2, 2, 1)

        arrow = QtWidgets.QLabel()
        arrow.setPixmap(scaled("next.png", 10))
        grid.addWidget(arrow, 0, 3, 2, 1)
        grid.setColumnStretch(1, 1)
        self.clicked.connect(lambda: self.opened.emit(self.identifier))
        self.refresh(identity)

    def refresh(self, ident):
        self.toggle.set_checked_silent(ident.active)
        self.toggle_label.setText("ENABLED" if ident.active else "DISABLED")
        fm = QtGui.QFontMetrics(self.name.font())
        self.name.setText(fm.elidedText(ident.name, Qt.TextElideMode.ElideRight, 200))
        self.name.setToolTip(ident.name)
        url = ident.controller
        fm2 = QtGui.QFontMetrics(self.url.font())
        self.url.setText(fm2.elidedText(url, Qt.TextElideMode.ElideRight, 200))
        if ident.active and ident.needs_ext_auth:
            self.badge.setPixmap(scaled("ext-auth-needed.png", 34))
            self.badge.setStyleSheet("")
            self.badge_label.setText("authenticate")
        elif ident.active and ident.mfa_needed:
            self.badge.setPixmap(scaled("mfaoff.png", 34))
            self.badge.setStyleSheet("")
            self.badge_label.setText("authorize")
        elif ident.active and ident.mfa_enabled and 0 <= (ident.min_timeout_remaining or -1) < 20 * 60:
            self.badge.setPixmap(scaled("timer.png", 24))
            self.badge.setStyleSheet("")
            self.badge_label.setText("timing out")
        else:
            self.badge.setPixmap(QtGui.QPixmap())
            self.badge.setText(str(len(ident.services)))
            self.badge.setFont(theme.font(10.5))
            self.badge.setStyleSheet("background: %s; color: white; border-radius: 13px;" % theme.BLUE)
            self.badge_label.setText("services")
        self.setToolTip("%s\n%s - %s" % (ident.name, url, ident.status_text()))

    def paintEvent(self, e):
        if self.underMouse():
            p = QtGui.QPainter(self)
            p.fillRect(self.rect(), QtGui.QColor(255, 255, 255, 18))
        super(IdentityRow, self).paintEvent(e)


class MenuItem(Clickable):
    """Row in the white main menu (OZMenuItem)."""

    def __init__(self, text, icon=None, arrow=True, parent=None, detail=None, tint=None):
        super(MenuItem, self).__init__(parent)
        self.setFixedHeight(54)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 20, 0)
        lay.setSpacing(14)
        if icon:
            ic = QtWidgets.QLabel()
            ic.setPixmap(scaled(icon, 20, 20))
            ic.setFixedWidth(22)
            if tint:
                ic.setGraphicsEffect(_tint(tint))
            lay.addWidget(ic)
        self.text = label(text, size=11)
        lay.addWidget(self.text, 1)
        self.detail = label(detail or "", role="muted", size=9.5)
        lay.addWidget(self.detail)
        if arrow:
            ar = QtWidgets.QLabel()
            ar.setPixmap(scaled("next.png", 9))
            ar.setStyleSheet("background: transparent;")
            # next.png is white; tint for the light panel
            ar.setGraphicsEffect(_tint(theme.COLUMN_HEADER))
            lay.addWidget(ar)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        if self.underMouse():
            p.fillRect(self.rect(), QtGui.QColor("#EEF4FD"))
        p.setPen(QtGui.QColor("#EDEFF3"))
        p.drawLine(24, self.height() - 1, self.width() - 20, self.height() - 1)
        super(MenuItem, self).paintEvent(e)


class OptionItem(MenuItem):
    """Selectable sub-option (e.g. log levels) with a check mark."""

    def __init__(self, text, parent=None):
        super(OptionItem, self).__init__(text, arrow=False, parent=parent)
        self.check = label("", color=theme.GREEN, size=12, bold=True)
        self.layout().addWidget(self.check)

    def set_selected(self, on):
        self.check.setText("✓" if on else "")


class ToggleItem(QtWidgets.QWidget):
    """Label + description + Toggler, for settings in white panels."""

    def __init__(self, text, description=None, parent=None):
        super(ToggleItem, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(24, 10, 20, 10)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(text, size=11))
        if description:
            d = label(description, role="muted", size=8.5, wrap=True)
            col.addWidget(d)
        lay.addLayout(col, 1)
        self.toggle = Toggler()
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QColor("#EDEFF3"))
        p.drawLine(24, self.height() - 1, self.width() - 20, self.height() - 1)


class KeyValue(QtWidgets.QWidget):
    def __init__(self, key, value="", parent=None):
        super(KeyValue, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 5, 0, 5)
        self.key = label(key, role="key", size=9.5)
        self.value = label(value, size=9.5, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value.setWordWrap(True)
        lay.addWidget(self.key)
        lay.addWidget(self.value, 1)

    def set(self, v):
        self.value.setText(v or "")


def _tint(color):
    eff = QtWidgets.QGraphicsColorizeEffect()
    eff.setColor(QtGui.QColor(color))
    eff.setStrength(1.0)
    return eff


class PanelHeader(QtWidgets.QWidget):
    """Back / Title / (close) header used by the white panels."""

    back = Signal()
    closeRequested = Signal()

    def __init__(self, title, back_text="Back", show_close=False, parent=None):
        super(PanelHeader, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 10)
        self.back_btn = Clickable()
        bl = QtWidgets.QHBoxLayout(self.back_btn)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        ic = QtWidgets.QLabel()
        ic.setPixmap(scaled("back.png", 12))
        ic.setGraphicsEffect(_tint(theme.TEXT_DARK))
        bl.addWidget(ic)
        bl.addWidget(label(back_text, size=9.5, bold=True))
        self.back_btn.setFixedWidth(80)
        self.back_btn.clicked.connect(self.back.emit)
        lay.addWidget(self.back_btn)
        self.title = label(title, role="title", align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title, 1)
        self.close_btn = Clickable()
        cl = QtWidgets.QHBoxLayout(self.close_btn)
        cl.setContentsMargins(0, 0, 0, 0)
        x = QtWidgets.QLabel()
        x.setPixmap(scaled("closeBlack.png", 16))
        cl.addStretch(1)
        cl.addWidget(x)
        self.close_btn.setFixedWidth(80)
        self.close_btn.clicked.connect(self.closeRequested.emit)
        self.close_btn.setVisible(show_close)
        if not show_close:
            spacer = QtWidgets.QWidget()
            spacer.setFixedWidth(80)
            lay.addWidget(spacer)
        lay.addWidget(self.close_btn)


class SlideOverlay(QtWidgets.QWidget):
    """Full-window overlay that slides in from the left or rises from below."""

    closed = Signal()

    def __init__(self, parent, direction="left"):
        super(SlideOverlay, self).__init__(parent)
        self.direction = direction
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()
        self._anim = QtCore.QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._closing = False
        self._anim.finished.connect(self._done)
        parent.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QtCore.QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.parent().rect())
        return False

    def _offscreen(self):
        r = self.parent().rect()
        return QtCore.QPoint(-r.width(), 0) if self.direction == "left" else QtCore.QPoint(0, r.height())

    def open(self):
        self._closing = False
        self.setGeometry(self.parent().rect())
        if self.isVisible():
            self.raise_()
            return
        self.move(self._offscreen())
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._offscreen())
        self._anim.setEndValue(QtCore.QPoint(0, 0))
        self._anim.start()

    def dismiss(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(self._offscreen())
        self._anim.start()

    def _done(self):
        if self._closing:
            self._closing = False
            self.hide()
            self.closed.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return
        super(SlideOverlay, self).keyPressEvent(e)


class Blurb(Clickable):
    """Bottom message bar (RedBlurb / InfoBlurb in the Windows client)."""

    def __init__(self, parent=None):
        super(Blurb, self).__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        self.text = label("", size=9.5, wrap=True)
        lay.addWidget(self.text, 1)
        self.action = None
        self.clicked.connect(self._on_click)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text, error=False, action=None, timeout_ms=6000):
        self.text.setText(text + ("  ›" if action else ""))
        self.action = action
        bg = "#3a1a1a" if error else "#1a3a6e"
        border = theme.RED if error else theme.BLUE
        self.setStyleSheet("Blurb { background: %s; border-top: 2px solid %s; }" % (bg, border))
        self.show()
        self.raise_()
        if timeout_ms:
            self._timer.start(timeout_ms)
        else:
            self._timer.stop()

    def _on_click(self):
        act, self.action = self.action, None
        self.hide()
        if act:
            act()


class QrView(QtWidgets.QWidget):
    """Renders a QR code with python3-qrcode when installed."""

    def __init__(self, parent=None):
        super(QrView, self).__init__(parent)
        self.setFixedSize(180, 180)
        self.matrix = None

    @staticmethod
    def available():
        import importlib.util
        return importlib.util.find_spec("qrcode") is not None

    def set_data(self, data):
        self.matrix = None
        try:
            import qrcode
            q = qrcode.QRCode(border=2)
            q.add_data(data)
            q.make(fit=True)
            self.matrix = q.get_matrix()
        except Exception:
            self.matrix = None
        self.update()

    def paintEvent(self, _):
        if not self.matrix:
            return
        p = QtGui.QPainter(self)
        n = len(self.matrix)
        cell = min(self.width(), self.height()) / float(n)
        p.fillRect(self.rect(), QtGui.QColor("white"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor("black"))
        for y, row in enumerate(self.matrix):
            for x, v in enumerate(row):
                if v:
                    p.drawRect(QtCore.QRectF(x * cell, y * cell, cell + 0.5, cell + 0.5))
