# RainRadarHub

Animated rain radar map for Home Assistant dashboards — powered by DWD Open Data.

RainRadarHub serves animated, scrubbable rain radar tiles directly from your Home Assistant instance. Tablets and wall-mounted displays with no direct internet access get all map tiles and radar frames through HA — no external connectivity needed on the client.

## Features

- **DWD Open Data** as the sole radar source (RW: past ~60 min, RV: nowcast +90 min)
- **Tile proxy** with LRU cache for OpenStreetMap / CARTO basemap tiles
- **REST API** for the companion Lovelace plugin
- **Multi-region** support — each region has its own coordinator and frame cache
- **No internet on the tablet** — all data is served from the HA server

## Requirements

- Home Assistant 2024.12 or newer
- [ha-map-card](https://github.com/nathan-gs/ha-map-card) (install via Marketplace or HACS)
- [ha-map-card-plugin-rain-radar](https://github.com/moerk-o/ha-map-card-plugin-rain-radar) (install via Marketplace or HACS)

## Installation

### Marketplace (Home Assistant 2026.11 and newer)

1. Settings → Marketplace → **Add from link**
2. Enter `moerk-o/rain_radar_hub` and select **Add**
3. Open the repository page and select **Install** — restart Home Assistant when the Marketplace asks for it

### HACS (Home Assistant 2026.10 and older)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/moerk-o/rain_radar_hub` as Integration
3. Install, then restart Home Assistant

### Manual

1. Download `rain_radar_hub.zip` from the latest [release](https://github.com/moerk-o/rain_radar_hub/releases)
2. Unpack it into `config/custom_components/rain_radar_hub/`
3. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration → RainRadarHub**
2. Complete the Hub setup (tile provider, cache size)
3. Add your first region (name, coordinates, radius)

## Data Source

Radar data: [DWD Open Data](https://opendata.dwd.de/) — free to use, attribution required.
License: [DWD Open Data Terms](https://opendata.dwd.de/README.txt)

## License

MIT — see [`LICENSE`](LICENSE)
