"""Common test fixtures for RainRadarHub."""
import os
import struct
import sys

import pytest

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# The pytest-homeassistant plugin loads itself, so it is not listed here.


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from this project's custom_components.

    The plugin ships its own ``custom_components`` package (testing_config),
    which gets cached as the top-level ``custom_components`` module. Drop that
    cache so Home Assistant re-resolves it as a namespace package that also
    includes this project's ``custom_components`` directory.
    """
    sys.modules.pop("custom_components", None)
    return enable_custom_integrations


@pytest.fixture
def fake_rw_payload() -> bytes:
    """Decompressed RADOLAN RW product (900×1100 grid, all 5 mm/h)."""
    rows, cols = 900, 1100
    header = (
        f"RW0000002604260000BY {rows * cols * 2 + 100} "
        f"GP {rows}x{cols}VV 0INT  60MS 0<>"
    ).encode("ascii") + b"\x03"
    # raw value for 5.0 mm/h: 5.0 / 0.1 = 50
    return header + struct.pack(f"<{rows * cols}H", *([50] * (rows * cols)))
