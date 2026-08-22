# Packaging

Build the application first:

```bash
pip install -e ".[build]"
python build.py --clean
```

## Windows

`build.py` produces `dist/Mediary/Mediary.exe`.

For an installer, install [Inno Setup](https://jrsoftware.org/isinfo.php) and run:

```
iscc packaging\mediary.iss
```

The result is `dist/Mediary-1.0.0-Setup.exe`. The uninstaller deliberately
leaves the user's media library and database in place and only clears the cache.

## macOS

`build.py` produces `dist/Mediary.app`.

Disk image:

```bash
hdiutil create -volname Mediary -srcfolder dist/Mediary.app \
    -ov -format UDZO dist/Mediary.dmg
```

Distributing outside the App Store requires signing and notarisation:

```bash
codesign --deep --force --options runtime \
    --sign "Developer ID Application: YOUR NAME (TEAMID)" dist/Mediary.app
xcrun notarytool submit dist/Mediary.dmg \
    --keychain-profile "AC_PASSWORD" --wait
xcrun stapler staple dist/Mediary.dmg
```

Build on Apple Silicon for arm64 and on (or under Rosetta for) Intel for x86_64;
`lipo` can merge the two if you want a universal binary.

## Linux

`build.py` produces `dist/Mediary/`.

AppImage:

```bash
mkdir -p build/AppDir/usr/bin
cp packaging/AppDir/AppRun packaging/AppDir/mediary.desktop build/AppDir/
cp packaging/icons/mediary.png build/AppDir/mediary.png
cp -r dist/Mediary/. build/AppDir/usr/bin/
appimagetool build/AppDir dist/Mediary-1.0.0-x86_64.AppImage
```

Get `appimagetool` from https://github.com/AppImage/AppImageKit. CI does this
automatically — see below.

## Icons

Place these in `packaging/icons/` before building:

| File | Platform | Size |
| --- | --- | --- |
| `mediary.ico` | Windows | multi-resolution, 16-256 px |
| `mediary.icns` | macOS | multi-resolution, 16-1024 px |
| `mediary.png` | Linux | 512x512 |

If they are absent the build still succeeds; Mediary draws its own window icon
at runtime, so only the installer and file-manager icons are affected.

## Bundling FFmpeg

Drop the binary into `bin/` before running `build.py` and it will be included,
with Mediary finding it automatically.

**Read the licence of the specific build first.** FFmpeg is LGPLv2.1+ or GPLv2+
depending on how it was configured, and some builds contain patent-encumbered
encoders. Shipping a GPL-configured build imposes GPL obligations on your
distribution. Mediary itself does not bundle FFmpeg for exactly this reason.

## CI builds

`.github/workflows/build.yml` is what produces the release artefacts. PyInstaller
cannot cross-compile, so each platform builds on its own runner:

| Runner | Produces |
| --- | --- |
| `windows-latest` | `Mediary-<version>-windows-x64.zip` |
| `macos-14` | `Mediary-<version>-macos-arm64.dmg` |
| `macos-13` | `Mediary-<version>-macos-x64.dmg` |
| `ubuntu-22.04` | `Mediary-<version>-x86_64.AppImage` |

The test suite and the linter run on Linux, macOS and Windows first; the builds
only start if all three are green.

Triggered by pushing a `v*` tag, or manually from the Actions tab with the tag
to build against. Assets are uploaded with `--clobber`, so re-running replaces
them rather than failing.

Ubuntu 22.04 is deliberate: building against an older glibc keeps the AppImage
working on more distributions. AppImages are not backwards compatible with
glibc, so building on a newer runner would narrow who can run it.

Nothing is signed or notarised. Doing that needs an Apple Developer ID and a
Windows code-signing certificate, plus secrets in the repo.
