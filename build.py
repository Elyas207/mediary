#!/usr/bin/env python3
"""Build a distributable Mediary application with PyInstaller.

    python build.py                # build for the current platform
    python build.py --onefile      # single-file executable (slower to start)
    python build.py --clean        # remove build artefacts first

FFmpeg is deliberately not bundled by default: its licence depends on how the
binary was configured. Drop an ``ffmpeg`` (or ``ffmpeg.exe``) into ``bin/``
before building to include one, and read the licensing note in the README first.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "Mediary"
ENTRY_POINT = ROOT / "app" / "main.py"
BIN_DIR = ROOT / "bin"
ICON_DIR = ROOT / "packaging" / "icons"

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"


def _generate_icons() -> None:
    """Render the icon files if they are not already there.

    They are generated from the same geometry as the in-app mark, so the repo
    does not need to carry binary art and a fresh clone still builds a properly
    branded installer.
    """
    script = ROOT / "packaging" / "make_icons.py"
    if not script.is_file():
        return
    try:
        subprocess.run([sys.executable, str(script)], cwd=ROOT, check=False)
    except OSError as exc:
        print(f"note: could not generate icons ({exc}); continuing with the default")


def _icon_argument() -> list:
    """Use a platform icon if one is available."""
    if not (IS_WINDOWS or IS_MACOS):
        return []

    candidate = ICON_DIR / ("mediary.ico" if IS_WINDOWS else "mediary.icns")
    if not candidate.is_file():
        _generate_icons()
    if candidate.is_file():
        return ["--icon", str(candidate)]

    print(f"note: no icon at {candidate}; using the default")
    return []


def _bundled_binaries() -> list:
    """Include anything the packager dropped into bin/."""
    if not BIN_DIR.is_dir():
        return []
    arguments = []
    for binary in sorted(BIN_DIR.iterdir()):
        if binary.is_file():
            separator = ";" if IS_WINDOWS else ":"
            arguments += ["--add-binary", f"{binary}{separator}bin"]
            print(f"bundling {binary.name}")
    return arguments


def build(onefile: bool = False, clean: bool = False, debug: bool = False) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print('PyInstaller is not installed. Run:  pip install -e ".[build]"')
        return 1

    if clean:
        for directory in (ROOT / "build", ROOT / "dist"):
            if directory.exists():
                print(f"removing {directory}")
                shutil.rmtree(directory, ignore_errors=True)
        for spec in ROOT.glob("*.spec"):
            spec.unlink()

    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        "--windowed" if not debug else "--console",
        "--onefile" if onefile else "--onedir",
        # PySide6 pulls in a great deal that Mediary never touches; excluding it
        # roughly halves the bundle.
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "PySide6.QtDataVisualization",
        "--exclude-module", "PySide6.QtQuick3D",
        "--exclude-module", "tkinter",
        "--exclude-module", "test",
        "--exclude-module", "pytest",
        # Qt multimedia backends are loaded dynamically, so PyInstaller cannot
        # see them by static analysis.
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--hidden-import", "PySide6.QtSvg",
    ]

    if IS_MACOS:
        command += ["--osx-bundle-identifier", "app.mediary.Mediary"]

    command += _icon_argument()
    command += _bundled_binaries()
    command.append(str(ENTRY_POINT))

    print("\n" + " ".join(command) + "\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    print("\nBuild complete.")
    if IS_MACOS:
        print(f"  {ROOT / 'dist' / (APP_NAME + '.app')}")
        print("\n  Disk image:")
        print(
            f"    hdiutil create -volname {APP_NAME} "
            f"-srcfolder dist/{APP_NAME}.app -ov -format UDZO dist/{APP_NAME}.dmg"
        )
    elif IS_WINDOWS:
        print(f"  {ROOT / 'dist' / APP_NAME / (APP_NAME + '.exe')}")
        print("\n  Installer:  iscc packaging/mediary.iss")
    else:
        print(f"  {ROOT / 'dist' / APP_NAME}")
        print("\n  AppImage:   appimagetool packaging/AppDir")

    if not (BIN_DIR / ("ffmpeg.exe" if IS_WINDOWS else "ffmpeg")).is_file():
        print(
            "\nNote: no FFmpeg was bundled. Mediary will look for one on the "
            "user's PATH and prompt if it cannot find it."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Mediary.")
    parser.add_argument("--onefile", action="store_true", help="single-file executable")
    parser.add_argument("--clean", action="store_true", help="remove build artefacts first")
    parser.add_argument("--debug", action="store_true", help="keep a console window")
    arguments = parser.parse_args()
    return build(onefile=arguments.onefile, clean=arguments.clean, debug=arguments.debug)


if __name__ == "__main__":
    raise SystemExit(main())
