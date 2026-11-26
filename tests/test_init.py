"""Tests for __init__.py (async_setup_entry / unload / remove)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.rain_radar_hub import (
    _async_hub_options_updated,
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.rain_radar_hub.const import (
    CONF_DEFAULT_ZOOM,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_REGION_NAME,
    CONF_TILE_CACHE_SIZE_MB,
    CONF_TILE_PROVIDER,
    DATA_COORDINATORS,
    DATA_TILE_PROXY,
    DEFAULT_TILE_CACHE_SIZE_MB,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_REGION,
    TILE_PROVIDER_CARTO_VOYAGER,
)

# ────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ────────────────────────────────────────────────────────────────────────────

REGION_ID = "hamburg"


def _make_hass(config_dir: str) -> MagicMock:
    hass = MagicMock()
    hass.config.config_dir = config_dir
    hass.data = {}
    return hass


def _hub_entry(options=None) -> MagicMock:
    entry = MagicMock()
    entry.data = {
        "entry_type": ENTRY_TYPE_HUB,
        CONF_TILE_PROVIDER: TILE_PROVIDER_CARTO_VOYAGER,
        CONF_TILE_CACHE_SIZE_MB: DEFAULT_TILE_CACHE_SIZE_MB,
        "custom_tile_url": "",
    }
    entry.options = options or {}
    return entry


def _hub_ready_data() -> dict:
    """Domain data as left behind by a hub that registered the views."""
    return {
        DOMAIN: {
            DATA_TILE_PROXY: None,
            DATA_COORDINATORS: {},
            "views_registered": True,
        }
    }


def _region_entry(
    region_id=REGION_ID, lat=53.5, lon=10.0, radius=100, zoom=9
) -> MagicMock:
    entry = MagicMock()
    entry.data = {
        "entry_type": ENTRY_TYPE_REGION,
        "region_id": region_id,
        CONF_REGION_NAME: region_id.capitalize(),
        CONF_LATITUDE: lat,
        CONF_LONGITUDE: lon,
        CONF_RADIUS_KM: radius,
        CONF_DEFAULT_ZOOM: zoom,
    }
    entry.options = {}
    return entry


# ────────────────────────────────────────────────────────────────────────────
# Hub setup
# ────────────────────────────────────────────────────────────────────────────

_PATCH_PROXY = "custom_components.rain_radar_hub.TileProxy"
_PATCH_COORD = "custom_components.rain_radar_hub.FrameUpdateCoordinator"


class TestSetupHub:

    async def test_returns_true(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            result = await async_setup_entry(hass, entry)
        assert result is True

    async def test_creates_tile_proxy(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        assert hass.data[DOMAIN][DATA_TILE_PROXY] is MockProxy.return_value

    async def test_tile_proxy_setup_called(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        MockProxy.return_value.async_setup.assert_called_once()

    async def test_cache_size_from_options_overrides_data(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry(options={CONF_TILE_CACHE_SIZE_MB: 200})
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        _, kwargs = MockProxy.call_args
        assert kwargs["max_size_bytes"] == 200 * 1_048_576

    async def test_cache_size_from_data_when_no_options(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()  # options = {}
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        _, kwargs = MockProxy.call_args
        assert kwargs["max_size_bytes"] == DEFAULT_TILE_CACHE_SIZE_MB * 1_048_576

    async def test_registers_http_views(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        assert hass.http.register_view.call_count == 4

    async def test_views_registered_only_once(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        # Still only 4 registrations from the first setup
        assert hass.http.register_view.call_count == 4

    async def test_empty_custom_url_passes_none(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()  # custom_tile_url = ""
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        _, kwargs = MockProxy.call_args
        assert kwargs["custom_url"] is None

    async def test_custom_url_passed_through(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = MagicMock()
        entry.data = {
            "entry_type": ENTRY_TYPE_HUB,
            CONF_TILE_PROVIDER: "custom_url",
            "custom_tile_url": "https://example.com/{z}/{x}/{y}.png",
            CONF_TILE_CACHE_SIZE_MB: 100,
        }
        entry.options = {}
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        _, kwargs = MockProxy.call_args
        assert kwargs["custom_url"] == "https://example.com/{z}/{x}/{y}.png"


# ────────────────────────────────────────────────────────────────────────────
# Region setup
# ────────────────────────────────────────────────────────────────────────────

class TestSetupRegion:

    async def test_returns_true(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.data = _hub_ready_data()
        entry = _region_entry()
        with patch(_PATCH_COORD) as MockCoord:
            MockCoord.return_value.async_config_entry_first_refresh = AsyncMock()
            result = await async_setup_entry(hass, entry)
        assert result is True

    async def test_coordinator_stored_in_data(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.data = _hub_ready_data()
        entry = _region_entry()
        with patch(_PATCH_COORD) as MockCoord:
            MockCoord.return_value.async_config_entry_first_refresh = AsyncMock()
            await async_setup_entry(hass, entry)
        assert hass.data[DOMAIN][DATA_COORDINATORS][REGION_ID] is MockCoord.return_value

    async def test_first_refresh_called(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.data = _hub_ready_data()
        entry = _region_entry()
        with patch(_PATCH_COORD) as MockCoord:
            MockCoord.return_value.async_config_entry_first_refresh = AsyncMock()
            await async_setup_entry(hass, entry)
        MockCoord.return_value.async_config_entry_first_refresh.assert_called_once()

    async def test_region_config_passed_to_coordinator(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.data = _hub_ready_data()
        entry = _region_entry(lat=48.14, lon=11.58, radius=150, zoom=10)
        with patch(_PATCH_COORD) as MockCoord:
            MockCoord.return_value.async_config_entry_first_refresh = AsyncMock()
            await async_setup_entry(hass, entry)
        # FrameUpdateCoordinator(hass, region_id, region_config) — positional
        pos_args = MockCoord.call_args.args
        region_config = pos_args[2]
        assert region_config[CONF_LATITUDE] == 48.14
        assert region_config[CONF_LONGITUDE] == 11.58

    async def test_unknown_entry_type_returns_false(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = MagicMock()
        entry.data = {"entry_type": "unknown"}
        result = await async_setup_entry(hass, entry)
        assert result is False

    async def test_hass_data_initialised_if_missing(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        with patch(_PATCH_PROXY) as MockProxy:
            MockProxy.return_value.async_setup = AsyncMock()
            await async_setup_entry(hass, entry)
        assert DOMAIN in hass.data


# ────────────────────────────────────────────────────────────────────────────
# Unload
# ────────────────────────────────────────────────────────────────────────────

class TestUnloadEntry:

    async def test_unload_hub_closes_proxy(self, tmp_path):
        proxy = MagicMock()
        proxy.async_close = AsyncMock()
        hass = _make_hass(str(tmp_path))
        hass.data = {DOMAIN: {DATA_TILE_PROXY: proxy, DATA_COORDINATORS: {}}}
        entry = _hub_entry()
        result = await async_unload_entry(hass, entry)
        assert result is True
        proxy.async_close.assert_called_once()

    async def test_unload_hub_clears_proxy_from_data(self, tmp_path):
        proxy = MagicMock()
        proxy.async_close = AsyncMock()
        hass = _make_hass(str(tmp_path))
        hass.data = {DOMAIN: {DATA_TILE_PROXY: proxy, DATA_COORDINATORS: {}}}
        entry = _hub_entry()
        await async_unload_entry(hass, entry)
        assert hass.data[DOMAIN][DATA_TILE_PROXY] is None

    async def test_unload_hub_no_proxy_is_safe(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.data = {DOMAIN: {DATA_TILE_PROXY: None, DATA_COORDINATORS: {}}}
        entry = _hub_entry()
        result = await async_unload_entry(hass, entry)
        assert result is True

    async def test_unload_region_removes_coordinator(self, tmp_path):
        coord = MagicMock()
        hass = _make_hass(str(tmp_path))
        hass.data = {
            DOMAIN: {DATA_TILE_PROXY: None, DATA_COORDINATORS: {REGION_ID: coord}}
        }
        entry = _region_entry()
        result = await async_unload_entry(hass, entry)
        assert result is True
        assert REGION_ID not in hass.data[DOMAIN][DATA_COORDINATORS]

    async def test_unload_region_missing_region_id_is_safe(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.data = {DOMAIN: {DATA_TILE_PROXY: None, DATA_COORDINATORS: {}}}
        entry = MagicMock()
        entry.data = {"entry_type": ENTRY_TYPE_REGION, "region_id": "nonexistent"}
        result = await async_unload_entry(hass, entry)
        assert result is True

    async def test_unload_hub_without_domain_data_is_safe(self, tmp_path):
        """Regression: unloading must not raise when setup never stored data."""
        hass = _make_hass(str(tmp_path))
        result = await async_unload_entry(hass, _hub_entry())
        assert result is True
        assert DOMAIN not in hass.data

    async def test_unload_region_without_domain_data_is_safe(self, tmp_path):
        """Regression: unloading must not raise when setup never stored data."""
        hass = _make_hass(str(tmp_path))
        result = await async_unload_entry(hass, _region_entry())
        assert result is True
        assert DOMAIN not in hass.data

    async def test_unload_unknown_entry_type_returns_true(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = MagicMock()
        entry.data = {"entry_type": "unknown"}
        assert await async_unload_entry(hass, entry) is True


# ────────────────────────────────────────────────────────────────────────────
# Options update
# ────────────────────────────────────────────────────────────────────────────

class TestHubOptionsUpdated:

    async def test_reloads_hub_entry(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        hass.config_entries.async_reload = AsyncMock()
        entry = _hub_entry()
        entry.entry_id = "hub_entry_id"
        await _async_hub_options_updated(hass, entry)
        hass.config_entries.async_reload.assert_awaited_once_with("hub_entry_id")


# ────────────────────────────────────────────────────────────────────────────
# Remove entry
# ────────────────────────────────────────────────────────────────────────────

class TestRemoveEntry:

    async def test_remove_hub_deletes_tile_cache(self, tmp_path):
        tile_dir = tmp_path / ".storage" / "rain_radar_hub" / "tile_cache"
        tile_dir.mkdir(parents=True)
        (tile_dir / "dummy.txt").write_text("x")
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        await async_remove_entry(hass, entry)
        assert not tile_dir.exists()

    async def test_remove_hub_deletes_db(self, tmp_path):
        db = tmp_path / ".storage" / "rain_radar_hub" / "tile_cache.db"
        db.parent.mkdir(parents=True)
        db.write_bytes(b"")
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        await async_remove_entry(hass, entry)
        assert not db.exists()

    async def test_remove_hub_no_files_is_safe(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _hub_entry()
        await async_remove_entry(hass, entry)  # Should not raise

    async def test_remove_region_deletes_frames_dir(self, tmp_path):
        frames_dir = (
            tmp_path / ".storage" / "rain_radar_hub" / "regions" / REGION_ID / "frames"
        )
        frames_dir.mkdir(parents=True)
        (frames_dir / "2026-04-27T14:00:00Z.png").write_bytes(b"x")
        hass = _make_hass(str(tmp_path))
        entry = _region_entry()
        await async_remove_entry(hass, entry)
        assert not frames_dir.exists()

    async def test_remove_region_no_frames_is_safe(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = _region_entry()
        await async_remove_entry(hass, entry)  # Should not raise

    async def test_remove_unknown_type_is_safe(self, tmp_path):
        hass = _make_hass(str(tmp_path))
        entry = MagicMock()
        entry.data = {"entry_type": "unknown"}
        entry.options = {}
        await async_remove_entry(hass, entry)  # Should not raise
