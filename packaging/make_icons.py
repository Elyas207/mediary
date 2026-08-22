#!/usr/bin/env python3
"""Render the Mediary mark to the icon formats each platform's packaging wants.

The app draws its own window icon at runtime, so these files exist only for the
installer, the dock/taskbar and the file manager. Generating them from the same
geometry as the in-app mark keeps everything consistent, and means the repo does
not have to carry binary art.

    python packaging/make_icons.py

Writes packaging/icons/mediary.png, mediary.ico and (on macOS) mediary.icns.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Rendering happens with no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT_DIR = Path(__file__).resolve().parent / "icons"
ACCENT = "#5B7CFA"
MARK = "#FFFFFF"

#: Sizes Windows expects inside a single .ico.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
#: The full set Apple's iconutil wants for a .icns.
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def render(size: int) -> "QImage":  # noqa: F821 - Qt type, imported lazily
    """Draw the Mediary mark: a play triangle in a rounded square."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(QColor(ACCENT))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)

    # Nudged right of centre so the triangle reads as motion rather than as a
    # generic play button sitting dead centre.
    cx, cy, unit = size * 0.54, size * 0.5, size / 22
    painter.setBrush(QColor(MARK))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(cx - 3.2 * unit, cy - 4.4 * unit),
                QPointF(cx + 4.4 * unit, cy),
                QPointF(cx - 3.2 * unit, cy + 4.4 * unit),
            ]
        )
    )
    painter.end()
    return image


def _ensure_app():
    """Qt needs an application object before it will paint."""
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.instance() or QGuiApplication([])


def write_png(path: Path, size: int = 512) -> Path:
    render(size).save(str(path), "PNG")
    return path


def write_ico(path: Path) -> Path | None:
    """Multi-resolution .ico, via Pillow when it is available.

    Qt can only write a single-size ICO, which looks poor in Explorer at
    anything other than that one size.
    """
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed; skipping .ico (install it for a Windows icon)")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        largest = Path(tmp) / "mark.png"
        write_png(largest, max(ICO_SIZES))
        Image.open(largest).save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    return path


def write_icns(path: Path) -> Path | None:
    """macOS .icns, built with iconutil from a generated .iconset."""
    if sys.platform != "darwin":
        print("Not macOS; skipping .icns")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "mediary.iconset"
        iconset.mkdir()
        for size in ICNS_SIZES:
            write_png(iconset / f"icon_{size}x{size}.png", size)
            # Retina variants are the next size up, named for the smaller one.
            if size * 2 <= max(ICNS_SIZES):
                write_png(iconset / f"icon_{size}x{size}@2x.png", size * 2)
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("iconutil failed:", result.stderr.strip())
            return None
    return path


def main() -> int:
    _ensure_app()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    written = [write_png(OUTPUT_DIR / "mediary.png", 512)]

    ico = write_ico(OUTPUT_DIR / "mediary.ico")
    if ico:
        written.append(ico)

    icns = write_icns(OUTPUT_DIR / "mediary.icns")
    if icns:
        written.append(icns)

    for path in written:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
