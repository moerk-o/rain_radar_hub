"""Tests for frame_pipeline.py."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pyproj
import pytest
from PIL import Image

from custom_components.rain_radar_hub.const import (
    DWD_GRID_COLS,
    DWD_GRID_PROJDEF,
    DWD_GRID_ROWS,
    DWD_GRID_STEP_M,
    RAIN_PALETTE,
    USER_AGENT,
)
from custom_components.rain_radar_hub.frame_pipeline import (
    _apply_palette,
    _bilinear_interpolate,
    _download,
    _list_dwd_directory,
    _parse_ry_filename,
    _ts_from_filename,
    cleanup_old_frames,
    fetch_radar_frames,
    generate_colorbar,
    reproject_to_png,
    ts_to_filename,
)
from custom_components.rain_radar_hub.radolan_decoder import RadarComposite

# Realistic test regions (WGS84 bounding boxes)
HAMBURG_BOUNDS = ((53.3, 9.6), (53.8, 10.4))
MUNICH_BOUNDS = ((47.9, 11.3), (48.4, 11.9))

# Tiny grid for fast tests (avoids allocating 900×1100 arrays where possible)
TINY = (4, 5)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _flat_grid(rows: int, cols: int, value: float) -> np.ndarray:
    """Return a uniform float32 grid."""
    return np.full((rows, cols), value, dtype=np.float32)


def _composite(values: np.ndarray | float) -> RadarComposite:
    """Composite on the DWD grid; a scalar fills the whole grid (mm/h)."""
    if np.isscalar(values):
        values = np.full((DWD_GRID_ROWS, DWD_GRID_COLS), values, np.float32)
    return RadarComposite(
        values=values.astype(np.float32),
        projdef=DWD_GRID_PROJDEF,
        x_ul=0.0,
        y_ul=0.0,
        xscale=DWD_GRID_STEP_M,
        yscale=DWD_GRID_STEP_M,
        timestamp=datetime(2026, 11, 26, 8, 10, tzinfo=UTC),
    )


def _png_size(png_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) of PNG bytes."""
    img = Image.open(BytesIO(png_bytes))
    return img.size  # (width, height)


def _png_mode(png_bytes: bytes) -> str:
    img = Image.open(BytesIO(png_bytes))
    return img.mode


def _png_array(png_bytes: bytes) -> np.ndarray:
    img = Image.open(BytesIO(png_bytes))
    return np.array(img)


# ────────────────────────────────────────────────────────────────────────────
# _apply_palette
# ────────────────────────────────────────────────────────────────────────────

class TestApplyPalette:

    def test_output_shape(self):
        v = _flat_grid(3, 4, 1.0)
        out = _apply_palette(v)
        assert out.shape == (3, 4, 4)

    def test_output_dtype(self):
        v = _flat_grid(2, 2, 1.0)
        assert _apply_palette(v).dtype == np.uint8

    def test_zero_rain_is_transparent(self):
        v = _flat_grid(1, 1, 0.0)
        rgba = _apply_palette(v)
        assert rgba[0, 0, 3] == 0  # alpha = 0

    def test_below_threshold_is_transparent(self):
        v = _flat_grid(1, 1, 0.05)
        rgba = _apply_palette(v)
        assert rgba[0, 0, 3] == 0

    def test_nan_is_transparent(self):
        v = np.array([[np.nan]], dtype=np.float32)
        rgba = _apply_palette(v)
        assert rgba[0, 0, 3] == 0

    def test_each_palette_band_correct_color(self):
        """Every palette band maps to the declared RGBA color."""
        for min_mmh, max_mmh, expected_color in RAIN_PALETTE:
            if expected_color[3] == 0:
                continue  # skip transparent band
            # Use midpoint of band as test value
            mid = min_mmh + 0.1 if max_mmh is None else (min_mmh + max_mmh) / 2
            v = np.array([[mid]], dtype=np.float32)
            rgba = _apply_palette(v)
            assert tuple(rgba[0, 0]) == expected_color, (
                f"Band [{min_mmh}, {max_mmh}) → expected {expected_color}, "
                f"got {tuple(rgba[0, 0])}"
            )

    def test_max_rain_magenta(self):
        """Values above 40 mm/h → magenta (last palette entry)."""
        v = np.array([[100.0]], dtype=np.float32)
        rgba = _apply_palette(v)
        assert rgba[0, 0, 3] > 0  # not transparent
        assert tuple(rgba[0, 0]) == (180, 30, 180, 255)

    def test_mixed_values(self):
        """Grid with multiple bands → each pixel correct."""
        v = np.array([[0.0, 5.5], [25.0, np.nan]], dtype=np.float32)
        rgba = _apply_palette(v)
        assert rgba[0, 0, 3] == 0    # 0.0 → transparent
        assert rgba[0, 1, 3] > 0     # 5.5 mm/h → yellow
        assert rgba[1, 0, 3] > 0     # 25.0 mm/h → red
        assert rgba[1, 1, 3] == 0    # NaN → transparent


# ────────────────────────────────────────────────────────────────────────────
# _bilinear_interpolate
# ────────────────────────────────────────────────────────────────────────────

class TestBilinearInterpolate:

    def _grid(self) -> np.ndarray:
        """4×4 grid with known values for easy manual verification."""
        return np.array([
            [0.0, 1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0, 7.0],
            [8.0, 9.0, 10.0, 11.0],
            [12.0, 13.0, 14.0, 15.0],
        ], dtype=np.float32)

    def test_exact_integer_indices(self):
        g = self._grid()
        row = np.array([[0.0, 1.0]])
        col = np.array([[0.0, 2.0]])
        result = _bilinear_interpolate(g, row, col)
        np.testing.assert_allclose(result[0, 0], 0.0)
        np.testing.assert_allclose(result[0, 1], 6.0)

    def test_midpoint_interpolation(self):
        """Midpoint of a 2×2 unit cell → average of four corners."""
        g = self._grid()
        row = np.array([[0.5]])
        col = np.array([[0.5]])
        result = _bilinear_interpolate(g, row, col)
        # corners: 0, 1, 4, 5 → average = 2.5
        np.testing.assert_allclose(result[0, 0], 2.5)

    def test_horizontal_midpoint(self):
        """Middle of a horizontal edge → average of left and right."""
        g = self._grid()
        row = np.array([[0.0]])
        col = np.array([[0.5]])
        result = _bilinear_interpolate(g, row, col)
        np.testing.assert_allclose(result[0, 0], 0.5)

    def test_vertical_midpoint(self):
        g = self._grid()
        row = np.array([[0.5]])
        col = np.array([[0.0]])
        result = _bilinear_interpolate(g, row, col)
        np.testing.assert_allclose(result[0, 0], 2.0)

    def test_oob_negative_indices_nan(self):
        g = self._grid()
        row = np.array([[-0.5]])
        col = np.array([[0.0]])
        result = _bilinear_interpolate(g, row, col)
        assert np.isnan(result[0, 0])

    def test_oob_too_large_nan(self):
        g = self._grid()
        row = np.array([[3.5]])  # last valid row is 2 (need r1=3 ≤ rows-1=3)
        col = np.array([[3.5]])  # last valid col is 2 (need c1=3 ≤ cols-1=3)
        # r1=4 >= rows=4 → OOB
        result = _bilinear_interpolate(g, row, col)
        assert np.isnan(result[0, 0])

    def test_nan_corner_propagates_nan(self):
        g = self._grid()
        g[0, 1] = np.nan  # poison one corner
        row = np.array([[0.5]])
        col = np.array([[0.5]])
        result = _bilinear_interpolate(g, row, col)
        assert np.isnan(result[0, 0])

    def test_output_shape_matches_index_shape(self):
        g = self._grid()
        row = np.zeros((3, 5), dtype=np.float64)
        col = np.zeros((3, 5), dtype=np.float64)
        result = _bilinear_interpolate(g, row, col)
        assert result.shape == (3, 5)


# ────────────────────────────────────────────────────────────────────────────
# reproject_to_png  (integration — uses pyproj)
# ────────────────────────────────────────────────────────────────────────────

class TestReprojectToPng:
    """Integration tests for the full reprojection pipeline.

    These tests use a realistic grid region (Hamburg) but a small output
    size to keep them fast.
    """

    def test_returns_bytes(self):
        result = reproject_to_png(_composite(5.0), HAMBURG_BOUNDS, output_size=(32, 32))
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_output_is_valid_png(self):
        result = reproject_to_png(_composite(5.0), HAMBURG_BOUNDS, output_size=(32, 32))
        assert result[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes

    def test_output_size_matches_request(self):
        result = reproject_to_png(_composite(5.0), HAMBURG_BOUNDS, output_size=(64, 48))
        assert _png_size(result) == (64, 48)

    def test_output_mode_rgba(self):
        result = reproject_to_png(_composite(5.0), HAMBURG_BOUNDS, output_size=(32, 32))
        assert _png_mode(result) == "RGBA"

    def test_zero_rain_all_transparent(self):
        """All-zero rain grid → fully transparent overlay."""
        result = reproject_to_png(_composite(0.0), HAMBURG_BOUNDS, output_size=(32, 32))
        arr = _png_array(result)
        assert np.all(arr[:, :, 3] == 0)

    def test_heavy_rain_has_opaque_pixels(self):
        """Heavy rain (25 mm/h) in Germany → at least some opaque pixels."""
        result = reproject_to_png(
            _composite(25.0), HAMBURG_BOUNDS, output_size=(64, 64)
        )
        arr = _png_array(result)
        assert np.any(arr[:, :, 3] > 0)

    def test_all_nan_grid_is_transparent(self):
        result = reproject_to_png(
            _composite(np.nan), HAMBURG_BOUNDS, output_size=(32, 32)
        )
        arr = _png_array(result)
        assert np.all(arr[:, :, 3] == 0)

    def test_rain_appears_at_its_location(self):
        """Rain placed on Hamburg shows in the Hamburg frame, not in Munich's."""
        values = np.zeros((DWD_GRID_ROWS, DWD_GRID_COLS), np.float32)
        x, y = pyproj.Proj(DWD_GRID_PROJDEF)(10.0, 53.55)  # Hamburg
        row, col = round(-y / DWD_GRID_STEP_M), round(x / DWD_GRID_STEP_M)
        values[row - 10 : row + 10, col - 10 : col + 10] = 25.0
        composite = _composite(values)

        hamburg = _png_array(
            reproject_to_png(composite, HAMBURG_BOUNDS, output_size=(64, 64))
        )
        munich = _png_array(
            reproject_to_png(composite, MUNICH_BOUNDS, output_size=(64, 64))
        )

        assert hamburg[28:36, 28:36, 3].min() > 0  # centre: rain
        assert hamburg[:4, :4, 3].max() == 0  # corner: dry
        assert munich[:, :, 3].max() == 0

    def test_custom_output_size_default(self):
        """Default size (1024×1024) produces correct PNG dimensions."""
        result = reproject_to_png(_composite(0.0), HAMBURG_BOUNDS)
        assert _png_size(result) == (1024, 1024)


# ────────────────────────────────────────────────────────────────────────────
# generate_colorbar
# ────────────────────────────────────────────────────────────────────────────

class TestGenerateColorbar:

    def test_returns_bytes(self):
        assert isinstance(generate_colorbar(), bytes)

    def test_valid_png(self):
        result = generate_colorbar()
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_default_size(self):
        result = generate_colorbar()
        assert _png_size(result) == (40, 200)

    def test_custom_size(self):
        result = generate_colorbar(width=20, height=100)
        assert _png_size(result) == (20, 100)

    def test_mode_rgba(self):
        assert _png_mode(generate_colorbar()) == "RGBA"

    def test_not_all_transparent(self):
        arr = _png_array(generate_colorbar())
        assert np.any(arr[:, :, 3] > 0)

    def test_contains_palette_colors(self):
        """At least one non-transparent palette color appears in the image."""
        arr = _png_array(generate_colorbar(width=1, height=200))
        colored = [c for _, _, c in RAIN_PALETTE if c[3] > 0]
        found_any = any(
            np.any(np.all(arr[:, 0] == list(color), axis=-1))
            for color in colored
        )
        assert found_any


# ────────────────────────────────────────────────────────────────────────────
# cleanup_old_frames
# ────────────────────────────────────────────────────────────────────────────

class TestCleanupOldFrames:

    def _write_frame(self, directory: Path, ts: datetime) -> Path:
        path = directory / f"{ts_to_filename(ts)}.png"
        path.write_bytes(b"fake")
        return path

    def test_nonexistent_dir_returns_zero(self, tmp_path):
        assert cleanup_old_frames(tmp_path / "nope", max_age_hours=3) == 0

    def test_deletes_old_frames(self, tmp_path):
        now = datetime.now(tz=UTC)
        old = now - timedelta(hours=4)
        self._write_frame(tmp_path, old)
        deleted = cleanup_old_frames(tmp_path, max_age_hours=3)
        assert deleted == 1
        assert len(list(tmp_path.glob("*.png"))) == 0

    def test_keeps_recent_frames(self, tmp_path):
        now = datetime.now(tz=UTC)
        recent = now - timedelta(hours=1)
        self._write_frame(tmp_path, recent)
        deleted = cleanup_old_frames(tmp_path, max_age_hours=3)
        assert deleted == 0
        assert len(list(tmp_path.glob("*.png"))) == 1

    def test_mixed_old_and_recent(self, tmp_path):
        now = datetime.now(tz=UTC)
        self._write_frame(tmp_path, now - timedelta(hours=5))
        self._write_frame(tmp_path, now - timedelta(hours=4))
        self._write_frame(tmp_path, now - timedelta(hours=1))
        deleted = cleanup_old_frames(tmp_path, max_age_hours=3)
        assert deleted == 2
        assert len(list(tmp_path.glob("*.png"))) == 1

    def test_unlink_error_is_logged_and_not_counted(self, tmp_path, caplog):
        old = datetime.now(tz=UTC) - timedelta(hours=4)
        frame = self._write_frame(tmp_path, old)

        with patch.object(Path, "unlink", side_effect=OSError("read-only")):
            deleted = cleanup_old_frames(tmp_path, max_age_hours=3)

        assert deleted == 0
        assert frame.exists()
        assert "Could not delete frame" in caplog.text

    def test_ignores_non_png_files(self, tmp_path):
        now = datetime.now(tz=UTC)
        (tmp_path / "other.txt").write_bytes(b"x")
        self._write_frame(tmp_path, now - timedelta(hours=5))
        cleanup_old_frames(tmp_path, max_age_hours=3)
        assert (tmp_path / "other.txt").exists()

    def test_ignores_unparseable_png_filenames(self, tmp_path):
        """PNGs with unrecognised names are left untouched."""
        (tmp_path / "unknown.png").write_bytes(b"x")
        deleted = cleanup_old_frames(tmp_path, max_age_hours=3)
        assert deleted == 0
        assert (tmp_path / "unknown.png").exists()

    def test_returns_correct_count(self, tmp_path):
        now = datetime.now(tz=UTC)
        for i in range(5):
            self._write_frame(tmp_path, now - timedelta(hours=4 + i))
        assert cleanup_old_frames(tmp_path, max_age_hours=3) == 5


# ────────────────────────────────────────────────────────────────────────────
# _ts_from_filename and ts_to_filename
# ────────────────────────────────────────────────────────────────────────────

class TestTimestampHelpers:

    def test_ts_from_filename_valid(self):
        ts = _ts_from_filename("2026-04-26T14:30:00Z.png")
        assert ts == datetime(2026, 4, 26, 14, 30, 0, tzinfo=UTC)

    def test_ts_from_filename_invalid(self):
        assert _ts_from_filename("garbage.png") is None

    def test_ts_from_filename_no_z(self):
        # Missing Z suffix → not parseable as UTC
        assert _ts_from_filename("2026-04-26T14:30:00.png") is None

    def test_ts_to_filename_roundtrip(self):
        ts = datetime(2026, 4, 26, 14, 30, 0, tzinfo=UTC)
        fname = ts_to_filename(ts) + ".png"
        assert _ts_from_filename(fname) == ts

    def test_ts_to_filename_format(self):
        ts = datetime(2026, 1, 5, 8, 5, 0, tzinfo=UTC)
        assert ts_to_filename(ts) == "2026-01-05T08:05:00Z"


# ────────────────────────────────────────────────────────────────────────────
# _parse_ry_filename
# ────────────────────────────────────────────────────────────────────────────

class TestParseRyFilename:

    def test_valid_filename(self):
        ts = _parse_ry_filename("raa01-ry_10000-2604260630-dwd---bin.hdf5")
        assert ts == datetime(2026, 4, 26, 6, 30, tzinfo=UTC)

    def test_valid_filename_midnight(self):
        ts = _parse_ry_filename("raa01-ry_10000-2601010000-dwd---bin.hdf5")
        assert ts == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def test_invalid_filename_returns_none(self):
        assert _parse_ry_filename("something-else.hdf5") is None

    def test_directory_listing_entry_returns_none(self):
        assert _parse_ry_filename("raa01-ry_10000-latest-dwd---bin.hdf5") is None

    def test_wrong_extension_returns_none(self):
        assert _parse_ry_filename("raa01-ry_10000-2604260630-dwd---bin.bz2") is None

    def test_impossible_date_returns_none(self):
        # Matches the pattern, but month 13 / day 32 is not a valid date
        assert _parse_ry_filename("raa01-ry_10000-2613320000-dwd---bin.hdf5") is None


# ────────────────────────────────────────────────────────────────────────────
# DWD download helpers (mocked network)
# ────────────────────────────────────────────────────────────────────────────

def _mock_get_session(*, text: str | None = None, body: bytes | None = None):
    """Mock aiohttp session whose GET returns *text* / *body*."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(return_value=text)
    resp.read = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session, resp


class TestDwdDownloadHelpers:

    async def test_list_directory_returns_hdf5_links_only(self):
        html = (
            '<a href="../">../</a>'
            '<a href="raa01-ry_10000-2611260700-dwd---bin.hdf5">ry</a>'
            '<a href="raa01-rw_10000-2611260700-dwd---bin.bz2">old</a>'
            '<a href="readme.txt">readme</a>'
        )
        session, resp = _mock_get_session(text=html)

        names = await _list_dwd_directory(session, "https://example.invalid/ry/")

        assert names == ["raa01-ry_10000-2611260700-dwd---bin.hdf5"]
        resp.raise_for_status.assert_called_once()
        assert session.get.call_args.kwargs["headers"]["User-Agent"] == USER_AGENT

    async def test_download_returns_body(self):
        session, resp = _mock_get_session(body=b"hdf5 payload")

        data = await _download(session, "https://example.invalid/ry/f.hdf5")

        assert data == b"hdf5 payload"
        resp.raise_for_status.assert_called_once()
        assert session.get.call_args.kwargs["headers"]["User-Agent"] == USER_AGENT


# ────────────────────────────────────────────────────────────────────────────
# fetch_radar_frames (mocked network)
# ────────────────────────────────────────────────────────────────────────────

class TestFetchRadarFrames:
    """Tests for fetch_radar_frames using mocked aiohttp session."""

    def _recent_fname(self, minutes_ago: int = 10) -> tuple[str, datetime]:
        """Return a (filename, datetime) for a frame *minutes_ago* minutes ago."""
        ts = datetime.now(tz=UTC) - timedelta(minutes=minutes_ago)
        # Round to 5-minute boundary (as DWD does)
        ts = ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)
        fname = f"raa01-ry_10000-{ts.strftime('%y%m%d%H%M')}-dwd---bin.hdf5"
        return fname, ts

    @pytest.mark.asyncio
    async def test_skips_existing_frames(self, tmp_path):
        """If PNG already exists for a timestamp, it is not re-downloaded."""
        fname, ts = self._recent_fname(minutes_ago=10)
        existing = tmp_path / f"{ts_to_filename(ts)}.png"
        existing.write_bytes(b"existing")

        mock_session = MagicMock()
        mock_session.get = MagicMock()

        with patch(
            "custom_components.rain_radar_hub.frame_pipeline._list_dwd_directory",
            new=AsyncMock(return_value=[fname]),
        ):
            written = await fetch_radar_frames(
                mock_session, tmp_path, HAMBURG_BOUNDS, lookback_minutes=60
            )

        assert written == []
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_new_frame(self, tmp_path, fake_ry_payload):
        """A frame not yet on disk is downloaded, decoded and written."""
        fname, _ = self._recent_fname(minutes_ago=10)

        with (
            patch(
                "custom_components.rain_radar_hub.frame_pipeline._list_dwd_directory",
                new=AsyncMock(return_value=[fname]),
            ),
            patch(
                "custom_components.rain_radar_hub.frame_pipeline._download",
                new=AsyncMock(return_value=fake_ry_payload),
            ),
        ):
            written = await fetch_radar_frames(
                MagicMock(), tmp_path, HAMBURG_BOUNDS, lookback_minutes=60
            )

        assert len(written) == 1
        assert written[0].exists()
        assert written[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_skips_frames_outside_lookback(self, tmp_path):
        """Frames older than lookback_minutes are ignored."""
        fname, _ = self._recent_fname(minutes_ago=180)  # 3 hours ago
        with patch(
            "custom_components.rain_radar_hub.frame_pipeline._list_dwd_directory",
            new=AsyncMock(return_value=[fname]),
        ):
            written = await fetch_radar_frames(
                MagicMock(), tmp_path, HAMBURG_BOUNDS, lookback_minutes=60
            )
        assert written == []

    @pytest.mark.asyncio
    async def test_continues_on_decode_error(self, tmp_path, fake_ry_payload):
        """A broken frame does not abort processing of subsequent frames."""
        fname1, _ = self._recent_fname(minutes_ago=20)
        fname2, _ = self._recent_fname(minutes_ago=15)

        # Extract the timestamp token from the filename (index 2 after split on "-")
        # e.g. "raa01-ry_10000-2604260835-dwd---bin.hdf5" → "2604260835"
        fname1_ts = fname1.split("-")[2]

        async def fake_download(session, url):
            # First file raises, second succeeds
            if fname1_ts in url:
                raise ValueError("Simulated decode error")
            return fake_ry_payload

        with (
            patch(
                "custom_components.rain_radar_hub.frame_pipeline._list_dwd_directory",
                new=AsyncMock(return_value=[fname1, fname2]),
            ),
            patch(
                "custom_components.rain_radar_hub.frame_pipeline._download",
                new=fake_download,
            ),
        ):
            written = await fetch_radar_frames(
                MagicMock(), tmp_path, HAMBURG_BOUNDS, lookback_minutes=60
            )

        # Only the second frame should be written
        assert len(written) == 1
