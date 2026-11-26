"""Constants for RainRadarHub."""

DOMAIN = "rain_radar_hub"

# Config entry types
ENTRY_TYPE_HUB = "hub"
ENTRY_TYPE_REGION = "region"

# Hub config keys
CONF_TILE_PROVIDER = "tile_provider"
CONF_TILE_CACHE_SIZE_MB = "tile_cache_size_mb"
CONF_CUSTOM_TILE_URL = "custom_tile_url"

# Region config keys
CONF_REGION_NAME = "region_name"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_KM = "radius_km"
CONF_DEFAULT_ZOOM = "default_zoom"

# Tile provider keys
TILE_PROVIDER_CARTO_VOYAGER = "carto_voyager"
TILE_PROVIDER_OSM_STANDARD = "osm_standard"
TILE_PROVIDER_CUSTOM_URL = "custom_url"

TILE_PROVIDERS = {
    TILE_PROVIDER_CARTO_VOYAGER: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}.png",
    TILE_PROVIDER_OSM_STANDARD: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}
TILE_PROVIDER_SUBDOMAINS = {
    TILE_PROVIDER_CARTO_VOYAGER: ["a", "b", "c", "d"],
    TILE_PROVIDER_OSM_STANDARD: [],
}

# Defaults
DEFAULT_TILE_PROVIDER = TILE_PROVIDER_CARTO_VOYAGER
DEFAULT_TILE_CACHE_SIZE_MB = 500
DEFAULT_RADIUS_KM = 100
DEFAULT_ZOOM = 9

# Limits
MIN_TILE_CACHE_SIZE_MB = 50
MIN_RADIUS_KM = 25
MAX_RADIUS_KM = 500
MIN_ZOOM = 6
MAX_ZOOM = 12

# Frame pipeline
FRAME_UPDATE_INTERVAL_MINUTES = 5
FRAME_MAX_AGE_HOURS = 3

# DWD endpoints: RADOLAN RY, precipitation rate every 5 minutes (ODIM HDF5)
DWD_RY_BASE_URL = "https://opendata.dwd.de/weather/radar/radolan/ry/"

# RADOLAN composite grid as published in the HDF5 files (/where): 1100 columns
# x 1200 rows of 1 km, polar stereographic on WGS84. The upper-left pixel
# centre is at (0, 0); rows run southwards (decreasing y). The frame pipeline
# reads the geometry from each file; these values serve the config flow check.
DWD_GRID_PROJDEF = (
    "+proj=stere +lat_0=90 +lat_ts=60 +lon_0=10 "
    "+a=6378137 +b=6356752.3142451802 +no_defs "
    "+x_0=543196.83521776402 +y_0=3622588.8619310018 +units=m"
)
DWD_GRID_COLS = 1100
DWD_GRID_ROWS = 1200
DWD_GRID_STEP_M = 1000.0

# Color palette: (min_mm_h, max_mm_h, RGBA)
RAIN_PALETTE = [
    (0.0,   0.1,  (0,   0,   0,   0)),    # transparent
    (0.1,   0.5,  (180, 220, 255, 180)),   # very light blue
    (0.5,   1.0,  (120, 180, 240, 200)),   # light blue
    (1.0,   2.5,  (60,  130, 220, 220)),   # blue
    (2.5,   5.0,  (80,  200, 100, 230)),   # green
    (5.0,  10.0,  (245, 220, 60,  240)),   # yellow
    (10.0, 20.0,  (245, 140, 50,  245)),   # orange
    (20.0, 40.0,  (220, 40,  40,  250)),   # red
    (40.0, None,  (180, 30,  180, 255)),   # magenta
]

# HTTP API prefix
API_PREFIX = "/api/rain_radar_hub"

# User-Agent for tile provider requests
USER_AGENT = "RainRadarHub/0.1.0 (Home Assistant; +https://github.com/moerk-o/rain_radar_hub)"

# Runtime data keys (hass.data[DOMAIN])
DATA_TILE_PROXY = "tile_proxy"
DATA_COORDINATORS = "coordinators"
