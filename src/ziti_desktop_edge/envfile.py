"""Read/write the systemd EnvironmentFile used by ziti-edge-tunnel.service.

The stock unit (ziti-edge-tunnel.service from the OpenZiti package) reads
``/opt/openziti/etc/ziti-edge-tunnel.env`` and passes the values to
``ziti-edge-tunnel run --verbose=${ZITI_VERBOSE}
--dns-ip-range=${ZITI_DNS_IP_RANGE} --identity-dir=${ZITI_IDENTITY_DIR}``.

This module has no Qt dependency because the root helper imports it.
Comments and unknown lines are preserved when writing.
"""
import ipaddress
import os
import re
import tempfile

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

# keys the GUI may change, with validators
LOG_LEVELS = ("none", "error", "warn", "info", "debug", "verbose", "trace")


def validate_dns_ip_range(value):
    """Return a normalised n.n.n.n/m string or raise ValueError.

    ziti-edge-tunnel rejects prefixes outside 10..18 (process_cmd.c).
    """
    value = (value or "").strip()
    m = re.match(r"^(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})$", value)
    if not m:
        raise ValueError("expected n.n.n.n/m, e.g. 100.64.0.1/10")
    ip = ipaddress.IPv4Address(m.group(1))  # raises ValueError on bad octets
    prefix = int(m.group(2))
    if prefix < 10 or prefix > 18:
        raise ValueError("prefix length must be between 10 and 18")
    return "%s/%d" % (ip, prefix)


def validate_log_level(value):
    v = (value or "").strip().lower()
    if v in LOG_LEVELS or (v.isdigit() and 0 <= int(v) <= 6):
        return v
    raise ValueError("log level must be one of %s" % ", ".join(LOG_LEVELS))


VALIDATORS = {
    "ZITI_DNS_IP_RANGE": validate_dns_ip_range,
    "ZITI_VERBOSE": validate_log_level,
}


def _unquote(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        inner = raw[1:-1]
        if raw[0] == '"':
            inner = re.sub(r'\\(["\\$`])', r"\1", inner)
        return inner
    # strip trailing comment on unquoted values
    return raw.split(" #", 1)[0].strip()


def parse(text):
    """Return {KEY: value} for active (uncommented) assignments."""
    out = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = _unquote(m.group(2))
    return out


def read(path):
    try:
        with open(path, "r") as f:
            return parse(f.read())
    except (IOError, OSError):
        return {}


def _quote(value):
    if "'" in value or "\n" in value:
        raise ValueError("value may not contain quotes or newlines")
    return "'%s'" % value


def update_text(text, changes):
    """Apply {KEY: value-or-None} to env-file text; None removes the key."""
    lines = text.splitlines()
    done = set()
    out = []
    for line in lines:
        m = None if line.lstrip().startswith("#") else _LINE.match(line)
        if m and m.group(1) in changes:
            key = m.group(1)
            if key in done:
                continue  # drop duplicates
            done.add(key)
            if changes[key] is None:
                continue
            out.append("%s=%s" % (key, _quote(changes[key])))
        else:
            out.append(line)
    pending = [k for k in changes if k not in done and changes[k] is not None]
    if pending:
        if out and out[-1].strip():
            out.append("")
        out.append("# set by Ziti Desktop Edge (ziti-edge-tunnel-gui)")
        for k in pending:
            out.append("%s=%s" % (k, _quote(changes[k])))
    return "\n".join(out) + "\n"


def write(path, changes):
    """Validate and atomically apply changes to the env file."""
    clean = {}
    for k, v in changes.items():
        if k not in VALIDATORS:
            raise ValueError("refusing to set unsupported key %s" % k)
        clean[k] = None if v is None else VALIDATORS[k](v)
    try:
        with open(path, "r") as f:
            text = f.read()
        st = os.stat(path)
        mode, uid, gid = st.st_mode & 0o7777, st.st_uid, st.st_gid
    except (IOError, OSError):
        text, mode, uid, gid = "", 0o644, 0, 0
    new = update_text(text, clean)
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".ziti-edge-tunnel.env.", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(new)
        os.chmod(tmp, mode)
        try:
            os.chown(tmp, uid, gid)
        except OSError:
            pass
        os.rename(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return clean
