"""Config flow for RainRadarHub."""
from __future__ import annotations

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import DOMAIN, ENTRY_TYPE_HUB, ENTRY_TYPE_REGION


class RainRadarHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for RainRadarHub."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Entry point — route to Hub or Region setup."""
        # TODO: implement Hub/Region routing
        raise NotImplementedError

    async def async_step_hub(self, user_input=None):
        """Hub setup: tile provider + cache size."""
        # TODO: implement
        raise NotImplementedError

    async def async_step_region_name(self, user_input=None):
        """Region setup step 1: name → region_id."""
        # TODO: implement
        raise NotImplementedError

    async def async_step_region_location(self, user_input=None):
        """Region setup step 2: lat/lon + DWD grid validation."""
        # TODO: implement
        raise NotImplementedError

    async def async_step_region_map(self, user_input=None):
        """Region setup step 3: radius + zoom."""
        # TODO: implement
        raise NotImplementedError

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
        # TODO: implement
        raise NotImplementedError
