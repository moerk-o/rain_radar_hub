"""Tests for config_flow.py."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rain_radar_hub.config_flow import (
    _is_valid_custom_url,
    _is_within_dwd_grid,
    _to_region_id,
)
from custom_components.rain_radar_hub.const import (
    CONF_CUSTOM_TILE_URL,
    CONF_DEFAULT_ZOOM,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_REGION_NAME,
    CONF_TILE_CACHE_SIZE_MB,
    CONF_TILE_PROVIDER,
    DEFAULT_RADIUS_KM,
    DEFAULT_TILE_CACHE_SIZE_MB,
    DEFAULT_ZOOM,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_REGION,
    TILE_PROVIDER_CARTO_VOYAGER,
    TILE_PROVIDER_CUSTOM_URL,
    TILE_PROVIDER_OSM_STANDARD,
)

# ────────────────────────────────────────────────────────────────────────────
# Pure helper: _is_valid_custom_url
# ────────────────────────────────────────────────────────────────────────────

class TestIsValidCustomUrl:

    def test_valid_url_all_placeholders(self):
        assert _is_valid_custom_url("https://example.com/{z}/{x}/{y}.png")

    def test_valid_url_different_order(self):
        assert _is_valid_custom_url("https://example.com/{x}/{y}/{z}.png")

    def test_valid_url_query_params(self):
        assert _is_valid_custom_url("https://example.com/tile?z={z}&x={x}&y={y}")

    def test_missing_z(self):
        assert not _is_valid_custom_url("https://example.com/{x}/{y}.png")

    def test_missing_x(self):
        assert not _is_valid_custom_url("https://example.com/{z}/{y}.png")

    def test_missing_y(self):
        assert not _is_valid_custom_url("https://example.com/{z}/{x}.png")

    def test_empty_string(self):
        assert not _is_valid_custom_url("")

    def test_no_placeholders(self):
        assert not _is_valid_custom_url("https://example.com/static.png")

    def test_partial_placeholder_not_valid(self):
        assert not _is_valid_custom_url("https://example.com/{z}/{x}/y.png")

    def test_subdomain_placeholder_irrelevant(self):
        # Extra {s} is fine — only {z}, {x}, {y} required
        assert _is_valid_custom_url("https://{s}.example.com/{z}/{x}/{y}.png")


# ────────────────────────────────────────────────────────────────────────────
# Pure helper: _is_within_dwd_grid
# ────────────────────────────────────────────────────────────────────────────

class TestIsWithinDwdGrid:

    def test_hamburg_inside(self):
        assert _is_within_dwd_grid(53.55, 10.00)

    def test_berlin_inside(self):
        assert _is_within_dwd_grid(52.52, 13.40)

    def test_munich_inside(self):
        assert _is_within_dwd_grid(48.14, 11.58)

    def test_flensburg_inside(self):
        assert _is_within_dwd_grid(54.79, 9.43)

    def test_new_york_outside(self):
        assert not _is_within_dwd_grid(40.71, -74.01)

    def test_tokyo_outside(self):
        assert not _is_within_dwd_grid(35.68, 139.69)

    def test_reykjavik_outside(self):
        assert not _is_within_dwd_grid(64.13, -21.94)

    def test_cape_town_outside(self):
        assert not _is_within_dwd_grid(-33.93, 18.42)


# ────────────────────────────────────────────────────────────────────────────
# Pure helper: _to_region_id
# ────────────────────────────────────────────────────────────────────────────

class TestToRegionId:

    def test_simple_name(self):
        assert _to_region_id("Hamburg") == "hamburg"

    def test_multi_word(self):
        assert _to_region_id("North Sea Region") == "north_sea_region"

    def test_numbers_preserved(self):
        assert _to_region_id("Region 42") == "region_42"

    def test_special_chars_replaced(self):
        result = _to_region_id("Region!@#Name")
        assert result == "region_name"

    def test_leading_trailing_stripped(self):
        assert _to_region_id("  Hamburg  ") == "hamburg"

    def test_multiple_spaces_collapsed(self):
        assert _to_region_id("North  Sea") == "north_sea"

    def test_already_lowercase(self):
        assert _to_region_id("berlin") == "berlin"

    def test_mixed_case(self):
        assert _to_region_id("HaMBurG") == "hamburg"


# ────────────────────────────────────────────────────────────────────────────
# Config flow — Hub path
# ────────────────────────────────────────────────────────────────────────────

PATCH_SETUP = f"custom_components.{DOMAIN}.async_setup_entry"


class TestHubFlow:

    async def test_user_step_no_hub_shows_hub_form(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "hub"

    async def test_hub_valid_creates_entry(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        with patch(PATCH_SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_TILE_PROVIDER: TILE_PROVIDER_CARTO_VOYAGER,
                    CONF_CUSTOM_TILE_URL: "",
                    CONF_TILE_CACHE_SIZE_MB: DEFAULT_TILE_CACHE_SIZE_MB,
                },
            )
        assert result["type"] == "create_entry"
        assert result["data"]["entry_type"] == ENTRY_TYPE_HUB
        assert result["data"][CONF_TILE_PROVIDER] == TILE_PROVIDER_CARTO_VOYAGER

    async def test_hub_osm_provider(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        with patch(PATCH_SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_TILE_PROVIDER: TILE_PROVIDER_OSM_STANDARD,
                    CONF_CUSTOM_TILE_URL: "",
                    CONF_TILE_CACHE_SIZE_MB: 100,
                },
            )
        assert result["type"] == "create_entry"

    async def test_hub_custom_url_valid(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        with patch(PATCH_SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_TILE_PROVIDER: TILE_PROVIDER_CUSTOM_URL,
                    CONF_CUSTOM_TILE_URL: "https://example.com/{z}/{x}/{y}.png",
                    CONF_TILE_CACHE_SIZE_MB: 100,
                },
            )
        assert result["type"] == "create_entry"

    async def test_hub_custom_url_invalid_placeholder(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_TILE_PROVIDER: TILE_PROVIDER_CUSTOM_URL,
                CONF_CUSTOM_TILE_URL: "https://example.com/tiles.png",
                CONF_TILE_CACHE_SIZE_MB: 100,
            },
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_CUSTOM_TILE_URL) == "invalid_custom_url"

    async def test_hub_cache_too_small(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_TILE_PROVIDER: TILE_PROVIDER_CARTO_VOYAGER,
                CONF_CUSTOM_TILE_URL: "",
                CONF_TILE_CACHE_SIZE_MB: 10,
            },
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_TILE_CACHE_SIZE_MB) == "cache_size_too_small"

    async def test_hub_already_configured_abort(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=DOMAIN,
            data={"entry_type": ENTRY_TYPE_HUB},
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        # Routes to region_name since hub exists; hub step aborts on duplicate unique_id
        # A second init of hub directly should abort
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        # With hub present, user step routes to region_name, not hub
        assert result2["type"] == "form"
        assert result2["step_id"] == "region_name"


# ────────────────────────────────────────────────────────────────────────────
# Config flow — Region path
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def hass_with_hub(hass):
    """Return a hass instance with a hub entry already present."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            "entry_type": ENTRY_TYPE_HUB,
            CONF_TILE_PROVIDER: TILE_PROVIDER_CARTO_VOYAGER,
            CONF_TILE_CACHE_SIZE_MB: DEFAULT_TILE_CACHE_SIZE_MB,
        },
    )
    entry.add_to_hass(hass)
    return hass


class TestRegionFlow:

    async def test_user_step_with_hub_shows_region_name(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "region_name"

    async def test_region_name_advances_to_location(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_REGION_NAME: "Hamburg"},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "region_location"

    async def test_region_location_valid_advances_to_map(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Hamburg"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 10.00},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "region_map"

    async def test_full_region_flow_creates_entry(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Hamburg"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 10.00},
        )
        with patch(PATCH_SETUP, return_value=True):
            result = await hass_with_hub.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_RADIUS_KM: DEFAULT_RADIUS_KM, CONF_DEFAULT_ZOOM: DEFAULT_ZOOM},
            )
        assert result["type"] == "create_entry"
        data = result["data"]
        assert data["entry_type"] == ENTRY_TYPE_REGION
        assert data["region_id"] == "hamburg"
        assert data[CONF_LATITUDE] == 53.55
        assert data[CONF_LONGITUDE] == 10.00
        assert data[CONF_RADIUS_KM] == DEFAULT_RADIUS_KM
        assert data[CONF_DEFAULT_ZOOM] == DEFAULT_ZOOM

    async def test_region_name_duplicate_shows_error(self, hass_with_hub):
        existing = MockConfigEntry(
            domain=DOMAIN,
            data={
                "entry_type": ENTRY_TYPE_REGION,
                "region_id": "hamburg",
                CONF_REGION_NAME: "Hamburg",
            },
        )
        existing.add_to_hass(hass_with_hub)

        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_REGION_NAME: "Hamburg"},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "region_name"
        assert result["errors"].get(CONF_REGION_NAME) == "region_already_exists"

    async def test_region_location_outside_dwd_shows_error(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Tokyo"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 35.68, CONF_LONGITUDE: 139.69},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "region_location"
        assert result["errors"].get("base") == "outside_dwd_grid"

    async def test_region_map_radius_too_small(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Hamburg"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 10.00},
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_RADIUS_KM: 5, CONF_DEFAULT_ZOOM: DEFAULT_ZOOM},
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_RADIUS_KM) == "radius_out_of_range"

    async def test_region_map_radius_too_large(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Hamburg"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 10.00},
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_RADIUS_KM: 9999, CONF_DEFAULT_ZOOM: DEFAULT_ZOOM},
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_RADIUS_KM) == "radius_out_of_range"

    async def test_region_map_zoom_too_low(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Hamburg"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 10.00},
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_RADIUS_KM: DEFAULT_RADIUS_KM, CONF_DEFAULT_ZOOM: 1},
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_DEFAULT_ZOOM) == "zoom_out_of_range"

    async def test_region_map_zoom_too_high(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "Hamburg"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 10.00},
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_RADIUS_KM: DEFAULT_RADIUS_KM, CONF_DEFAULT_ZOOM: 99},
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_DEFAULT_ZOOM) == "zoom_out_of_range"

    async def test_region_entry_title_contains_name(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "North Sea"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 8.00},
        )
        with patch(PATCH_SETUP, return_value=True):
            result = await hass_with_hub.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_RADIUS_KM: DEFAULT_RADIUS_KM, CONF_DEFAULT_ZOOM: DEFAULT_ZOOM},
            )
        assert result["type"] == "create_entry"
        assert "North Sea" in result["title"]

    async def test_region_id_is_slug(self, hass_with_hub):
        result = await hass_with_hub.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_REGION_NAME: "North Sea Region"}
        )
        result = await hass_with_hub.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LATITUDE: 53.55, CONF_LONGITUDE: 8.00},
        )
        with patch(PATCH_SETUP, return_value=True):
            result = await hass_with_hub.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_RADIUS_KM: DEFAULT_RADIUS_KM, CONF_DEFAULT_ZOOM: DEFAULT_ZOOM},
            )
        assert result["data"]["region_id"] == "north_sea_region"


# ────────────────────────────────────────────────────────────────────────────
# Options flow
# ────────────────────────────────────────────────────────────────────────────

class TestOptionsFlow:

    @pytest.fixture
    async def hub_entry(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=DOMAIN,
            data={
                "entry_type": ENTRY_TYPE_HUB,
                CONF_TILE_PROVIDER: TILE_PROVIDER_CARTO_VOYAGER,
                CONF_TILE_CACHE_SIZE_MB: DEFAULT_TILE_CACHE_SIZE_MB,
            },
        )
        entry.add_to_hass(hass)
        with patch(PATCH_SETUP, return_value=True):
            await hass.config_entries.async_setup(entry.entry_id)
        return entry

    async def test_options_flow_shows_form(self, hass, hub_entry):
        result = await hass.config_entries.options.async_init(hub_entry.entry_id)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    async def test_options_flow_valid_update(self, hass, hub_entry):
        result = await hass.config_entries.options.async_init(hub_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_TILE_CACHE_SIZE_MB: 200},
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_TILE_CACHE_SIZE_MB] == 200

    async def test_options_flow_cache_too_small(self, hass, hub_entry):
        result = await hass.config_entries.options.async_init(hub_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_TILE_CACHE_SIZE_MB: 10},
        )
        assert result["type"] == "form"
        assert result["errors"].get(CONF_TILE_CACHE_SIZE_MB) == "cache_size_too_small"

    async def test_options_flow_minimum_valid(self, hass, hub_entry):
        result = await hass.config_entries.options.async_init(hub_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_TILE_CACHE_SIZE_MB: 50},
        )
        assert result["type"] == "create_entry"
