"""Filesystem helpers — storage paths of the integration."""
from __future__ import annotations

from pathlib import Path


def get_storage_root(config_dir: str) -> Path:
    """Return the root storage path for RainRadarHub."""
    return Path(config_dir) / ".storage" / "rain_radar_hub"


def get_tile_cache_db(config_dir: str) -> Path:
    return get_storage_root(config_dir) / "tile_cache.db"


def get_frames_dir(config_dir: str, region_id: str) -> Path:
    return get_storage_root(config_dir) / "regions" / region_id / "frames"
