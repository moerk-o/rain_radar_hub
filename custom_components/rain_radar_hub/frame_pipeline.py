"""Frame pipeline — download, decode, reproject, save DWD radar PNGs.

Public API
----------
Core (pure, synchronous, fully testable):
    reproject_to_png(composite, bounds, size) → bytes
    generate_colorbar(width, height)          → bytes
    cleanup_old_frames(frames_dir, hours)     → int

Async (require network / filesystem):
    fetch_radar_frames(session, frames_dir, region_bounds, lookback) → list[Path]

DWD data
--------
RY  : RADOLAN precipitation rate in mm/h, one composite every 5 minutes, as
      ODIM HDF5. Directory: DWD_RY_BASE_URL,
      filenames: raa01-ry_10000-YYMMDDHHMM-dwd---bin.hdf5 (UTC)

Decoding, reprojection and file access block, so fetch_radar_frames runs
them in the executor.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyproj
from PIL import Image

from .const import (
    DWD_RY_BASE_URL,
    RAIN_PALETTE,
    USER_AGENT,
)
from .radolan_decoder import RadarComposite, decode_composite

_LOGGER = logging.getLogger(__name__)

# Output size for reprojected radar overlay PNGs
OUTPUT_WIDTH = 1024
OUTPUT_HEIGHT = 1024

# DWD RY filename pattern: raa01-ry_10000-YYMMDDHHMM-dwd---bin.hdf5
_RY_FILENAME_RE = re.compile(
    r"raa01-ry_10000-(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})-dwd---bin\.hdf5"
)

# ────────────────────────────────────────────────────────────────────────────
# Core: reprojection
# ────────────────────────────────────────────────────────────────────────────

def reproject_to_png(
    composite: RadarComposite,
    region_bounds: tuple[tuple[float, float], tuple[float, float]],
    output_size: tuple[int, int] = (OUTPUT_WIDTH, OUTPUT_HEIGHT),
) -> bytes:
    """Reproject a radar composite to a Web Mercator PNG overlay for one region.

    Uses inverse mapping: for each output pixel, the corresponding grid
    coordinate is found via pyproj, then bilinearly interpolated.

    Args:
        composite: decoded composite (values in mm/h, NaN = no data).
        region_bounds: ((lat_sw, lon_sw), (lat_ne, lon_ne)) — WGS84 degrees.
        output_size: (width, height) in pixels.

    Returns:
        PNG bytes with RGBA alpha channel.  Transparent where no precipitation
        (< 0.1 mm/h) or outside the RADOLAN coverage area.
    """
    (lat_sw, lon_sw), (lat_ne, lon_ne) = region_bounds
    width, height = output_size

    # ── 1. Region bounds → Web Mercator (EPSG:3857) ────────────────────────
    wgs84 = pyproj.CRS.from_epsg(4326)
    mercator = pyproj.CRS.from_epsg(3857)
    to_merc = pyproj.Transformer.from_crs(wgs84, mercator, always_xy=True)

    x_min, y_min = to_merc.transform(lon_sw, lat_sw)
    x_max, y_max = to_merc.transform(lon_ne, lat_ne)

    # ── 2. Output pixel grid in Web Mercator ───────────────────────────────
    x_out = np.linspace(x_min, x_max, width, dtype=np.float64)
    y_out = np.linspace(y_max, y_min, height, dtype=np.float64)  # N→S
    xx_out, yy_out = np.meshgrid(x_out, y_out)

    # ── 3. Output pixels → composite grid CRS ──────────────────────────────
    grid_crs = pyproj.CRS.from_proj4(composite.projdef)
    to_grid = pyproj.Transformer.from_crs(mercator, grid_crs, always_xy=True)

    xx_grid, yy_grid = to_grid.transform(xx_out.ravel(), yy_out.ravel())
    xx_grid = xx_grid.reshape(height, width)
    yy_grid = yy_grid.reshape(height, width)

    # ── 4. Grid coords → fractional pixel indices (row 0 = north) ──────────
    col_idx = (xx_grid - composite.x_ul) / composite.xscale
    row_idx = (composite.y_ul - yy_grid) / composite.yscale

    # ── 5. Bilinear interpolation ──────────────────────────────────────────
    values = _bilinear_interpolate(composite.values, row_idx, col_idx)

    # ── 6. Color palette → RGBA ───────────────────────────────────────────
    rgba = _apply_palette(values)

    # ── 7. Encode PNG ──────────────────────────────────────────────────────
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _bilinear_interpolate(
    grid: np.ndarray,
    row_idx: np.ndarray,
    col_idx: np.ndarray,
) -> np.ndarray:
    """Bilinear interpolation of *grid* at fractional (row_idx, col_idx).

    Out-of-bounds pixels and pixels with any NaN corner → NaN in output.

    Args:
        grid:    (rows, cols) float32 source array (may contain NaN).
        row_idx: output-shaped float64 array of source row indices.
        col_idx: output-shaped float64 array of source column indices.

    Returns:
        float32 array, same shape as row_idx.
    """
    rows, cols = grid.shape

    r0 = np.floor(row_idx).astype(np.int32)
    c0 = np.floor(col_idx).astype(np.int32)
    r1 = r0 + 1
    c1 = c0 + 1

    dr = (row_idx - r0).astype(np.float32)
    dc = (col_idx - c0).astype(np.float32)

    # Pixels whose four corners are not all inside the grid
    oob = (r0 < 0) | (r1 >= rows) | (c0 < 0) | (c1 >= cols)

    # Clamp for safe array access; OOB pixels get NaN below anyway
    r0c = np.clip(r0, 0, rows - 1)
    r1c = np.clip(r1, 0, rows - 1)
    c0c = np.clip(c0, 0, cols - 1)
    c1c = np.clip(c1, 0, cols - 1)

    v00 = grid[r0c, c0c]
    v01 = grid[r0c, c1c]
    v10 = grid[r1c, c0c]
    v11 = grid[r1c, c1c]

    result = (
        v00 * (1 - dr) * (1 - dc)
        + v01 * (1 - dr) * dc
        + v10 * dr * (1 - dc)
        + v11 * dr * dc
    )

    nan_corners = np.isnan(v00) | np.isnan(v01) | np.isnan(v10) | np.isnan(v11)
    result[oob | nan_corners] = np.nan

    return result


def _apply_palette(values: np.ndarray) -> np.ndarray:
    """Map mm/h values to RGBA pixels using RAIN_PALETTE.

    Values below 0.1 mm/h (including NaN) → fully transparent (0, 0, 0, 0).

    Args:
        values: float32 array of mm/h values.

    Returns:
        uint8 RGBA array with shape (*values.shape, 4).
    """
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)  # transparent by default

    for min_mmh, max_mmh, color in RAIN_PALETTE:
        valid = ~np.isnan(values)
        if max_mmh is None:
            mask = valid & (values >= min_mmh)
        else:
            mask = valid & (values >= min_mmh) & (values < max_mmh)
        rgba[mask] = color

    return rgba


# ────────────────────────────────────────────────────────────────────────────
# Core: colorbar (legend image)
# ────────────────────────────────────────────────────────────────────────────

def generate_colorbar(width: int = 40, height: int = 200) -> bytes:
    """Generate a vertical colorbar PNG from RAIN_PALETTE.

    The image runs from the highest precipitation (top) to zero (bottom).
    Fully transparent bands (alpha=0) are left out.

    Args:
        width:  Width in pixels.
        height: Height in pixels.

    Returns:
        PNG bytes (RGBA).
    """
    # Build a 1-column gradient, then tile horizontally
    colored_bands = [(lo, hi, c) for lo, hi, c in RAIN_PALETTE if c[3] > 0]
    n_bands = len(colored_bands)

    # Each band gets an equal share of the image height (ceiling division
    # ensures the total is always ≥ height before the final crop).
    band_h = max(1, -(-height // n_bands))  # ceil division: -(-a//b)
    img_array = np.zeros((n_bands * band_h, 1, 4), dtype=np.uint8)

    for i, (_, _, color) in enumerate(reversed(colored_bands)):
        # reversed: lowest mm/h at bottom → top of image = highest
        row_start = i * band_h
        img_array[row_start : row_start + band_h, 0] = color

    # Crop to exact height and tile to width
    img_array = img_array[:height]
    img_array = np.tile(img_array, (1, width, 1))

    img = Image.fromarray(img_array, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ────────────────────────────────────────────────────────────────────────────
# Core: frame cleanup
# ────────────────────────────────────────────────────────────────────────────

def cleanup_old_frames(frames_dir: Path, max_age_hours: int) -> int:
    """Delete PNG frames older than *max_age_hours* from *frames_dir*.

    Frame filenames must encode the UTC timestamp as ISO 8601:
    ``2026-04-26T14:30:00Z.png``

    Args:
        frames_dir:    Directory containing ``*.png`` frame files.
        max_age_hours: Files older than this are deleted.

    Returns:
        Number of files deleted.
    """
    if not frames_dir.exists():
        return 0

    cutoff = datetime.now(tz=UTC) - timedelta(hours=max_age_hours)
    deleted = 0

    for png in frames_dir.glob("*.png"):
        ts = _ts_from_filename(png.name)
        if ts is not None and ts < cutoff:
            try:
                png.unlink()
                deleted += 1
                _LOGGER.debug("Deleted old frame: %s", png.name)
            except OSError as exc:
                _LOGGER.warning("Could not delete frame %s: %s", png.name, exc)

    return deleted


def _ts_from_filename(filename: str) -> datetime | None:
    """Parse UTC datetime from a frame filename like ``2026-04-26T14:30:00Z.png``.

    Returns None if the filename is not parseable or the timestamp is naive
    (i.e. has no timezone info — filenames without a trailing Z are rejected).
    """
    stem = filename.removesuffix(".png")
    try:
        ts = datetime.fromisoformat(stem.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Reject naive datetimes (stem had no timezone suffix)
    if ts.tzinfo is None:
        return None
    return ts


def ts_to_filename(ts: datetime) -> str:
    """Format a UTC datetime as a frame filename stem (without .png)."""
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# ────────────────────────────────────────────────────────────────────────────
# Async: HTTP fetch — RY (past frames, ODIM HDF5)
# ────────────────────────────────────────────────────────────────────────────

async def fetch_radar_frames(
    session,
    frames_dir: Path,
    region_bounds: tuple[tuple[float, float], tuple[float, float]],
    lookback_minutes: int = 60,
) -> list[Path]:
    """Download, decode and reproject the RY frames of the last minutes.

    Fetches every RY composite from the past *lookback_minutes* whose PNG
    does not exist yet.

    Args:
        session:          aiohttp.ClientSession.
        frames_dir:       Output directory for PNG files.
        region_bounds:    ((lat_sw, lon_sw), (lat_ne, lon_ne)).
        lookback_minutes: How far back to look for frames (default 60 min).

    Returns:
        List of Path objects for newly written PNGs.
    """
    loop = asyncio.get_running_loop()
    existing = await loop.run_in_executor(None, _prepare_frames_dir, frames_dir)
    written: list[Path] = []

    filenames = await _list_dwd_directory(session, DWD_RY_BASE_URL)
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=lookback_minutes)

    for fname in filenames:
        ts = _parse_ry_filename(fname)
        if ts is None or ts < cutoff:
            continue

        out_name = f"{ts_to_filename(ts)}.png"
        if out_name in existing:
            continue  # already processed

        out_path = frames_dir / out_name
        try:
            data = await _download(session, DWD_RY_BASE_URL + fname)
            await loop.run_in_executor(
                None, _render_frame, data, region_bounds, out_path
            )
            written.append(out_path)
            _LOGGER.debug("RY frame written: %s", out_path.name)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to process RY frame %s: %s", fname, exc)

    return written


def _prepare_frames_dir(frames_dir: Path) -> set[str]:
    """Create *frames_dir* if needed and return the names of existing frames."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    return {png.name for png in frames_dir.glob("*.png")}


def _render_frame(
    data: bytes,
    region_bounds: tuple[tuple[float, float], tuple[float, float]],
    out_path: Path,
) -> None:
    """Decode one composite, reproject it for the region and write the PNG."""
    composite = decode_composite(data)
    out_path.write_bytes(reproject_to_png(composite, region_bounds))


# ────────────────────────────────────────────────────────────────────────────
# Async helpers (internal)
# ────────────────────────────────────────────────────────────────────────────

async def _list_dwd_directory(session, url: str) -> list[str]:
    """Return filenames from a DWD Open Data HTML directory listing."""
    headers = {"User-Agent": USER_AGENT}
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        html = await resp.text()

    # DWD directory listings use plain <a href="filename"> links
    return re.findall(r'href="([^"]+\.hdf5)"', html)


async def _download(session, url: str) -> bytes:
    """Download a file and return its bytes."""
    headers = {"User-Agent": USER_AGENT}
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        return await resp.read()


def _parse_ry_filename(filename: str) -> datetime | None:
    """Parse UTC datetime from a DWD RY filename.

    Format: ``raa01-ry_10000-YYMMDDHHMM-dwd---bin.hdf5``
    Year is assumed to be 2000+YY.
    """
    m = _RY_FILENAME_RE.match(filename)
    if not m:
        return None
    yy, mm, dd, hh, mi = (int(g) for g in m.groups())
    try:
        return datetime(2000 + yy, mm, dd, hh, mi, tzinfo=UTC)
    except ValueError:
        return None
