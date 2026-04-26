"""RADOLAN binary format decoder — pure Python, no wradlib."""
from __future__ import annotations

import numpy as np


def decode_radolan(data: bytes) -> tuple[np.ndarray, dict]:
    """Decode a RADOLAN binary blob.

    Returns:
        grid: numpy array shape (900, 1100), values in mm/h
        header: dict with parsed header fields (timestamp, product, ...)
    """
    # TODO: implement
    # 1. Find header end marker \\x03
    # 2. Parse ASCII header fields
    # 3. Read int16 binary values
    # 4. Apply scale factor (0.1 mm/h per unit)
    # 5. Handle no-data / clutter flags
    raise NotImplementedError
