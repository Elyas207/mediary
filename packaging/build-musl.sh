#!/bin/sh
# Build Mediary against musl libc, for Alpine and other musl distributions.
#
# Run this inside an Alpine container with the repository mounted at /src:
#
#     docker run --rm -v "$PWD:/src" -w /src alpine:edge sh packaging/build-musl.sh
#
# Why this exists as its own script rather than a pip install like the other
# platforms: PySide6 publishes no musllinux wheels, only manylinux ones, so
# `pip install PySide6` cannot work here at all. Alpine packages Qt and the
# PySide6 bindings itself, so the build uses those from the system and pip only
# supplies the pure-Python pieces.
set -eu

VERSION="${VERSION:-0.0.0}"
OUT_NAME="Mediary-${VERSION}-linux-x86_64-musl.tar.gz"
VENV=/venv

echo "==> Installing build and runtime packages"
apk add --no-cache \
    python3 python3-dev py3-pip \
    py3-pyside6 py3-shiboken6 \
    qt6-qtbase qt6-qtbase-x11 qt6-qtsvg qt6-qtmultimedia \
    binutils gcc musl-dev zlib-dev \
    tar

echo "==> Creating a venv that can see Alpine's PySide6"
# --system-site-packages is essential: PySide6 comes from apk, not from pip.
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --no-cache-dir --upgrade pip

echo "==> Installing the pieces pip can provide"
# --no-deps on Mediary itself, so pip does not try to pull the PySide6 wheel
# that does not exist for musl.
"$VENV/bin/pip" install --no-cache-dir yt-dlp pyinstaller pillow pytest
"$VENV/bin/pip" install --no-cache-dir --no-deps -e .

echo "==> Confirming the interpreter can see Qt"
"$VENV/bin/python" - <<'PY'
import platform
import PySide6
from PySide6 import QtCore
print("  PySide6 :", PySide6.__version__)
print("  Qt      :", QtCore.qVersion())
print("  libc    :", platform.libc_ver())
try:
    from PySide6 import QtMultimedia  # noqa: F401
    print("  QtMultimedia: present")
except ImportError as exc:
    # Not fatal - Mediary disables in-app playback and carries on.
    print("  QtMultimedia: absent (%s)" % exc)
PY

echo "==> Running the test suite"
QT_QPA_PLATFORM=offscreen "$VENV/bin/python" -m pytest -q

echo "==> Generating icons"
QT_QPA_PLATFORM=offscreen "$VENV/bin/python" packaging/make_icons.py

echo "==> Building"
"$VENV/bin/python" build.py --clean

echo "==> Smoke-testing the built binary"
./dist/Mediary/Mediary --version

echo "==> Packaging $OUT_NAME"
# A tarball rather than an AppImage: the AppImage runtime is glibc-based, so an
# AppImage would defeat the point of a musl build.
cp README.md LICENSE dist/Mediary/
tar -czf "dist/$OUT_NAME" -C dist Mediary

# The container runs as root; hand the artefacts back to the host user so the
# workflow steps that follow can read them.
if [ -n "${HOST_UID:-}" ]; then
    chown -R "${HOST_UID}:${HOST_GID:-$HOST_UID}" dist build 2>/dev/null || true
fi

ls -lh "dist/$OUT_NAME"
echo "==> Done"
