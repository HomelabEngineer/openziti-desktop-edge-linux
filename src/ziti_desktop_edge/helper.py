"""Privileged helper, run as root through pkexec.

Only a small, validated set of operations is offered:

  set-env KEY=VALUE [KEY=VALUE...]   edit ziti-edge-tunnel.env (whitelisted keys)
  unset-env KEY [KEY...]
  join-group                          add the calling desktop user to group 'ziti'
  install-update FILE                 upgrade this app from a .deb/.rpm of package
                                      ziti-edge-tunnel-gui (any other package is refused)
  install-tray-extension              install GNOME's AppIndicator extension package
                                      (fixed package name; dnf or apt only)
  service start|stop|restart|enable|disable
                                      fallback for systems whose polkit cannot
                                      grant per-unit rights (polkit < 0.106)

The polkit action is org.openziti.ziti-edge-tunnel-gui.helper.
"""
import grp
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile

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


APP_PACKAGE = "ziti-edge-tunnel-gui"
MAX_UPDATE_SIZE = 64 * 1024 * 1024


def _which_root(name):
    for d in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _package_of(path, kind):
    """Return (name, version) read from the package file itself."""
    if kind == "deb":
        out = subprocess.check_output([_which_root("dpkg-deb"), "--field", path, "Package", "Version"])
        fields = dict(l.split(":", 1) for l in out.decode().splitlines() if ":" in l)
        return fields.get("Package", "").strip(), fields.get("Version", "").strip()
    out = subprocess.check_output([_which_root("rpm"), "-qp", "--nosignature", "--qf",
                                   "%{NAME} %{VERSION}-%{RELEASE}", path], stderr=subprocess.DEVNULL)
    name, _, ver = out.decode().strip().partition(" ")
    return name, ver


def cmd_install_update(args):
    if len(args) != 1:
        _die("usage: install-update FILE.deb|FILE.rpm")
    src = args[0]
    kind = "deb" if src.endswith(".deb") else "rpm" if src.endswith(".rpm") else None
    if kind is None:
        _die("only .deb or .rpm files can be installed")
    # copy into a root-only directory first, so the file cannot change after it is checked
    try:
        fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        _die("cannot open %s: %s" % (src, e))
    work = tempfile.mkdtemp(prefix="ziti-gui-update-")
    os.chmod(work, 0o700)
    dst = os.path.join(work, "update." + kind)
    try:
        with os.fdopen(fd, "rb") as fin:
            st = os.fstat(fin.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_UPDATE_SIZE:
                _die("not a regular package file")
            with open(dst, "wb") as fout:
                shutil.copyfileobj(fin, fout)
        if kind == "deb" and not _which_root("dpkg-deb"):
            _die("this system does not use .deb packages")
        if kind == "rpm" and not _which_root("rpm"):
            _die("this system does not use .rpm packages")
        try:
            name, version = _package_of(dst, kind)
        except (subprocess.CalledProcessError, OSError):
            _die("the file is not a valid %s package" % kind)
        if name != APP_PACKAGE:
            _die("refusing to install package '%s' (only %s updates are allowed)" % (name, APP_PACKAGE))
        print("installing %s %s" % (name, version))
        sys.stdout.flush()
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        if kind == "deb":
            cmd = [_which_root("apt-get"), "install", "-y", dst] if _which_root("apt-get") \
                else [_which_root("dpkg"), "-i", dst]
        elif _which_root("dnf"):
            cmd = [_which_root("dnf"), "install", "-y", dst]
        elif _which_root("zypper"):
            cmd = [_which_root("zypper"), "--non-interactive", "install", "--allow-unsigned-rpm", dst]
        else:
            cmd = [_which_root("rpm"), "-Uvh", dst]
        rc = subprocess.call(cmd, env=env)
        sys.exit(rc)
    finally:
        shutil.rmtree(work, ignore_errors=True)


TRAY_PACKAGE = "gnome-shell-extension-appindicator"


def cmd_install_tray_extension(_args):
    for pm, cmd in (("dnf", ["dnf", "install", "-y", TRAY_PACKAGE]),
                    ("apt-get", ["apt-get", "install", "-y", TRAY_PACKAGE]),
                    ("zypper", ["zypper", "--non-interactive", "install", TRAY_PACKAGE])):
        for d in ("/usr/bin", "/bin", "/usr/sbin"):
            if os.path.exists(os.path.join(d, pm)):
                env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
                sys.exit(subprocess.call(cmd, env=env))
    _die("no supported package manager (dnf, apt-get, zypper) found")


COMMANDS = {
    "set-env": cmd_set_env,
    "unset-env": cmd_unset_env,
    "join-group": cmd_join_group,
    "service": cmd_service,
    "install-tray-extension": cmd_install_tray_extension,
    "install-update": cmd_install_update,
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
