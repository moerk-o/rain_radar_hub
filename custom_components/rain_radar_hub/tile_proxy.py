"""Tile proxy with SQLite-backed LRU cache."""
from __future__ import annotations


class TileProxy:
    """Fetches and caches basemap tiles with LRU eviction."""

    def __init__(self, hass, provider_key: str, cache_dir: str, db_path: str, max_size_bytes: int) -> None:
        self.hass = hass
        self.provider_key = provider_key
        self.cache_dir = cache_dir
        self.db_path = db_path
        self.max_size_bytes = max_size_bytes
        # TODO: init asyncio.Semaphore(2), open/create SQLite DB

    async def async_setup(self) -> None:
        """Initialize DB schema and semaphore."""
        # TODO: implement
        raise NotImplementedError

    async def get_tile(self, z: int, x: int, y: int) -> bytes:
        """Return PNG bytes for tile z/x/y, fetching from upstream if needed."""
        # TODO: implement cache lookup → upstream fetch → eviction
        raise NotImplementedError

    async def wipe_cache(self) -> None:
        """Delete all cached tiles and reset the DB."""
        # TODO: implement
        raise NotImplementedError

    async def clear_provider(self, provider_key: str) -> None:
        """Delete cached tiles for a specific provider only."""
        # TODO: implement
        raise NotImplementedError
