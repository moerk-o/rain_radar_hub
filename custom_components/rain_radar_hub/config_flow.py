"""Config flow for RainRadarHub."""
from __future__ import annotations

import re
from typing import Any

import pyproj
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import (
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
    DEFAULT_TILE_PROVIDER,
    DEFAULT_ZOOM,
    DOMAIN,
    DWD_GRID_COLS,
    DWD_GRID_PROJDEF,
    DWD_GRID_ROWS,
    DWD_GRID_STEP_M,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_REGION,
    MAX_RADIUS_KM,
    MAX_ZOOM,
    MIN_RADIUS_KM,
    MIN_TILE_CACHE_SIZE_MB,
    MIN_ZOOM,
    TILE_PROVIDER_CARTO_VOYAGER,
    TILE_PROVIDER_CUSTOM_URL,
    TILE_PROVIDER_OSM_STANDARD,
)

_DWD_GRID_PROJ = pyproj.Proj(DWD_GRID_PROJDEF)

_TILE_PROVIDER_OPTIONS = [
    TILE_PROVIDER_CARTO_VOYAGER,
    TILE_PROVIDER_OSM_STANDARD,
    TILE_PROVIDER_CUSTOM_URL,
]

_SCHEMA_HUB = vol.Schema(
    {
        vol.Required(CONF_TILE_PROVIDER, default=DEFAULT_TILE_PROVIDER): vol.In(
            _TILE_PROVIDER_OPTIONS
        ),
        vol.Optional(CONF_CUSTOM_TILE_URL, default=""): str,
        vol.Required(
            CONF_TILE_CACHE_SIZE_MB, default=DEFAULT_TILE_CACHE_SIZE_MB
        ): vol.Coerce(int),
    }
)

_SCHEMA_REGION_NAME = vol.Schema(
    {
        vol.Required(CONF_REGION_NAME): str,
    }
)

_SCHEMA_REGION_LOCATION = vol.Schema(
    {
        vol.Required(CONF_LATITUDE): vol.Coerce(float),
        vol.Required(CONF_LONGITUDE): vol.Coerce(float),
    }
)

_SCHEMA_REGION_MAP = vol.Schema(
    {
        vol.Required(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): vol.Coerce(int),
        vol.Required(CONF_DEFAULT_ZOOM, default=DEFAULT_ZOOM): vol.Coerce(int),
    }
)


def _is_valid_custom_url(url: str) -> bool:
    """Return True if the URL template contains {z}, {x}, and {y} placeholders."""
    return "{z}" in url and "{x}" in url and "{y}" in url


def _is_within_dwd_grid(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) falls within the DWD RADOLAN composite grid."""
    x, y = _DWD_GRID_PROJ(lon, lat)
    # The upper-left pixel is centred on (0, 0); rows run towards negative y
    col = x / DWD_GRID_STEP_M + 0.5
    row = -y / DWD_GRID_STEP_M + 0.5
    return 0 <= col < DWD_GRID_COLS and 0 <= row < DWD_GRID_ROWS


def _to_region_id(name: str) -> str:
    """Convert a region display name to a stable slug-style ID."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class RainRadarHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for RainRadarHub."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._region_data: dict[str, Any] = {}

    async def async_step_user(self, user_input=None):
        """Entry point — route to Hub or Region setup."""
        hub_entries = [
            e
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if e.data.get("entry_type") == ENTRY_TYPE_HUB
        ]
        if not hub_entries:
            return await self.async_step_hub(user_input)
        return await self.async_step_region_name(user_input)

    async def async_step_hub(self, user_input=None):
        """Hub setup: tile provider + cache size."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            provider = user_input.get(CONF_TILE_PROVIDER, "")
            custom_url = user_input.get(CONF_CUSTOM_TILE_URL, "")
            cache_mb = user_input.get(CONF_TILE_CACHE_SIZE_MB, 0)

            if provider == TILE_PROVIDER_CUSTOM_URL and not _is_valid_custom_url(
                custom_url
            ):
                errors[CONF_CUSTOM_TILE_URL] = "invalid_custom_url"
            elif cache_mb < MIN_TILE_CACHE_SIZE_MB:
                errors[CONF_TILE_CACHE_SIZE_MB] = "cache_size_too_small"
            else:
                return self.async_create_entry(
                    title="RainRadarHub",
                    data={
                        "entry_type": ENTRY_TYPE_HUB,
                        CONF_TILE_PROVIDER: provider,
                        CONF_CUSTOM_TILE_URL: custom_url,
                        CONF_TILE_CACHE_SIZE_MB: cache_mb,
                    },
                )

        return self.async_show_form(
            step_id="hub",
            data_schema=_SCHEMA_HUB,
            errors=errors,
        )

    async def async_step_region_name(self, user_input=None):
        """Region step 1: name → region_id."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_REGION_NAME].strip()
            region_id = _to_region_id(name)

            existing = [
                e
                for e in self.hass.config_entries.async_entries(DOMAIN)
                if e.data.get("entry_type") == ENTRY_TYPE_REGION
                and e.data.get("region_id") == region_id
            ]
            if existing:
                errors[CONF_REGION_NAME] = "region_already_exists"
            else:
                self._region_data[CONF_REGION_NAME] = name
                self._region_data["region_id"] = region_id
                return await self.async_step_region_location()

        return self.async_show_form(
            step_id="region_name",
            data_schema=_SCHEMA_REGION_NAME,
            errors=errors,
        )

    async def async_step_region_location(self, user_input=None):
        """Region step 2: lat/lon + DWD grid validation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            lat = user_input[CONF_LATITUDE]
            lon = user_input[CONF_LONGITUDE]

            if not _is_within_dwd_grid(lat, lon):
                errors["base"] = "outside_dwd_grid"
            else:
                self._region_data[CONF_LATITUDE] = lat
                self._region_data[CONF_LONGITUDE] = lon
                return await self.async_step_region_map()

        return self.async_show_form(
            step_id="region_location",
            data_schema=_SCHEMA_REGION_LOCATION,
            errors=errors,
        )

    async def async_step_region_map(self, user_input=None):
        """Region step 3: radius + zoom."""
        errors: dict[str, str] = {}

        if user_input is not None:
            radius = user_input[CONF_RADIUS_KM]
            zoom = user_input[CONF_DEFAULT_ZOOM]

            if not MIN_RADIUS_KM <= radius <= MAX_RADIUS_KM:
                errors[CONF_RADIUS_KM] = "radius_out_of_range"
            elif not MIN_ZOOM <= zoom <= MAX_ZOOM:
                errors[CONF_DEFAULT_ZOOM] = "zoom_out_of_range"
            else:
                return self.async_create_entry(
                    title=f"Region: {self._region_data[CONF_REGION_NAME]}",
                    data={
                        "entry_type": ENTRY_TYPE_REGION,
                        "region_id": self._region_data["region_id"],
                        CONF_REGION_NAME: self._region_data[CONF_REGION_NAME],
                        CONF_LATITUDE: self._region_data[CONF_LATITUDE],
                        CONF_LONGITUDE: self._region_data[CONF_LONGITUDE],
                        CONF_RADIUS_KM: radius,
                        CONF_DEFAULT_ZOOM: zoom,
                    },
                )

        return self.async_show_form(
            step_id="region_map",
            data_schema=_SCHEMA_REGION_MAP,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow for Hub entries."""
        return RainRadarHubOptionsFlow(config_entry)


class RainRadarHubOptionsFlow(OptionsFlow):
    """Options flow — only for Hub entry (cache size)."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Tile cache size adjustment."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cache_mb = user_input.get(CONF_TILE_CACHE_SIZE_MB, 0)
            if cache_mb < MIN_TILE_CACHE_SIZE_MB:
                errors[CONF_TILE_CACHE_SIZE_MB] = "cache_size_too_small"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_TILE_CACHE_SIZE_MB: cache_mb},
                )

        current = self._config_entry.options.get(
            CONF_TILE_CACHE_SIZE_MB,
            self._config_entry.data.get(
                CONF_TILE_CACHE_SIZE_MB, DEFAULT_TILE_CACHE_SIZE_MB
            ),
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_TILE_CACHE_SIZE_MB, default=current): vol.Coerce(int),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
