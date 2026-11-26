"""Tile proxy with SQLite-backed LRU cache.

Design
------
- One TileProxy instance per HA instance (Hub singleton).
- Tiles are stored as PNG files under: {tile_dir}/{provider}/{z}/{x}/{y}.png
- A SQLite DB tracks (provider, z, x, y, filepath, size_bytes, accessed_at, created_at).
- LRU eviction: when total size exceeds max_size_bytes, delete the
  least-recently-accessed tiles until the cache is below the limit.
- Upstream concurrency is limited to MAX_UPSTREAM_REQUESTS simultaneous fetches.
- Tiles older than TILE_EXPIRY_DAYS are treated as stale and re-fetched.
"""
from __future__ import annotations

import asyncio
import logging
import random
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from .const import (
    TILE_PROVIDER_SUBDOMAINS,
    TILE_PROVIDERS,
    USER_AGENT,
)

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MAX_UPSTREAM_REQUESTS = 2
TILE_EXPIRY_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tiles (
    provider    TEXT    NOT NULL,
    z           INTEGER NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    filepath    TEXT    NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    accessed_at REAL    NOT NULL,
    created_at  REAL    NOT NULL,
    PRIMARY KEY (provider, z, x, y)
);
CREATE INDEX IF NOT EXISTS idx_tiles_accessed ON tiles (provider, accessed_at);
"""


class TileProxy:
    """Fetches and caches basemap tiles with SQLite-tracked LRU eviction."""

    def __init__(
        self,
        hass: HomeAssistant,
        provider_key: str,
        tile_dir: Path,
        db_path: Path,
        max_size_bytes: int,
        custom_url: str | None = None,
    ) -> None:
        self._hass = hass
        self._provider_key = provider_key
        self._tile_dir = tile_dir
        self._db_path = db_path
        self._max_size_bytes = max_size_bytes
        self._db: aiosqlite.Connection | None = None
        self._semaphore = asyncio.Semaphore(MAX_UPSTREAM_REQUESTS)

        # Resolve the URL template and subdomains for this provider
        if custom_url:
            self._url_template = custom_url
            self._subdomains: list[str] = []
        else:
            self._url_template = TILE_PROVIDERS.get(provider_key, "")
            self._subdomains = TILE_PROVIDER_SUBDOMAINS.get(provider_key, [])

    # ────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Open the SQLite database and create the schema if needed."""
        self._tile_dir.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        _LOGGER.debug(
            "TileProxy ready (provider=%s, max=%d MB)",
            self._provider_key,
            self._max_size_bytes // 1_048_576,
        )

    async def async_close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ────────────────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────────────────

    async def get_tile(
        self, session: aiohttp.ClientSession, z: int, x: int, y: int
    ) -> bytes:
        """Return PNG bytes for tile (z, x, y).

        Returns the cached version if available and not stale.
        Otherwise fetches from upstream, stores and evicts if needed.
        """
        assert self._db is not None, "Call async_setup() first."

        row = await self._db_get(z, x, y)
        if row and not self._is_stale(row["created_at"]):
            path = Path(row["filepath"])
            if path.exists():
                await self._db_touch(z, x, y)
                return path.read_bytes()
            # File missing (deleted externally) — remove stale DB row, re-fetch
            await self._db_delete_one(z, x, y)

        # Upstream fetch — limited by semaphore
        async with self._semaphore:
            data = await self._fetch_upstream(session, z, x, y)

        await self._store(z, x, y, data)
        await self._evict_if_needed()
        return data

    async def wipe_cache(self) -> None:
        """Delete ALL cached tiles for this provider (DB rows + files)."""
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM tiles WHERE provider = ?", (self._provider_key,)
        )
        await self._db.commit()
        provider_dir = self._tile_dir / self._provider_key
        if provider_dir.exists():
            shutil.rmtree(provider_dir, ignore_errors=True)
        _LOGGER.info("Tile cache wiped for provider %s", self._provider_key)

    async def clear_provider(self, provider_key: str) -> None:
        """Delete all cached tiles for *provider_key*.

        Used when switching providers.
        """
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM tiles WHERE provider = ?", (provider_key,)
        )
        await self._db.commit()
        provider_dir = self._tile_dir / provider_key
        if provider_dir.exists():
            shutil.rmtree(provider_dir, ignore_errors=True)

    # ────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_stale(created_at: float) -> bool:
        return (time.time() - created_at) > TILE_EXPIRY_DAYS * 86_400

    def _tile_path(self, z: int, x: int, y: int) -> Path:
        return self._tile_dir / self._provider_key / str(z) / str(x) / f"{y}.png"

    def _build_url(self, z: int, x: int, y: int) -> str:
        s = random.choice(self._subdomains) if self._subdomains else ""
        return self._url_template.format(z=z, x=x, y=y, s=s)

    async def _fetch_upstream(
        self, session: aiohttp.ClientSession, z: int, x: int, y: int
    ) -> bytes:
        url = self._build_url(z, x, y)
        headers = {"User-Agent": USER_AGENT}
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.read()
        _LOGGER.debug("Fetched upstream tile z=%d x=%d y=%d (%d B)", z, x, y, len(data))
        return data

    async def _store(self, z: int, x: int, y: int, data: bytes) -> None:
        path = self._tile_path(z, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        now = time.time()
        await self._db.execute(
            """INSERT OR REPLACE INTO tiles
               (provider, z, x, y, filepath, size_bytes, accessed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (self._provider_key, z, x, y, str(path), len(data), now, now),
        )
        await self._db.commit()

    async def _evict_if_needed(self) -> None:
        """Remove LRU tiles until total cache size is below max_size_bytes."""
        async with self._db.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM tiles WHERE provider = ?",
            (self._provider_key,),
        ) as cur:
            row = await cur.fetchone()
        total: int = row[0]

        if total <= self._max_size_bytes:
            return

        _LOGGER.debug(
            "Cache %.1f MB > limit %.1f MB — evicting LRU tiles",
            total / 1_048_576,
            self._max_size_bytes / 1_048_576,
        )

        while total > self._max_size_bytes:
            async with self._db.execute(
                """SELECT filepath, size_bytes FROM tiles
                   WHERE provider = ? ORDER BY accessed_at ASC LIMIT 20""",
                (self._provider_key,),
            ) as cur:
                rows = await cur.fetchall()

            if not rows:
                break

            for row in rows:
                fp, size = row["filepath"], row["size_bytes"]
                try:
                    Path(fp).unlink(missing_ok=True)
                except OSError as exc:
                    _LOGGER.warning("Could not delete tile file %s: %s", fp, exc)
                await self._db.execute(
                    "DELETE FROM tiles WHERE provider = ? AND filepath = ?",
                    (self._provider_key, fp),
                )
                total -= size
                if total <= self._max_size_bytes:
                    break

        await self._db.commit()

    # ── SQLite micro-helpers ─────────────────────────────────────────────────

    async def _db_get(self, z: int, x: int, y: int) -> aiosqlite.Row | None:
        async with self._db.execute(
            """SELECT filepath, created_at FROM tiles
               WHERE provider=? AND z=? AND x=? AND y=?""",
            (self._provider_key, z, x, y),
        ) as cur:
            return await cur.fetchone()

    async def _db_touch(self, z: int, x: int, y: int) -> None:
        await self._db.execute(
            """UPDATE tiles SET accessed_at=?
               WHERE provider=? AND z=? AND x=? AND y=?""",
            (time.time(), self._provider_key, z, x, y),
        )
        await self._db.commit()

    async def _db_delete_one(self, z: int, x: int, y: int) -> None:
        await self._db.execute(
            "DELETE FROM tiles WHERE provider=? AND z=? AND x=? AND y=?",
            (self._provider_key, z, x, y),
        )
        await self._db.commit()
