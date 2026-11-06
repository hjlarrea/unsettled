# Unsettled download

This download includes Python, Pygame, and the game's assets. You do not need to
install Python, Homebrew, or any other dependencies.

## Windows x64

Extract the entire ZIP, open the `Unsettled` folder, and double-click
`Unsettled.exe`. Keep the `_internal` folder beside the executable. Do not run
the game from inside the ZIP or move only the executable.

## macOS

Extract the ZIP using Finder and drag `Unsettled.app` into Applications.
The `macos-arm64` download is for Apple Silicon Macs (M1 and later);
`macos-x64`, if provided, is for Intel Macs. Open the app from Applications.

## No publisher signing yet

These are early builds without verified publisher signing. Windows executables
are unsigned. macOS apps have only an ad hoc signature required for execution;
they are not Developer ID signed or notarized by Apple.

Windows may show a Microsoft Defender SmartScreen warning such as "Windows
protected your PC" or "unrecognized app". If you trust the source, the dialog
may offer **More info → Run anyway**. Antivirus software or managed-device
policies may block the app even if SmartScreen permits it.

macOS may block the first launch because the developer cannot be verified or
Apple cannot check the app for malicious software. After trying to open it,
**System Settings → Privacy & Security → Open Anyway** may allow a per-app
exception. Managed-device policies may prohibit this. Do not disable system-wide
security protections. If no exception is available, run from source instead.

Download only from this project's
[GitHub Releases](https://github.com/hjlarrea/unsettled/releases).
The release's `SHA256SUMS.txt` lets you check download integrity; checksums do
not establish publisher identity or replace signing and notarization.

## Updates and saves

To update, quit the game, download the new release, and replace the entire app
or extracted Windows folder. Saves are stored separately and are not removed
when replacing the application.

- macOS: `~/Library/Application Support/Unsettled/`
- Windows: `%USERPROFILE%\.local\share\unsettled\`

Linux users can run the Python source; no Linux binary is provided.
Source setup instructions and the full game guide are in the
[project README](https://github.com/hjlarrea/unsettled#readme).

The project's license is included in `LICENSE`. Third-party dependencies retain
their own licenses, with bundled dependency notices included where supplied.
