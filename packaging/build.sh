#!/bin/sh
# Build the .deb and .rpm packages into dist/.
#   packaging/build.sh            # both
#   packaging/build.sh deb|rpm    # one
# Env: RELEASE (default 1), MAINTAINER (default "Open Source <opensource@openziti.invalid>"),
#      UPDATE_REPO=owner/repo  -> the app checks that repo's GitHub releases for updates
#        (attach the .deb, .rpm and dist/SHA256SUMS to each release)
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/ziti_desktop_edge/__init__.py)"
RELEASE="${RELEASE:-1}"
MAINTAINER="${MAINTAINER:-Open Source <opensource@openziti.invalid>}"
WHAT="${1:-all}"
DIST="$ROOT/dist"
mkdir -p "$DIST"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

subst() {
    sed -e "s|@VERSION@|$VERSION|g" -e "s|@RELEASE@|$RELEASE|g" \
        -e "s|@MAINTAINER@|$MAINTAINER|g" -e "s|@UPDATE_REPO@|${UPDATE_REPO:-}|g" \
        -e "s|@CHANGELOG_DATE@|$(LC_ALL=C date +'%a %b %d %Y')|g" "$1"
}

build_deb() {
    command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found, skipping .deb" >&2; return 0; }
    R="$BUILD/deb"
    sh packaging/install.sh "$R"
    install -d "$R/DEBIAN"
    subst packaging/deb/control.in > "$R/DEBIAN/control"
    echo "Installed-Size: $(du -sk "$R" | cut -f1)" >> "$R/DEBIAN/control"
    install -m 0755 packaging/deb/postinst "$R/DEBIAN/postinst"
    echo "/etc/xdg/autostart/ziti-edge-tunnel-gui.desktop" > "$R/DEBIAN/conffiles"
    # Debian puts the copyright file in place of LICENSE
    mv "$R/usr/share/doc/ziti-edge-tunnel-gui/LICENSE" "$R/usr/share/doc/ziti-edge-tunnel-gui/copyright"
    dpkg-deb --root-owner-group -Zxz --build "$R" \
        "$DIST/ziti-edge-tunnel-gui_${VERSION}-${RELEASE}_all.deb"
}

build_rpm() {
    command -v rpmbuild >/dev/null || { echo "rpmbuild not found, skipping .rpm" >&2; return 0; }
    T="$BUILD/rpm"
    mkdir -p "$T/SOURCES" "$T/SPECS" "$T/src/ziti-edge-tunnel-gui-$VERSION"
    tar --exclude=./dist --exclude=./.mock --exclude=./.git --exclude='__pycache__' -cf - . |
        tar -xf - -C "$T/src/ziti-edge-tunnel-gui-$VERSION"
    tar -czf "$T/SOURCES/ziti-edge-tunnel-gui-$VERSION.tar.gz" -C "$T/src" "ziti-edge-tunnel-gui-$VERSION"
    subst packaging/rpm/ziti-edge-tunnel-gui.spec.in > "$T/SPECS/ziti-edge-tunnel-gui.spec"
    rpmbuild --define "_topdir $T" -bb "$T/SPECS/ziti-edge-tunnel-gui.spec" >/dev/null
    cp "$T"/RPMS/noarch/*.rpm "$DIST/"
}

export UPDATE_REPO="${UPDATE_REPO:-}"
case "$UPDATE_REPO" in ""|*/*) ;; *) echo "UPDATE_REPO must be owner/repo" >&2; exit 2 ;; esac
case "$WHAT" in
    deb) build_deb ;;
    rpm) build_rpm ;;
    all) build_deb; build_rpm ;;
    *) echo "usage: $0 [deb|rpm|all]" >&2; exit 2 ;;
esac
( cd "$DIST" && ls ziti-edge-tunnel-gui*.deb ziti-edge-tunnel-gui*.rpm 2>/dev/null | xargs -r sha256sum > SHA256SUMS )
ls -l "$DIST"
