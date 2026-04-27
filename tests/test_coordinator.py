"""Tests for coordinator.py."""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.rain_radar_hub.const import (
    API_PREFIX,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    FRAME_MAX_AGE_HOURS,
)
from custom_components.rain_radar_hub.coordinator import (
    FrameUpdateCoordinator,
    _EARTH_RADIUS_KM,
    _build_inventory,
    _compute_bounds,
)

# ────────────────────────────────────────────────────────────────────────────
# Shared fixtures / helpers
# ────────────────────────────────────────────────────────────────────────────

REGION_ID = "hamburg"
REGION_LAT = 53.5
REGION_LON = 10.0
REGION_RADIUS = 100.0
REGION_CONFIG = {
    CONF_LATITUDE: REGION_LAT,
    CONF_LONGITUDE: REGION_LON,
    CONF_RADIUS_KM: REGION_RADIUS,
}


def _make_hass(config_dir: str) -> MagicMock:
    hass = MagicMock()
    hass.config.config_dir = config_dir
    return hass


def _make_coord(tmp_path) -> FrameUpdateCoordinator:
    hass = _make_hass(str(tmp_path))
    return FrameUpdateCoordinator(hass, REGION_ID, REGION_CONFIG)


# ────────────────────────────────────────────────────────────────────────────
# _compute_bounds
# ────────────────────────────────────────────────────────────────────────────

class TestComputeBounds:

    def test_symmetric_around_center(self):
        lon_min, lat_min, lon_max, lat_max = _compute_bounds(53.5, 10.0, 100.0)
        assert abs((lon_min + lon_max) / 2 - 10.0) < 1e-9
        assert abs((lat_min + lat_max) / 2 - 53.5) < 1e-9

    def test_lat_span_correct(self):
        lat_deg = math.degrees(100.0 / _EARTH_RADIUS_KM)
        _, lat_min, _, lat_max = _compute_bounds(53.5, 10.0, 100.0)
        assert abs((lat_max - lat_min) / 2 - lat_deg) < 1e-9

    def test_lon_span_wider_at_mid_latitude(self):
        lon_min, lat_min, lon_max, lat_max = _compute_bounds(53.5, 10.0, 100.0)
        # cos(53.5°) ≈ 0.594 < 1  →  lon degrees > lat degrees
        assert (lon_max - lon_min) > (lat_max - lat_min)

    def test_equator_lon_equals_lat_span(self):
        lon_min, lat_min, lon_max, lat_max = _compute_bounds(0.0, 0.0, 100.0)
        assert abs((lon_max - lon_min) - (lat_max - lat_min)) < 1e-6

    def test_min_less_than_max(self):
        lon_min, lat_min, lon_max, lat_max = _compute_bounds(53.5, 10.0, 100.0)
        assert lon_min < lon_max
        assert lat_min < lat_max

    def test_zero_radius_collapses_to_point(self):
        lon_min, lat_min, lon_max, lat_max = _compute_bounds(53.5, 10.0, 0.0)
        assert lon_min == lon_max == 10.0
        assert lat_min == lat_max == 53.5

    def test_negative_longitude(self):
        lon_min, _, lon_max, _ = _compute_bounds(51.5, -0.1, 50.0)
        assert lon_min < -0.1 < lon_max

    def test_result_is_four_floats(self):
        result = _compute_bounds(53.5, 10.0, 100.0)
        assert len(result) == 4
        assert all(isinstance(v, float) for v in result)


# ────────────────────────────────────────────────────────────────────────────
# _build_inventory
# ────────────────────────────────────────────────────────────────────────────

class TestBuildInventory:

    def test_nonexistent_dir_returns_empty_frames(self, tmp_path):
        result = _build_inventory(tmp_path / "no_such_dir", "r1")
        assert result["frames"] == []

    def test_empty_dir_returns_empty_frames(self, tmp_path):
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        result = _build_inventory(frames_dir, "r1")
        assert result["frames"] == []

    def test_single_frame_timestamp_and_url(self, tmp_path):
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "2026-04-27T14:00:00Z.png").write_bytes(b"x")
        result = _build_inventory(frames_dir, "r1")
        assert len(result["frames"]) == 1
        entry = result["frames"][0]
        assert entry["timestamp"] == "2026-04-27T14:00:00Z"
        assert entry["url"] == f"{API_PREFIX}/regions/r1/frames/2026-04-27T14:00:00Z.png"

    def test_multiple_frames_sorted_ascending(self, tmp_path):
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        for name in [
            "2026-04-27T16:00:00Z.png",
            "2026-04-27T14:00:00Z.png",
            "2026-04-27T15:00:00Z.png",
        ]:
            (frames_dir / name).write_bytes(b"x")
        result = _build_inventory(frames_dir, "r1")
        timestamps = [f["timestamp"] for f in result["frames"]]
        assert timestamps == sorted(timestamps)
        assert len(timestamps) == 3

    def test_colorbar_url_contains_region_id(self, tmp_path):
        result = _build_inventory(tmp_path, "my_region")
        assert result["colorbar_url"] == f"{API_PREFIX}/regions/my_region/colorbar"

    def test_ignores_non_png_files(self, tmp_path):
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "2026-04-27T14:00:00Z.png").write_bytes(b"x")
        (frames_dir / "readme.txt").write_bytes(b"x")
        (frames_dir / "data.bin").write_bytes(b"x")
        result = _build_inventory(frames_dir, "r1")
        assert len(result["frames"]) == 1

    def test_url_uses_api_prefix(self, tmp_path):
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "2026-04-27T14:00:00Z.png").write_bytes(b"x")
        result = _build_inventory(frames_dir, "r1")
        assert result["frames"][0]["url"].startswith(API_PREFIX)


# ────────────────────────────────────────────────────────────────────────────
# FrameUpdateCoordinator — __init__ and properties
# ────────────────────────────────────────────────────────────────────────────

class TestCoordinatorInit:

    def test_bounds_match_compute_bounds(self, tmp_path):
        coord = _make_coord(tmp_path)
        expected = _compute_bounds(REGION_LAT, REGION_LON, REGION_RADIUS)
        assert coord.region_bounds == expected

    def test_frames_dir_contains_region_id(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert REGION_ID in str(coord._frames_dir)

    def test_frames_dir_under_config_dir(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert str(coord._frames_dir).startswith(str(tmp_path))

    def test_frames_dir_ends_with_frames(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert coord._frames_dir.name == "frames"

    def test_colorbar_cache_initially_none(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert coord._colorbar_cache is None

    def test_region_id_stored(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert coord.region_id == REGION_ID

    def test_region_config_stored(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert coord.region_config is REGION_CONFIG


# ────────────────────────────────────────────────────────────────────────────
# colorbar_png property
# ────────────────────────────────────────────────────────────────────────────

class TestColorbarPng:

    def test_returns_bytes(self, tmp_path):
        coord = _make_coord(tmp_path)
        png = coord.colorbar_png
        assert isinstance(png, bytes)
        assert len(png) > 0

    def test_valid_png_header(self, tmp_path):
        coord = _make_coord(tmp_path)
        assert coord.colorbar_png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_generate_called_only_once(self, tmp_path):
        coord = _make_coord(tmp_path)
        with patch(
            "custom_components.rain_radar_hub.coordinator.generate_colorbar",
            return_value=b"fake_png_bytes",
        ) as mock_gen:
            coord._colorbar_cache = None
            first = coord.colorbar_png
            second = coord.colorbar_png
        mock_gen.assert_called_once()
        assert first is second

    def test_cached_value_returned(self, tmp_path):
        coord = _make_coord(tmp_path)
        coord._colorbar_cache = b"already_cached"
        with patch(
            "custom_components.rain_radar_hub.coordinator.generate_colorbar",
        ) as mock_gen:
            result = coord.colorbar_png
        mock_gen.assert_not_called()
        assert result == b"already_cached"


# ────────────────────────────────────────────────────────────────────────────
# _async_update_data
# ────────────────────────────────────────────────────────────────────────────

class TestAsyncUpdateData:

    async def test_returns_inventory_dict(self, tmp_path):
        coord = _make_coord(tmp_path)
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
            ),
            patch("custom_components.rain_radar_hub.coordinator.cleanup_old_frames"),
        ):
            result = await coord._async_update_data()
        assert "frames" in result
        assert "colorbar_url" in result

    async def test_calls_fetch_rw_frames_with_correct_args(self, tmp_path):
        coord = _make_coord(tmp_path)
        with (
            patch(
                "custom_components.rain_radar_hub.coordinator.async_get_clientsession",
            ) as mock_session,
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch("custom_components.rain_radar_hub.coordinator.cleanup_old_frames"),
        ):
            await coord._async_update_data()
        mock_fetch.assert_called_once_with(
            mock_session.return_value,
            coord._frames_dir,
            coord._bounds,
            lookback_minutes=FRAME_MAX_AGE_HOURS * 60,
        )

    async def test_calls_cleanup_with_correct_args(self, tmp_path):
        coord = _make_coord(tmp_path)
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.rain_radar_hub.coordinator.cleanup_old_frames",
            ) as mock_cleanup,
        ):
            await coord._async_update_data()
        mock_cleanup.assert_called_once_with(coord._frames_dir, FRAME_MAX_AGE_HOURS)

    async def test_raises_update_failed_on_fetch_error(self, tmp_path):
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coord = _make_coord(tmp_path)
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
                side_effect=RuntimeError("network error"),
            ),
        ):
            with pytest.raises(UpdateFailed, match="DWD RW fetch failed"):
                await coord._async_update_data()

    async def test_update_failed_wraps_original_exception(self, tmp_path):
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coord = _make_coord(tmp_path)
        original = OSError("timeout")
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
                side_effect=original,
            ),
        ):
            with pytest.raises(UpdateFailed) as exc_info:
                await coord._async_update_data()
        assert exc_info.value.__cause__ is original

    async def test_cleanup_not_called_on_fetch_error(self, tmp_path):
        coord = _make_coord(tmp_path)
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
                side_effect=RuntimeError("fail"),
            ),
            patch(
                "custom_components.rain_radar_hub.coordinator.cleanup_old_frames",
            ) as mock_cleanup,
        ):
            with pytest.raises(Exception):
                await coord._async_update_data()
        mock_cleanup.assert_not_called()

    async def test_inventory_reflects_frame_files(self, tmp_path):
        coord = _make_coord(tmp_path)
        coord._frames_dir.mkdir(parents=True, exist_ok=True)
        (coord._frames_dir / "2026-04-27T14:00:00Z.png").write_bytes(b"x")
        (coord._frames_dir / "2026-04-27T15:00:00Z.png").write_bytes(b"x")
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
            ),
            patch("custom_components.rain_radar_hub.coordinator.cleanup_old_frames"),
        ):
            result = await coord._async_update_data()
        assert len(result["frames"]) == 2

    async def test_empty_frames_dir_returns_empty_list(self, tmp_path):
        coord = _make_coord(tmp_path)
        with (
            patch("custom_components.rain_radar_hub.coordinator.async_get_clientsession"),
            patch(
                "custom_components.rain_radar_hub.coordinator.fetch_rw_frames",
                new_callable=AsyncMock,
            ),
            patch("custom_components.rain_radar_hub.coordinator.cleanup_old_frames"),
        ):
            result = await coord._async_update_data()
        assert result["frames"] == []
