"""Removing Mediary's traces from the machine.

A local-first app that scatters a database, a config file, a cache and an
autostart entry across platform-specific directories owes the user a way to
clear them out. Deleting the application folder does not do it.

Two principles run through this module:

* **The media library is never touched by default.** Those are the user's files,
  often the whole point of having used the app. Removing them is a separate,
  explicitly-opted-into step.
* **Nothing is deleted that was not listed first.** Every operation is planned
  and shown before anything is removed, and the plan reports real sizes so
  "delete my library" is never an abstract choice.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.paths import (
    cache_dir,
    config_dir,
    data_dir,
    logs_dir,
)

log = get_logger("uninstall")


@dataclass
class Target:
    """One thing that can be removed."""

    key: str
    label: str
    description: str
    path: Path
    size: int = 0
    file_count: int = 0
    exists: bool = False
    #: True for anything the user would be upset to lose.
    destructive: bool = False


@dataclass
class UninstallPlan:
    """What would be removed, measured before anything happens."""

    targets: list = field(default_factory=list)
    autostart_registered: bool = False

    def by_key(self, key: str) -> Target | None:
        return next((t for t in self.targets if t.key == key), None)

    def total_size(self, keys) -> int:
        chosen = set(keys)
        return sum(t.size for t in self.targets if t.key in chosen and t.exists)


@dataclass
class UninstallResult:
    removed: list = field(default_factory=list)
    failed: list = field(default_factory=list)   # (label, reason)
    autostart_removed: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        # Failures are reported first and unconditionally. Saying "nothing was
        # removed" when every deletion failed would read as "there was nothing
        # to do", which is the opposite of what happened.
        failure_text = ""
        if self.failed:
            count = len(self.failed)
            failure_text = f"{count} item{'s' if count != 1 else ''} could not be removed."

        parts = []
        if self.removed:
            parts.append(f"Removed {len(self.removed)} item{'s' if len(self.removed) != 1 else ''}")
        if self.autostart_removed:
            parts.append("cleared the sign-in entry")

        if not parts:
            return failure_text or "Nothing was removed."
        return ", ".join(parts) + "." + (f" {failure_text}" if failure_text else "")


def _measure(path: Path) -> tuple:
    """Return ``(bytes, file_count)`` for a file or directory tree."""
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 1

    total = 0
    count = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                    count += 1
            except OSError:
                continue
    except OSError:
        pass
    return total, count


class UninstallService:
    """Plans and performs removal of Mediary's local data."""

    def __init__(self, library_root: Path | str | None = None) -> None:
        self._library_root = Path(library_root).expanduser() if library_root else None

    # ------------------------------------------------------------------

    def plan(self) -> UninstallPlan:
        """Measure everything that could be removed. Deletes nothing."""
        from app.services.autostart_service import AutostartService

        definitions = [
            (
                "settings", "Settings and preferences",
                "Your configuration, including the library location and defaults.",
                config_dir(), False,
            ),
            (
                "database", "Library index",
                "The SQLite database: titles, tags, licence notes and favourites. "
                "Your media files are not in here.",
                data_dir(), False,
            ),
            (
                "cache", "Cache and thumbnails",
                "Regenerable artwork and extractor caches. Safe to remove at any time.",
                cache_dir(), False,
            ),
            (
                "logs", "Logs",
                "Local diagnostic logs.",
                logs_dir(), False,
            ),
        ]

        targets = []
        for key, label, description, path, destructive in definitions:
            size, count = _measure(path)
            targets.append(
                Target(
                    key=key, label=label, description=description, path=path,
                    size=size, file_count=count, exists=path.exists(),
                    destructive=destructive,
                )
            )

        if self._library_root is not None:
            size, count = _measure(self._library_root)
            targets.append(
                Target(
                    key="library",
                    label="Downloaded media",
                    description=(
                        "Every file Mediary has downloaded. This is your media - "
                        "deleting it cannot be undone."
                    ),
                    path=self._library_root,
                    size=size,
                    file_count=count,
                    exists=self._library_root.exists(),
                    destructive=True,
                )
            )

        return UninstallPlan(
            targets=targets,
            autostart_registered=AutostartService.is_enabled(),
        )

    # ------------------------------------------------------------------

    def execute(self, keys, *, remove_autostart: bool = True) -> UninstallResult:
        """Remove the selected targets. Returns what happened to each."""
        from app.services.autostart_service import AutostartService

        result = UninstallResult()
        plan = self.plan()
        chosen = set(keys)

        # The sign-in entry goes first: if a later deletion fails and the user
        # gives up, at least the app is not still launching itself at boot.
        if remove_autostart and plan.autostart_registered:
            ok, error = AutostartService.set_enabled(False)
            if ok:
                result.autostart_removed = True
            else:
                result.failed.append(("Sign-in entry", error))

        # Deliberately ordered so the library is last: if something goes wrong
        # earlier, the irreversible step has not happened yet.
        order = ["cache", "logs", "database", "settings", "library"]
        for key in sorted(chosen, key=lambda k: order.index(k) if k in order else 99):
            target = plan.by_key(key)
            if target is None or not target.exists:
                continue
            ok, error = self._remove(target.path)
            if ok:
                result.removed.append(target.label)
                log.info("Uninstall removed %s (%s)", target.label, target.path)
            else:
                result.failed.append((target.label, error))
                log.error("Uninstall could not remove %s: %s", target.path, error)

        return result

    @staticmethod
    def _remove(path: Path) -> tuple:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=False)
            elif path.exists():
                path.unlink()
            return True, ""
        except OSError as exc:
            return False, str(exc.strerror or exc)

    # ------------------------------------------------------------------

    @staticmethod
    def application_hint() -> str:
        """How to remove the application itself, which Mediary cannot do.

        A running process cannot reliably delete its own executable, and the
        right gesture differs per platform anyway.
        """
        import sys

        if sys.platform.startswith("win"):
            return (
                "To remove the application itself: if you installed Mediary with the "
                "installer, use Settings › Apps › Installed apps. If you are running "
                "the portable build, delete the folder you extracted."
            )
        if sys.platform == "darwin":
            return (
                "To remove the application itself: drag Mediary from your "
                "Applications folder to the Bin."
            )
        return (
            "To remove the application itself: delete the AppImage, or uninstall "
            "the package you installed it from."
        )
