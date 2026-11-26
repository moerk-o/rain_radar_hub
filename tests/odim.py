"""Synthetic ODIM HDF5 composites shaped like the DWD radar files."""
import io

import h5py
import numpy as np

# Georeference of the DWD RADOLAN composites, copied from the root "where"
# group of a real RY file (raa01-ry_10000-2611260810-dwd---bin.hdf5).
DWD_PROJDEF = (
    "+proj=stere +lat_0=90 +lat_ts=60 +lon_0=10 "
    "+a=6378137 +b=6356752.3142451802 +no_defs "
    "+x_0=543196.83521776402 +y_0=3622588.8619310018 +units=m"
)
DWD_UL_LON, DWD_UL_LAT = 1.46330151, 55.86208711
DWD_ROWS, DWD_COLS = 1200, 1100


def build_odim_composite(
    raw: np.ndarray,
    *,
    quantity: str = "RATE",
    gain: float = 0.01,
    offset: float = 0.0,
    nodata: float = 65535.0,
    undetect: float = 0.0,
    date: str = "20261126",
    time: str = "081000",
    xsize: int | None = None,
    as_bytes: bool = True,
) -> bytes:
    """Build an ODIM HDF5 composite shaped like the files DWD publishes.

    *raw* holds the stored uint16 values (row 0 = north). String attributes
    are written as fixed-length bytes like in the DWD files unless
    *as_bytes* is False.
    """
    def text(value: str):
        return np.bytes_(value) if as_bytes else value

    rows, cols = raw.shape
    buf = io.BytesIO()
    with h5py.File(buf, "w") as h5:
        h5.attrs["Conventions"] = text("ODIM_H5/V2_3")
        what = h5.create_group("what")
        what.attrs["date"] = text(date)
        what.attrs["time"] = text(time)
        what.attrs["object"] = text("COMP")
        where = h5.create_group("where")
        where.attrs["projdef"] = text(DWD_PROJDEF)
        where.attrs["xsize"] = xsize if xsize is not None else cols
        where.attrs["ysize"] = rows
        where.attrs["xscale"] = 1000.0
        where.attrs["yscale"] = 1000.0
        where.attrs["UL_lon"] = DWD_UL_LON
        where.attrs["UL_lat"] = DWD_UL_LAT
        data1 = h5.create_group("dataset1/data1")
        data1.create_dataset("data", data=raw.astype(np.uint16), compression="gzip")
        data_what = data1.create_group("what")
        data_what.attrs["quantity"] = text(quantity)
        data_what.attrs["gain"] = gain
        data_what.attrs["offset"] = offset
        data_what.attrs["nodata"] = nodata
        data_what.attrs["undetect"] = undetect
    return buf.getvalue()
