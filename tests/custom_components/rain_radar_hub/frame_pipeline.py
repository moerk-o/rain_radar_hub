"""Frame pipeline — download, decode, reproject, save DWD radar PNGs."""
from __future__ import annotations

from pathlib import Path


async def fetch_rw_frames(hass, frames_dir: Path) -> list[Path]:
    """Download and process RW (past) RADOLAN frames."""
    # TODO: implement
    raise NotImplementedError


async def fetch_rv_frames(hass, frames_dir: Path) -> list[Path]:
    """Download and process RV (nowcast) frames."""
    # TODO: implement
    raise NotImplementedError


def cleanup_old_frames(frames_dir: Path, max_age_hours: int) -> int:
    """Delete PNGs older than max_age_hours. Returns count of deleted files."""
    # TODO: implement
    raise NotImplementedError
