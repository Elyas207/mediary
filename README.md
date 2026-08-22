# Mediary

A desktop app for downloading media from the web and actually keeping it organised.

Most downloaders hand you a file called `videoplayback.mp4` and leave you to it. Mediary does the boring part after the download: puts the file in a sensible folder, gives it a clean name, reads its technical metadata, and indexes the whole lot so you can find it again six months later by typing "whoosh".

It's Python and PySide6, using yt-dlp to do the extraction and FFmpeg for anything that needs converting or merging. Everything is local. There's no account, no server, and nothing gets uploaded.

Runs on Windows, macOS and Linux.

## What it does

Paste one URL or twenty. Mediary reads what's there first and shows you the title, creator, length and every format the source actually offers, so you're picking from real options rather than guessing. Choose a format and a category, hit download, and it handles the rest in the background.

Downloads go into a folder structure by category:

```
Mediary/
├── Video/
├── Inspiration/
├── Audio/
│   ├── Music/
│   ├── Sound Effects/
│   ├── Voice/
│   ├── Ambience/
│   └── Foley/
└── Other/
```

Everything that lands there gets indexed in SQLite with full-text search across title, filename, creator, tags, category, notes and licence notes. The library has grid and list views, filter chips, favourites, and a detail panel where you can edit metadata and add tags.

Video comes in MP4, MKV or WebM up to whatever the source has. Audio comes in MP3, M4A, WAV or FLAC, with bitrate options for the lossy ones. The bitrate picker greys out for WAV and FLAC, because a bitrate doesn't mean anything for a lossless container.

## A note on licensing

Mediary won't tell you whether you're allowed to use something. It doesn't guess, it doesn't detect, and it will never label a file "royalty free" just because it was publicly reachable.

Public accessibility and reuse rights are different things. What Mediary does instead is give you somewhere to record what you've worked out yourself — licence type, licence URL, whether attribution is required, and free-text notes. New items start as `Unknown` and stay that way until you change them.

It also doesn't try to get around access controls. No DRM circumvention, no paywall bypass, no reading your browser cookies, no private account scraping. If something is private, paid or region-locked, you get told that and it stops there.

## Running in the background

There's a setting to launch Mediary when you sign in, and another to start it hidden — no window, no taskbar entry, just a tray icon. There's also an option to keep it running when you close the window so downloads finish.

The tray icon is the only way back to a hidden window, so if your desktop doesn't have a system tray those options are disabled rather than leaving you with an unreachable process. On Windows it registers under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; macOS gets a LaunchAgent in `~/Library/LaunchAgents`; Linux gets an XDG autostart entry in `~/.config/autostart`. All per-user, so it never needs admin rights.

Launching Mediary a second time while it's already running won't start a duplicate — it just brings the existing window forward.

## Installing

### Prebuilt

Grab the latest build from [Releases](https://github.com/Elyas207/mediary/releases). You'll still need FFmpeg (see below).

### From source

```bash
git clone https://github.com/Elyas207/mediary.git
cd mediary

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -e .
mediary
```

Needs Python 3.10 or newer. 3.12+ is a bit happier.

## FFmpeg

Mediary will start without it, but you won't get audio extraction, format conversion, embedded artwork, or merged high-resolution video — the things most people want. It's worth installing.

```bash
brew install ffmpeg              # macOS
sudo apt install ffmpeg          # Debian / Ubuntu
sudo dnf install ffmpeg          # Fedora
sudo pacman -S ffmpeg            # Arch
winget install Gyan.FFmpeg       # Windows
```

Mediary looks for it in the path you set in Settings, then a binary bundled next to the app, then `PATH`, then the usual install locations. If it can't find one, Settings shows "Not found" and the Download screen puts up a notice with a button to point at it manually.

Without FFmpeg, Mediary asks yt-dlp for already-muxed streams rather than separate video and audio, so you don't end up with a silent video file.

**FFmpeg isn't bundled here on purpose.** It's LGPL or GPL depending on how the binary was built, and some builds include patent-encumbered encoders. If you make a build that ships one, the licence obligations of that specific binary are yours. Dropping `ffmpeg` (or `ffmpeg.exe`) into a `bin/` folder next to the executable is enough for Mediary to pick it up.

## yt-dlp

Sites change and extractors break. Updating yt-dlp fixes most downloads that suddenly stop working:

```bash
pip install --upgrade yt-dlp
```

Mediary won't update it behind your back. Settings shows the installed version and gives you the command.

## Keyboard shortcuts

| | Windows / Linux | macOS |
| --- | --- | --- |
| Search | `Ctrl+F` | `Cmd+F` |
| Download screen | `Ctrl+N` | `Cmd+N` |
| Analyse pasted URLs | `Ctrl+Enter` | `Cmd+Enter` |
| Library | `Ctrl+L` | `Cmd+L` |
| Queue | `Ctrl+J` | `Cmd+J` |
| Settings | `Ctrl+,` | `Cmd+,` |
| Rescan library | `Ctrl+R` | `Cmd+R` |
| Refresh view | `F5` | `F5` |
| Remove selected | `Delete` | `Delete` |

## Where things live

Mediary uses each platform's normal directories. Nothing is hardcoded, and Settings has buttons to open all of them.

| | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Config | `%APPDATA%\Mediary` | `~/Library/Application Support/Mediary` | `$XDG_CONFIG_HOME/mediary` |
| Database | `%LOCALAPPDATA%\Mediary` | `~/Library/Application Support/Mediary` | `$XDG_DATA_HOME/mediary` |
| Cache | `%LOCALAPPDATA%\Mediary\Cache` | `~/Library/Caches/Mediary` | `$XDG_CACHE_HOME/mediary` |
| Logs | `%LOCALAPPDATA%\Mediary\logs` | `~/Library/Logs/Mediary` | `$XDG_DATA_HOME/mediary/logs` |
| Default library | `~/Videos/Mediary` | `~/Movies/Mediary` | `~/Videos/Mediary` |

Set `MEDIARY_HOME` to move all of it somewhere else, which is handy for testing:

```bash
MEDIARY_HOME=/tmp/mediary-sandbox python -m app.main
```

## Filenames

The default template is `{title}`, and you can also use `{creator}`, `{platform}`, `{category}`, `{quality}`, `{ext}`, `{date}` and `{id}`. Empty values collapse properly, so `{creator} - {title} [{quality}]` with no creator and no quality gives you just the title, not `- Title []`. Settings shows a live preview.

Names get sanitised for all three platforms at once, not just the one you're on. That covers illegal characters, control characters, Windows reserved names like `CON` and `NUL`, trailing dots and spaces, Unicode normalisation and titles that are too long. The point is that a library built on Windows still works when you plug the drive into a Mac.

Nothing ever gets silently overwritten. Collisions become `name (1).ext`.

## Duplicates, removing, deleting

Mediary spots likely duplicates by source URL, platform media ID, file path and filename, then asks whether you want to skip, download anyway or replace. It won't stop you downloading a second copy on purpose.

There are two different destructive actions and they're kept distinct:

- **Remove from Library** drops the database entry and leaves the file exactly where it is.
- **Delete File** removes both, and asks first.

If you move or delete files outside the app, **Rescan Library** reconciles things — it relocates same-named files under the library root, flags what's genuinely missing, and picks up anything new you dropped in.

## Architecture

```
UI (PySide6)
  │  signals only
  ▼
Services ── Download ── Organisation ── Library ── Rescan
  │              │            │            │
  ▼              ▼            ▼            ▼
DownloadManager  FFmpeg    filesystem   SQLite + FTS5
  │ (QThreadPool)
  ▼
yt-dlp adapter
```

A few rules the code sticks to, because breaking them causes real bugs:

- Nothing blocks the UI thread. Every network call, subprocess and probe runs on a worker.
- Workers don't own widgets or database handles. They emit signals; services on the GUI side do the persisting.
- `library_service.py` is the only place that writes SQL against `media`, `tags` and `media_tags`.
- `ytdlp_adapter.py` is the only module that knows yt-dlp exists. Everything else deals in `MediaInfo` and `DownloadOptions`.
- All paths go through `utils/paths.py`.
- All colours, sizes and fonts come from `ui/theme/tokens.py`. No hex codes scattered through widgets.

```
app/
├── main.py                  entry point, CLI flags, single-instance guard
├── config/settings.py       typed settings, atomic JSON writes
├── database/                connections, versioned migrations
├── models/                  media, download, category (no Qt, no SQL)
├── downloader/              yt-dlp adapter, queue, worker pool
├── media/ffmpeg.py          detection and ffprobe
├── services/                download, library, organisation, rescan, autostart
├── ui/
│   ├── theme/               tokens, stylesheet, generated icons
│   ├── widgets/             the shared component library
│   ├── views/               download, queue, library, tags, settings, onboarding
│   ├── dialogs/             detail, duplicate, error
│   └── tray.py
└── utils/                   paths, filenames, formatting, logging
```

## Privacy

Local-first, and that's not marketing. There is no backend to talk to.

Cookie files, browser cookie extraction and `netrc` are explicitly disabled in every yt-dlp call, so Mediary never touches your credentials. Logs are scrubbed at the handler level — cookies, `Authorization` headers, bearer tokens, passwords, API keys and signed-URL parameters get redacted before anything is written, so a careless debug log can't leak a secret.

No analytics, no telemetry, no crash reporting.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

553 tests, all offline. yt-dlp and FFmpeg are mocked or driven from JSON fixtures in `tests/fixtures/`, so the suite passes on a machine with no network and no FFmpeg installed.

They cover URL parsing, filename sanitisation on all three platforms, path generation, duplicate detection, SQLite CRUD and migrations, search, tagging, favourites, settings persistence and corruption recovery, queue state, format selection, metadata normalisation, FFmpeg detection, log redaction, rescan, autostart registration, the tray, the single-instance handoff, the full download pipeline, and a headless pass over every screen in both themes.

```bash
pytest tests/test_pipeline.py -v     # the end-to-end scenarios
pytest -k "duplicate"                # a subset
ruff check app tests                 # lint
```

## Building

```bash
pip install -e ".[build]"
python build.py --clean
```

That wraps PyInstaller and writes to `dist/`.

**Windows** gives you `dist/Mediary/Mediary.exe`. For an installer, run `iscc packaging\mediary.iss` with [Inno Setup](https://jrsoftware.org/isinfo.php).

**macOS** gives you `dist/Mediary.app`. Turn it into a disk image with:

```bash
hdiutil create -volname Mediary -srcfolder dist/Mediary.app -ov -format UDZO dist/Mediary.dmg
```

Distributing outside the App Store means signing and notarising it as well.

**Linux** gives you `dist/Mediary/`, which [appimagetool](https://github.com/AppImage/AppImageKit) can turn into an AppImage using `packaging/AppDir/`.

More detail in [packaging/README.md](packaging/README.md).

## Troubleshooting

**A download fails saying the content is private or unavailable.** It isn't publicly reachable. Mediary doesn't work around access controls.

**Downloads that used to work suddenly don't.** Update yt-dlp and restart. This is nearly always it.

**Audio downloads come out as video files, or video has no sound.** FFmpeg isn't set up. Check Settings → Tools.

**An item says "File unavailable".** It moved or got deleted outside the app. Run Rescan Library.

**Search isn't finding something it should.** Settings → Library data → Rebuild search index.

**Something crashed.** Settings → Local files → Open logs folder. Logs are plain text and already credential-scrubbed.

**Downloads are slow or you're getting rate-limited.** Turn the concurrency down in Settings → Performance. The default of 2 is deliberately conservative.

## Licences

Mediary's own code is MIT — see [LICENSE](LICENSE). That covers this code only, not the dependencies:

- **PySide6 / Qt** — LGPLv3, dynamically linked
- **yt-dlp** — Unlicense (public domain)
- **FFmpeg** — LGPLv2.1+ or GPLv2+ depending on the build, not bundled here
- **SQLite** — public domain, comes with Python

If you redistribute a build, you take on the obligations of whatever you ship with it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
