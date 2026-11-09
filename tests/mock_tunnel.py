#!/usr/bin/env python3
"""Mock ziti-edge-tunnel for developing and testing the GUI without a network.

Implements the same IPC protocol as ziti-edge-tunnel (command socket with
JSON request/response lines, event socket with pushed JSON events) and a fake
``systemctl`` so connect/disconnect can be exercised.

    # terminal 1: the mock service (sockets in ./.mock/sock)
    python3 tests/mock_tunnel.py serve --dir .mock

    # terminal 2: the GUI pointed at it
    ZDE_SOCKET_DIR=.mock/sock ZDE_SKIP_GROUP_CHECK=1 \
    ZDE_MOCK_SYSTEMD="python3 tests/mock_tunnel.py --dir .mock systemctl" \
    ZDE_JOURNAL_CMD="python3 tests/mock_tunnel.py --dir .mock journal" \
    PYTHONPATH=src python3 -m ziti_desktop_edge
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time

CMD = "ziti-edge-tunnel.sock"
EVT = "ziti-edge-tunnel-event.sock"


def _svc(name, host=None, ip=None, ports=((443, 443),), protos=("tcp",), bind=False):
    addrs = []
    if host:
        addrs.append({"IsHost": True, "HostName": host, "IP": "", "Prefix": 0})
    if ip:
        addrs.append({"IsHost": False, "HostName": "", "IP": ip, "Prefix": 32})
    return {"Id": "svc-" + name, "Name": name, "Protocols": list(protos), "Addresses": addrs,
            "Ports": [{"Low": lo, "High": hi} for lo, hi in ports], "IsAccessible": True,
            "Permissions": {"Dial": not bind, "Bind": bind}, "PostureChecks": [],
            "Timeout": -1, "TimeoutRemaining": -1}


def default_identities(idir):
    return [
        {"Name": "home-lab", "Identifier": os.path.join(idir, "home-lab.json"), "FingerPrint": "a1b2c3",
         "Active": True, "Loaded": True, "Config": {"ztAPI": "https://ctrl.example.net:1280"},
         "ControllerVersion": "v1.6.8", "MfaEnabled": False, "MfaNeeded": False, "NeedsExtAuth": False,
         "Services": [_svc("nas-web", host="nas.ziti", ports=((443, 443),)),
                      _svc("ssh-jumpbox", host="jump.ziti", ports=((22, 22),)),
                      _svc("home-assistant", host="ha.ziti", ports=((8123, 8123),)),
                      _svc("rdp-desktop", ip="10.20.0.15", ports=((3389, 3389),), protos=("tcp", "udp")),
                      _svc("printer", host="printer.ziti", ports=((631, 631), (9100, 9100)))],
         "Metrics": {"Up": 0, "Down": 0}, "MfaMinTimeoutRem": -1, "MfaMaxTimeoutRem": -1},
        {"Name": "work-network", "Identifier": os.path.join(idir, "work-network.json"), "FingerPrint": "d4e5f6",
         "Active": True, "Loaded": True, "Config": {"ztAPI": "https://zt.corp.example.com:443"},
         "ControllerVersion": "v1.5.4", "MfaEnabled": True, "MfaNeeded": True, "NeedsExtAuth": False,
         "Services": [_svc("intranet", host="intranet.corp", ports=((80, 80), (443, 443))),
                      _svc("git", host="git.corp", ports=((22, 22), (443, 443)))],
         "Metrics": {"Up": 0, "Down": 0}, "MfaMinTimeoutRem": -1, "MfaMaxTimeoutRem": -1},
        {"Name": "lake-cabin", "Identifier": os.path.join(idir, "lake-cabin.json"), "FingerPrint": "0718aa",
         "Active": False, "Loaded": False, "Config": {"ztAPI": "https://ctrl.cabin.example:8441"},
         "ControllerVersion": "", "MfaEnabled": False, "MfaNeeded": False, "NeedsExtAuth": False,
         "Services": [_svc("camera-nvr", host="nvr.cabin", ports=((443, 443),))],
         "Metrics": {"Up": 0, "Down": 0}, "MfaMinTimeoutRem": -1, "MfaMaxTimeoutRem": -1},
    ]


class Mock(object):
    def __init__(self, d):
        self.dir = os.path.abspath(d)
        self.sockdir = os.path.join(self.dir, "sock")
        self.idir = os.path.join(self.dir, "identities")
        os.makedirs(self.sockdir, exist_ok=True)
        os.makedirs(self.idir, exist_ok=True)
        self.identities = dict((i["Identifier"], i) for i in default_identities(self.idir))
        self.log_level = "info"
        self.start = time.time()
        self.event_writers = set()
        self.servers = []
        self.journal = open(os.path.join(self.dir, "journal.log"), "a")

    def logline(self, msg):
        self.journal.write("%s ziti-edge-tunnel[4242]: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), msg))
        self.journal.flush()

    # -- state ---------------------------------------------------------------
    def status(self):
        return {"Active": True, "Duration": int(time.time() - self.start),
                "StartTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.start)),
                "Identities": list(self.identities.values()),
                "IpInfo": {"Ip": "100.64.0.1", "Subnet": "255.192.0.0", "MTU": 65535, "DNS": "100.64.0.2"},
                "LogLevel": self.log_level,
                "ServiceVersion": {"Version": "v1.7.12", "Revision": "mock", "BuildDate": "2026-10-01"},
                "TunIpv4": "100.64.0.1", "TunPrefixLength": 10, "AddDns": False,
                "ConfigDir": self.idir}

    async def emit(self, ev):
        data = (json.dumps(ev) + "\n").encode()
        for w in list(self.event_writers):
            try:
                w.write(data)
                await w.drain()
            except Exception:
                self.event_writers.discard(w)

    # -- command handling ----------------------------------------------------
    async def handle(self, cmd):
        name = cmd.get("Command")
        d = cmd.get("Data") or {}
        ok = lambda data=None: {"Success": True, "Code": 0, "Data": data}
        err = lambda e: {"Success": False, "Code": 1, "Error": e}
        self.logline("IPC command %s" % name)
        ident = self.identities.get(d.get("Identifier")) if isinstance(d, dict) else None
        if name == "Status":
            return ok(self.status())
        if name == "IdentityOnOff":
            if not ident:
                return err("identity not found")
            ident["Active"] = bool(d.get("OnOff"))
            ident["Loaded"] = ident["Active"]
            await self.emit({"Op": "identity", "Action": "updated", "Id": ident, "Fingerprint": ident["FingerPrint"]})
            return ok()
        if name == "RemoveIdentity":
            if not ident:
                return err("identity not found")
            self.identities.pop(ident["Identifier"])
            await self.emit({"Op": "identity", "Action": "removed", "Id": {"Identifier": ident["Identifier"]}})
            return ok()
        if name == "AddIdentity":
            fn = d.get("IdentityFilename")
            if not fn:
                return err("identity filename not provided")
            path = os.path.join(self.idir, fn + ".json")
            if path in self.identities:
                return err("identity exists with the same name: %s" % fn)
            await asyncio.sleep(1.2)
            new = {"Name": fn, "Identifier": path, "FingerPrint": "%06x" % random.randrange(1 << 24),
                   "Active": True, "Loaded": True,
                   "Config": {"ztAPI": d.get("ControllerURL") or "https://enrolled.example.org:1280"},
                   "ControllerVersion": "v1.6.8", "MfaEnabled": False, "MfaNeeded": False,
                   "NeedsExtAuth": bool(d.get("ControllerURL")),
                   "ExtAuthProviders": ["keycloak"] if d.get("ControllerURL") else [],
                   "Services": [] if d.get("ControllerURL") else [_svc("welcome", host="welcome.ziti")],
                   "Metrics": {"Up": 0, "Down": 0}}
            self.identities[path] = new
            await self.emit({"Op": "identity", "Action": "added", "Id": new})
            return ok(new)
        if name == "SetLogLevel":
            self.log_level = (d.get("Level") or "info").lower()
            return ok()
        if name == "RefreshIdentity":
            return ok() if ident else err("identity not found")
        if name == "EnableMFA":
            if not ident:
                return err("identity not found")
            return ok({"Identifier": ident["Identifier"], "IsVerified": False,
                       "ProvisioningUrl": "otpauth://totp/ziti:%s?issuer=ziti&secret=JBSWY3DPEHPK3PXP" % ident["Name"],
                       "RecoveryCodes": ["AB12CD", "EF34GH", "IJ56KL", "MN78OP", "QR90ST", "UV12WX"]})
        if name in ("VerifyMFA", "SubmitMFA", "RemoveMFA", "GetMFACodes", "GenerateMFACodes"):
            if not ident:
                return err("identity not found")
            if d.get("Code") not in ("123456", "AB12CD"):
                return err("invalid code")
            if name == "VerifyMFA":
                ident["MfaEnabled"], ident["MfaNeeded"] = True, False
                await self.emit({"Op": "mfa", "Action": "enrollment_verification", "Identifier": ident["Identifier"],
                                 "Successful": True})
            elif name == "SubmitMFA":
                ident["MfaNeeded"] = False
                await self.emit({"Op": "mfa", "Action": "mfa_auth_status", "Identifier": ident["Identifier"],
                                 "Successful": True})
            elif name == "RemoveMFA":
                ident["MfaEnabled"], ident["MfaNeeded"] = False, False
                await self.emit({"Op": "mfa", "Action": "enrollment_remove", "Identifier": ident["Identifier"],
                                 "Successful": True})
            else:
                return ok({"Identifier": ident["Identifier"],
                           "RecoveryCodes": ["AB12CD", "EF34GH", "IJ56KL", "MN78OP", "QR90ST", "UV12WX"]})
            return ok()
        if name == "ExternalAuth":
            if not ident:
                return err("identity not found")
            ident["NeedsExtAuth"] = False
            asyncio.get_event_loop().call_later(2, lambda: asyncio.ensure_future(self.emit(
                {"Op": "identity", "Action": "updated", "Id": ident})))
            return ok({"identifier": ident["Identifier"], "url": "https://idp.example.com/auth?mock=1"})
        if name == "SetUpstreamDNS":
            return ok()
        return err("unsupported command %s" % name)

    async def on_cmd(self, reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    cmd = json.loads(line)
                    res = await self.handle(cmd)
                except ValueError:
                    res = {"Success": False, "Error": "failed to parse command", "Code": 1}
                writer.write((json.dumps(res) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def on_evt(self, reader, writer):
        self.event_writers.add(writer)
        writer.write((json.dumps({"Op": "status", "Status": self.status()}) + "\n").encode())
        await writer.drain()
        try:
            await reader.read()
        except Exception:
            pass
        self.event_writers.discard(writer)

    async def metrics_loop(self):
        while True:
            await asyncio.sleep(1)
            if not self.event_writers:
                continue
            ids = []
            for i in self.identities.values():
                if i["Active"]:
                    i["Metrics"] = {"Up": random.randint(2000, 90000), "Down": random.randint(20000, 2500000)}
                else:
                    i["Metrics"] = {"Up": 0, "Down": 0}
                ids.append({"Identifier": i["Identifier"], "Active": i["Active"], "Metrics": i["Metrics"],
                            "MfaMinTimeoutRem": -1, "MfaMaxTimeoutRem": -1})
            await self.emit({"Op": "metrics", "Identities": ids})

    # -- service lifecycle driven by the fake systemctl ------------------------
    def state(self):
        try:
            with open(os.path.join(self.dir, "state")) as f:
                return f.read().strip()
        except IOError:
            return "active"

    async def run(self):
        asyncio.ensure_future(self.metrics_loop())
        running = False
        while True:
            want = self.state() == "active"
            if want and not running:
                for p in (CMD, EVT):
                    try:
                        os.unlink(os.path.join(self.sockdir, p))
                    except OSError:
                        pass
                self.servers = [
                    await asyncio.start_unix_server(self.on_cmd, os.path.join(self.sockdir, CMD)),
                    await asyncio.start_unix_server(self.on_evt, os.path.join(self.sockdir, EVT)),
                ]
                self.start = time.time()
                running = True
                self.logline("ziti-edge-tunnel started, IPC on %s" % self.sockdir)
            elif not want and running:
                for s in self.servers:
                    s.close()
                for w in list(self.event_writers):
                    w.close()
                self.event_writers.clear()
                for p in (CMD, EVT):
                    try:
                        os.unlink(os.path.join(self.sockdir, p))
                    except OSError:
                        pass
                running = False
                self.logline("ziti-edge-tunnel stopped")
            await asyncio.sleep(0.3)


def fake_systemctl(d, args):
    sf = os.path.join(d, "state")
    tf = os.path.join(d, "since")
    ef = os.path.join(d, "enabled")
    st = open(sf).read().strip() if os.path.exists(sf) else "active"
    if args and args[0] == "show":
        since = float(open(tf).read()) if os.path.exists(tf) else time.monotonic()
        enabled = open(ef).read().strip() if os.path.exists(ef) else "enabled"
        print("LoadState=loaded\nActiveState=%s\nSubState=%s\nUnitFileState=%s\n"
              "ActiveEnterTimestampMonotonic=%d\nMainPID=%d" % (
                  st, "running" if st == "active" else "dead", enabled,
                  int(since * 1e6) if st == "active" else 0, 4242 if st == "active" else 0))
        return 0
    action = args[0] if args else ""
    if action in ("start", "restart"):
        time.sleep(0.6)
        open(sf, "w").write("active")
        open(tf, "w").write(str(time.monotonic()))
    elif action == "stop":
        time.sleep(0.4)
        open(sf, "w").write("inactive")
    elif action in ("enable", "disable"):
        open(ef, "w").write(action + "d")
    else:
        sys.stderr.write("unsupported: %s\n" % args)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".mock")
    ap.add_argument("mode", choices=["serve", "systemctl", "journal"])
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    if a.mode == "systemctl":
        sys.exit(fake_systemctl(a.dir, a.rest))
    if a.mode == "journal":
        try:
            sys.stdout.write(open(os.path.join(a.dir, "journal.log")).read())
        except IOError:
            print("-- No entries --")
        return
    if not os.path.exists(os.path.join(a.dir, "since")):
        open(os.path.join(a.dir, "since"), "w").write(str(time.monotonic()))
    asyncio.run(Mock(a.dir).run())


if __name__ == "__main__":
    main()
