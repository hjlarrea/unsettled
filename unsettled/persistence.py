"""Versioned, atomic local saves, including mid-decision state."""
from pathlib import Path
import json
import os
import sys
import tempfile
from .engine import Game, RuleError


def save_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Unsettled"
    return Path.home() / ".local" / "share" / "unsettled"


def save(game: Game, path: Path | None = None):
    path = path or save_dir() / "autosave.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".unsettled-", suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            json.dump(game.to_dict(), f, separators=(",", ":"), allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load(path: Path | None = None) -> Game:
    path = path or save_dir() / "autosave.json"
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("File is too large.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected a save object.")
        return Game.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, StopIteration, OverflowError) as exc:
        raise RuleError(f"Cannot load save: {exc}") from exc
