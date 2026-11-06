"""Build a native ZIP and verify it outside the source checkout."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent


def run(*command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def main():
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in ("arm64", "x86_64"):
        target = "macos-arm64" if machine == "arm64" else "macos-x64"
        bundle_name = "Unsettled.app"
        executable = Path(bundle_name) / "Contents" / "MacOS" / "Unsettled"
    elif sys.platform == "win32" and machine in ("amd64", "x86_64"):
        target = "windows-x64"
        bundle_name = "Unsettled"
        executable = Path(bundle_name) / "Unsettled.exe"
    else:
        raise SystemExit("Build on Windows x64 or macOS arm64/x64; Linux downloads are not built.")

    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    build_environment = os.environ.copy()
    build_environment.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build" / "pyinstaller-cache"))
    run(sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "packaging/Unsettled.spec", cwd=ROOT, env=build_environment)

    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    download = output / f"Unsettled-{version}-{target}.zip"
    # Keep generated staging files under the already-ignored build directory.
    stage = Path(tempfile.mkdtemp(prefix="release-", dir=ROOT / "build"))
    try:
        bundle = stage / bundle_name
        shutil.copytree(ROOT / "dist" / bundle_name, bundle, symlinks=True)
        for source, name in ((ROOT / "packaging" / "DOWNLOAD_README.md", "README.md"),
                             (ROOT / "LICENSE", "LICENSE")):
            shutil.copy2(source, stage / name)
        if sys.platform == "darwin":
            # ditto retains the app's symlinks, permissions, and ad hoc signature.
            run("ditto", "-c", "-k", "--sequesterRsrc", str(stage), str(download))
        else:
            shutil.make_archive(str(download.with_suffix("")), "zip", stage)
    finally:
        shutil.rmtree(stage)

    with tempfile.TemporaryDirectory(prefix="unsettled-smoke-") as temporary:
        extracted = Path(temporary)
        if sys.platform == "darwin":
            run("ditto", "-x", "-k", str(download), str(extracted))
        else:
            shutil.unpack_archive(download, extracted)
        if not list((extracted / bundle_name).rglob("terrain-classic.png")):
            raise RuntimeError("Terrain artwork is missing from the download.")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        program = str(extracted / executable)
        run(program, "--simulate", "1", "--bots", "2", "--seed", "1",
            cwd=extracted, env=environment, timeout=180)
        screenshot = extracted / "smoke.png"
        run(program, "--screenshot", str(screenshot),
            cwd=extracted, env=environment, timeout=180)
        if not screenshot.exists() or screenshot.stat().st_size < 1000:
            raise RuntimeError("The packaged app did not render its smoke-test screenshot.")
        if sys.platform == "darwin":
            run("codesign", "--verify", "--deep", "--strict", str(extracted / bundle_name))

    print(f"Built and verified {download.name}")
    with download.open("rb") as archive:
        print(f"SHA256: {hashlib.file_digest(archive, 'sha256').hexdigest()}")


if __name__ == "__main__":
    main()
