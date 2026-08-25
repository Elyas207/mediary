# Mediary

A desktop app for downloading media from the web and actually keeping it organised.

Most downloaders hand you a file called `videoplayback.mp4` and leave you to it. Mediary does the boring part after the download: puts the file in a sensible folder, gives it a clean name, reads its technical metadata, and indexes the whole lot so you can find it again six months later by typing "whoosh".

It's Python and PySide6, using yt-dlp to do the extraction and FFmpeg for anything that needs converting or merging. Everything is local. There's no account, no server, and nothing gets uploaded.

Runs on Windows, macOS and Linux.

## What it does

Paste one URL or twenty. Mediary reads what's there first and shows you the title, creator, length and every format the source actually offers, side by side: what it has as video, and what it can be turned into as audio. Every row carries its size, because 1080p and 720p aren't a real choice until you know one is 1.2 GB and the other is 240 MB. Sizes the source reported are shown plainly; sizes worked out for a conversion that hasn't happened yet get a `~`.

Picking a row in one list clears the other, and that's what decides whether you get a video or an audio file — there's no separate switch to contradict it. Tag it there and then if you want; tags applied at download time land with the file, which is the only moment you reliably remember why you wanted it.

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

After a while Mediary stops asking you where things go. It watches what you actually do — this creator always ends up in Foley, anything from Instagram ends up in Inspiration — and pre-selects the folder, with a line under the card saying why: "7 of 8 from Studio Kern went to Ambience". If it's wrong, change it. It offers to remember that as a rule, and rules beat everything else it thinks it knows. A fresh library has no history to go on, so it falls back to reading the title and the clip length: a four-second file called "metal whoosh 03" is a sound effect, a four-minute one probably isn't. When nothing in the item points anywhere, it says nothing and uses your default rather than inventing a reason.

It never counts its own guesses as evidence. An item you let through unchallenged carries less weight than one you deliberately filed, so it can't slowly talk itself into a bad habit. Settings → Organisation has the toggle and the full list of rules.

Everything that lands there gets indexed in SQLite with full-text search across title, filename, creator, tags, category, notes and licence notes. The library has grid and list views, filter chips and favourites, with a detail rail down the right-hand side showing everything known about whatever is selected — metadata, licensing, tags and notes, all editable in place. It's docked rather than modal because picking between near-identical sound effects means selecting the next one constantly, and a dialog per file would make that unbearable. On a narrow window it folds away on its own.

Audio auditions in place. Click a tile's artwork or hit space on a selected row and it plays in a dock at the bottom of the window, with a waveform you can scrub. Finding the right whoosh means listening to fifteen of them, and a modal per file would make that unbearable.

Items without cover art — which is most sound effects — get generated artwork instead of a grey rectangle. The colour comes from the category, so the hue tells you what something is before you read the label.

Video comes in MP4, MKV or WebM up to whatever the source has. Audio comes in MP3, M4A, WAV or FLAC, with bitrate options for the lossy ones. The bitrate picker greys out for WAV and FLAC, because a bitrate doesn't mean anything for a lossless container.

## A note on licensing

Mediary won't tell you whether you're allowed to use something. It doesn't guess, it doesn't detect, and it will never label a file "royalty free" just because it was publicly reachable.

Public accessibility and reuse rights are different things. What Mediary does instead is give you somewhere to record what you've worked out yourself — licence type, licence URL, whether attribution is required, and free-text notes. New items start as `Unknown` and stay that way until you change them.

It also doesn't try to get around access controls. No DRM circumvention, no paywall bypass, no reading your browser cookies, no private account scraping. If something is private, paid or region-locked, you get told that and it stops there.

## Running in the background

There's a setting to launch Mediary when you sign in, and another to start it hidden — no window, no taskbar entry, just a tray icon. There's also an option to keep it running when you close the window so downloads finish.

The tray icon is the only way back to a hidden window, so if your desktop doesn't have a system tray those options are disabled rather than leaving you with an unreachable process. On Windows it registers under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; macOS gets a LaunchAgent in `~/Library/LaunchAgents`; Linux gets an XDG autostart entry in `~/.config/autostart`. All per-user, so it never needs admin rights.

Launching Mediary a second time while it's already running won't start a duplicate — it just brings the existing window forward.

## Appearance

Dark and light themes, or follow your desktop. "Follow system" tracks changes live rather than only at startup.

Mediary also picks up your system accent colour by default — the highlight colour from Windows personalisation, macOS appearance settings, or the XDG portal on Linux. Only the accent moves; surfaces and text stay Mediary's, because a system accent says nothing about those and letting it drive them wrecks contrast. If your accent is near-black or near-white the hue is kept and the lightness corrected, so you never end up with invisible buttons. Turn it off in Settings for Mediary's own blue.

There's a **Reduce motion** switch if animations bother you. It's a real off switch, not a shorter duration.

## Uninstalling

Settings › Library data › Remove Mediary's data lists everything the app has put on your machine — settings, the library index, caches, logs — with real sizes and paths, and lets you pick what goes.

Your downloaded media is a separate, unticked entry that needs a typed confirmation. Deleting settings shouldn't quietly take your files with it.

## Installing

### Prebuilt

Builds for all three platforms are on the [Releases](https://github.com/Elyas207/mediary/releases) page. You'll still want FFmpeg either way — see below.

**Windows** — download the zip, extract it anywhere, run `Mediary.exe`. It's portable, so there's no installer. The exe isn't signed, so SmartScreen will warn the first time: More info, then Run anyway.

**macOS** — open the `.dmg` and drag Mediary to Applications. Pick the `arm64` build for Apple Silicon or `x64` for Intel. It isn't notarised, so macOS will refuse to open it on the first try. Either right-click the app and choose Open, or clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine /Applications/Mediary.app
```

**Linux** — download the AppImage, make it executable, run it:

```bash
chmod +x Mediary-*.AppImage
./Mediary-*.AppImage
```

Built on Ubuntu 22.04, so it needs glibc 2.35 or newer. On older distributions, build from source.

**Alpine and other musl systems** — the AppImage won't run there, so there's a separate tarball:

```bash
tar xzf Mediary-*-linux-x86_64-musl.tar.gz
./Mediary/Mediary
```

PySide6 publishes no musl wheels, so this build uses Alpine's own Qt and PySide6 packages. That means `pip install PySide6` won't work on Alpine either — if you're running from source there, install `py3-pyside6` from apk instead.

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
| Audition selected audio | `Space` | `Space` |
| Close the preview | `Esc` | `Esc` |

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

621 tests, all offline. yt-dlp and FFmpeg are mocked or driven from JSON fixtures in `tests/fixtures/`, so the suite passes on a machine with no network and no FFmpeg installed.

They cover URL parsing, filename sanitisation on all three platforms, path generation, duplicate detection, SQLite CRUD and migrations, search, tagging, favourites, settings persistence and corruption recovery, queue state, format selection, metadata normalisation, FFmpeg detection, log redaction, rescan, autostart registration, the tray, the single-instance handoff, the full download pipeline, and a headless pass over every screen in both themes.

```bash
pytest tests/test_pipeline.py -v     # the end-to-end scenarios
pytest -k "duplicate"                # a subset
ruff check app tests                 # lint
```

## Building

Release builds happen in CI, because PyInstaller can't cross-compile — each platform has to be built on itself. `.github/workflows/build.yml` runs the test suite on Linux, macOS and Windows, then builds and attaches a zip, two DMGs and an AppImage to the release. It fires on any `v*` tag, and can be dispatched manually against an existing one.

Locally:

```bash
pip install -e ".[build]"
python build.py --clean
```

That wraps PyInstaller and writes to `dist/`. Icons get generated from the app's own artwork on first build, so there's no binary art in the repo.

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
