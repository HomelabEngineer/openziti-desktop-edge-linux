"""Client for the ziti-edge-tunnel IPC sockets.

The tunneler exposes two Unix domain sockets (see ipc_cmd.c / ipc_event.c in
openziti/ziti-tunnel-sdk-c):

* command socket - the client writes a JSON object
  ``{"Command": "<name>", "Data": {...}}`` and the tunneler answers with one
  JSON line ``{"Success": bool, "Error": str, "Code": int, "Data": ...}``.
  Responses carry no correlation id, so commands are sent strictly one at a
  time (the Windows client does the same).
* event socket - the tunneler pushes newline-delimited JSON events
  (``Op`` = status, identity, controller, bulkservice, metrics, mfa,
  notification, router, posturestatus). A full ``status`` event is sent as
  soon as a client connects.

Both sockets are owned by the ``ziti`` group, so the desktop user must be a
member of that group.
"""
import json
import logging

from .qt import QtCore, QtNetwork, Signal
from . import paths

log = logging.getLogger(__name__)

LocalSocket = QtNetwork.QLocalSocket
_Connected = LocalSocket.LocalSocketState.ConnectedState
_Unconnected = LocalSocket.LocalSocketState.UnconnectedState

# commands that wait on the controller can take a while
_SLOW = {"AddIdentity": 90000, "Enroll": 90000, "ExternalAuth": 60000,
         "EnableMFA": 30000, "VerifyMFA": 30000, "SubmitMFA": 30000,
         "RemoveMFA": 30000, "GenerateMFACodes": 30000, "GetMFACodes": 30000,
         "RefreshIdentity": 30000}
DEFAULT_TIMEOUT = 10000


class IpcResult(object):
    def __init__(self, success, error=None, data=None, code=None):
        self.success = bool(success)
        self.error = error
        self.data = data
        self.code = code

    @classmethod
    def from_json(cls, obj):
        data = obj.get("Data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                pass
        return cls(obj.get("Success"), obj.get("Error"), data, obj.get("Code"))

    def __repr__(self):
        return "IpcResult(success=%r, error=%r)" % (self.success, self.error)


class _Pending(object):
    __slots__ = ("command", "data", "callback", "timeout")

    def __init__(self, command, data, callback, timeout):
        self.command = command
        self.data = data
        self.callback = callback
        self.timeout = timeout


def _line_splitter():
    buf = bytearray()

    def feed(chunk):
        buf.extend(chunk)
        out = []
        while True:
            idx = buf.find(b"\n")
            if idx < 0:
                break
            line = bytes(buf[:idx]).strip()
            del buf[:idx + 1]
            if line:
                out.append(line)
        return out

    def reset():
        del buf[:]

    feed.reset = reset
    return feed


class CommandClient(QtCore.QObject):
    """Serialised request/response client for the command socket."""

    connectedChanged = Signal(bool)

    def __init__(self, path=None, parent=None):
        super(CommandClient, self).__init__(parent)
        self.path = path or paths.CMD_SOCKET
        self._sock = LocalSocket(self)
        self._sock.readyRead.connect(self._on_ready)
        self._sock.disconnected.connect(self._on_disconnected)
        self._sock.connected.connect(lambda: self.connectedChanged.emit(True))
        try:
            self._sock.errorOccurred.connect(self._on_error)
        except AttributeError:  # Qt5 < 5.15
            self._sock.error.connect(self._on_error)
        self._split = _line_splitter()
        self._queue = []
        self._inflight = None
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    # -- public -------------------------------------------------------------
    def is_connected(self):
        return self._sock.state() == _Connected

    def send(self, command, data=None, callback=None, timeout=None):
        """Queue a command. ``callback(IpcResult)`` is always invoked once."""
        t = timeout or _SLOW.get(command, DEFAULT_TIMEOUT)
        self._queue.append(_Pending(command, data, callback, t))
        self._pump()

    def close(self):
        self._sock.abort()

    # -- internals ------------------------------------------------------------
    def _ensure_connected(self):
        st = self._sock.state()
        if st == _Connected:
            return True
        if st == _Unconnected:
            self._sock.connectToServer(self.path)
            if not self._sock.waitForConnected(1500):
                return False
            return True
        return self._sock.waitForConnected(1500)

    def _pump(self):
        if self._inflight is not None or not self._queue:
            return
        if not self._ensure_connected():
            err = self._sock.errorString() or "tunnel service is not reachable"
            pending, self._queue = self._queue, []
            for p in pending:
                self._finish(p, IpcResult(False, "Cannot reach %s: %s" % (self.path, err)))
            return
        p = self._queue.pop(0)
        self._inflight = p
        msg = {"Command": p.command}
        if p.data is not None:
            msg["Data"] = p.data
        payload = json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n"
        log.debug("ipc >> %s", p.command)
        self._sock.write(payload)
        self._sock.flush()
        self._timer.start(p.timeout)

    def _finish(self, p, result):
        if p.callback is not None:
            try:
                p.callback(result)
            except Exception:  # never let a UI callback kill the queue
                log.exception("IPC callback for %s failed", p.command)

    def _complete(self, result):
        p, self._inflight = self._inflight, None
        self._timer.stop()
        if p is not None:
            log.debug("ipc << %s %r", p.command, result)
            self._finish(p, result)
        self._pump()

    def _on_ready(self):
        for line in self._split(bytes(self._sock.readAll())):
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                log.warning("unparseable IPC response: %r", line[:200])
                continue
            if self._inflight is None:
                log.debug("unsolicited IPC response ignored")
                continue
            self._complete(IpcResult.from_json(obj))

    def _on_timeout(self):
        if self._inflight is not None:
            name = self._inflight.command
            # a late answer would be matched to the wrong command: start fresh
            self._sock.abort()
            self._split.reset()
            self._complete(IpcResult(False, "%s timed out" % name))

    def _on_error(self, *_):
        if self._inflight is not None and self._sock.state() != _Connected:
            self._complete(IpcResult(False, self._sock.errorString()))

    def _on_disconnected(self):
        self._split.reset()
        self.connectedChanged.emit(False)
        if self._inflight is not None:
            self._complete(IpcResult(False, "tunnel service closed the connection"))


class EventClient(QtCore.QObject):
    """Auto-reconnecting listener for the event socket."""

    received = Signal(dict)
    connectedChanged = Signal(bool)

    def __init__(self, path=None, parent=None, retry_ms=2000):
        super(EventClient, self).__init__(parent)
        self.path = path or paths.EVENT_SOCKET
        self._sock = LocalSocket(self)
        self._sock.readyRead.connect(self._on_ready)
        self._sock.connected.connect(self._on_connected)
        self._sock.disconnected.connect(self._on_disconnected)
        try:
            self._sock.errorOccurred.connect(self._on_error)
        except AttributeError:
            self._sock.error.connect(self._on_error)
        self._split = _line_splitter()
        self._retry = QtCore.QTimer(self)
        self._retry.setInterval(retry_ms)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.start)
        self._connected = False
        self.last_error = None

    def start(self):
        if self._sock.state() == _Unconnected:
            self._sock.connectToServer(self.path)

    def stop(self):
        self._retry.stop()
        self._sock.abort()

    def is_connected(self):
        return self._connected

    def _on_connected(self):
        self._connected = True
        self.last_error = None
        self._split.reset()
        log.info("connected to event socket %s", self.path)
        self.connectedChanged.emit(True)

    def _on_disconnected(self):
        was = self._connected
        self._connected = False
        if was:
            log.info("event socket disconnected")
            self.connectedChanged.emit(False)
        self._retry.start()

    def _on_error(self, *_):
        self.last_error = self._sock.errorString()
        if self._sock.state() == _Unconnected:
            if self._connected:
                self._on_disconnected()
            else:
                self._retry.start()

    def _on_ready(self):
        for line in self._split(bytes(self._sock.readAll())):
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                log.warning("unparseable event: %r", line[:200])
                continue
            if isinstance(obj, dict):
                self.received.emit(obj)
