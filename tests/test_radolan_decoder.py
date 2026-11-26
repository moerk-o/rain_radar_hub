"""Tests for radolan_decoder.py."""
import struct

import numpy as np
import pytest

from custom_components.rain_radar_hub.radolan_decoder import (
    _MASK_CLUTTER,
    _MASK_NO_DATA,
    GRID_COLS,
    GRID_ROWS,
    RADOLAN_GRID_STEP,
    RADOLAN_X_SW,
    RADOLAN_Y_SW,
    _parse_header,
    decode_radolan,
    get_radolan_grid_coords,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_radolan_blob(
    rows: int = 4,
    cols: int = 5,
    values: list[int] | None = None,
    product: str = "RW",
    day: int = 3,
    hour: int = 6,
    minute: int = 0,
    forecast_minutes: int = 0,
) -> bytes:
    """Build a minimal synthetic RADOLAN binary blob for testing.

    Uses a small grid (default 4×5) to keep tests fast.
    Values are raw uint16 integers (before flag masking).
    """
    header = (
        f"{product}00000{day:02d}{hour:02d}{minute:02d}"
        f"BY {rows * cols * 2 + 100} "
        f"VS 3 "
        f"PR E-02 "
        f"INT  60 "
        f"GP {rows}x{cols} "
        f"VV {forecast_minutes} "
        f"MS 0<>"
    )
    if values is None:
        # Default: 10 mm/h raw value (= 100 as uint16, i.e. 100 * 0.1 = 10.0 mm/h)
        values = [100] * (rows * cols)

    binary = struct.pack(f"<{rows * cols}H", *values)
    return header.encode("ascii") + b"\x03" + binary


# ---------------------------------------------------------------------------
# decode_radolan: basic decoding
# ---------------------------------------------------------------------------

class TestDecodeRadolan:

    def test_returns_correct_shape(self):
        blob = _make_radolan_blob(rows=4, cols=5)
        grid, _ = decode_radolan(blob)
        assert grid.shape == (4, 5)

    def test_returns_float32(self):
        blob = _make_radolan_blob(rows=4, cols=5)
        grid, _ = decode_radolan(blob)
        assert grid.dtype == np.float32

    def test_value_scaling(self):
        # raw value 100 → 100 * 0.1 = 10.0 mm/h
        blob = _make_radolan_blob(rows=2, cols=2, values=[100, 50, 0, 4095])
        grid, _ = decode_radolan(blob)
        np.testing.assert_allclose(grid[0, 0], 10.0)
        np.testing.assert_allclose(grid[0, 1], 5.0)
        np.testing.assert_allclose(grid[1, 0], 0.0)
        np.testing.assert_allclose(grid[1, 1], 409.5)  # max 12-bit value

    def test_zero_precipitation_is_zero(self):
        blob = _make_radolan_blob(rows=1, cols=1, values=[0])
        grid, _ = decode_radolan(blob)
        assert grid[0, 0] == 0.0

    def test_no_data_flag_produces_nan(self):
        raw = _MASK_NO_DATA | 200  # flag set + some value
        blob = _make_radolan_blob(rows=1, cols=1, values=[raw])
        grid, _ = decode_radolan(blob)
        assert np.isnan(grid[0, 0])

    def test_clutter_flag_produces_nan(self):
        raw = _MASK_CLUTTER | 150
        blob = _make_radolan_blob(rows=1, cols=1, values=[raw])
        grid, _ = decode_radolan(blob)
        assert np.isnan(grid[0, 0])

    def test_both_flags_produce_nan(self):
        raw = _MASK_NO_DATA | _MASK_CLUTTER | 100
        blob = _make_radolan_blob(rows=1, cols=1, values=[raw])
        grid, _ = decode_radolan(blob)
        assert np.isnan(grid[0, 0])

    def test_valid_pixels_not_nan(self):
        blob = _make_radolan_blob(rows=2, cols=2, values=[0, 1, 100, 4095])
        grid, _ = decode_radolan(blob)
        assert not np.any(np.isnan(grid))

    def test_mixed_valid_and_no_data(self):
        values = [100, _MASK_NO_DATA | 50, 200, _MASK_CLUTTER | 300]
        blob = _make_radolan_blob(rows=2, cols=2, values=values)
        grid, _ = decode_radolan(blob)
        np.testing.assert_allclose(grid[0, 0], 10.0)
        assert np.isnan(grid[0, 1])
        np.testing.assert_allclose(grid[1, 0], 20.0)
        assert np.isnan(grid[1, 1])

    def test_header_is_dict(self):
        blob = _make_radolan_blob()
        _, header = decode_radolan(blob)
        assert isinstance(header, dict)

    def test_raises_on_missing_etx(self):
        with pytest.raises(ValueError, match="ETX"):
            decode_radolan(b"RW00000030600GP 4x5 " + b"\x00" * 100)

    def test_raises_on_binary_too_short(self):
        header = b"RW00000030600GP 4x5 VV 0 MS 0<>\x03"
        # Only 1 byte of binary data instead of 4*5*2 = 40
        with pytest.raises(ValueError, match="too short"):
            decode_radolan(header + b"\x00")

    def test_defaults_to_full_grid_size_without_gp_field(self):
        """When GP field is absent, decoder defaults to GRID_ROWS×GRID_COLS."""
        rows, cols = GRID_ROWS, GRID_COLS
        header = "RW0000001020000VV 0 MS 0<>".encode("ascii")
        binary = struct.pack(f"<{rows * cols}H", *([0] * (rows * cols)))
        blob = header + b"\x03" + binary
        grid, _ = decode_radolan(blob)
        assert grid.shape == (rows, cols)


# ---------------------------------------------------------------------------
# _parse_header: header parsing
# ---------------------------------------------------------------------------

class TestParseHeader:

    def test_product_rw(self):
        h = _parse_header("RW00000030600GP 900x1100VV 0INT  60BY 2097600MS 0<>")
        assert h["product"] == "RW"

    def test_product_rv(self):
        h = _parse_header("RV00000030600GP 900x1100VV  30INT   5BY 2097600MS 0<>")
        assert h["product"] == "RV"

    def test_grid_dimensions_standard(self):
        h = _parse_header("RW00000030600GP 900x1100VV 0MS 0<>")
        assert h["rows"] == 900
        assert h["cols"] == 1100

    def test_grid_dimensions_custom(self):
        h = _parse_header("RW00000030600GP 4x5VV 0MS 0<>")
        assert h["rows"] == 4
        assert h["cols"] == 5

    def test_grid_dimensions_uppercase_x(self):
        h = _parse_header("RW00000030600GP 4X5VV 0MS 0<>")
        assert h["rows"] == 4
        assert h["cols"] == 5

    def test_timestamp_day_hour_minute(self):
        # "RW" + "00000" + day="15" + hour="12" + minute="30"
        h = _parse_header("RW0000015123015GP 4x5VV 0MS 0<>")
        assert h["day"] == 15
        assert h["hour"] == 12
        assert h["minute"] == 30

    def test_forecast_minutes_zero(self):
        h = _parse_header("RW00000030600GP 4x5VV 0MS 0<>")
        assert h["forecast_minutes"] == 0

    def test_forecast_minutes_nonzero(self):
        h = _parse_header("RV00000030600GP 4x5VV  90MS 0<>")
        assert h["forecast_minutes"] == 90

    def test_interval_minutes(self):
        h = _parse_header("RW00000030600GP 4x5INT  60VV 0MS 0<>")
        assert h["interval_minutes"] == 60

    def test_interval_minutes_rv(self):
        h = _parse_header("RV00000030600GP 4x5INT   5VV 0MS 0<>")
        assert h["interval_minutes"] == 5

    def test_total_bytes(self):
        h = _parse_header("RW00000030600BY 2097600GP 4x5VV 0MS 0<>")
        assert h["total_bytes"] == 2097600

    def test_missing_optional_fields_absent(self):
        h = _parse_header("RW00000030600")
        assert "forecast_minutes" not in h
        assert "interval_minutes" not in h
        assert "total_bytes" not in h

    def test_non_numeric_timestamp_handled_gracefully(self):
        # Corrupt timestamp — should not raise
        h = _parse_header("RWXXXXX  XYZGP 4x5VV 0MS 0<>")
        assert "day" not in h
        assert h.get("product") == "RW"

    def test_empty_header(self):
        h = _parse_header("")
        assert h == {}

    def test_too_short_for_product(self):
        h = _parse_header("R")
        # Only 1 char, product should not be set
        assert "product" not in h


# ---------------------------------------------------------------------------
# get_radolan_grid_coords: coordinate arrays
# ---------------------------------------------------------------------------

class TestGetRadolanGridCoords:

    def test_shape(self):
        xx, yy = get_radolan_grid_coords()
        assert xx.shape == (GRID_ROWS, GRID_COLS)
        assert yy.shape == (GRID_ROWS, GRID_COLS)

    def test_dtype_float64(self):
        xx, yy = get_radolan_grid_coords()
        assert xx.dtype == np.float64
        assert yy.dtype == np.float64

    def test_x_increases_with_column(self):
        xx, _ = get_radolan_grid_coords()
        # All rows should have identical x values; x increases left-to-right
        assert np.all(np.diff(xx[0, :]) > 0)

    def test_y_decreases_with_row(self):
        _, yy = get_radolan_grid_coords()
        # Row 0 = north (highest y), y decreases as row index increases
        assert np.all(np.diff(yy[:, 0]) < 0)

    def test_sw_corner_matches_constant(self):
        xx, yy = get_radolan_grid_coords()
        # Bottom-left corner (last row, first col) should match the SW constant
        np.testing.assert_allclose(xx[-1, 0], RADOLAN_X_SW)
        np.testing.assert_allclose(yy[-1, 0], RADOLAN_Y_SW)

    def test_ne_corner(self):
        xx, yy = get_radolan_grid_coords()
        expected_x_ne = RADOLAN_X_SW + (GRID_COLS - 1) * RADOLAN_GRID_STEP
        expected_y_ne = RADOLAN_Y_SW + (GRID_ROWS - 1) * RADOLAN_GRID_STEP
        np.testing.assert_allclose(xx[0, -1], expected_x_ne)
        np.testing.assert_allclose(yy[0, -1], expected_y_ne)

    def test_grid_step_x(self):
        xx, _ = get_radolan_grid_coords()
        diffs = np.diff(xx[0, :])
        np.testing.assert_allclose(diffs, RADOLAN_GRID_STEP)

    def test_grid_step_y(self):
        _, yy = get_radolan_grid_coords()
        diffs = np.diff(yy[:, 0])
        np.testing.assert_allclose(diffs, -RADOLAN_GRID_STEP)
