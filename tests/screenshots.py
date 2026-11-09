#!/usr/bin/env python3
"""Drive the GUI against tests/mock_tunnel.py and save screenshots.

    QT_QPA_PLATFORM=offscreen python3 tests/screenshots.py OUTDIR
(the mock must already be serving; see mock_tunnel.py)
"""
import os
import sys
import traceback
sys.excepthook = lambda t, v, tb: traceback.print_exception(t, v, tb)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ziti_desktop_edge.qt import QtCore, QtWidgets, exec_  # noqa: E402
from ziti_desktop_edge import app as appmod, theme  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(out, exist_ok=True)

qapp = QtWidgets.QApplication(["zde"])
theme.apply(qapp)


class Args(object):
    minimized = False
    debug = True


a = appmod.App(qapp, Args())
w = a.window
w.resize(430, 780)
w.show()
steps = []
errors = []


def shot(name):
    def f():
        qapp.processEvents()
        w.grab().save(os.path.join(out, name + ".png"))
        print("saved", name)
    return f


def step(ms, fn):
    steps.append((ms, fn))


def check(cond, msg):
    def f():
        ok = cond()
        print(("PASS " if ok else "FAIL ") + msg)
        if not ok:
            errors.append(msg)
    return f


m = a.model
step(2500, check(lambda: a.events.is_connected(), "event socket connected"))
step(0, check(lambda: len(m.identities) == 3, "3 identities loaded from status"))
step(0, check(lambda: m.up > 0 or m.down > 0, "metrics flowing"))
step(0, shot("01-main-connected"))
step(0, lambda: w.menu.open_menu())
step(600, shot("02-main-menu"))
step(0, lambda: w.menu.show_page("advanced"))
step(400, shot("03-advanced"))
step(0, lambda: w.menu.show_page("tunnel"))
step(400, shot("04-tunnel-config"))
step(0, lambda: w.menu.show_page("loglevel"))
step(0, lambda: a.set_log_level("debug"))
step(800, check(lambda: m.log_level == "debug", "log level changed via IPC"))
step(0, shot("05-log-level"))
step(0, lambda: w.menu.show_logs("service_logs"))
step(800, shot("06-service-logs"))
step(0, lambda: w.menu.show_page("app_settings"))
step(300, shot("07-app-settings"))
step(0, lambda: w.menu.show_page("about"))
step(300, shot("08-about"))
step(0, lambda: w.menu.dismiss())
def _find(suffix):
    return [i for i in m.identities if i.endswith(suffix)][0]


home = lambda: _find("home-lab.json")  # noqa: E731
work = lambda: _find("work-network.json")  # noqa: E731
step(400, lambda: w.open_identity(home()))
step(600, shot("09-identity-details"))
step(0, lambda: w.details.dismiss())
step(400, lambda: w.open_identity(work()))
step(600, shot("10-identity-mfa-needed"))
step(0, lambda: w.mfa.authenticate(work()))
step(500, lambda: w.mfa.code_edit.setText("123456"))
step(0, shot("11-mfa-auth"))
step(0, lambda: w.mfa._submit())
step(800, check(lambda: not m.identity(work()).mfa_needed, "MFA submit clears MfaNeeded"))
step(0, lambda: (w.details.dismiss(), w.mfa.dismiss()))
step(400, lambda: w.mfa.setup(home()))
step(900, shot("12-mfa-setup"))
step(0, lambda: w.mfa.dismiss())
step(400, lambda: a.set_identity_enabled(home(), False))
step(800, check(lambda: not m.identity(home()).active, "identity toggled off via IPC"))
step(0, lambda: a.set_identity_enabled(home(), True))
step(800, check(lambda: m.identity(home()).active, "identity toggled on via IPC"))
jwt = os.path.join(out, "new-laptop.jwt")
open(jwt, "w").write("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2ln")
step(0, lambda: a.add_identity_jwt(jwt))
step(2200, check(lambda: any(i.endswith("new-laptop.json") for i in m.identities), "JWT enrollment adds identity"))
step(0, shot("13-identity-added"))
step(0, lambda: a.forget_identity([i for i in m.identities if i.endswith("new-laptop.json")][0]))
step(800, check(lambda: not any(i.endswith("new-laptop.json") for i in m.identities), "forget removes identity"))
step(0, lambda: a.toggle_connection())  # disconnect
step(4500, check(lambda: not a.service.state.running and not a.events.is_connected(), "disconnect stops service"))
step(0, check(lambda: len(m.identities) == 0, "model cleared on disconnect"))
step(0, shot("14-disconnected"))
step(0, lambda: a.toggle_connection())  # connect
step(5500, check(lambda: a.service.state.running and a.events.is_connected(), "connect starts service + IPC"))
step(0, check(lambda: len(m.identities) == 3, "identities back after reconnect"))
step(0, shot("15-reconnected"))
step(0, lambda: a.restart_tunnel())
step(5500, check(lambda: a.service.state.running and a.events.is_connected(), "restart reconnects"))


def run(i=0):
    if i >= len(steps):
        print("DONE errors=%d" % len(errors))
        qapp.exit(1 if errors else 0)
        return
    ms, fn = steps[i]

    def go():
        try:
            fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            errors.append("%s" % e)
        run(i + 1)
    QtCore.QTimer.singleShot(ms, go)


run()
sys.exit(exec_(qapp))
