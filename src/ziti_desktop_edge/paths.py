"""Locations used by the stock OpenZiti ziti-edge-tunnel Linux packages.

These match the .deb/.rpm published by OpenZiti (ziti-tunnel-sdk-c,
programs/ziti-edge-tunnel/package): the service runs as user ``ziti`` and
listens on Unix sockets in ``/tmp/.ziti`` (directory mode 0750, group
``ziti``). Every value can be overridden with an environment variable so the
GUI keeps working if a future tunneler release moves something, and so it can
be pointed at the bundled mock tunneler for development.
"""
import os

APP_ID = "ziti-edge-tunnel-gui"

# project home; update checks use this repo's GitHub releases
PROJECT_REPO = "HomelabEngineer/openziti-desktop-edge-linux"
PROJECT_URL = "https://github.com/" + PROJECT_REPO
RELEASES_URL = PROJECT_URL + "/releases"
ISSUES_URL = PROJECT_URL + "/issues"
TUNNEL_DOWNLOADS_URL = "https://netfoundry.io/docs/openziti/downloads/?os=Linux"
APP_NAME = "Ziti Desktop Edge"
ORG_NAME = "openziti-community"


def _env(name, default):
    return os.environ.get(name) or default


SOCKET_DIR = _env("ZDE_SOCKET_DIR", "/tmp/.ziti")
# A discriminator lets several tunnelers coexist (ziti-edge-tunnel -I/--ipc-discriminator)
DISCRIMINATOR = _env("ZDE_DISCRIMINATOR", "")


def _sock(base):
    # the tunneler appends the discriminator: ziti-edge-tunnel.sock.<discriminator>
    if DISCRIMINATOR:
        base = "%s.%s" % (base, DISCRIMINATOR)
    return os.path.join(SOCKET_DIR, base)


CMD_SOCKET = _env("ZDE_CMD_SOCKET", _sock("ziti-edge-tunnel.sock"))
EVENT_SOCKET = _env("ZDE_EVENT_SOCKET", _sock("ziti-edge-tunnel-event.sock"))

SERVICE_UNIT = _env("ZDE_SERVICE_UNIT", "ziti-edge-tunnel.service")
ENV_FILE = _env("ZDE_ENV_FILE", "/opt/openziti/etc/ziti-edge-tunnel.env")
IDENTITY_DIR = _env("ZDE_IDENTITY_DIR", "/opt/openziti/etc/identities")
TUNNEL_BINARY = _env("ZDE_TUNNEL_BINARY", "/opt/openziti/bin/ziti-edge-tunnel")
ZITI_GROUP = _env("ZDE_ZITI_GROUP", "ziti")

# privileged helper invoked through pkexec for root-only changes
HELPER = _env("ZDE_HELPER", "/usr/libexec/ziti-edge-tunnel-gui/ziti-edge-tunnel-gui-helper")
# set ZDE_NO_PKEXEC=1 to run the helper directly (development / running as root)
USE_PKEXEC = not os.environ.get("ZDE_NO_PKEXEC")

# when set, systemctl calls are replaced by a fake (used with tests/mock_tunnel.py)
MOCK_SYSTEMD = _env("ZDE_MOCK_SYSTEMD", "")

DEFAULT_DNS_IP_RANGE = "100.64.0.1/10"
LOG_LEVELS = ["error", "warn", "info", "debug", "verbose", "trace"]

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def asset(*parts):
    return os.path.join(ASSET_DIR, *parts)


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    d = os.path.join(base, APP_ID)
    os.makedirs(d, exist_ok=True)
    return d


def autostart_file():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", APP_ID + ".desktop")
