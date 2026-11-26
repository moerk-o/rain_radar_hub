"""FrameUpdateCoordinator — one instance per region."""
from __future__ import annotations

import logging
import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_PREFIX,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    DOMAIN,
    FRAME_MAX_AGE_HOURS,
    FRAME_UPDATE_INTERVAL_MINUTES,
)
from .frame_pipeline import cleanup_old_frames, fetch_rw_frames, generate_colorbar
from .storage import get_frames_dir

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_EARTH_RADIUS_KM = 6371.0


class FrameUpdateCoordinator(DataUpdateCoordinator):
    """Fetches, decodes and reprojects DWD radar frames for one region."""

    def __init__(
        self, hass: HomeAssistant, region_id: str, region_config: dict
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{region_id}",
            update_interval=timedelta(minutes=FRAME_UPDATE_INTERVAL_MINUTES),
        )
        self.region_id = region_id
        self.region_config = region_config
        self._colorbar_cache: bytes | None = None

        lat = region_config[CONF_LATITUDE]
        lon = region_config[CONF_LONGITUDE]
        radius_km = region_config[CONF_RADIUS_KM]
        self._bounds = _compute_bounds(lat, lon, radius_km)
        lon_min, lat_min, lon_max, lat_max = self._bounds
        # reproject_to_png expects ((lat_sw, lon_sw), (lat_ne, lon_ne))
        self._sw_ne_bounds = ((lat_min, lon_min), (lat_max, lon_max))
        self._frames_dir = Path(get_frames_dir(hass.config.config_dir, region_id))

    @property
    def region_bounds(self) -> tuple[float, float, float, float]:
        """Return (lon_min, lat_min, lon_max, lat_max) in WGS84."""
        return self._bounds

    @property
    def colorbar_png(self) -> bytes:
        """Return colorbar PNG bytes (generated once, cached in memory)."""
        if self._colorbar_cache is None:
            self._colorbar_cache = generate_colorbar()
        return self._colorbar_cache

    async def _async_update_data(self) -> dict:
        """Full update cycle: fetch DWD data, decode, reproject, clean up."""
        session = async_get_clientsession(self.hass)
        try:
            await fetch_rw_frames(
                session,
                self._frames_dir,
                self._sw_ne_bounds,
                lookback_minutes=FRAME_MAX_AGE_HOURS * 60,
            )
        except Exception as exc:
            raise UpdateFailed(f"DWD RW fetch failed: {exc}") from exc

        cleanup_old_frames(self._frames_dir, FRAME_MAX_AGE_HOURS)
        return _build_inventory(self._frames_dir, self.region_id)


def _compute_bounds(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Compute (lon_min, lat_min, lon_max, lat_max) in WGS84.

    Uses great-circle approximation — accurate enough for radii ≤ 500 km.
    """
    lat_deg = math.degrees(radius_km / _EARTH_RADIUS_KM)
    cos_lat = math.cos(math.radians(lat))
    lon_deg = (
        math.degrees(radius_km / (_EARTH_RADIUS_KM * cos_lat))
        if cos_lat > 0
        else 180.0
    )
    return (
        lon - lon_deg,
        lat - lat_deg,
        lon + lon_deg,
        lat + lat_deg,
    )


def _build_inventory(frames_dir: Path, region_id: str) -> dict:
    """Scan frames_dir and return a sorted list of frame metadata."""
    frames: list[dict] = []
    if frames_dir.exists():
        for png in sorted(frames_dir.glob("*.png")):
            ts = png.stem  # e.g. "2026-04-27T14:00:00Z"
            url = f"{API_PREFIX}/regions/{region_id}/frames/{png.name}"
            frames.append({"timestamp": ts, "url": url})
    _LOGGER.debug("Region %s: %d frames in inventory", region_id, len(frames))
    return {
        "frames": frames,
        "colorbar_url": f"{API_PREFIX}/regions/{region_id}/colorbar.png",
    }
