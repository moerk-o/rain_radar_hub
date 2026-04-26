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

- Home Assistant 2026.4.x or newer
- [ha-map-card](https://github.com/nathan-gs/ha-map-card) (install via HACS)
- [ha-map-card-plugin-rain-radar](https://github.com/moerk-o/ha-map-card-plugin-rain-radar) (install via HACS)

## Installation

1. Install via HACS (Custom Repository: `moerk-o/rain_radar_hub`, category: Integration)
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration → RainRadarHub**
4. Complete the Hub setup (tile provider, cache size)
5. Add your first region (name, coordinates, radius)

## Data Source

Radar data: [DWD Open Data](https://opendata.dwd.de/) — free to use, attribution required.
License: [DWD Open Data Terms](https://opendata.dwd.de/README.txt)

## License

MIT
