#!/bin/sh
# Install ziti-edge-tunnel-gui into DESTDIR (shared by the .deb and .rpm builds).
# Usage: packaging/install.sh DESTDIR
set -eu
DESTDIR="${1:?usage: install.sh DESTDIR}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$DESTDIR/usr/lib/ziti-edge-tunnel-gui"

install -d "$LIB"
( cd "$SRC/src" && find ziti_desktop_edge -type f \( -name '*.py' -o -name '*.png' -o -name '*.ttf' \) ) |
while read -r f; do
    install -D -m 0644 "$SRC/src/$f" "$LIB/$f"
done
install -D -m 0755 "$SRC/bin/ziti-edge-tunnel-gui" "$DESTDIR/usr/bin/ziti-edge-tunnel-gui"
install -D -m 0755 "$SRC/libexec/ziti-edge-tunnel-gui-helper" \
    "$DESTDIR/usr/libexec/ziti-edge-tunnel-gui/ziti-edge-tunnel-gui-helper"
install -D -m 0644 "$SRC/data/ziti-edge-tunnel-gui.desktop" \
    "$DESTDIR/usr/share/applications/ziti-edge-tunnel-gui.desktop"
install -D -m 0644 "$SRC/data/ziti-edge-tunnel-gui-autostart.desktop" \
    "$DESTDIR/etc/xdg/autostart/ziti-edge-tunnel-gui.desktop"
install -D -m 0644 "$SRC/data/ziti-edge-tunnel-gui.metainfo.xml" \
    "$DESTDIR/usr/share/metainfo/ziti-edge-tunnel-gui.metainfo.xml"
install -D -m 0644 "$SRC/data/polkit/org.openziti.ziti-edge-tunnel-gui.policy" \
    "$DESTDIR/usr/share/polkit-1/actions/org.openziti.ziti-edge-tunnel-gui.policy"
install -D -m 0644 "$SRC/data/polkit/49-ziti-edge-tunnel-gui.rules" \
    "$DESTDIR/usr/share/polkit-1/rules.d/49-ziti-edge-tunnel-gui.rules"
for d in "$SRC"/data/icons/*x*; do
    s="$(basename "$d")"
    install -D -m 0644 "$d/ziti-edge-tunnel-gui.png" \
        "$DESTDIR/usr/share/icons/hicolor/$s/apps/ziti-edge-tunnel-gui.png"
done
for f in README.md LICENSE NOTICE; do
    [ -f "$SRC/$f" ] && install -D -m 0644 "$SRC/$f" "$DESTDIR/usr/share/doc/ziti-edge-tunnel-gui/$f"
done
exit 0
