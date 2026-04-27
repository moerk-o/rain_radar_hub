"""Tests for http.py views."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from custom_components.rain_radar_hub.const import (
    DATA_COORDINATORS,
    DATA_TILE_PROXY,
    DOMAIN,
)
from custom_components.rain_radar_hub.http import (
    ColorbarView,
    FrameView,
    ManifestView,
    TileView,
)

# ────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ────────────────────────────────────────────────────────────────────────────

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
FAKE_JSON = {"frames": [{"timestamp": "2026-04-27T14:00:00Z", "url": "/api/..."}]}
REGION_ID = "hamburg"


def _make_hass(domain_data: dict) -> MagicMock:
    hass = MagicMock()
    hass.data = {DOMAIN: domain_data}
    return hass


def _make_coord(tmp_path, data=None, colorbar=FAKE_PNG) -> MagicMock:
    coord = MagicMock()
    coord.data = data
    coord.colorbar_png = colorbar
    coord._frames_dir = tmp_path / "frames"
    coord._frames_dir.mkdir(parents=True, exist_ok=True)
    return coord


def _make_request() -> MagicMock:
    return MagicMock()


# ────────────────────────────────────────────────────────────────────────────
# TileView
# ────────────────────────────────────────────────────────────────────────────

class TestTileView:

    def _make_tile_proxy(self, png=FAKE_PNG) -> MagicMock:
        proxy = MagicMock()
        proxy.get_tile = AsyncMock(return_value=png)
        return proxy

    async def test_returns_png_bytes(self, tmp_path):
        proxy = self._make_tile_proxy()
        hass = _make_hass({DATA_TILE_PROXY: proxy})
        view = TileView(hass)
        with patch(
            "custom_components.rain_radar_hub.http.async_get_clientsession",
            return_value=MagicMock(),
        ):
            response = await view.get(_make_request(), "10", "1", "2")
        assert isinstance(response, web.Response)
        assert response.body == FAKE_PNG

    async def test_content_type_image_png(self, tmp_path):
        proxy = self._make_tile_proxy()
        hass = _make_hass({DATA_TILE_PROXY: proxy})
        view = TileView(hass)
        with patch(
            "custom_components.rain_radar_hub.http.async_get_clientsession",
            return_value=MagicMock(),
        ):
            response = await view.get(_make_request(), "10", "1", "2")
        assert response.content_type == "image/png"

    async def test_calls_get_tile_with_int_args(self, tmp_path):
        proxy = self._make_tile_proxy()
        hass = _make_hass({DATA_TILE_PROXY: proxy})
        view = TileView(hass)
        with patch(
            "custom_components.rain_radar_hub.http.async_get_clientsession",
        ) as mock_session:
            await view.get(_make_request(), "10", "544", "340")
        proxy.get_tile.assert_called_once_with(mock_session.return_value, 10, 544, 340)

    async def test_no_tile_proxy_raises_503(self):
        hass = _make_hass({})
        view = TileView(hass)
        with pytest.raises(web.HTTPServiceUnavailable):
            await view.get(_make_request(), "10", "1", "2")

    async def test_invalid_z_raises_400(self):
        hass = _make_hass({DATA_TILE_PROXY: MagicMock()})
        view = TileView(hass)
        with pytest.raises(web.HTTPBadRequest):
            await view.get(_make_request(), "abc", "1", "2")

    async def test_upstream_error_raises_502(self):
        proxy = MagicMock()
        proxy.get_tile = AsyncMock(side_effect=RuntimeError("upstream down"))
        hass = _make_hass({DATA_TILE_PROXY: proxy})
        view = TileView(hass)
        with patch(
            "custom_components.rain_radar_hub.http.async_get_clientsession",
            return_value=MagicMock(),
        ):
            with pytest.raises(web.HTTPBadGateway):
                await view.get(_make_request(), "10", "1", "2")

    async def test_domain_data_missing_raises_503(self):
        hass = MagicMock()
        hass.data = {}
        view = TileView(hass)
        with pytest.raises(web.HTTPServiceUnavailable):
            await view.get(_make_request(), "10", "1", "2")


# ────────────────────────────────────────────────────────────────────────────
# ManifestView
# ────────────────────────────────────────────────────────────────────────────

class TestManifestView:

    async def test_returns_json_response(self, tmp_path):
        coord = _make_coord(tmp_path, data=FAKE_JSON)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = ManifestView(hass)
        response = await view.get(_make_request(), REGION_ID)
        assert response is not None

    async def test_unknown_region_raises_404(self):
        hass = _make_hass({DATA_COORDINATORS: {}})
        view = ManifestView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), "unknown")

    async def test_no_coordinators_raises_404(self):
        hass = _make_hass({})
        view = ManifestView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), REGION_ID)

    async def test_empty_data_returns_fallback(self, tmp_path):
        coord = _make_coord(tmp_path, data=None)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = ManifestView(hass)
        # Should not raise — returns an empty inventory
        response = await view.get(_make_request(), REGION_ID)
        assert response is not None

    async def test_domain_data_missing_raises_404(self):
        hass = MagicMock()
        hass.data = {}
        view = ManifestView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), REGION_ID)


# ────────────────────────────────────────────────────────────────────────────
# FrameView
# ────────────────────────────────────────────────────────────────────────────

class TestFrameView:

    async def test_returns_png_bytes(self, tmp_path):
        coord = _make_coord(tmp_path)
        ts = "2026-04-27T14:00:00Z"
        (coord._frames_dir / f"{ts}.png").write_bytes(FAKE_PNG)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = FrameView(hass)
        response = await view.get(_make_request(), REGION_ID, ts)
        assert response.body == FAKE_PNG

    async def test_content_type_image_png(self, tmp_path):
        coord = _make_coord(tmp_path)
        ts = "2026-04-27T14:00:00Z"
        (coord._frames_dir / f"{ts}.png").write_bytes(FAKE_PNG)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = FrameView(hass)
        response = await view.get(_make_request(), REGION_ID, ts)
        assert response.content_type == "image/png"

    async def test_unknown_region_raises_404(self):
        hass = _make_hass({DATA_COORDINATORS: {}})
        view = FrameView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), "unknown", "2026-04-27T14:00:00Z")

    async def test_missing_frame_file_raises_404(self, tmp_path):
        coord = _make_coord(tmp_path)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = FrameView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), REGION_ID, "2099-01-01T00:00:00Z")

    async def test_no_coordinators_raises_404(self):
        hass = _make_hass({})
        view = FrameView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), REGION_ID, "2026-04-27T14:00:00Z")


# ────────────────────────────────────────────────────────────────────────────
# ColorbarView
# ────────────────────────────────────────────────────────────────────────────

class TestColorbarView:

    async def test_returns_colorbar_bytes(self, tmp_path):
        coord = _make_coord(tmp_path, colorbar=FAKE_PNG)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = ColorbarView(hass)
        response = await view.get(_make_request(), REGION_ID)
        assert response.body == FAKE_PNG

    async def test_content_type_image_png(self, tmp_path):
        coord = _make_coord(tmp_path, colorbar=FAKE_PNG)
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = ColorbarView(hass)
        response = await view.get(_make_request(), REGION_ID)
        assert response.content_type == "image/png"

    async def test_unknown_region_raises_404(self):
        hass = _make_hass({DATA_COORDINATORS: {}})
        view = ColorbarView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), "unknown")

    async def test_no_coordinators_raises_404(self):
        hass = _make_hass({})
        view = ColorbarView(hass)
        with pytest.raises(web.HTTPNotFound):
            await view.get(_make_request(), REGION_ID)

    async def test_calls_colorbar_png_property(self, tmp_path):
        coord = _make_coord(tmp_path, colorbar=b"custom_bar")
        hass = _make_hass({DATA_COORDINATORS: {REGION_ID: coord}})
        view = ColorbarView(hass)
        response = await view.get(_make_request(), REGION_ID)
        assert response.body == b"custom_bar"
