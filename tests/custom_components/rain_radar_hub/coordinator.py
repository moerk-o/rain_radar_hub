"""FrameUpdateCoordinator — one instance per region."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, FRAME_UPDATE_INTERVAL_MINUTES


class FrameUpdateCoordinator(DataUpdateCoordinator):
    """Fetches, decodes and reprojects DWD radar frames for one region."""

    def __init__(self, hass, region_id: str, region_config: dict) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=f"{DOMAIN}_{region_id}",
            update_interval=timedelta(minutes=FRAME_UPDATE_INTERVAL_MINUTES),
        )
        self.region_id = region_id
        self.region_config = region_config

    async def _async_update_data(self) -> dict:
        """Full update cycle: fetch DWD data, decode, reproject, clean up."""
        # TODO: implement
        # 1. Fetch RW (past frames)
        # 2. Fetch RV (nowcast frames)
        # 3. Decode + reproject each new frame
        # 4. Clean up frames older than FRAME_MAX_AGE_HOURS
        # 5. Build and return frame inventory
        raise NotImplementedError
