"""HomeAssistantView endpoints for the RainRadarHub REST API."""
from __future__ import annotations

from homeassistant.components.http import HomeAssistantView


class TileView(HomeAssistantView):
    """GET /api/rain_radar_hub/tiles/{z}/{x}/{y}.png"""

    url = "/api/rain_radar_hub/tiles/{z}/{x}/{y}.png"
    name = "api:rain_radar_hub:tile"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, z, x, y):
        # TODO: implement
        raise NotImplementedError


class ManifestView(HomeAssistantView):
    """GET /api/rain_radar_hub/regions/{region_id}/manifest.json"""

    url = "/api/rain_radar_hub/regions/{region_id}/manifest.json"
    name = "api:rain_radar_hub:manifest"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, region_id):
        # TODO: implement
        raise NotImplementedError


class FrameView(HomeAssistantView):
    """GET /api/rain_radar_hub/regions/{region_id}/frames/{ts}.png"""

    url = "/api/rain_radar_hub/regions/{region_id}/frames/{ts}.png"
    name = "api:rain_radar_hub:frame"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, region_id, ts):
        # TODO: implement
        raise NotImplementedError


class ColorbarView(HomeAssistantView):
    """GET /api/rain_radar_hub/regions/{region_id}/colorbar.png"""

    url = "/api/rain_radar_hub/regions/{region_id}/colorbar.png"
    name = "api:rain_radar_hub:colorbar"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, region_id):
        # TODO: implement
        raise NotImplementedError
