"""Tests for radolan_decoder.py (ODIM HDF5 composites)."""
import io
from datetime import UTC, datetime

import h5py
import numpy as np
import pytest

from custom_components.rain_radar_hub.radolan_decoder import decode_composite

from .odim import DWD_PROJDEF

# ---------------------------------------------------------------------------
# decode_composite: values
# ---------------------------------------------------------------------------


class TestDecodeValues:

    def test_returns_grid_shape(self, make_odim_composite):
        raw = np.zeros((4, 5), np.uint16)
        composite = decode_composite(make_odim_composite(raw))
        assert composite.values.shape == (4, 5)

    def test_returns_float32(self, make_odim_composite):
        composite = decode_composite(make_odim_composite(np.zeros((2, 2), np.uint16)))
        assert composite.values.dtype == np.float32

    def test_applies_gain_and_offset(self, make_odim_composite):
        raw = np.array([[50, 500], [1234, 4095]], np.uint16)
        composite = decode_composite(make_odim_composite(raw, gain=0.01))
        np.testing.assert_allclose(
            composite.values, [[0.5, 5.0], [12.34, 40.95]], rtol=1e-6
        )

    def test_offset_is_added(self, make_odim_composite):
        raw = np.array([[100]], np.uint16)
        composite = decode_composite(make_odim_composite(raw, gain=0.1, offset=2.0))
        np.testing.assert_allclose(composite.values[0, 0], 12.0)

    def test_undetect_is_zero_rain(self, make_odim_composite):
        raw = np.array([[0]], np.uint16)
        composite = decode_composite(
            make_odim_composite(raw, offset=1.0, undetect=0.0)
        )
        assert composite.values[0, 0] == 0.0

    def test_nodata_is_nan(self, make_odim_composite):
        raw = np.array([[65535, 500]], np.uint16)
        composite = decode_composite(make_odim_composite(raw))
        assert np.isnan(composite.values[0, 0])
        np.testing.assert_allclose(composite.values[0, 1], 5.0)

    def test_row_order_is_kept(self, make_odim_composite):
        # Row 0 is the northern edge in ODIM files and stays row 0
        raw = np.array([[100], [200]], np.uint16)
        composite = decode_composite(make_odim_composite(raw))
        np.testing.assert_allclose(composite.values[:, 0], [1.0, 2.0])


# ---------------------------------------------------------------------------
# decode_composite: metadata
# ---------------------------------------------------------------------------


class TestDecodeMetadata:

    def test_upper_left_pixel_centre_from_corner(self, make_odim_composite):
        # The DWD corner coordinates give the outer corner of the upper-left
        # pixel at (-500 m, +500 m); its centre is the grid origin.
        composite = decode_composite(make_odim_composite(np.zeros((3, 3), np.uint16)))
        assert composite.x_ul == pytest.approx(0.0, abs=0.01)
        assert composite.y_ul == pytest.approx(0.0, abs=0.01)

    def test_pixel_size(self, make_odim_composite):
        composite = decode_composite(make_odim_composite(np.zeros((3, 3), np.uint16)))
        assert composite.xscale == 1000.0
        assert composite.yscale == 1000.0

    def test_projdef(self, make_odim_composite):
        composite = decode_composite(make_odim_composite(np.zeros((1, 1), np.uint16)))
        assert composite.projdef == DWD_PROJDEF

    def test_timestamp_in_utc(self, make_odim_composite):
        composite = decode_composite(
            make_odim_composite(
                np.zeros((1, 1), np.uint16), date="20261126", time="081000"
            )
        )
        assert composite.timestamp == datetime(2026, 11, 26, 8, 10, tzinfo=UTC)

    def test_reads_string_attributes_stored_as_str(self, make_odim_composite):
        raw = np.array([[500]], np.uint16)
        composite = decode_composite(make_odim_composite(raw, as_bytes=False))
        np.testing.assert_allclose(composite.values[0, 0], 5.0)
        assert composite.projdef == DWD_PROJDEF


# ---------------------------------------------------------------------------
# decode_composite: invalid input
# ---------------------------------------------------------------------------


class TestDecodeErrors:

    def test_rejects_non_hdf5_bytes(self):
        with pytest.raises(ValueError, match="Not a readable HDF5 file"):
            decode_composite(b"not an hdf5 file")

    def test_rejects_hdf5_without_odim_groups(self):
        buf = io.BytesIO()
        with h5py.File(buf, "w") as h5:
            h5.create_group("what")
        with pytest.raises(ValueError, match="Not an ODIM composite"):
            decode_composite(buf.getvalue())

    def test_rejects_other_quantity(self, make_odim_composite):
        raw = np.zeros((1, 1), np.uint16)
        with pytest.raises(ValueError, match="Unsupported quantity 'ACRR'"):
            decode_composite(make_odim_composite(raw, quantity="ACRR"))

    def test_rejects_data_not_matching_grid_size(self, make_odim_composite):
        raw = np.zeros((2, 3), np.uint16)
        with pytest.raises(ValueError, match="does not match grid"):
            decode_composite(make_odim_composite(raw, xsize=4))
