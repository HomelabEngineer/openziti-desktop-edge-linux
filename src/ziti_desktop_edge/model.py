"""Tunnel state assembled from the tunneler's status and event stream."""
import logging

from .qt import QtCore, Signal

log = logging.getLogger(__name__)


class Identity(object):
    """Thin wrapper around a tunnel_identity JSON object (dtos.h)."""

    def __init__(self, raw):
        self.raw = dict(raw or {})

    def update(self, raw):
        for k, v in (raw or {}).items():
            if v is not None:
                self.raw[k] = v

    def get(self, key, default=None):
        v = self.raw.get(key)
        return default if v is None else v

    identifier = property(lambda s: s.get("Identifier", ""))
    fingerprint = property(lambda s: s.get("FingerPrint", ""))
    active = property(lambda s: bool(s.get("Active", False)))
    loaded = property(lambda s: bool(s.get("Loaded", False)))
    mfa_enabled = property(lambda s: bool(s.get("MfaEnabled", False)))
    mfa_needed = property(lambda s: bool(s.get("MfaNeeded", False)))
    needs_ext_auth = property(lambda s: bool(s.get("NeedsExtAuth", False)))
    ext_auth_providers = property(lambda s: list(s.get("ExtAuthProviders", []) or []))
    controller_version = property(lambda s: s.get("ControllerVersion", ""))
    services = property(lambda s: list(s.get("Services", []) or []))

    @property
    def name(self):
        n = self.get("Name")
        if n:
            return n
        ident = self.identifier
        return ident.rsplit("/", 1)[-1].rsplit(".json", 1)[0] if ident else "(unnamed)"

    @property
    def controller(self):
        cfg = self.get("Config", {}) or {}
        return cfg.get("ztAPI") or (cfg.get("ztAPIs") or [""])[0] or ""

    @property
    def metrics(self):
        m = self.get("Metrics", {}) or {}
        return int(m.get("Up", 0) or 0), int(m.get("Down", 0) or 0)

    @property
    def min_timeout_remaining(self):
        return self.get("MfaMinTimeoutRem", -1)

    def status_text(self):
        if not self.active:
            return "disabled"
        if self.needs_ext_auth:
            return "authentication required"
        if self.mfa_needed:
            return "MFA required"
        if not self.loaded:
            return "connecting"
        return "active"


class TunnelModel(QtCore.QObject):
    identitiesChanged = Signal()
    statusChanged = Signal()
    metricsChanged = Signal(int, int)          # total up, down (bytes/s)
    servicesChanged = Signal(str)               # identifier
    mfaEvent = Signal(dict)
    notification = Signal(str, str, str)        # title, message, severity
    controllerEvent = Signal(str, bool)          # identifier, connected

    def __init__(self, parent=None):
        super(TunnelModel, self).__init__(parent)
        self.identities = {}
        self.status = {}
        self.up = 0
        self.down = 0
        self.connected = False

    # -- accessors ------------------------------------------------------------
    def identity(self, identifier):
        return self.identities.get(identifier)

    def sorted_identities(self, key="name"):
        ids = list(self.identities.values())
        if key == "status":
            ids.sort(key=lambda i: (not i.active, i.name.lower()))
        elif key == "services":
            ids.sort(key=lambda i: (-len(i.services), i.name.lower()))
        else:
            ids.sort(key=lambda i: i.name.lower())
        return ids

    @property
    def ip_info(self):
        return self.status.get("IpInfo") or {}

    @property
    def log_level(self):
        return (self.status.get("LogLevel") or "").lower()

    @property
    def version(self):
        v = self.status.get("ServiceVersion") or {}
        return v.get("Version", "")

    def any_mfa_needed(self):
        return any(i.active and (i.mfa_needed or i.needs_ext_auth) for i in self.identities.values())

    def any_timing_out(self):
        return any(i.active and i.mfa_enabled and 0 <= (i.min_timeout_remaining or -1) < 20 * 60
                   for i in self.identities.values())

    # -- mutation -------------------------------------------------------------
    def clear(self):
        self.identities = {}
        self.status = {}
        self.up = self.down = 0
        self.connected = False
        self.identitiesChanged.emit()
        self.statusChanged.emit()
        self.metricsChanged.emit(0, 0)

    def apply_status(self, status):
        if not isinstance(status, dict):
            return
        self.status = dict(status)
        self.connected = True
        fresh = {}
        for raw in status.get("Identities") or []:
            ident = raw.get("Identifier")
            if not ident:
                continue
            obj = self.identities.get(ident) or Identity({})
            obj.raw = dict(raw)
            fresh[ident] = obj
        self.identities = fresh
        self.statusChanged.emit()
        self.identitiesChanged.emit()

    def handle_event(self, ev):
        op = (ev.get("Op") or "").lower()
        try:
            handler = getattr(self, "_ev_" + op, None)
            if handler is None:
                log.debug("ignoring event op %s", op)
                return
            handler(ev)
        except Exception:
            log.exception("failed handling event %s", op)

    def _ev_status(self, ev):
        self.apply_status(ev.get("Status") or {})

    def _ev_identity(self, ev):
        action = (ev.get("Action") or "").lower()
        raw = ev.get("Id") or {}
        ident = raw.get("Identifier") or ev.get("Identifier")
        if not ident:
            return
        if action == "removed":
            self.identities.pop(ident, None)
        else:
            obj = self.identities.get(ident)
            if obj is None:
                self.identities[ident] = Identity(raw)
            else:
                obj.update(raw)
            if action == "needs_ext_login":
                self.identities[ident].raw["NeedsExtAuth"] = True
        self.identitiesChanged.emit()

    def _ev_controller(self, ev):
        ident = ev.get("Identifier")
        connected = (ev.get("Action") or "").lower() == "connected"
        obj = self.identities.get(ident)
        if obj is not None:
            obj.raw["Loaded"] = True
            self.identitiesChanged.emit()
        self.controllerEvent.emit(ident or "", connected)

    def _ev_bulkservice(self, ev):
        ident = ev.get("Identifier")
        obj = self.identities.get(ident)
        if obj is None:
            return
        services = dict((s.get("Id") or s.get("Name"), s) for s in obj.services)
        for s in ev.get("RemovedServices") or []:
            services.pop(s.get("Id") or s.get("Name"), None)
        for s in ev.get("AddedServices") or []:
            services[s.get("Id") or s.get("Name")] = s
        obj.raw["Services"] = list(services.values())
        self.servicesChanged.emit(ident)
        self.identitiesChanged.emit()

    _ev_service = _ev_bulkservice

    def _ev_metrics(self, ev):
        up = down = 0
        for raw in ev.get("Identities") or []:
            obj = self.identities.get(raw.get("Identifier"))
            m = raw.get("Metrics") or {}
            if obj is not None:
                obj.raw["Metrics"] = m
                for k in ("MfaMinTimeoutRem", "MfaMaxTimeoutRem"):
                    if k in raw:
                        obj.raw[k] = raw[k]
            if raw.get("Active", True):
                up += int(m.get("Up", 0) or 0)
                down += int(m.get("Down", 0) or 0)
        self.up, self.down = up, down
        self.metricsChanged.emit(up, down)

    def _ev_mfa(self, ev):
        ident = ev.get("Identifier")
        obj = self.identities.get(ident)
        action = (ev.get("Action") or "").lower()
        if obj is not None:
            if action in ("auth_challenge", "enrollment_required"):
                obj.raw["MfaNeeded"] = True
            elif action == "mfa_auth_status" and ev.get("Successful"):
                obj.raw["MfaNeeded"] = False
            elif action == "enrollment_verification" and ev.get("Successful"):
                obj.raw["MfaEnabled"] = True
                obj.raw["MfaNeeded"] = False
            elif action == "enrollment_remove" and ev.get("Successful"):
                obj.raw["MfaEnabled"] = False
                obj.raw["MfaNeeded"] = False
            self.identitiesChanged.emit()
        self.mfaEvent.emit(ev)
        if action == "auth_challenge" and obj is not None:
            self.notification.emit("MFA required",
                                   "%s needs an authentication code" % obj.name, "major")

    def _ev_notification(self, ev):
        for n in ev.get("Notification") or []:
            self.notification.emit(n.get("IdentityName") or "Ziti",
                                   n.get("Message") or "", n.get("Severity") or "minor")
