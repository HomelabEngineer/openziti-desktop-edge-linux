"""Unit tests: env-file handling, IPC framing and the state model (no display needed)."""
import json
import os
import socket
import sys
import tempfile
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ziti_desktop_edge import envfile  # noqa: E402


class EnvFileTests(unittest.TestCase):
    STOCK = ("# reserved dynamic IP range for proxied services\n"
             "ZITI_IDENTITY_DIR='/opt/openziti/etc/identities'\n"
             "ZITI_DNS_IP_RANGE='100.64.0.1/10'\n"
             "#ZITI_VERBOSE='debug'\n")

    def test_parse_ignores_comments(self):
        v = envfile.parse(self.STOCK)
        self.assertEqual(v["ZITI_DNS_IP_RANGE"], "100.64.0.1/10")
        self.assertNotIn("ZITI_VERBOSE", v)

    def test_update_preserves_comments_and_appends(self):
        out = envfile.update_text(self.STOCK, {"ZITI_DNS_IP_RANGE": "100.80.0.1/12", "ZITI_VERBOSE": "debug"})
        self.assertIn("# reserved dynamic IP range", out)
        self.assertIn("ZITI_DNS_IP_RANGE='100.80.0.1/12'", out)
        self.assertIn("#ZITI_VERBOSE='debug'", out)
        self.assertEqual(envfile.parse(out)["ZITI_VERBOSE"], "debug")
        self.assertEqual(out.count("ZITI_DNS_IP_RANGE="), 1)

    def test_validation(self):
        self.assertEqual(envfile.validate_dns_ip_range(" 100.64.0.1/10 "), "100.64.0.1/10")
        for bad in ("100.64.0.1", "300.1.1.1/10", "100.64.0.1/24", "100.64.0.1/9", "x/10", "1.1.1.1/10; rm"):
            with self.assertRaises(ValueError, msg=bad):
                envfile.validate_dns_ip_range(bad)
        with self.assertRaises(ValueError):
            envfile.validate_log_level("loud")

    def test_write_rejects_unknown_keys(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(self.STOCK)
        try:
            with self.assertRaises(ValueError):
                envfile.write(f.name, {"ZITI_IDENTITY_DIR": "/tmp"})
            envfile.write(f.name, {"ZITI_DNS_IP_RANGE": "100.64.0.1/11"})
            self.assertEqual(envfile.read(f.name)["ZITI_DNS_IP_RANGE"], "100.64.0.1/11")
        finally:
            os.unlink(f.name)


class IpcTests(unittest.TestCase):
    """CommandClient against a tiny socket server mimicking ipc_cmd.c framing."""

    def setUp(self):
        from ziti_desktop_edge.qt import QtCore
        self.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "cmd.sock")
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(1)
        self.seen = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        c, _ = self.srv.accept()
        buf = b""
        while True:
            d = c.recv(4096)
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = json.loads(line)
                self.seen.append(cmd)
                resp = {"Success": True, "Code": 0, "Data": {"echo": cmd["Command"]}}
                # answer in two chunks to exercise reassembly
                raw = (json.dumps(resp) + "\n").encode()
                c.sendall(raw[:7])
                c.sendall(raw[7:])

    def test_serialised_round_trip(self):
        from ziti_desktop_edge.ipc import CommandClient
        from ziti_desktop_edge.qt import QtCore
        cl = CommandClient(self.path)
        got = []
        cl.send("Status", None, got.append)
        cl.send("IdentityOnOff", {"Identifier": "x", "OnOff": True}, got.append)
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(3000, loop.quit)
        t = QtCore.QTimer()
        t.timeout.connect(lambda: loop.quit() if len(got) == 2 else None)
        t.start(20)
        loop.exec() if hasattr(loop, "exec") else loop.exec_()
        self.assertEqual([r.data["echo"] for r in got], ["Status", "IdentityOnOff"])
        self.assertTrue(all(r.success for r in got))
        self.assertEqual(self.seen[1]["Data"], {"Identifier": "x", "OnOff": True})

    def test_unreachable_socket_reports_error(self):
        from ziti_desktop_edge.ipc import CommandClient
        cl = CommandClient(os.path.join(self.dir, "missing.sock"))
        got = []
        cl.send("Status", None, got.append)
        self.assertEqual(len(got), 1)
        self.assertFalse(got[0].success)


class ModelTests(unittest.TestCase):
    def setUp(self):
        from ziti_desktop_edge.qt import QtCore
        self.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
        from ziti_desktop_edge.model import TunnelModel
        self.m = TunnelModel()
        self.m.apply_status({"Identities": [{"Identifier": "/i/a.json", "Name": "a", "Active": True,
                                             "Services": [{"Id": "1", "Name": "s1"}]}]})

    def test_identity_events(self):
        self.m.handle_event({"Op": "identity", "Action": "added", "Id": {"Identifier": "/i/b.json", "Name": "b"}})
        self.assertEqual(sorted(i.name for i in self.m.sorted_identities()), ["a", "b"])
        self.m.handle_event({"Op": "identity", "Action": "removed", "Id": {"Identifier": "/i/b.json"}})
        self.assertIsNone(self.m.identity("/i/b.json"))

    def test_bulkservice_and_metrics(self):
        self.m.handle_event({"Op": "bulkservice", "Identifier": "/i/a.json",
                             "AddedServices": [{"Id": "2", "Name": "s2"}], "RemovedServices": [{"Id": "1"}]})
        self.assertEqual([s["Name"] for s in self.m.identity("/i/a.json").services], ["s2"])
        self.m.handle_event({"Op": "metrics", "Identities": [{"Identifier": "/i/a.json", "Active": True,
                                                              "Metrics": {"Up": 10, "Down": 20}}]})
        self.assertEqual((self.m.up, self.m.down), (10, 20))

    def test_mfa_flow(self):
        self.m.handle_event({"Op": "mfa", "Action": "auth_challenge", "Identifier": "/i/a.json"})
        self.assertTrue(self.m.identity("/i/a.json").mfa_needed)
        self.m.handle_event({"Op": "mfa", "Action": "mfa_auth_status", "Identifier": "/i/a.json", "Successful": True})
        self.assertFalse(self.m.identity("/i/a.json").mfa_needed)

    def test_name_falls_back_to_filename(self):
        self.m.handle_event({"Op": "identity", "Action": "added", "Id": {"Identifier": "/x/y/office.json"}})
        self.assertEqual(self.m.identity("/x/y/office.json").name, "office")


class DesktopTests(unittest.TestCase):
    def _fake_ext(self, info_output, rc=0):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "gnome-extensions")
        with open(f, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%s'\nexit %d\n" % (info_output.replace("\n", "\\n"), rc))
        os.chmod(f, 0o755)
        return d

    def _state(self, bindir):
        from ziti_desktop_edge import desktop
        old = os.environ["PATH"]
        os.environ["PATH"] = bindir + os.pathsep + "/usr/bin:/bin"
        os.environ.pop("ZDE_FAKE_EXT_STATE", None)
        try:
            return desktop.appindicator_state()
        finally:
            os.environ["PATH"] = old

    def test_extension_states(self):
        self.assertEqual(self._state(self._fake_ext("x\n  State: ACTIVE\n  Enabled: Yes\n")), "enabled")
        self.assertEqual(self._state(self._fake_ext("x\n  State: INACTIVE\n  Enabled: No\n")), "disabled")
        self.assertEqual(self._state(self._fake_ext("Extension does not exist", rc=2)), "missing")

    def test_gvariant_quoting(self):
        from ziti_desktop_edge.desktop import _gv_str
        self.assertEqual(_gv_str("it's \\ ok"), "'it\\'s \\\\ ok'")

    def test_gnome_detection(self):
        from ziti_desktop_edge import desktop
        os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
        self.assertTrue(desktop.is_gnome())
        os.environ["XDG_CURRENT_DESKTOP"] = "KDE"
        os.environ.pop("XDG_SESSION_DESKTOP", None)
        os.environ.pop("DESKTOP_SESSION", None)
        self.assertFalse(desktop.is_gnome())


if __name__ == "__main__":
    unittest.main()
