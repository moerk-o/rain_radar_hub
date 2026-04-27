"""RainRadarHub — DWD rain radar integration for Home Assistant."""
from __future__ import annotations

import logging
import shutil

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CUSTOM_TILE_URL,
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
)
from .coordinator import FrameUpdateCoordinator
from .http import ColorbarView, FrameView, ManifestView, TileView
from .storage import get_frames_dir, get_storage_root, get_tile_cache_db
from .tile_proxy import TileProxy

_LOGGER = logging.getLogger(__name__)

_KEY_VIEWS_REGISTERED = "views_registered"

_REGION_CONF_KEYS = (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_DEFAULT_ZOOM,
    CONF_REGION_NAME,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RainRadarHub from a config entry."""
    hass.data.setdefault(
        DOMAIN,
        {DATA_TILE_PROXY: None, DATA_COORDINATORS: {}, _KEY_VIEWS_REGISTERED: False},
    )

    entry_type = entry.data.get("entry_type")

    if entry_type == ENTRY_TYPE_HUB:
        return await _async_setup_hub(hass, entry)
    if entry_type == ENTRY_TYPE_REGION:
        return await _async_setup_region(hass, entry)

    _LOGGER.error("RainRadarHub: unknown entry type '%s'", entry_type)
    return False


async def _async_setup_hub(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    provider = entry.data[CONF_TILE_PROVIDER]
    raw_custom = entry.data.get(CONF_CUSTOM_TILE_URL, "")
    custom_url = raw_custom if raw_custom else None
    cache_mb = entry.options.get(
        CONF_TILE_CACHE_SIZE_MB,
        entry.data.get(CONF_TILE_CACHE_SIZE_MB, DEFAULT_TILE_CACHE_SIZE_MB),
    )

    config_dir = hass.config.config_dir
    tile_dir = get_storage_root(config_dir) / "tile_cache"
    db_path = get_tile_cache_db(config_dir)

    proxy = TileProxy(
        hass=hass,
        provider_key=provider,
        tile_dir=tile_dir,
        db_path=db_path,
        max_size_bytes=cache_mb * 1_048_576,
        custom_url=custom_url,
    )
    await proxy.async_setup()
    hass.data[DOMAIN][DATA_TILE_PROXY] = proxy

    # Register HTTP views only once (they reference hass, so no re-registration needed)
    if not hass.data[DOMAIN].get(_KEY_VIEWS_REGISTERED):
        hass.http.register_view(TileView(hass))
        hass.http.register_view(ManifestView(hass))
        hass.http.register_view(FrameView(hass))
        hass.http.register_view(ColorbarView(hass))
        hass.data[DOMAIN][_KEY_VIEWS_REGISTERED] = True

    entry.async_on_unload(entry.add_update_listener(_async_hub_options_updated))
    return True


async def _async_hub_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the hub entry when its options (cache size) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_setup_region(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    region_id = entry.data["region_id"]
    region_config = {k: entry.data[k] for k in _REGION_CONF_KEYS if k in entry.data}

    coord = FrameUpdateCoordinator(hass, region_id, region_config)
    await coord.async_config_entry_first_refresh()
    hass.data[DOMAIN][DATA_COORDINATORS][region_id] = coord
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_type = entry.data.get("entry_type")

    if entry_type == ENTRY_TYPE_HUB:
        proxy = hass.data[DOMAIN].get(DATA_TILE_PROXY)
        if proxy:
            await proxy.async_close()
            hass.data[DOMAIN][DATA_TILE_PROXY] = None
        return True

    if entry_type == ENTRY_TYPE_REGION:
        region_id = entry.data.get("region_id")
        if region_id:
            hass.data[DOMAIN][DATA_COORDINATORS].pop(region_id, None)
        return True

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a config entry and clean up persisted resources."""
    entry_type = entry.data.get("entry_type")

    if entry_type == ENTRY_TYPE_HUB:
        # Remove tile cache DB and files
        db_path = get_tile_cache_db(hass.config.config_dir)
        if db_path.exists():
            db_path.unlink(missing_ok=True)
        tile_dir = get_storage_root(hass.config.config_dir) / "tile_cache"
        if tile_dir.exists():
            shutil.rmtree(tile_dir, ignore_errors=True)

    elif entry_type == ENTRY_TYPE_REGION:
        region_id = entry.data.get("region_id")
        if region_id:
            frames_dir = get_frames_dir(hass.config.config_dir, region_id)
            if frames_dir.exists():
                shutil.rmtree(frames_dir, ignore_errors=True)
