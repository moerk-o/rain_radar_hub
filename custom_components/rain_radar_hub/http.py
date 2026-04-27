"""HomeAssistantView endpoints for the RainRadarHub REST API."""
from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DATA_COORDINATORS, DATA_TILE_PROXY, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_domain_data(hass) -> dict:
    return hass.data.get(DOMAIN, {})


class TileView(HomeAssistantView):
    """GET /api/rain_radar_hub/tiles/{z}/{x}/{y}.png"""

    url = "/api/rain_radar_hub/tiles/{z}/{x}/{y}.png"
    name = "api:rain_radar_hub:tile"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, z, x, y):
        try:
            zi, xi, yi = int(z), int(x), int(y)
        except (ValueError, TypeError):
            raise web.HTTPBadRequest()

        tile_proxy = _get_domain_data(self.hass).get(DATA_TILE_PROXY)
        if tile_proxy is None:
            raise web.HTTPServiceUnavailable()

        session = async_get_clientsession(self.hass)
        try:
            png = await tile_proxy.get_tile(session, zi, xi, yi)
        except Exception as exc:
            _LOGGER.error("Tile fetch failed z=%d x=%d y=%d: %s", zi, xi, yi, exc)
            raise web.HTTPBadGateway()

        return web.Response(body=png, content_type="image/png")


class ManifestView(HomeAssistantView):
    """GET /api/rain_radar_hub/regions/{region_id}/manifest.json"""

    url = "/api/rain_radar_hub/regions/{region_id}/manifest.json"
    name = "api:rain_radar_hub:manifest"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, region_id):
        coordinators = _get_domain_data(self.hass).get(DATA_COORDINATORS, {})
        coord = coordinators.get(region_id)
        if coord is None:
            raise web.HTTPNotFound()

        inventory = coord.data if coord.data is not None else {"frames": [], "colorbar_url": ""}
        return self.json(inventory)


class FrameView(HomeAssistantView):
    """GET /api/rain_radar_hub/regions/{region_id}/frames/{ts}.png"""

    url = "/api/rain_radar_hub/regions/{region_id}/frames/{ts}.png"
    name = "api:rain_radar_hub:frame"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, region_id, ts):
        coordinators = _get_domain_data(self.hass).get(DATA_COORDINATORS, {})
        coord = coordinators.get(region_id)
        if coord is None:
            raise web.HTTPNotFound()

        frame_path = coord._frames_dir / f"{ts}.png"
        if not frame_path.exists():
            raise web.HTTPNotFound()

        return web.Response(body=frame_path.read_bytes(), content_type="image/png")


class ColorbarView(HomeAssistantView):
    """GET /api/rain_radar_hub/regions/{region_id}/colorbar.png"""

    url = "/api/rain_radar_hub/regions/{region_id}/colorbar.png"
    name = "api:rain_radar_hub:colorbar"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, region_id):
        coordinators = _get_domain_data(self.hass).get(DATA_COORDINATORS, {})
        coord = coordinators.get(region_id)
        if coord is None:
            raise web.HTTPNotFound()

        return web.Response(body=coord.colorbar_png, content_type="image/png")
