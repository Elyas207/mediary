# Contributing to Mediary

Thanks for taking an interest. This document covers how to get set up, the
conventions the codebase holds to, and what a reviewable pull request looks like.

---

## Development setup

```bash
git clone https://github.com/Elyas207/mediary.git
cd mediary

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Verify:

```bash
pytest              # 553 tests, all offline
ruff check app tests
python -m app.main
```

Work against a sandbox so you never touch your real library:

```bash
MEDIARY_HOME=/tmp/mediary-dev python -m app.main
```

`MEDIARY_HOME` relocates config, database, cache, logs and the default library
root. The test suite sets it automatically for every test.

---

## Architecture rules

These are not style preferences — breaking one of them causes real bugs, so a PR
that does will be asked to change.

**1. The UI thread never blocks.**
Every network call, subprocess and `ffprobe` runs on a `QRunnable` in a
`QThreadPool`. If you are about to call something that can take 50ms, it belongs
on a worker.

**2. Workers own no widgets and no database handle.**
A worker emits a signal; a service on the GUI side does the persisting. This is
what keeps SQLite writes serialised and Qt object ownership sane.

**3. `services/library_service.py` is the only module that writes SQL**
against `media`, `tags` and `media_tags`. If a view needs data, add a method
there rather than reaching for a connection.

**4. `downloader/ytdlp_adapter.py` is the only module that knows yt-dlp exists.**
Option dictionaries, format selector strings and error-message matching all live
there. Everything upstream deals in `MediaInfo`, `DownloadOptions` and
`ExtractionError`.

**5. Every path goes through `utils/paths.py`.**
No `~/Library/…`, no `%APPDATA%`, no `/tmp` anywhere else in the tree.

**6. Every colour, size, radius and font comes from `ui/theme/tokens.py`.**
No literal hex codes in widgets. If you need a new value, add a token — and add
it to *both* palettes; a test enforces that they stay in sync.

**7. Styling lives in `ui/theme/stylesheet.py`,** selected by object name or a
dynamic Qt property. `setStyleSheet()` on an individual widget is a last resort,
and only for something genuinely one-off (a scrim over artwork, for instance).

---

## Product rules

Mediary makes some deliberate promises. Please do not quietly break them.

**Never infer licensing.** Mediary does not guess whether media is reusable, and
must never label anything "royalty free" because it happens to be public.
Licensing fields are user input, and default to *Unknown*.

**Never bypass access controls.** No DRM circumvention, no paywall bypass, no
cookie or credential reading, no private-account scraping. When extraction fails
because content is restricted, report it clearly and stop. Never retry
differently to get around a restriction.

**Never silently destroy data.** Files are never overwritten (`unique_path`
handles collisions), deletions are always confirmed, and *Remove from Library*
must never touch the file on disk.

**Never log a secret.** `utils/logging.py` redacts at the handler level. If you
add a new field that could carry one, add a pattern there too.

**Never block the user over a missing optional dependency.** No FFmpeg means
degraded capability with a clear explanation, not a crash or a locked UI.

**Never leave the app unreachable.** Nothing may hide the window unless a tray
icon is present and visible. If the desktop has no tray, the background options
turn themselves off — a running process with no window and no icon is a bug, not
a feature.

---

## Code style

- `ruff check app tests` must pass. Configuration is in `pyproject.toml`.
- Line length 100.
- `from __future__ import annotations` at the top of every module.
- Type hints on public functions; internal helpers can be looser.
- Qt method overrides keep Qt's camelCase and carry `# noqa: N802 - Qt naming`.

### Comments

Comment the *why*, never the *what*. A comment that restates the code is noise;
a comment that explains a non-obvious constraint saves the next person an hour.

Good:

```python
# yt-dlp uses the literal string "none" to mean "this stream is absent".
# A *missing* codec field means "the extractor does not know", which is very
# different - several extractors (archive.org among them) never report codecs.
```

Not useful:

```python
# Set the codec
self.vcodec = vcodec
```

### Docstrings

One line for anything obvious. A short paragraph where a module or class carries
a design decision worth recording.

---

## Testing

Every behavioural change needs a test. Every bug fix needs a test that fails
before the fix.

**Tests must work offline.** yt-dlp and FFmpeg are always mocked or driven from
fixtures. A test that needs the network will be rejected — that is what
`tests/fixtures/*.json` exists for.

Adding a fixture: capture a real payload once, trim it to the fields Mediary
actually reads, and commit it. `tests/fixtures/unknown_codecs.json` is a good
example — it exists specifically because archive.org omits codec fields, which
was a real bug.

Layout:

| File | Covers |
| --- | --- |
| `test_filenames.py` | Sanitisation, de-duplication, templates |
| `test_urls.py` | URL parsing, platform naming, error translation |
| `test_paths_and_database.py` | Platform paths, migrations, SQLite behaviour |
| `test_settings.py` | Persistence, clamping, corruption recovery |
| `test_library.py` | CRUD, search, tags, favourites, duplicates, integrity |
| `test_organization.py` | Path generation, folder tree, placement |
| `test_ytdlp_adapter.py` | Fixture-driven normalisation and option building |
| `test_download_queue.py` | Task lifecycle and queue mechanics |
| `test_media_tools.py` | FFmpeg detection, probing, formatting, redaction |
| `test_rescan.py` | Disk ↔ index reconciliation |
| `test_pipeline.py` | The end-to-end acceptance scenarios |
| `test_ui.py` | Headless smoke tests for every screen, both themes |
| `test_startup.py` | Autostart registration, tray, background running, single instance |

Useful fixtures in `conftest.py`: `mediary_home`, `settings`, `store`,
`database`, `library`, `organizer`, `make_item`, `real_file`, `fixture_info`.

```bash
pytest                              # everything
pytest tests/test_library.py -v     # one module
pytest -k "duplicate"               # by name
pytest tests/test_ui.py             # headless UI (offscreen Qt)
```

---

## Adding things

### A new library field

1. Add it to `MediaItem` (`models/media.py`) and to `to_row` / `from_row`.
2. Add a **new** migration in `database/migrations.py` and bump `SCHEMA_VERSION`. Never edit a shipped migration.
3. Add the column to `_MEDIA_COLUMNS` in `library_service.py`.
4. Surface it in the detail inspector if the user should see it.
5. Test the round trip and the migration.

### A new setting

1. Add the field to the `Settings` dataclass with a default.
2. Validate it in `Settings.clamp()`.
3. Add a `SettingRow` to the right group in `views/settings_view.py`.
4. Handle it in `MainWindow._on_settings_changed` if it needs to take effect immediately.
5. Test persistence and clamping.

### A new icon

Add a 24×24 stroke path to `_PATHS` in `ui/theme/icons.py`. Match the existing
geometry: 1.7 stroke width, round caps and joins, generous negative space.
`test_ui.py` renders every icon, so a malformed path fails the suite.

### A new screen

1. Build it in `ui/views/`, assembled from `ui/widgets/common.py`.
2. Register it in `NAV_ITEMS` (`ui/sidebar.py`) and in `MainWindow.navigate`.
3. Give it a real empty state — not a blank panel.
4. Add it to the nav parametrisation in `test_ui.py`.

---

## Design conventions

The UI aims at the density and restraint of a professional creative tool.

- **Grouped small-caps sidebar sections**, one active item.
- **Filter chips over the content**, not a heavy filter sidebar.
- **A count/sort strip** between the filters and the results.
- **Contextual actions**: hover overlays and context menus, not fifteen buttons per card.
- **Fixed columns** in dense lists so values line up while scrolling.
- **Thin progress underlines** in the queue rather than chunky bars.
- **A 4px spacing rhythm** — nothing off-scale.
- Both themes are first-class. Light mode is not an inverted afterthought, and a
  colour that only works in one of them is a bug (the favourite star over
  artwork uses fixed colours for exactly this reason).

Empty states get real copy that tells the user what the screen is *for*, and an
action where one makes sense.

---

## Pull requests

**Before opening one**

```bash
ruff check app tests
pytest
python -m app.main        # it should actually launch
```

**In the description**

- What changed and why.
- Screenshots for any UI change — **both themes**.
- The manual verification you did, if it is not covered by a test.

**Keep PRs focused.** A bug fix and a refactor in one diff is two PRs.

**Commit messages**: imperative subject under ~72 characters, with a body
explaining the reasoning when it is not obvious.

```
Infer codec presence when the extractor omits it

archive.org and several other extractors return vcodec/acodec as null
rather than "none". Treating null as absent made every archive.org video
appear audio-only, and locked the format picker to audio.
```

---

## Reporting bugs

Include:

- Mediary version, OS and Python version
- yt-dlp version (Settings → Tools) and whether updating fixed it
- Whether FFmpeg is detected
- Exact steps to reproduce
- The relevant log excerpt (Settings → Open logs folder — already
  credential-scrubbed, but do skim it)
- The URL, **only if it is publicly accessible**

Please do not file issues asking for help downloading private, paid or
DRM-protected content. Mediary will not do that, and the request will be closed.
