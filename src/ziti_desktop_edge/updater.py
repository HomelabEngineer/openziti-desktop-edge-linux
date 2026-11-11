"""In-app updates.

Ubuntu's App Center / GNOME Software only offer "Remove" when you open a .deb
whose package is already installed, so double-clicking a newer .deb cannot
upgrade it. The app therefore installs updates itself, through the pkexec
helper (``install-update``), which uses apt/dnf so it is a normal package
upgrade, and then restarts into the new version.

Two sources:
* a .deb/.rpm file the user picks ("Install Update From File...");
* the latest GitHub release of the project repository
  (https://github.com/HomelabEngineer/openziti-desktop-edge-linux by default;
  override with ``UPDATE_REPO=owner/repo packaging/build.sh`` or at run time with
  ``ZDE_UPDATE_REPO``; use ``none`` to turn update checks off). Release assets
  are verified against a SHA256SUMS asset when the release has one.

How a release is matched: GET /repos/<repo>/releases/latest returns the newest
published release that is not a draft or pre-release. From its assets the .deb
(Debian/Ubuntu) or .rpm (Fedora/RHEL) is picked, the version is read from that
file name (ziti-edge-tunnel-gui_1.0.3-1_all.deb -> 1.0.3-1), falling back to
the tag (v1.0.3), and it is offered only if newer than the running version.
"""
import hashlib
import json
import logging
import os
import re

from .qt import QtCore, QtNetwork, Signal
from . import __version__, paths

log = logging.getLogger(__name__)


def update_repo():
    repo = os.environ.get("ZDE_UPDATE_REPO")
    if repo is None:
        try:
            from ._build_config import UPDATE_REPO as repo  # written by packaging/install.sh
        except ImportError:
            repo = ""
        repo = repo or paths.PROJECT_REPO
    repo = (repo or "").strip().strip("/")
    if repo.lower() in ("none", "off", "disabled"):
        return ""
    return repo if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$", repo) else ""


def parse_version(v):
    """'v1.2.3-1' -> (1, 2, 3, 1); non-numeric parts are ignored."""
    v = (v or "").strip().lstrip("vV")
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def upstream(v):
    """Drop the package revision: '1.0.3-1' -> '1.0.3' (the app only knows its upstream version)."""
    return re.sub(r"-[0-9][0-9A-Za-z.]*$", "", (v or "").strip().lstrip("vV"))


def is_newer(candidate, current=__version__):
    a, b = list(parse_version(upstream(candidate))), list(parse_version(upstream(current)))
    n = max(len(a), len(b))
    return a + [0] * (n - len(a)) > b + [0] * (n - len(b))


def package_kind():
    """How this copy was installed: 'deb', 'rpm' or None (running from source)."""
    if os.path.exists("/var/lib/dpkg/info/%s.list" % paths.APP_ID):
        return "deb"
    if os.path.isdir("/var/lib/rpm") or os.path.isdir("/usr/lib/sysimage/rpm"):
        if os.path.exists("/usr/lib/%s" % paths.APP_ID):
            return "rpm"
    if os.path.exists("/usr/bin/dpkg"):
        return "deb"
    if os.path.exists("/usr/bin/rpm"):
        return "rpm"
    return None


def _matches(name, kind):
    n = name.lower()
    if kind == "deb":
        return n.endswith(".deb") and ("_all" in n or "_amd64" in n or "noarch" not in n)
    return n.endswith(".rpm") and not n.endswith(".src.rpm")


def pick_asset(assets, kind):
    """The release's package for this system; prefers files named after the package."""
    candidates = [a for a in assets if _matches(a.get("name", ""), kind)]
    named = [a for a in candidates if a.get("name", "").startswith(paths.APP_ID)]
    pool = named or candidates
    return pool[0] if len(pool) >= 1 else None


_ASSET_VERSION = re.compile(r"[_-](\d+(?:\.\d+)+(?:-[0-9][0-9A-Za-z.]*)?)(?:[._](?:all|noarch|amd64|x86_64))")


def asset_version(name):
    """'ziti-edge-tunnel-gui_1.0.3-1_all.deb' -> '1.0.3-1'; '' if the name has no version."""
    m = _ASSET_VERSION.search(name or "")
    return m.group(1) if m else ""


def release_version(rel, kind):
    asset = pick_asset(rel.get("assets") or [], kind)
    v = asset_version(asset.get("name", "")) if asset else ""
    return v or (rel.get("tag_name") or "").lstrip("vV")


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, paths.APP_ID)
    os.makedirs(d, exist_ok=True)
    return d


class Updater(QtCore.QObject):
    available = Signal(str, object)     # version, release info dict
    upToDate = Signal(str)              # latest version seen
    failed = Signal(str)
    progress = Signal(str)
    downloaded = Signal(str)            # local file path

    def __init__(self, parent=None):
        super(Updater, self).__init__(parent)
        self.repo = update_repo()
        self.net = QtNetwork.QNetworkAccessManager(self)
        self.latest = None
        self._busy = False

    def enabled(self):
        return bool(self.repo)

    def _get(self, url, cb, accept="application/vnd.github+json"):
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        req.setRawHeader(b"Accept", accept.encode())
        req.setRawHeader(b"User-Agent", ("%s/%s" % (paths.APP_ID, __version__)).encode())
        try:
            req.setAttribute(QtNetwork.QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QtNetwork.QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        except AttributeError:  # pragma: no cover - old Qt5
            pass
        reply = self.net.get(req)

        def done():
            err = reply.error()
            data = bytes(reply.readAll())
            status = reply.attribute(QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            reply.deleteLater()
            if err != QtNetwork.QNetworkReply.NetworkError.NoError:
                cb(None, reply.errorString() or "network error (HTTP %s)" % status)
            else:
                cb(data, None)
        reply.finished.connect(done)
        return reply

    def check(self):
        if not self.repo:
            self.failed.emit("Update checks are not configured for this build")
            return
        if self._busy:
            return
        self._busy = True
        self.progress.emit("Checking for updates...")

        def got(data, err):
            self._busy = False
            if err:
                self.failed.emit("Could not check for updates: %s" % err)
                return
            try:
                rel = json.loads(data.decode("utf-8"))
            except ValueError:
                self.failed.emit("Unexpected answer from GitHub")
                return
            tag = rel.get("tag_name") or ""
            self.latest = rel
            kind = package_kind()
            if rel.get("draft") or rel.get("prerelease") or not tag:
                self.upToDate.emit(__version__)
                return
            if pick_asset(rel.get("assets") or [], kind) is None:
                self.failed.emit("Release %s has no .%s file attached" % (tag, kind or "deb/.rpm"))
                return
            version = release_version(rel, kind)
            log.info("latest release %s: %s package version %s (running %s)", tag, kind, version, __version__)
            if is_newer(version):
                self.available.emit(upstream(version), rel)
            else:
                self.upToDate.emit(upstream(version))
        api = os.environ.get("ZDE_UPDATE_API", "https://api.github.com").rstrip("/")
        self._get("%s/repos/%s/releases/latest" % (api, self.repo), got)

    def download(self, rel):
        kind = package_kind()
        asset = pick_asset(rel.get("assets") or [], kind)
        if asset is None:
            self.failed.emit("The release has no %s package for this system" % (kind or "suitable"))
            return
        sums = next((a for a in rel.get("assets") or [] if a.get("name") == "SHA256SUMS"), None)
        name = os.path.basename(asset["name"])
        dest = os.path.join(cache_dir(), name)
        self.progress.emit("Downloading %s..." % name)

        def got_pkg(data, err, expected=None):
            if err:
                self.failed.emit("Download failed: %s" % err)
                return
            if expected and hashlib.sha256(data).hexdigest() != expected:
                self.failed.emit("Download did not match SHA256SUMS; not installing")
                return
            with open(dest, "wb") as f:
                f.write(data)
            self.downloaded.emit(dest)

        if sums is None:
            log.warning("release has no SHA256SUMS asset; relying on HTTPS only")
            self._get(asset["browser_download_url"], got_pkg, accept="application/octet-stream")
            return

        def got_sums(data, err):
            if err:
                self.failed.emit("Could not fetch SHA256SUMS: %s" % err)
                return
            expected = None
            for line in data.decode("utf-8", "replace").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[-1].lstrip("*") == name:
                    expected = parts[0].lower()
            if not expected:
                self.failed.emit("SHA256SUMS has no entry for %s; not installing" % name)
                return
            self._get(asset["browser_download_url"], lambda d, e: got_pkg(d, e, expected),
                      accept="application/octet-stream")
        self._get(sums["browser_download_url"], got_sums, accept="application/octet-stream")
