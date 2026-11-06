# Building and releasing Unsettled

Player instructions are in [DOWNLOAD_README.md](DOWNLOAD_README.md), which is
included as `README.md` in each downloadable ZIP. Public downloads live in
[GitHub Releases](https://github.com/hjlarrea/unsettled/releases), not GitHub Packages.

## Automatic builds

The [release workflow](../.github/workflows/release.yml) runs when a `v*` tag is
pushed. Git tags are not attached to branches, so the first job verifies that
the tagged commit is reachable from `origin/main`. It rejects tags on unmerged
branches. Ordinary pushes to `main` do not create a release.

The tag must be `vMAJOR.MINOR.PATCH`, matching `[project].version` in
`pyproject.toml`. For example, with version `0.1.0` committed on `main`:

```sh
git switch main
git pull --ff-only
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

Use a new version and tag for each release. Commit and push all intended changes
to `main` before tagging; the workflow packages the tagged commit exactly.

Each build installs Python 3.13 and the pinned dependencies, runs the tests,
builds the native desktop bundle, and ZIPs it with the license and download
instructions. It then extracts the ZIP outside the checkout and runs a bot
simulation and an offscreen screenshot through the bundled executable. It
also checks that terrain artwork exists in the download. macOS builds verify
the extracted bundle's ad hoc signature, preserving symlinks with `ditto`.

The matrix currently builds Windows x64 on `windows-2022` and macOS Apple Silicon
on `macos-15`. There are no Intel macOS or Linux downloads in the workflow.
The runner OS is the automated test baseline, not a guarantee that all older
desktop OS versions work. Real-window testing is still necessary.

Only after both builds pass does the workflow create a **draft** GitHub Release
with the ZIPs, generated release notes, an unsigned-build notice, and
`SHA256SUMS.txt`. Review the files and notes, then click **Publish release**.
Drafts are not public downloads. If no release has been published yet, players
must run from source. A failed build creates no release. If a draft was already
created, manage it in GitHub before attempting to recreate the same release;
the workflow does not overwrite an existing release.

GitHub Actions must be enabled. The publishing job uses `GITHUB_TOKEN` with
`contents: write`; no personal token or signing secrets are needed. Repository
or organization policies must permit that permission. Other jobs have read-only
repository access.

## Local builds

Build on the target operating system; PyInstaller does not cross-compile.
Inside an activated Python 3.13 virtual environment:

```sh
python -m pip install . -r requirements-dev.txt -r packaging/requirements.txt
python -m pytest -q
python packaging/build.py
```

Downloads appear in `release/`; intermediate files go in `build/` and `dist/`.
The spec derives the app version from `pyproject.toml` and includes package data.
The macOS bundle identifier is `io.github.hjlarrea.unsettled`. No custom icon is
configured yet; builds use PyInstaller's default icon.

## Signing status

There is **no verified publisher signing**. Windows executables are unsigned;
macOS uses PyInstaller's automatic ad hoc signature and is neither Developer ID
signed nor Apple-notarized. Windows SmartScreen and macOS Gatekeeper warnings
are expected. Checksums verify file integrity, not publisher identity. See
[the player instructions](DOWNLOAD_README.md#no-publisher-signing-yet).

References: [GitHub tag triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push),
[PyInstaller bundles](https://pyinstaller.org/en/stable/operating-mode.html),
[Apple's opening guidance](https://support.apple.com/en-gb/102445), and
[Microsoft SmartScreen](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation).
