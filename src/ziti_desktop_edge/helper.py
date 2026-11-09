"""Privileged helper, run as root through pkexec.

Only a small, validated set of operations is offered:

  set-env KEY=VALUE [KEY=VALUE...]   edit ziti-edge-tunnel.env (whitelisted keys)
  unset-env KEY [KEY...]
  join-group                          add the calling desktop user to group 'ziti'
  service start|stop|restart|enable|disable
                                      fallback for systems whose polkit cannot
                                      grant per-unit rights (polkit < 0.106)

The polkit action is org.openziti.ziti-edge-tunnel-gui.helper.
"""
import grp
import os
import pwd
import subprocess
import sys

from . import envfile

ENV_FILE = "/opt/openziti/etc/ziti-edge-tunnel.env"
UNIT = "ziti-edge-tunnel.service"
GROUP = "ziti"


def _die(msg, code=1):
    sys.stderr.write("ziti-edge-tunnel-gui-helper: %s\n" % msg)
    sys.exit(code)


def _caller():
    uid = os.environ.get("PKEXEC_UID")
    if uid is None:
        if os.getuid() == 0 and os.environ.get("SUDO_USER"):
            return os.environ["SUDO_USER"]
        _die("must be started through pkexec")
    return pwd.getpwuid(int(uid)).pw_name


def cmd_set_env(args):
    changes = {}
    for a in args:
        if "=" not in a:
            _die("expected KEY=VALUE, got %r" % a)
        k, v = a.split("=", 1)
        changes[k] = v
    if not changes:
        _die("nothing to set")
    try:
        applied = envfile.write(ENV_FILE, changes)
    except ValueError as e:
        _die(str(e), 2)
    for k, v in applied.items():
        print("%s=%s" % (k, v))


def cmd_unset_env(args):
    try:
        envfile.write(ENV_FILE, dict((k, None) for k in args))
    except ValueError as e:
        _die(str(e), 2)


def cmd_join_group(_args):
    user = _caller()
    try:
        grp.getgrnam(GROUP)
    except KeyError:
        _die("group '%s' does not exist - is ziti-edge-tunnel installed?" % GROUP)
    rc = subprocess.call(["usermod", "--append", "--groups", GROUP, user])
    if rc != 0:
        _die("usermod failed (%d)" % rc)
    print("added %s to %s" % (user, GROUP))


def cmd_service(args):
    if len(args) != 1 or args[0] not in ("start", "stop", "restart", "enable", "disable"):
        _die("usage: service start|stop|restart|enable|disable")
    sys.exit(subprocess.call(["systemctl", args[0], UNIT]))


COMMANDS = {
    "set-env": cmd_set_env,
    "unset-env": cmd_unset_env,
    "join-group": cmd_join_group,
    "service": cmd_service,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.geteuid() != 0:
        _die("must run as root (via pkexec)")
    if not argv or argv[0] not in COMMANDS:
        _die("usage: %s {%s} ..." % (os.path.basename(sys.argv[0]), "|".join(sorted(COMMANDS))))
    COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    main()
