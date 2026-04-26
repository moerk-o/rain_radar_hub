"""Filesystem helpers — paths, directory setup, size measurement."""
from __future__ import annotations

from pathlib import Path


def get_storage_root(config_dir: str) -> Path:
    """Return the root storage path for RainRadarHub."""
    return Path(config_dir) / ".storage" / "rain_radar_hub"


def get_tile_cache_dir(config_dir: str, provider_key: str) -> Path:
    return get_storage_root(config_dir) / "tile_cache" / provider_key


def get_tile_cache_db(config_dir: str) -> Path:
    return get_storage_root(config_dir) / "tile_cache.db"


def get_frames_dir(config_dir: str, region_id: str) -> Path:
    return get_storage_root(config_dir) / "regions" / region_id / "frames"


def ensure_dirs(*paths: Path) -> None:
    """Create directories if they don't exist."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def dir_size_bytes(path: Path) -> int:
    """Return total size of all files in a directory tree."""
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
