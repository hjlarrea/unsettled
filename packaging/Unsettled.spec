"""Native windowed desktop builds; run through packaging/build.py."""
from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]

analysis = Analysis(
    [str(root / "packaging" / "launch.py")],
    pathex=[str(root)],
    datas=collect_data_files("unsettled") + collect_data_files("pygame")
    + copy_metadata("pygame") + [(str(root / "LICENSE"), ".")],
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Unsettled",
    console=False,
    upx=False,
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas, name="Unsettled", upx=False,
)
if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Unsettled.app",
        bundle_identifier="io.github.hjlarrea.unsettled",
        version=version,
        info_plist={"CFBundleVersion": version},
    )
