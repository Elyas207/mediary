"""Shared fixtures.

Every test runs against a temporary ``MEDIARY_HOME`` and an in-memory or
throwaway database, so the suite never touches a real user library and never
needs the network.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def mediary_home(tmp_path, monkeypatch):
    """Redirect every Mediary directory into a per-test temp folder."""
    from app.utils import paths

    home = tmp_path / "mediary-home"
    home.mkdir()
    monkeypatch.setenv(paths.ENV_HOME, str(home))
    paths.reset_path_cache()

    from app.config import settings as settings_module

    settings_module.reset_settings_store()

    yield home

    paths.reset_path_cache()
    settings_module.reset_settings_store()


@pytest.fixture
def settings(mediary_home):
    """A Settings object rooted inside the temp home."""
    from app.config.settings import Settings

    return Settings(library_root=str(mediary_home / "library"), first_run_complete=True)


@pytest.fixture
def store(mediary_home):
    from app.config.settings import SettingsStore

    return SettingsStore()


@pytest.fixture
def database():
    """A migrated in-memory database."""
    from app.database.database import Database

    db = Database(":memory:")
    db.initialise()
    yield db
    db.close()


@pytest.fixture
def library(database):
    from app.services.library_service import LibraryService

    return LibraryService(database)


@pytest.fixture
def organizer(settings):
    from app.services.organization_service import OrganizationService

    service = OrganizationService(settings)
    service.ensure_library_tree()
    return service


@pytest.fixture
def fixture_info():
    """Load a yt-dlp metadata fixture by name."""

    def _load(name: str) -> dict:
        path = FIXTURES / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def make_item():
    """Factory for MediaItem instances with sensible defaults."""
    from app.models.media import MediaItem

    counter = {"n": 0}

    def _make(**overrides):
        counter["n"] += 1
        n = counter["n"]
        defaults = {
            "filename": f"Item {n}.mp3",
            "file_path": f"/library/Audio/Item {n}.mp3",
            "file_size": 1024 * n,
            "title": f"Item {n}",
            "creator": "Example Creator",
            "media_kind": "audio",
            "category": "Sound Effects",
            "container": "mp3",
            "duration": 10.0 * n,
            "source_url": f"https://example.com/{n}",
            "platform": "Example",
            "platform_id": f"id{n}",
            "downloaded_at": f"2026-01-{min(28, n):02d}T10:00:00",
        }
        defaults.update(overrides)
        return MediaItem(**defaults)

    return _make


@pytest.fixture
def real_file(tmp_path):
    """Create a throwaway file on disk and return its path."""

    def _make(name: str = "sample.mp3", size: int = 64) -> Path:
        path = tmp_path / "files" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
        return path

    return _make


def pytest_configure(config):
    # Qt widgets are only constructed in the UI tests; make sure they can run
    # on a machine with no display.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
