"""RADOLAN binary format decoder — pure Python + numpy, no wradlib.

Reference: DWD RADOLAN/RADVOR-OP Composite Format (PDF)
https://www.dwd.de/DE/leistungen/radolan/radolan_info/radolan_radvor_op_komposit_format_pdf.pdf

Grid constants and SW-corner coordinates are derived from the DWD specification
for the national composite (RW/RV, 1100 × 900 km²). Verify against actual DWD
data when testing for the first time — see Spec 2, section 10.
"""
from __future__ import annotations

import re

import numpy as np

# ---------------------------------------------------------------------------
# RADOLAN national composite grid (1100 cols × 900 rows, 1 km resolution)
# ---------------------------------------------------------------------------
GRID_COLS = 1100
GRID_ROWS = 900

# SW corner of the grid in RADOLAN stereographic coordinates (PROJ4 meters).
#
# DWD spec gives the SW corner in km from the projection centre:
#   x_sw_km = -523.4622,  y_sw_km = -4658.645
# The PROJ4 string uses false easting/northing (x_0, y_0) that shift these:
#   x_0 = 543196.83521 m,  y_0 = 3622588.65186 m
# → PROJ4 x_sw = -523462.2 + 543196.83521 ≈ 19734.6 m
# → PROJ4 y_sw = -4658645.0 + 3622588.65186 ≈ -1036056.3 m
#
# ⚠ Verify these values against actual DWD data (Spec 2, open question 2).
RADOLAN_X_SW: float = -523462.2 + 543196.83521   # ≈  19 734.6 m
RADOLAN_Y_SW: float = -4658645.0 + 3622588.65186  # ≈ -1 036 056.3 m
RADOLAN_GRID_STEP: float = 1000.0  # 1 km in metres

# ---------------------------------------------------------------------------
# Bit masks for RADOLAN uint16 pixel values
# ---------------------------------------------------------------------------
_MASK_VALUE: int = 0x0FFF   # bits 0–11: precipitation value (0–4095)
_MASK_CLUTTER: int = 0x1000  # bit 12: clutter detected
_MASK_NO_DATA: int = 0x2000  # bit 13: no data / missing


def decode_radolan(data: bytes) -> tuple[np.ndarray, dict]:
    """Decode a RADOLAN binary blob (decompressed, bz2 already stripped).

    Args:
        data: Raw bytes of one RADOLAN product file (RW or RV).

    Returns:
        grid:   numpy float32 array, shape (GRID_ROWS, GRID_COLS).
                Values are in mm/h. No-data and clutter pixels are NaN.
                Row 0 is the northernmost row.
        header: Dict of parsed header fields (see _parse_header).

    Raises:
        ValueError: If the ETX marker is missing or binary data is too short.
    """
    # 1. Split header / binary at the ETX marker (0x03)
    try:
        etx_pos = data.index(0x03)
    except ValueError:
        raise ValueError(
            "No ETX marker (0x03) found — not a valid RADOLAN file."
        ) from None

    header_str = data[:etx_pos].decode("ascii", errors="replace")
    binary_data = data[etx_pos + 1:]

    # 2. Parse header
    header = _parse_header(header_str)

    rows: int = header.get("rows", GRID_ROWS)
    cols: int = header.get("cols", GRID_COLS)

    # 3. Validate binary length
    expected_bytes = rows * cols * 2
    if len(binary_data) < expected_bytes:
        raise ValueError(
            f"Binary section too short: expected {expected_bytes} B, "
            f"got {len(binary_data)} B."
        )

    # 4. Decode little-endian unsigned 16-bit integers
    raw = np.frombuffer(binary_data[:expected_bytes], dtype="<u2").reshape(rows, cols)

    # 5. Extract precipitation values (lower 12 bits) and flag masks
    values = (raw & _MASK_VALUE).astype(np.float32) * 0.1  # → mm/h
    invalid = ((raw & _MASK_NO_DATA) | (raw & _MASK_CLUTTER)).astype(bool)
    values[invalid] = np.nan

    return values, header


def _parse_header(header_str: str) -> dict:
    """Parse fields from a RADOLAN ASCII header string.

    RADOLAN header layout (positions 0–12 are fixed, rest are key-value tokens):
        Pos 0-1  : product identifier (e.g. "RW", "RV")
        Pos 2-6  : station number (5 chars, e.g. "00000" for composite)
        Pos 7-8  : day of month (DD)
        Pos 9-10 : hour (HH)
        Pos 11-12: minute (MM)
        Remaining: space-separated tokens  BY GP PR INT VV MF MS …

    ⚠ The position-based timestamp (day/hour/minute) must be verified against
    real DWD files.  Year and month are NOT stored in the fixed prefix and must
    be supplied externally (e.g. from the filename or the current UTC date).
    """
    header: dict = {}

    # Product identifier
    if len(header_str) >= 2:
        header["product"] = header_str[:2]

    # Position-based timestamp (day / hour / minute)
    if len(header_str) >= 13:
        try:
            header["day"] = int(header_str[7:9])
            header["hour"] = int(header_str[9:11])
            header["minute"] = int(header_str[11:13])
        except ValueError:
            pass  # non-numeric — skip silently

    # Grid dimensions  "GP <rows>x<cols>"  (e.g. "GP 900x1100")
    # No \b: digit→letter transitions have no word boundary in RADOLAN headers.
    gp = re.search(r"GP\s+(\d+)\s*[xX]\s*(\d+)", header_str)
    if gp:
        header["rows"] = int(gp.group(1))
        header["cols"] = int(gp.group(2))

    # Forecast offset  "VV <minutes>"  (0 = observation, >0 = nowcast)
    vv = re.search(r"VV\s+(\d+)", header_str)
    if vv:
        header["forecast_minutes"] = int(vv.group(1))

    # Accumulation interval  "INT <minutes>"
    iv = re.search(r"INT\s+(\d+)", header_str)
    if iv:
        header["interval_minutes"] = int(iv.group(1))

    # Total byte count  "BY <n>"
    by = re.search(r"BY\s+(\d+)", header_str)
    if by:
        header["total_bytes"] = int(by.group(1))

    return header


def get_radolan_grid_coords() -> tuple[np.ndarray, np.ndarray]:
    """Return (xx, yy) coordinate arrays for the full RADOLAN grid.

    Both arrays have shape (GRID_ROWS, GRID_COLS) and are in PROJ4 metres
    (i.e. the RADOLAN stereographic CRS including the DWD false easting/northing).

    Row 0 corresponds to the northernmost row of the grid (as stored in the
    binary file).  Y coordinates therefore decrease as the row index increases.

    Use together with the PROJ4 string from const.DWD_RADOLAN_PROJ4 to
    transform to any target CRS via pyproj.
    """
    x_row = RADOLAN_X_SW + np.arange(GRID_COLS, dtype=np.float64) * RADOLAN_GRID_STEP
    # Row 0 = north → y_north = Y_SW + (GRID_ROWS-1)*step; decreases by 1 step per row
    y_col = (
        RADOLAN_Y_SW
        + (GRID_ROWS - 1 - np.arange(GRID_ROWS, dtype=np.float64)) * RADOLAN_GRID_STEP
    )
    return np.meshgrid(x_row, y_col)
