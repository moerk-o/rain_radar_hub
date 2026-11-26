"""Tests for tile_proxy.py."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.rain_radar_hub.const import (
    TILE_PROVIDER_CARTO_VOYAGER,
    TILE_PROVIDER_OSM_STANDARD,
)
from custom_components.rain_radar_hub.tile_proxy import (
    TILE_EXPIRY_DAYS,
    TileProxy,
)

# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

FAKE_TILE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG bytes
_SET_ACCESSED_AT = (
    "UPDATE tiles SET accessed_at=? WHERE provider=? AND z=? AND x=? AND y=?"
)


def _tile_path(tmp_path: Path, z: int, x: int, y: int) -> Path:
    """Path where the proxy fixture stores a CARTO Voyager tile."""
    provider_dir = tmp_path / "tiles" / TILE_PROVIDER_CARTO_VOYAGER
    return provider_dir / str(z) / str(x) / f"{y}.png"


@pytest.fixture
async def proxy(tmp_path):
    """A fully set-up TileProxy backed by a real SQLite DB in tmp_path."""
    tile_dir = tmp_path / "tiles"
    db_path = tmp_path / "tile_cache.db"
    p = TileProxy(
        hass=MagicMock(),
        provider_key=TILE_PROVIDER_CARTO_VOYAGER,
        tile_dir=tile_dir,
        db_path=db_path,
        max_size_bytes=10 * 1024 * 1024,  # 10 MB
    )
    await p.async_setup()
    yield p
    await p.async_close()


def _mock_session(data: bytes = FAKE_TILE, status: int = 200):
    """Build a mock aiohttp.ClientSession that returns *data* on GET."""
    resp = AsyncMock()
    resp.status = status
    resp.read = AsyncMock(return_value=data)
    resp.raise_for_status = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


# ────────────────────────────────────────────────────────────────────────────
# async_setup
# ────────────────────────────────────────────────────────────────────────────

class TestAsyncSetup:

    async def test_creates_tile_dir(self, tmp_path):
        tile_dir = tmp_path / "tiles"
        p = TileProxy(MagicMock(), TILE_PROVIDER_OSM_STANDARD, tile_dir,
                      tmp_path / "db.sqlite", 1024)
        await p.async_setup()
        await p.async_close()
        assert tile_dir.exists()

    async def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "sub" / "cache.db"
        p = TileProxy(MagicMock(), TILE_PROVIDER_OSM_STANDARD,
                      tmp_path / "tiles", db_path, 1024)
        await p.async_setup()
        await p.async_close()
        assert db_path.exists()

    async def test_idempotent_second_setup(self, tmp_path):
        """Calling async_setup twice must not raise (IF NOT EXISTS in schema)."""
        p = TileProxy(MagicMock(), TILE_PROVIDER_CARTO_VOYAGER,
                      tmp_path / "t", tmp_path / "d.db", 1024)
        await p.async_setup()
        await p.async_close()
        # Second setup on same DB
        await p.async_setup()
        await p.async_close()


# ────────────────────────────────────────────────────────────────────────────
# get_tile — cache miss
# ────────────────────────────────────────────────────────────────────────────

class TestGetTileCacheMiss:

    async def test_fetches_upstream_on_miss(self, proxy):
        session = _mock_session()
        data = await proxy.get_tile(session, z=10, x=544, y=340)
        assert data == FAKE_TILE
        session.get.assert_called_once()

    async def test_returns_upstream_data(self, proxy):
        custom_data = b"custom_tile_bytes"
        session = _mock_session(data=custom_data)
        data = await proxy.get_tile(session, z=9, x=272, y=170)
        assert data == custom_data

    async def test_stores_tile_file_on_miss(self, proxy, tmp_path):
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=2)
        expected = _tile_path(tmp_path, 10, 1, 2)
        assert expected.exists()
        assert expected.read_bytes() == FAKE_TILE

    async def test_stores_db_row_on_miss(self, proxy):
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=2)
        # _db_get only returns filepath/created_at; query size_bytes directly
        async with proxy._db.execute(
            "SELECT size_bytes FROM tiles WHERE provider=? AND z=? AND x=? AND y=?",
            (proxy._provider_key, 10, 1, 2),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == len(FAKE_TILE)


# ────────────────────────────────────────────────────────────────────────────
# get_tile — cache hit
# ────────────────────────────────────────────────────────────────────────────

class TestGetTileCacheHit:

    async def test_returns_cached_data_on_hit(self, proxy):
        session = _mock_session()
        # Prime the cache
        await proxy.get_tile(session, z=10, x=1, y=2)
        session.get.reset_mock()

        # Second call — should not hit upstream
        data = await proxy.get_tile(session, z=10, x=1, y=2)
        assert data == FAKE_TILE
        session.get.assert_not_called()

    async def test_updates_accessed_at_on_hit(self, proxy):
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=2)
        stale = time.time() - 1000
        await proxy._db.execute(
            _SET_ACCESSED_AT, (stale, proxy._provider_key, 10, 1, 2)
        )
        await proxy._db.commit()

        await proxy.get_tile(session, z=10, x=1, y=2)

        async with proxy._db.execute(
            "SELECT accessed_at FROM tiles WHERE provider=? AND z=? AND x=? AND y=?",
            (proxy._provider_key, 10, 1, 2),
        ) as cur:
            (accessed_at,) = await cur.fetchone()
        assert accessed_at > stale

    async def test_refetches_if_file_deleted(self, proxy, tmp_path):
        """If cached file is missing from disk, proxy must re-fetch."""
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=2)
        # Delete the file
        _tile_path(tmp_path, 10, 1, 2).unlink()
        session.get.reset_mock()

        data = await proxy.get_tile(session, z=10, x=1, y=2)
        assert data == FAKE_TILE
        session.get.assert_called_once()

    async def test_refetches_stale_tile(self, proxy):
        """Tiles older than TILE_EXPIRY_DAYS are re-fetched."""
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=2)

        # Force the created_at into the past
        old_ts = time.time() - (TILE_EXPIRY_DAYS + 1) * 86_400
        await proxy._db.execute(
            "UPDATE tiles SET created_at=? WHERE provider=? AND z=? AND x=? AND y=?",
            (old_ts, proxy._provider_key, 10, 1, 2),
        )
        await proxy._db.commit()
        session.get.reset_mock()

        await proxy.get_tile(session, z=10, x=1, y=2)
        session.get.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# LRU eviction
# ────────────────────────────────────────────────────────────────────────────

class TestEviction:

    async def _proxy_tiny(self, tmp_path, max_bytes: int) -> TileProxy:
        """TileProxy with a very small cache limit."""
        p = TileProxy(
            hass=MagicMock(),
            provider_key=TILE_PROVIDER_CARTO_VOYAGER,
            tile_dir=tmp_path / "tiles",
            db_path=tmp_path / "cache.db",
            max_size_bytes=max_bytes,
        )
        await p.async_setup()
        return p

    async def test_no_eviction_under_limit(self, tmp_path):
        tile_size = len(FAKE_TILE)
        proxy = await self._proxy_tiny(tmp_path, tile_size * 10)

        for i in range(3):
            await proxy._store(10, i, 0, FAKE_TILE)

        await proxy._evict_if_needed()

        async with proxy._db.execute(
            "SELECT COUNT(*) FROM tiles WHERE provider=?", (proxy._provider_key,)
        ) as cur:
            count = (await cur.fetchone())[0]

        assert count == 3
        await proxy.async_close()

    async def test_evicts_lru_when_over_limit(self, tmp_path):
        tile_size = len(FAKE_TILE)
        # Allow only 2 tiles
        proxy = await self._proxy_tiny(tmp_path, tile_size * 2)

        # Store 3 tiles with increasing accessed_at
        for i in range(3):
            await proxy._store(10, i, 0, FAKE_TILE)
            # Manually set accessed_at so tile 0 is oldest
            await proxy._db.execute(
                _SET_ACCESSED_AT,
                (time.time() - (3 - i) * 1000, proxy._provider_key, 10, i, 0),
            )
        await proxy._db.commit()

        await proxy._evict_if_needed()

        # Tile 0 (oldest) should be gone
        row = await proxy._db_get(10, 0, 0)
        assert row is None

        # Tiles 1 and 2 should still exist
        assert await proxy._db_get(10, 1, 0) is not None
        assert await proxy._db_get(10, 2, 0) is not None
        await proxy.async_close()

    async def test_evicted_file_deleted(self, tmp_path):
        tile_size = len(FAKE_TILE)
        proxy = await self._proxy_tiny(tmp_path, tile_size)

        # Store first tile (oldest)
        await proxy._store(10, 0, 0, FAKE_TILE)
        await proxy._db.execute(
            _SET_ACCESSED_AT,
            (time.time() - 2000, proxy._provider_key, 10, 0, 0),
        )
        await proxy._db.commit()

        # Store second tile — triggers eviction of the first
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=0)

        old_file = _tile_path(tmp_path, 10, 0, 0)
        assert not old_file.exists()
        await proxy.async_close()


# ────────────────────────────────────────────────────────────────────────────
# wipe_cache
# ────────────────────────────────────────────────────────────────────────────

class TestWipeCache:

    async def test_wipe_removes_all_db_rows(self, proxy):
        session = _mock_session()
        for i in range(3):
            await proxy.get_tile(session, z=10, x=i, y=0)

        await proxy.wipe_cache()

        async with proxy._db.execute(
            "SELECT COUNT(*) FROM tiles WHERE provider=?", (proxy._provider_key,)
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count == 0

    async def test_wipe_removes_tile_files(self, proxy, tmp_path):
        session = _mock_session()
        await proxy.get_tile(session, z=10, x=1, y=2)

        await proxy.wipe_cache()

        provider_dir = tmp_path / "tiles" / TILE_PROVIDER_CARTO_VOYAGER
        assert not provider_dir.exists()

    async def test_wipe_idempotent_on_empty_cache(self, proxy):
        await proxy.wipe_cache()  # Should not raise


# ────────────────────────────────────────────────────────────────────────────
# clear_provider
# ────────────────────────────────────────────────────────────────────────────

class TestClearProvider:

    async def test_clears_only_target_provider(self, tmp_path):
        """clear_provider removes tiles for the given provider, not others."""
        p1 = TileProxy(MagicMock(), TILE_PROVIDER_CARTO_VOYAGER,
                       tmp_path / "tiles", tmp_path / "cache.db", 10 * 1024 * 1024)
        await p1.async_setup()
        # Manually insert tiles for a second "provider"
        other = TILE_PROVIDER_OSM_STANDARD
        other_path = tmp_path / "tiles" / other / "10" / "0" / "0.png"
        other_path.parent.mkdir(parents=True)
        other_path.write_bytes(FAKE_TILE)
        now = time.time()
        await p1._db.execute(
            """INSERT INTO tiles
               (provider,z,x,y,filepath,size_bytes,accessed_at,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (other, 10, 0, 0, str(other_path), len(FAKE_TILE), now, now),
        )
        await p1._db.commit()

        # Prime main provider cache
        session = _mock_session()
        await p1.get_tile(session, z=10, x=1, y=0)

        # Clear only the other provider
        await p1.clear_provider(other)

        async with p1._db.execute(
            "SELECT COUNT(*) FROM tiles WHERE provider=?", (other,)
        ) as cur:
            other_count = (await cur.fetchone())[0]
        async with p1._db.execute(
            "SELECT COUNT(*) FROM tiles WHERE provider=?",
            (TILE_PROVIDER_CARTO_VOYAGER,),
        ) as cur:
            main_count = (await cur.fetchone())[0]

        assert other_count == 0
        assert main_count == 1
        assert not other_path.exists()
        await p1.async_close()


# ────────────────────────────────────────────────────────────────────────────
# URL building
# ────────────────────────────────────────────────────────────────────────────

class TestUrlBuilding:

    def test_carto_url_contains_zxy(self, tmp_path):
        p = TileProxy(MagicMock(), TILE_PROVIDER_CARTO_VOYAGER,
                      tmp_path, tmp_path / "db", 1024)
        url = p._build_url(z=10, x=544, y=340)
        assert "10" in url
        assert "544" in url
        assert "340" in url

    def test_osm_url_no_subdomain(self, tmp_path):
        p = TileProxy(MagicMock(), TILE_PROVIDER_OSM_STANDARD,
                      tmp_path, tmp_path / "db", 1024)
        url = p._build_url(z=5, x=17, y=11)
        assert "tile.openstreetmap.org" in url
        assert "5/17/11" in url

    def test_carto_url_has_subdomain(self, tmp_path):
        p = TileProxy(MagicMock(), TILE_PROVIDER_CARTO_VOYAGER,
                      tmp_path, tmp_path / "db", 1024)
        url = p._build_url(z=5, x=17, y=11)
        # CARTO uses {s} subdomain — one of a/b/c/d should appear before the dot
        assert any(f"{s}." in url for s in ["a", "b", "c", "d"])

    def test_custom_url_template(self, tmp_path):
        custom = "https://example.com/tiles/{z}/{x}/{y}.png"
        p = TileProxy(MagicMock(), "custom", tmp_path, tmp_path / "db", 1024,
                      custom_url=custom)
        url = p._build_url(z=8, x=100, y=200)
        assert url == "https://example.com/tiles/8/100/200.png"


# ────────────────────────────────────────────────────────────────────────────
# _is_stale
# ────────────────────────────────────────────────────────────────────────────

class TestIsStale:

    def test_fresh_tile_not_stale(self):
        assert not TileProxy._is_stale(time.time())

    def test_tile_just_under_expiry_not_stale(self):
        created = time.time() - (TILE_EXPIRY_DAYS - 1) * 86_400
        assert not TileProxy._is_stale(created)

    def test_tile_over_expiry_is_stale(self):
        created = time.time() - (TILE_EXPIRY_DAYS + 1) * 86_400
        assert TileProxy._is_stale(created)

    def test_tile_exactly_at_expiry_is_stale(self):
        created = time.time() - TILE_EXPIRY_DAYS * 86_400 - 1
        assert TileProxy._is_stale(created)
