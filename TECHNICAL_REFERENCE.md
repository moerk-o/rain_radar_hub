# Technical Reference: RainRadarHub

**Version:** 1.0.0
**Stand:** November 2026
**Target Platform:** Home Assistant Custom Integration
**Development Language:** English (code, comments, variables)
**Translations:** English (fallback), German
**Repository:** https://github.com/moerk-o/rain_radar_hub

The integration version is defined in `custom_components/rain_radar_hub/manifest.json`
(`version`), the minimum Home Assistant version in `hacs.json` (`homeassistant`). This
document does not repeat either value.

---

## 1. Project Overview

### 1.1 Purpose

RainRadarHub is the backend for an animated rain radar map on Home Assistant dashboards.
It downloads the RADOLAN RY precipitation rate from DWD Open Data every 5 minutes,
reprojects each composite for every configured region into a transparent PNG overlay, and
serves the overlays together with proxied and cached basemap tiles through HTTP endpoints
under `/api/rain_radar_hub/`.

The client is a Lovelace plugin for `ha-map-card` (`ha-map-card-plugin-rain-radar`, in
development and not published yet). The client only talks to Home Assistant. The target
devices are wall-mounted tablets that reach the Home Assistant server over the LAN and
have no internet access of their own (see the ADR in
[2.1](#21-adr-serving-all-image-data-through-home-assistant)).

The integration creates no entities, registers no platforms and no services. Its only
interface is the HTTP API in [2.8](#28-http-api).

Frames cover the past `FRAME_MAX_AGE_HOURS` (3 hours) in 5-minute steps. A nowcast (DWD
product RV) is not implemented.

### 1.2 Components and Entry Types

RainRadarHub is one of three components. The split of responsibilities is fixed: logic
does not move across component boundaries.

| Component | Repository | Does | Does not |
|-----------|------------|------|----------|
| Integration (this repo) | `moerk-o/rain_radar_hub` | Fetch, cache and serve tiles and frames | Display, animation, UI |
| Lovelace plugin | not published yet (planned: `ha-map-card-plugin-rain-radar`) | Time slider, animation, frame layer on the map | Fetch data, render the map |
| Map card (external) | `nathan-gs/ha-map-card` | Leaflet map, markers, tile layer, plugin host | Slider, radar logic |

Within the integration there are two kinds of config entries, distinguished by
`entry.data["entry_type"]` (see the ADR in [3.1](#31-adr-hub-entry-plus-region-entries)):

| Entry type | Constant | Count | Holds | Runtime object |
|------------|----------|-------|-------|----------------|
| `hub` | `ENTRY_TYPE_HUB` | exactly one | tile provider, custom tile URL, tile cache size | one `TileProxy`; registers the four HTTP views |
| `region` | `ENTRY_TYPE_REGION` | any number | name, `region_id`, center, radius, default zoom | one `FrameUpdateCoordinator` |

### 1.3 Naming and Conventions

- **Domain:** `rain_radar_hub` (`DOMAIN`).
- **API prefix:** `/api/rain_radar_hub` (`API_PREFIX`). The coordinator builds frame and
  colorbar URLs from `API_PREFIX`; the view routes in `http.py` are string literals with
  the same prefix.
- **`region_id`:** derived from the region name by `_to_region_id` in `config_flow.py`:
  lower-case, every run of characters outside `[a-z0-9]` replaced by `_`, leading and
  trailing `_` removed. `"Hamburg-Ost"` becomes `hamburg_ost`. Non-ASCII letters are
  replaced as well (`"München"` becomes `m_nchen`).
- **Frame file name:** UTC timestamp in ISO 8601 with a trailing `Z`, for example
  `2026-11-26T08:20:00Z.png` (`ts_to_filename` in `frame_pipeline.py`).
- **Coordinator name:** `rain_radar_hub_<region_id>`.
- **Storage root:** `<config>/.storage/rain_radar_hub/` (`storage.get_storage_root`), see
  [4.7](#47-storage-layout).
- **Loggers:** one per module, `custom_components.rain_radar_hub.<module>`.

---

## 2. Core Logic

### 2.1 ADR: Serving All Image Data Through Home Assistant

**Decision:** Everything the client displays (basemap tiles, radar frames, legend) is
delivered by Home Assistant through the integration's HTTP views. The client never
contacts DWD, CARTO or OpenStreetMap.

**Context:** The primary clients are wall-mounted tablets showing Home Assistant
dashboards. They reach the Home Assistant server over the LAN and have no internet access.
Several tablets may show the map at the same time, each with its own region, zoom level
and playback position.

**Why this approach:** A client without internet access can only show what Home Assistant
delivers, so Home Assistant has to be the single source for tiles and radar images. The
backend keeps no shared "current frame"; each plugin instance tracks its own frame index.
Several tablets therefore work on the same data without affecting each other.

**Alternatives considered:**
- Client loads basemap tiles and radar data directly from the providers — rejected
  because the target clients have no internet access.

**Consequences:** Home Assistant acts as a tile proxy with a cache, an upstream request
limit and a User-Agent ([2.7](#27-tile-proxy-and-lru-cache)), and as a renderer for radar
frames ([2.2](#22-frame-pipeline) to [2.6](#26-frame-storage-and-retention)). The interface
to the frontend is HTTP only; there are no entities, services or WebSocket commands. All
views require Home Assistant authentication ([2.8](#28-http-api)). The first request for
any tile needs internet access on the Home Assistant host.

### 2.2 Frame Pipeline

One `FrameUpdateCoordinator` per region runs the pipeline in `_async_update_data`:

```
1. fetch_radar_frames(session, frames_dir, sw_ne_bounds,
                      lookback_minutes=FRAME_MAX_AGE_HOURS * 60)
   a. [executor] create frames_dir if needed, collect the names of existing *.png
      (_prepare_frames_dir)
   b. GET DWD_RY_BASE_URL (HTML directory listing); collect every href ending in ".hdf5"
      (_list_dwd_directory)
   c. Parse each name as raa01-ry_10000-YYMMDDHHMM-dwd---bin.hdf5 (_parse_ry_filename);
      skip names that do not match (including the "latest" file) and timestamps older
      than now - lookback
   d. Skip the timestamp if <ts>.png is in the set from step a
   e. Download the file (_download), then [executor] decode_composite ->
      reproject_to_png -> write <frames_dir>/<ts>.png (_render_frame)
   f. Any exception in e: log WARNING, continue with the next file
2. [executor] cleanup_old_frames(frames_dir, FRAME_MAX_AGE_HOURS)
3. [executor] _build_inventory(frames_dir, region_id) -> coordinator data (see 2.8)
```

**Error handling:** An exception from the directory listing (connection error, or an HTTP
error status through `raise_for_status`) leaves `fetch_radar_frames` and is wrapped as
`UpdateFailed("DWD radar fetch failed: ...")`. Cleanup is skipped in that case, and the
`DataUpdateCoordinator` keeps the previous inventory. Failures of single frames never fail
the update.

**HTTP details:** All DWD requests use Home Assistant's shared aiohttp session
(`async_get_clientsession`) and send `USER_AGENT`. The integration sets no request
timeout of its own. The RY directory listing holds about 48 hours of files; only the
last 180 minutes are processed.

**Frame timestamp:** The file name of a frame comes from the timestamp in the DWD file
name. `decode_composite` also reads the composite time (`what/date`, `what/time`) into
`RadarComposite.timestamp`; the pipeline does not use it.

**Per-region work:** Every region runs its own pipeline. With several regions, each DWD file
is downloaded, decoded and reprojected once per region; there is no shared download or
decode cache. Within one region, frames are processed one after another.

#### ADR: RY precipitation rate instead of RW

**Decision:** The pipeline uses the RADOLAN product RY (`DWD_RY_BASE_URL`,
`raa01-ry_10000-YYMMDDHHMM-dwd---bin.hdf5`), not RW.

**Context:** RW is an hourly precipitation sum, published every 10 minutes. RY is the
current precipitation rate in mm/h, published every 5 minutes. Both are published as ODIM
HDF5 composites.

**Why this approach:** Each RW value is the rain of the past hour, so an animation of RW
frames shows smeared accumulations instead of where it rains at that moment. RY shows the
rate at each step, in 5-minute steps.

**Alternatives considered:**
- RW — rejected because an animation of hourly sums does not show the movement of the
  rain areas.

**Consequences:** A region holds about 36 frames (180 minutes in 5-minute steps). The
palette thresholds in mm/h ([2.5](#25-color-palette-and-colorbar)) apply to RY values
directly. The nowcast product RV is published as one tar archive per 5-minute step with 25
HDF5 files (forecast steps 0 to 120 minutes); the decoder in
[2.3](#23-decoding-odim-hdf5-composites) is intended to be reused for it.

#### ADR: Blocking work in the executor

**Decision:** Decoding, reprojection, the PNG write and the scans of the frames directory
run in the executor: `loop.run_in_executor(None, ...)` in `fetch_radar_frames`
(`_prepare_frames_dir`, `_render_frame`) and `hass.async_add_executor_job` in the
coordinator (`cleanup_old_frames`, `_build_inventory`).

**Context:** These steps block: h5py, pyproj, numpy and Pillow do synchronous CPU work
(one frame transforms 1,048,576 coordinates), and directory scans and file writes are
synchronous system calls. Home Assistant reports calls such as `glob`, `os.scandir` and
`open` inside the event loop as blocking calls.

**Why this approach:** Running the work in the executor keeps the event loop free while a
frame is decoded and rendered, and avoids Home Assistant's blocking-call reports.

**Consequences:** The directory listing and the downloads stay in the event loop (aiohttp).
Frames of one region are rendered sequentially; several regions can render at the same time
in Home Assistant's default executor. The rule covers the frame pipeline and the
coordinator; `TileProxy` and `FrameView` access their files directly in the event loop.

### 2.3 Decoding ODIM HDF5 Composites

`decode_composite(data)` in `radolan_decoder.py` takes the bytes of one ODIM HDF5 file and
returns a `RadarComposite`:

1. Open the bytes with h5py (`io.BytesIO`). An unreadable file raises `ValueError`.
2. Read the attributes of `where` and `what`, the attributes of `dataset1/data1/what` and
   the array `dataset1/data1/data`. A missing group raises `ValueError`.
3. Require `quantity == "RATE"` (`QUANTITY_RATE`), otherwise `ValueError`.
4. Require the array shape to equal `(ysize, xsize)` from `where`, otherwise `ValueError`.
5. Values in mm/h: `raw × gain + offset` as `float32`; pixels equal to `undetect` become
   `0.0` (no precipitation detected), pixels equal to `nodata` become `NaN`.
6. Geometry from `where`: `projdef`, `xscale`, `yscale`, and `UL_lon`/`UL_lat`, the outer
   corner of the upper-left pixel. The corner is projected with `projdef` and shifted by
   half a pixel to the pixel centre: `x_ul = x_corner + xscale / 2`,
   `y_ul = y_corner − yscale / 2`.
7. Timestamp from `what/date` and `what/time`, as UTC.

String attributes may arrive as `bytes` or `str`; `_text` normalises them.

| `RadarComposite` field | Content |
|------------------------|---------|
| `values` | `float32` array `(rows, cols)` in mm/h; row 0 is the northern edge; `NaN` = no data |
| `projdef` | PROJ definition of the grid |
| `x_ul`, `y_ul` | centre of the upper-left pixel, metres in `projdef` |
| `xscale`, `yscale` | pixel size in metres; x grows with the column index, y shrinks with the row index |
| `timestamp` | nominal time of the composite (UTC) |

**Grid as published by DWD** (root `where` group of the RY files): 1100 columns × 1200
rows of 1 km, polar stereographic on the WGS84 ellipsoid (`lat_0=90`, `lat_ts=60`,
`lon_0=10`, with false easting/northing), upper-left pixel centre at (0, 0), rows running
south. The pixel centres span about 45.7° N to 55.9° N and 1.5° E to 18.7° E. `const.py`
holds the same geometry as `DWD_GRID_PROJDEF`, `DWD_GRID_COLS`, `DWD_GRID_ROWS` and
`DWD_GRID_STEP_M` for the config flow check ([3.3](#33-region-setup)).

#### ADR: Reading ODIM HDF5 with h5py

**Decision:** Radar composites are read with h5py (`h5py>=3.12,<4` in `manifest.json`).

**Context:** DWD publishes its radar composites (RW, RY, SF; RV as a tar archive of HDF5
files) only in the OPERA ODIM HDF5 format. The earlier RADOLAN binary files (bz2) are no
longer published. The datasets in these files are chunked and gzip-compressed.

**Why this approach:** h5py reads chunked and compressed HDF5 datasets and their
attributes, so the decoder only has to know the ODIM group and attribute names.

**Alternatives considered:**
- Own HDF5 parser — rejected because the format (chunked, gzip-compressed datasets) is too
  complex to reimplement.
- Another radar provider — rejected because DWD is fixed as the only radar source.
- `wradlib` — rejected earlier as too heavyweight a dependency for one decoding step.

**Consequences:** h5py is a binary package that bundles the HDF5 library. For CPython
3.14 there are wheels for manylinux and musllinux on x86_64 and aarch64 (about 5.2 to
5.4 MB each); installed, the package takes about 17 MB. The decoder handles one quantity
(`RATE`); a product with another quantity is rejected with `ValueError`.

#### ADR: Grid geometry from each file

**Decision:** The reprojection takes the grid geometry (`projdef`, pixel size, upper-left
pixel centre) from the `where` group of each file. The `DWD_GRID_*` constants in
`const.py` are only used for the config flow check.

**Context:** An earlier binary decoder used hard-coded grid constants: a sphere instead of
the WGS84 ellipsoid, 900 rows instead of 1200, and corner coordinates that were not taken
from DWD data. They did not match the grid DWD publishes.

**Why this approach:** Every ODIM file carries its own georeference. Reading it removes
hand-maintained constants as a source of error, and a change of the grid on the DWD side
reaches the reprojection without a code change.

**Consequences:** The row orientation (row 0 = north) is not read from the file; it is
built into the decoder and the reprojection. It was checked against a real RY file: the
no-data mask matches 150 km circles around the DWD radar sites with an IoU of 0.97 when
read top-down and 0.83 when read bottom-up. The config flow has no file at hand, so
`DWD_GRID_*` repeats the geometry and must be updated if DWD changes the grid.
`tests/odim.py` copies the georeference of a real RY file.

### 2.4 Reprojection

`reproject_to_png(composite, region_bounds, output_size=(OUTPUT_WIDTH, OUTPUT_HEIGHT))`
in `frame_pipeline.py` produces one overlay image. `OUTPUT_WIDTH` and `OUTPUT_HEIGHT` are
1024 (module constants in `frame_pipeline.py`). `region_bounds` is
`((lat_sw, lon_sw), (lat_ne, lon_ne))` in WGS84 degrees.

1. Transform the SW and NE corners from EPSG:4326 to Web Mercator (EPSG:3857).
2. Build the output grid: 1024 evenly spaced x values from `x_min` to `x_max` and 1024
   y values from `y_max` to `y_min` (row 0 is north); both edges are included.
3. Transform all 1,048,576 output coordinates from EPSG:3857 to the composite's CRS
   (`composite.projdef`) in one vectorised pyproj call (`always_xy=True`).
4. Convert to fractional pixel indices:
   `col = (x − composite.x_ul) / composite.xscale`,
   `row = (composite.y_ul − y) / composite.yscale`.
5. Bilinear interpolation over the four neighbouring pixels (`_bilinear_interpolate`).
   The result is `NaN` if any of the four is `NaN` or outside the grid.
6. Map values to RGBA with the palette ([2.5](#25-color-palette-and-colorbar)).
7. Encode as RGBA PNG with Pillow (`optimize=True`).

The pyproj CRS and transformer objects are created on every call.

**Region bounding box:** `_compute_bounds(lat, lon, radius_km)` in `coordinator.py`
computes `Δlat = degrees(radius / 6371 km)` and
`Δlon = degrees(radius / (6371 km × cos(lat)))` and returns the box around the center as
`(lon_min, lat_min, lon_max, lat_max)` (`region_bounds` property). The coordinator passes
it to the pipeline as `((lat_min, lon_min), (lat_max, lon_max))` (`_sw_ne_bounds`). The
box is about `2 × radius` km wide and high. At the default radius of 100 km one 1024 px
frame covers about 200 km, about 0.2 km per pixel; at the maximum of 500 km it is about
1 km per pixel. A RADOLAN pixel is 1 km.

The config flow only checks that the region center lies inside the grid
([3.3](#33-region-setup)). Parts of the box outside the grid stay transparent.

#### ADR: Per-region Web Mercator overlay by inverse mapping

**Decision:** For each region and DWD timestamp, the backend renders one 1024 × 1024 px
PNG on a regular Web Mercator grid. Each output pixel is mapped back into the radar grid
(inverse mapping) and its value is interpolated bilinearly.

**Context:** The radar data lies on a polar stereographic grid with 1 km pixels. The
frontend (Leaflet, through `ha-map-card`) displays Web Mercator XYZ basemap tiles and
places each frame as an image between a SW and a NE corner in WGS84.

**Why this approach:** An image stretched between two corners on a Web Mercator map only
lines up with the basemap if its pixels are evenly spaced in Web Mercator, so the frame is
rendered on a regular EPSG:3857 grid rather than in the DWD projection.

**Consequences:** Inverse mapping assigns exactly one value to every output pixel, so the
image has no gaps regardless of the ratio between radar pixel size and output pixel size.
The CPU cost per frame is one pyproj transformation of 1,048,576 points plus interpolation
and PNG encoding. It grows with regions × frames and is independent of the number of
clients. The overlay covers the region's bounding box only; outside it the map shows
basemap without radar. Because interpolation needs all four neighbours, every output pixel
within one radar pixel of a `NaN` pixel is transparent.

### 2.5 Color Palette and Colorbar

`RAIN_PALETTE` in `const.py` maps mm/h to RGBA. Each band covers `min ≤ value < max`; the
last band has no upper bound.

| mm/h | Color | RGBA |
|------|-------|------|
| < 0.1 | transparent | (0, 0, 0, 0) |
| 0.1 – 0.5 | very light blue | (180, 220, 255, 180) |
| 0.5 – 1.0 | light blue | (120, 180, 240, 200) |
| 1.0 – 2.5 | blue | (60, 130, 220, 220) |
| 2.5 – 5.0 | green | (80, 200, 100, 230) |
| 5.0 – 10.0 | yellow | (245, 220, 60, 240) |
| 10.0 – 20.0 | orange | (245, 140, 50, 245) |
| 20.0 – 40.0 | red | (220, 40, 40, 250) |
| ≥ 40.0 | magenta | (180, 30, 180, 255) |

`NaN` (no data, outside the grid) is transparent as well.

`generate_colorbar(width=40, height=200)` draws the eight non-transparent bands as equal
horizontal stripes of 25 px, highest intensity at the top. The image has no text labels.
Frames and colorbar read the same constant, so the legend always matches the overlay. Each
coordinator generates the colorbar on first access and keeps the bytes in memory
(`colorbar_png` property).

### 2.6 Frame Storage and Retention

Frames are stored at
`<config>/.storage/rain_radar_hub/regions/<region_id>/frames/<YYYY-MM-DDTHH:MM:SSZ>.png`.

- **Retention:** `cleanup_old_frames` deletes every PNG whose file-name timestamp is older
  than `FRAME_MAX_AGE_HOURS` (3 hours). It reads the timestamp from the file name, not the
  file modification time. Files whose names do not parse are left alone.
- **Lookback:** the same constant sets the download window, `FRAME_MAX_AGE_HOURS × 60`
  = 180 minutes.
- **Inventory:** `_build_inventory` lists all `*.png` files in the directory, sorted by
  name. Because of the ISO 8601 format, name order equals time order.
- **Removal:** deleting a region entry deletes its `frames/` directory
  ([4.6](#46-entry-type-routing)).

#### ADR: Pre-rendered PNG frames on disk

**Decision:** The coordinator renders each frame once per DWD timestamp and region, writes
it as an RGBA PNG into the region's frames directory, and `FrameView` serves the file.
Frames older than `FRAME_MAX_AGE_HOURS` are deleted in each update cycle.

**Context:** The integration's job is to fetch, cache and serve; display and animation
belong to the plugin. Once DWD has published a timestamp, the frame for that timestamp
does not change.

**Why this approach:** Rendering in the backend gives clients finished overlays, so they
need no radar logic. Because a frame never changes for its timestamp, the pipeline skips
every timestamp whose PNG already exists: each DWD file is processed once per region, not
once per update cycle. Deleting by age keeps disk usage bounded during long uptimes.

**Consequences:** Frames survive a Home Assistant restart and are reused afterwards. The
file name is the only record of a frame; the inventory is a directory scan. The images are
RGBA PNG; a palette PNG (PNG-8 with transparency) was left open as a size optimisation,
to be decided after a visual comparison, and is not implemented.

### 2.7 Tile Proxy and LRU Cache

`TileProxy` (`tile_proxy.py`) exists once per Home Assistant instance and is created by the
hub entry.

**URL template:**

| `tile_provider` | Template (`TILE_PROVIDERS`) | Subdomains (`TILE_PROVIDER_SUBDOMAINS`) |
|-----------------|------------------------------|------------------------------------------|
| `carto_voyager` (default) | `https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}.png` | `a`, `b`, `c`, `d`, one picked at random per request |
| `osm_standard` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | none |
| `custom_url` | user template, must contain `{z}`, `{x}`, `{y}` | none; `{s}` is replaced by an empty string |

A non-empty `custom_tile_url` in the hub entry takes precedence: `TileProxy` uses it as
the template whatever `tile_provider` says. Otherwise it uses the template for
`tile_provider`. Tiles are stored under the `tile_provider` key in both cases.

**Storage:**
- Tile files: `<config>/.storage/rain_radar_hub/tile_cache/<provider_key>/<z>/<x>/<y>.png`.
- Metadata: SQLite database `<config>/.storage/rain_radar_hub/tile_cache.db`, accessed via
  `aiosqlite`. One connection stays open from hub setup to hub unload.

```sql
CREATE TABLE IF NOT EXISTS tiles (
    provider    TEXT    NOT NULL,
    z           INTEGER NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    filepath    TEXT    NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    accessed_at REAL    NOT NULL,   -- epoch seconds
    created_at  REAL    NOT NULL,   -- epoch seconds
    PRIMARY KEY (provider, z, x, y)
);
CREATE INDEX IF NOT EXISTS idx_tiles_accessed ON tiles (provider, accessed_at);
```

**`get_tile(session, z, x, y)`:**

```
1. Look up the row for (provider, z, x, y)
   - row exists, created_at not older than TILE_EXPIRY_DAYS (30), file exists:
       update accessed_at -> return file bytes
   - row exists, file missing: delete row, continue with 2
   - row older than 30 days or no row: continue with 2
2. Upstream GET under asyncio.Semaphore(MAX_UPSTREAM_REQUESTS = 2), header USER_AGENT,
   raise_for_status
3. Write file, INSERT OR REPLACE row (accessed_at = created_at = now)
4. Evict if needed, return bytes
```

**Eviction:** `SUM(size_bytes)` over the current provider. While the sum exceeds the
limit, the 20 rows with the oldest `accessed_at` are fetched and deleted one by one (file
and row) until the sum is at or below the limit. Eviction runs only after an upstream
fetch, not on cache hits and not at setup. The limit is `tile_cache_size_mb × 1,048,576`
bytes; `size_bytes` is the tile payload length, so file system overhead and the database
are not counted.

**Concurrency:** Concurrent requests for the same uncached tile are not merged; each one
fetches upstream (at most two at a time).

`wipe_cache()` and `clear_provider()` are not called by production code.
`MAX_UPSTREAM_REQUESTS` and `TILE_EXPIRY_DAYS` are module constants in `tile_proxy.py`, not
in `const.py`.

#### ADR: Passive tile cache with SQLite metadata and LRU eviction

**Decision:** Basemap tiles are fetched only when a client requests them, stored as files,
tracked in a SQLite table and evicted least-recently-used first once their total size
exceeds a limit the user sets. Tiles older than 30 days are fetched again.

**Context:** Tablets need basemap tiles but cannot reach the tile provider
([2.1](#21-adr-serving-all-image-data-through-home-assistant)). OpenStreetMap requires an
identifying User-Agent, and requests to a provider are limited to two in parallel. The
cache shares the disk with the rest of the Home Assistant configuration.

**Why this approach:** A passive proxy cache stores only what clients actually display;
after the first view of an area, repeated requests are served from the LAN. A
user-configurable limit (default `DEFAULT_TILE_CACHE_SIZE_MB` = 500 MB, minimum
`MIN_TILE_CACHE_SIZE_MB` = 50 MB) with LRU eviction keeps disk usage bounded and keeps the
tiles of the areas shown regularly. One cache serves all regions because all regions use
the same basemap.

**Alternatives considered:**
- Pre-caching the tiles of configured regions — excluded from the scope of the first
  version; no tile is downloaded before a client asks for it.

**Consequences:** The SQLite table answers "total size" (`SUM`) and "least recently used"
(`ORDER BY accessed_at`) without walking the tile directory. Every cache hit writes to the
database (update of `accessed_at` plus commit). Files and rows can drift apart: a file
deleted outside the integration is noticed on the next access; a file without a row is
never counted or evicted. `aiosqlite` is a manifest requirement. Upstream errors reach the
client as HTTP 502.

### 2.8 HTTP API

All views are `HomeAssistantView` subclasses in `http.py` with `requires_auth = True`.

| Method | Path | View | Response | Errors |
|--------|------|------|----------|--------|
| GET | `/api/rain_radar_hub/tiles/{z}/{x}/{y}.png` | `TileView` | `image/png` from `TileProxy.get_tile` | 400 if z/x/y are not integers; 503 if no `TileProxy` is loaded; 502 on any exception from `get_tile` |
| GET | `/api/rain_radar_hub/regions/{region_id}/manifest.json` | `ManifestView` | JSON inventory (below) | 404 for an unknown `region_id` |
| GET | `/api/rain_radar_hub/regions/{region_id}/frames/{ts}.png` | `FrameView` | `image/png`, file content | 404 for an unknown `region_id` or missing file |
| GET | `/api/rain_radar_hub/regions/{region_id}/colorbar.png` | `ColorbarView` | `image/png` (2.5) | 404 for an unknown `region_id` |

**Manifest response** (not to be confused with the integration's `manifest.json`): the
coordinator data as built by `_build_inventory`:

```json
{
  "frames": [
    {
      "timestamp": "2026-11-26T08:20:00Z",
      "url": "/api/rain_radar_hub/regions/hamburg/frames/2026-11-26T08:20:00Z.png"
    }
  ],
  "colorbar_url": "/api/rain_radar_hub/regions/hamburg/colorbar.png"
}
```

`frames` is sorted ascending by `timestamp`. If the coordinator has no data, the view
returns `{"frames": [], "colorbar_url": ""}`. Region bounds, center and `default_zoom` are
not part of the response.

**Authentication:** Home Assistant's HTTP auth middleware accepts an access token in the
`Authorization: Bearer` header or a signed path (`authSig` query parameter, issued by the
WebSocket command `auth/sign_path`). Requests without either receive 401.

**Headers:** The views set `Content-Type` only; no `Cache-Control` headers are sent.

**Registration:** The hub entry registers the four views during its setup, once per Home
Assistant process (flag `views_registered` in `hass.data[DOMAIN]`). Home Assistant cannot
unregister views. The views look up `TileProxy` and coordinators in `hass.data[DOMAIN]`
on every request, so a reloaded hub or region is picked up without registering again.
After the hub is unloaded, `TileView` answers 503. If no hub entry has been set up since
Home Assistant started, none of the four routes exists, including the region endpoints.

**Input handling:** Route parameters cannot contain `/`, so `FrameView` only reads files
inside the region's frames directory. `TileView` forwards any integer z/x/y upstream
without a range check. The tile response is always labelled `image/png`, regardless of
what the upstream server returned.

---

## 3. ConfigFlow

### 3.1 ADR: Hub entry plus region entries

**Decision:** One config flow creates two kinds of entries: exactly one hub entry (tile
provider, custom tile URL, cache size) and any number of region entries (name, center,
radius, default zoom), distinguished by `entry.data["entry_type"]`.

**Context:** The tile cache is one store shared by all regions. Radar frames, in contrast,
are rendered and stored per region.

**Why this approach:** Tile provider and cache size belong to the shared cache and are not
meant to be set per region. Giving every region its own entry, coordinator and frame
directory lets regions be added and removed independently.

**Alternatives considered:**
- Tile provider and cache size as fields of each region entry — rejected because there is
  only one tile cache.

**Consequences:**
- `async_step_user` routes by state: if no entry with `entry_type == "hub"` exists, it
  opens the hub step, otherwise the region steps.
- Hub uniqueness: the hub step sets `unique_id = DOMAIN` and aborts with
  `already_configured`. Region entries have no unique ID; their uniqueness is a comparison
  of `region_id` across existing region entries.
- The hub owns the shared runtime parts (`TileProxy`, HTTP views). A region entry sets up
  without a hub, but then has no tile endpoint, and after a restart no endpoint at all
  ([2.8](#28-http-api)).
- Region entries cannot be edited; a change means deleting the region and adding it again.
- Changing the tile provider is not offered: it would require cache invalidation for many
  edge cases. To switch, delete the hub entry and create it again.

`ConfigFlow.VERSION` is 1; there is no `async_migrate_entry`.

### 3.2 Hub Setup

Step `hub`, one form:

| Field | Key | Type | Default | Validation | Error key |
|-------|-----|------|---------|------------|-----------|
| Tile provider | `tile_provider` | `vol.In` of `carto_voyager`, `osm_standard`, `custom_url` | `DEFAULT_TILE_PROVIDER` (`carto_voyager`) | — | — |
| Custom tile URL | `custom_tile_url` | string, optional | `""` | only if provider is `custom_url`: must contain `{z}`, `{x}` and `{y}` | `invalid_custom_url` |
| Tile cache size (MB) | `tile_cache_size_mb` | `vol.Coerce(int)` | `DEFAULT_TILE_CACHE_SIZE_MB` (500) | ≥ `MIN_TILE_CACHE_SIZE_MB` (50) | `cache_size_too_small` |

Entry title: `RainRadarHub`. Entry data: `entry_type` (`hub`), `tile_provider`,
`custom_tile_url`, `tile_cache_size_mb`.

### 3.3 Region Setup

Three steps; the values are collected in `self._region_data`.

| Step | Field | Key | Type | Default | Validation | Error key |
|------|-------|-----|------|---------|------------|-----------|
| `region_name` | Region name | `region_name` | string | — | stripped; its `region_id` must not exist yet | `region_already_exists` |
| `region_location` | Latitude | `latitude` | `vol.Coerce(float)` | — | center inside the DWD grid | `outside_dwd_grid` (form-level, `base`) |
| `region_location` | Longitude | `longitude` | `vol.Coerce(float)` | — | (checked together with latitude) | — |
| `region_map` | Radius (km) | `radius_km` | `vol.Coerce(int)` | `DEFAULT_RADIUS_KM` (100) | `MIN_RADIUS_KM` (25) – `MAX_RADIUS_KM` (500) | `radius_out_of_range` |
| `region_map` | Default zoom | `default_zoom` | `vol.Coerce(int)` | `DEFAULT_ZOOM` (9) | `MIN_ZOOM` (6) – `MAX_ZOOM` (12) | `zoom_out_of_range` |

**Grid check:** `_is_within_dwd_grid(lat, lon)` projects the center with
`DWD_GRID_PROJDEF` and computes `col = x / DWD_GRID_STEP_M + 0.5` and
`row = −y / DWD_GRID_STEP_M + 0.5` (the upper-left pixel is centred on (0, 0)). The center
is accepted if `0 ≤ col < DWD_GRID_COLS` and `0 ≤ row < DWD_GRID_ROWS`, that is inside the
outer pixel edges of the grid ([2.3](#23-decoding-odim-hdf5-composites)). Only the center
is checked, not the area covered by the radius. The `pyproj.Proj` object is built once at
module import.

Entry title: `Region: <region_name>`. Entry data: `entry_type` (`region`), `region_id`,
`region_name`, `latitude`, `longitude`, `radius_km`, `default_zoom`.

`default_zoom` is stored and passed to the coordinator, but no backend code uses it and no
endpoint returns it.

### 3.4 Options Flow

Step `init`, one field:

| Field | Key | Default | Validation | Error key |
|-------|-----|---------|------------|-----------|
| Tile cache size (MB) | `tile_cache_size_mb` | current value (`entry.options`, then `entry.data`, then 500) | ≥ `MIN_TILE_CACHE_SIZE_MB` (50) | `cache_size_too_small` |

The value is stored in `entry.options`. An update listener on the hub entry reloads it;
the new `TileProxy` uses the new limit. Existing tiles stay in place. If the cache is
larger than the new limit, LRU eviction trims it after the next upstream download
([2.7](#27-tile-proxy-and-lru-cache)). The dialog text says the same.

`async_get_options_flow` does not check the entry type, so region entries offer the same
dialog. No code reads options of region entries.

---

## 4. Technical Reference

### 4.1 Project Language and Code Style

English throughout: code, comments, docstrings, UI strings (German as translation).
Linting with ruff (`pyproject.toml`: `target-version = "py314"`, `line-length = 88`, rule
sets E, F, W, I, B, UP, SIM). The pipeline and decoder modules use Google-style docstrings
with `Args:`/`Returns:`/`Raises:`. Type hints are used on most functions; the HTTP view
methods are not annotated.

### 4.2 Distribution (Marketplace / HACS)

- **Home Assistant 2026.11 and newer:** Marketplace (Settings → Marketplace → Add from
  link). The repository is not in the default catalog.
- **Home Assistant 2026.10 and older:** HACS, custom repository `moerk-o/rain_radar_hub`,
  category Integration.
- **`hacs.json`:** `homeassistant` (minimum version, see [4.4](#44-dependencies) for its
  reason), `zip_release: true`, `filename: rain_radar_hub.zip`, `render_readme: true`.
- **Brand images:** `custom_components/rain_radar_hub/brand/icon.png` (256 × 256 px) and
  `icon@2x.png` (512 × 512 px). The SVG source is `assets/icon.svg` in the repository
  root; it is not part of the ZIP.
- **Release asset:** `.github/workflows/release.yml` runs when a GitHub release is
  published. Job `test` installs `requirements-test.txt` on Python 3.14 and runs pytest
  with coverage; job `release` then zips the contents of
  `custom_components/rain_radar_hub/` (files at the archive root) as `rain_radar_hub.zip`
  and attaches it to the release.
- **Validation:** `.github/workflows/validate.yaml` runs hassfest and the HACS action on
  push, pull request, daily at 00:00 UTC and on manual dispatch.

### 4.3 File Structure

```
RainRadarHub/
├── custom_components/
│   └── rain_radar_hub/
│       ├── __init__.py          # Entry setup/unload/remove, routes hub vs region, registers views
│       ├── config_flow.py       # ConfigFlow (hub step, three region steps) + OptionsFlow
│       ├── const.py             # Domain, config keys, defaults, limits, DWD URL and grid, palette
│       ├── coordinator.py       # FrameUpdateCoordinator (one per region), bounds, inventory
│       ├── frame_pipeline.py    # DWD listing/download, reprojection, palette, colorbar, cleanup
│       ├── radolan_decoder.py   # ODIM HDF5 decoder (decode_composite, RadarComposite)
│       ├── tile_proxy.py        # TileProxy: upstream fetch, file cache, SQLite LRU
│       ├── http.py              # TileView, ManifestView, FrameView, ColorbarView
│       ├── storage.py           # Path helpers below <config>/.storage/rain_radar_hub/
│       ├── manifest.json
│       ├── strings.json         # English UI strings (source)
│       ├── brand/               # icon.png, icon@2x.png
│       └── translations/
│           ├── en.json
│           └── de.json
├── tests/
│   ├── conftest.py              # Integration loading, ODIM fixtures
│   ├── odim.py                  # Synthetic ODIM HDF5 composites with the DWD georeference
│   └── test_*.py                # One test module per production module
├── assets/icon.svg              # Source of the brand images
├── .github/workflows/
│   ├── validate.yaml            # hassfest + HACS validation
│   └── release.yml              # Tests, then ZIP asset on release
├── hacs.json
├── pyproject.toml               # pytest, coverage and ruff settings
├── requirements-test.txt
├── LICENSE                      # MIT
├── README.md
└── RELEASENOTES.md
```

### 4.4 Dependencies

| Package | Used for | Declared in |
|---------|----------|-------------|
| h5py | Reading ODIM HDF5 composites | `manifest.json` requirements |
| numpy | Value arrays, interpolation, palette, colorbar | `manifest.json` requirements |
| pyproj | Coordinate transformations (EPSG:4326, EPSG:3857, DWD grid), grid check | `manifest.json` requirements |
| aiosqlite | Async access to the tile cache database | `manifest.json` requirements |
| Pillow | PNG encoding of frames and colorbar | not declared: ships with Home Assistant, and hassfest rejects listing it |
| aiohttp | HTTP client (Home Assistant's shared session) and view responses | part of Home Assistant |
| voluptuous | Config flow schemas | part of Home Assistant |
| `re`, `io`, `sqlite3` (via aiosqlite) | Listing parsing, in-memory files, cache metadata | Python standard library |

`manifest.json` declares `dependencies: ["http"]` because the integration registers HTTP
views.

**numpy and the minimum Home Assistant version:** Home Assistant pins numpy itself
(`package_constraints.txt`), so the integration always runs with Home Assistant's numpy.
The requirement `numpy>=2.0,<3` excludes releases that pin numpy 1.x; the `homeassistant`
minimum in `hacs.json` is the first release that pins numpy 2. `requirements-test.txt`
pins numpy to the version of the Home Assistant release the tests run against.

### 4.5 DataUpdateCoordinator

`FrameUpdateCoordinator(hass, region_id, region_config)` in `coordinator.py`:

- one instance per region entry, stored in `hass.data[DOMAIN]["coordinators"][region_id]`;
- `name = "rain_radar_hub_<region_id>"`,
  `update_interval = timedelta(minutes=FRAME_UPDATE_INTERVAL_MINUTES)` (5 minutes);
- the config entry is not passed explicitly; `DataUpdateCoordinator` takes it from the
  setup context;
- `data` is the inventory dict ([2.8](#28-http-api));
- setup calls `async_config_entry_first_refresh`. If the first update fails, it raises
  `ConfigEntryNotReady` and Home Assistant retries the setup later; no coordinator is
  stored until then, so the region endpoints answer 404.

#### ADR: Five-minute polling with a no-op listener

**Decision:** Every region coordinator uses `update_interval` =
`FRAME_UPDATE_INTERVAL_MINUTES` = 5 minutes. After the first refresh, `_async_setup_region`
registers a listener that does nothing:
`entry.async_on_unload(coord.async_add_listener(lambda: None))`.

**Context:** DWD publishes a new RY composite every 5 minutes. Home Assistant's
`DataUpdateCoordinator` schedules interval refreshes only while at least one listener is
registered; listeners are normally entities. The integration has no entities, and the
HTTP views read `coordinator.data` without subscribing.

**Why this approach:** The interval matches the RY publication interval, so a new
composite is picked up within one interval. A cycle without new files is cheap: existing
timestamps are skipped, so the cycle costs one directory listing plus two local directory
scans per region. Without a listener the coordinator would run only its first refresh.

**Consequences:** Adding the listener schedules the next refresh one interval later; from
then on each refresh schedules the next. Unloading the entry removes the listener, which
stops the polling. With N regions, the DWD directory listing is requested N times per
interval. A failed cycle (`UpdateFailed`) keeps the last inventory and the frames on disk;
the next cycle runs as scheduled. `tests/test_init.py` (`TestRegionPolling`) checks the
periodic refresh with a real `hass` instance and `async_fire_time_changed`.

### 4.6 Entry Type Routing

`hass.data[DOMAIN]` is created on the first `async_setup_entry` call:

| Key | Constant | Content |
|-----|----------|---------|
| `tile_proxy` | `DATA_TILE_PROXY` | `TileProxy` or `None` |
| `coordinators` | `DATA_COORDINATORS` | `dict[region_id, FrameUpdateCoordinator]` |
| `views_registered` | `_KEY_VIEWS_REGISTERED` (`__init__.py`) | `bool` |

| Hook | Hub entry | Region entry |
|------|-----------|--------------|
| `async_setup_entry` | Create `TileProxy`, create directories, open the database, create the schema; register the four views if not done yet; add the update listener | Create `FrameUpdateCoordinator`, run the first refresh, register the no-op listener, store it under `region_id` |
| `async_unload_entry` | Close the database, set `tile_proxy` to `None` | Remove the coordinator from `coordinators` |
| `async_remove_entry` | Delete `tile_cache.db` and the `tile_cache/` directory | Delete `regions/<region_id>/frames/`; the empty `regions/<region_id>/` directory remains |

An unknown `entry_type` logs an error and makes `async_setup_entry` return `False`.
`async_unload_entry` always returns `True` (no platforms to unload) and also works when
`hass.data[DOMAIN]` does not exist, for example when setup never ran.

### 4.7 Storage Layout

```
<config>/.storage/rain_radar_hub/
├── tile_cache.db                          # SQLite metadata (2.7)
├── tile_cache/
│   └── <provider_key>/<z>/<x>/<y>.png     # basemap tiles
└── regions/
    └── <region_id>/
        └── frames/
            └── <YYYY-MM-DDTHH:MM:SSZ>.png # radar frames (2.6)
```

`storage.py` provides `get_storage_root`, `get_tile_cache_db` and `get_frames_dir`.
`__init__.py` builds the `tile_cache/` path as `get_storage_root(...) / "tile_cache"`.

### 4.8 Time Handling

- All times are UTC. The integration does not use the Home Assistant time zone; the
  frontend converts for display.
- **DWD file names:** `YYMMDDHHMM` is read as UTC with year `2000 + YY`
  (`_parse_ry_filename`).
- **Frame file names and manifest timestamps:** `%Y-%m-%dT%H:%M:%SZ`. The manifest's
  `timestamp` is the file name without `.png`.
- **Lookback and retention cutoffs:** `datetime.now(UTC)` minus 180 minutes or
  `FRAME_MAX_AGE_HOURS`, compared with the timestamps from the file names.
- **Parsing frame names:** `_ts_from_filename` accepts only timestamps with a time zone
  (`Z`); other names return `None` and the file is never deleted by the cleanup.
- **Composite time:** `what/date` + `what/time` of the HDF5 file, as UTC, in
  `RadarComposite.timestamp`; not used for naming.
- **Tile ages:** `time.time()` epoch seconds in the SQLite `REAL` columns; a tile is stale
  when it is older than `TILE_EXPIRY_DAYS × 86,400` seconds.

### 4.9 Translations

`strings.json` is the English source and identical to `translations/en.json`;
`translations/de.json` holds the German texts. They cover the config steps `hub`,
`region_name`, `region_location` and `region_map`, the six error keys from
[3.2](#32-hub-setup) and [3.3](#33-region-setup), the abort reason `already_configured`
and the options step `init`, whose description explains the reload and the LRU trimming
([3.4](#34-options-flow)). There are no entity or service strings. The tile provider
field is a plain `vol.In` list without selector translations, so the dialog shows the raw
keys (`carto_voyager`, `osm_standard`, `custom_url`).

### 4.10 manifest.json

| Key | Value |
|-----|-------|
| `domain` | `rain_radar_hub` |
| `name` | `RainRadarHub` |
| `categories` | `["weather_alerts.forecasts"]` |
| `codeowners` | `["@moerk-o"]` |
| `config_flow` | `true` |
| `dependencies` | `["http"]` |
| `documentation` | repository URL |
| `iot_class` | `cloud_polling` (DWD and the tile providers are cloud sources) |
| `issue_tracker` | repository issues URL |
| `requirements` | `aiosqlite>=0.20,<1`, `h5py>=3.12,<4`, `numpy>=2.0,<3`, `pyproj>=3.6,<4` |
| `version` | see the file |

Pillow is not listed: Home Assistant ships it, and hassfest rejects it as a requirement.
`categories` groups the integration in the "Add integration" dialog of Home Assistant
2026.11 and newer; older versions ignore the key.

### 4.11 Testing

Tests use `pytest-homeassistant`; its version is the Home Assistant version of the test
system and is pinned in `requirements-test.txt`, together with numpy at that release's
version ([4.4](#44-dependencies)). They need Python 3.14. The tests import the
integration directly from `custom_components/rain_radar_hub/`; there is no copy under
`tests/`. `tests/conftest.py` removes the cached top-level `custom_components` module so
that Home Assistant resolves it as a namespace package that includes the project
directory.

DWD and tile requests are mocked. `tests/odim.py` builds synthetic ODIM HDF5 files with
the georeference of a real RY file. Tests that go beyond single functions:

- `test_coordinator.py::TestAsyncUpdateData::test_update_writes_frame_for_region` runs a
  full update cycle through the real pipeline; only the directory listing and the
  download are mocked.
- `test_init.py::TestRegionPolling` checks the periodic refresh ([4.5](#45-dataupdatecoordinator)).
- `test_frame_pipeline.py::TestReprojectToPng::test_rain_appears_at_its_location` places
  rain on Hamburg and checks that it appears in the Hamburg frame and not in a Munich frame.

Structure, coverage and the test system: TESTING_GUIDE.

---

## 5. Resources

### Home Assistant Development

| Topic | Link |
|-------|------|
| Developer documentation | https://developers.home-assistant.io/ |
| Integration manifest | https://developers.home-assistant.io/docs/creating_integration_manifest/ |
| Config flow | https://developers.home-assistant.io/docs/config_entries_config_flow_handler/ |
| Options flow | https://developers.home-assistant.io/docs/config_entries_options_flow_handler/ |
| DataUpdateCoordinator | https://developers.home-assistant.io/docs/integration_fetching_data/ |

### Data Sources and Libraries

| Topic | Link |
|-------|------|
| DWD Open Data | https://opendata.dwd.de/ |
| DWD Open Data terms | https://opendata.dwd.de/README.txt |
| RADOLAN RY directory | https://opendata.dwd.de/weather/radar/radolan/ry/ |
| Radar composite RV directory | https://opendata.dwd.de/weather/radar/composite/rv/ |
| OpenStreetMap tile usage policy | https://operations.osmfoundation.org/policies/tiles/ |
| h5py | https://docs.h5py.org/ |
| pyproj | https://pyproj4.github.io/pyproj/stable/ |
| aiosqlite | https://aiosqlite.omnilib.dev/ |

### Related Projects

| Project | Relevance |
|---------|-----------|
| [ha-map-card](https://github.com/nathan-gs/ha-map-card) | Leaflet map card that hosts the frontend plugin |
| [ha-map-card-plugin-bom-radar](https://github.com/bezmi/ha-map-card-plugin-bom-radar) | Planned base of the frontend plugin (fork) |
| [DWD-Nowcast](https://github.com/Thyraz/DWD-Nowcast) | Loads DWD RV data without wradlib; reference for RV |
| [ha-dwd-precipitation-forecast](https://github.com/stoppegp/ha-dwd-precipitation-forecast) | Loads DWD RV data without wradlib; reference for RV |

---

## 6. Release Process

See RELEASE_GUIDE. Specific to this project:

- `release.yml` runs the test suite before it builds and attaches `rain_radar_hub.zip`
  ([4.2](#42-distribution-marketplace--hacs)); a failing test stops the upload.
- `USER_AGENT` in `const.py` contains the integration version as a literal string; it is
  not derived from `manifest.json`. Update it together with `version` in `manifest.json`.
- When a test-stack update moves `pytest-homeassistant` to a new Home Assistant release,
  update the numpy pin in `requirements-test.txt` to that release's numpy.

---

## 7. Version History

| Doc version | Date | Change |
|-------------|------|--------|
| 1.0.0 | November 2026 | Initial version |
