"""Decoder for DWD RADOLAN composites in ODIM HDF5 format.

DWD publishes its radar composites (RW, RY, RV, ...) as files in the OPERA
Data Information Model for HDF5 (ODIM_H5). Each file carries its own
georeference in the root ``where`` group (PROJ definition, grid size, pixel
size and corner coordinates), so nothing about the grid is hard-coded here.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime

import h5py
import numpy as np
import pyproj

# ODIM quantity for a precipitation rate in mm/h
QUANTITY_RATE = "RATE"


@dataclass(frozen=True)
class RadarComposite:
    """One decoded radar composite.

    Attributes:
        values:    float32 array (rows, cols) in mm/h. Row 0 is the northern
                   edge. Pixels without data are NaN; "no precipitation
                   detected" is 0.0.
        projdef:   PROJ definition of the grid's coordinate system.
        x_ul:      x of the centre of the upper-left pixel, in metres.
        y_ul:      y of the centre of the upper-left pixel, in metres.
        xscale:    pixel width in metres (x grows with the column index).
        yscale:    pixel height in metres (y shrinks with the row index).
        timestamp: nominal time of the composite (UTC).
    """

    values: np.ndarray
    projdef: str
    x_ul: float
    y_ul: float
    xscale: float
    yscale: float
    timestamp: datetime


def decode_composite(data: bytes) -> RadarComposite:
    """Decode one ODIM HDF5 radar composite holding a precipitation rate.

    Raises:
        ValueError: if the file is not a readable HDF5 composite, holds
            another quantity than a rate, or its data does not match the
            grid described in ``where``.
    """
    try:
        h5 = h5py.File(io.BytesIO(data), "r")
    except OSError as exc:
        raise ValueError(f"Not a readable HDF5 file: {exc}") from exc

    with h5:
        try:
            where = h5["where"].attrs
            what = h5["what"].attrs
            data_what = h5["dataset1/data1/what"].attrs
            raw = h5["dataset1/data1/data"][()]
        except KeyError as exc:
            raise ValueError(f"Not an ODIM composite: missing {exc}") from exc

        quantity = _text(data_what["quantity"])
        if quantity != QUANTITY_RATE:
            raise ValueError(f"Unsupported quantity {quantity!r}, expected RATE")

        cols, rows = int(where["xsize"]), int(where["ysize"])
        if raw.shape != (rows, cols):
            raise ValueError(
                f"Data shape {raw.shape} does not match grid {rows}x{cols}"
            )

        projdef = _text(where["projdef"])
        xscale, yscale = float(where["xscale"]), float(where["yscale"])
        # UL_lon/UL_lat give the outer corner of the upper-left pixel
        x_corner, y_corner = pyproj.Proj(projdef)(
            float(where["UL_lon"]), float(where["UL_lat"])
        )

        gain = float(data_what["gain"])
        offset = float(data_what["offset"])
        nodata = float(data_what["nodata"])
        undetect = float(data_what["undetect"])
        timestamp = datetime.strptime(
            _text(what["date"]) + _text(what["time"]), "%Y%m%d%H%M%S"
        ).replace(tzinfo=UTC)

    values = (raw.astype(np.float32) * gain + offset).astype(np.float32)
    values[raw == undetect] = 0.0
    values[raw == nodata] = np.nan

    return RadarComposite(
        values=values,
        projdef=projdef,
        x_ul=x_corner + xscale / 2,
        y_ul=y_corner - yscale / 2,
        xscale=xscale,
        yscale=yscale,
        timestamp=timestamp,
    )


def _text(value: bytes | str) -> str:
    """Return an HDF5 string attribute as str (h5py yields bytes for some)."""
    return value.decode("ascii") if isinstance(value, bytes) else str(value)
