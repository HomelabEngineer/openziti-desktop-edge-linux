"""In-app updates.

Ubuntu's App Center / GNOME Software only offer "Remove" when you open a .deb
whose package is already installed, so double-clicking a newer .deb cannot
upgrade it. The app therefore installs updates itself, through the pkexec
helper (``install-update``), which uses apt/dnf so it is a normal package
upgrade, and then restarts into the new version.

Two sources:
* a .deb/.rpm file the user picks ("Install Update From File...");
* optionally the latest GitHub release of UPDATE_REPO (set at build time with
  ``UPDATE_REPO=owner/repo packaging/build.sh`` or at run time with
  ``ZDE_UPDATE_REPO``). Release assets are verified against a SHA256SUMS
  asset when the release has one.
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
    repo = (repo or "").strip().strip("/")
    return repo if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$", repo) else ""


def parse_version(v):
    """'v1.2.3-1' -> (1, 2, 3, 1); non-numeric parts are ignored."""
    v = (v or "").strip().lstrip("vV")
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def is_newer(candidate, current=__version__):
    a, b = list(parse_version(candidate)), list(parse_version(current))
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


def pick_asset(assets, kind):
    for a in assets:
        name = a.get("name", "")
        if not name.startswith(paths.APP_ID):
            continue
        if (kind == "deb" and name.endswith(".deb")) or (kind == "rpm" and name.endswith(".rpm")):
            return a
    return None


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
            if rel.get("draft") or rel.get("prerelease") or not tag:
                self.upToDate.emit(__version__)
            elif is_newer(tag):
                self.available.emit(tag.lstrip("vV"), rel)
            else:
                self.upToDate.emit(tag.lstrip("vV"))
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
