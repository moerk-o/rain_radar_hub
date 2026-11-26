# RainRadarHub

Rain radar frames and map tiles for Home Assistant dashboards — powered by DWD Open Data.

RainRadarHub downloads radar data from the German Weather Service (DWD), renders it into PNG frames for the regions you define and serves them, together with cached basemap tiles, from your Home Assistant instance. Tablets and wall-mounted displays without direct internet access get everything through Home Assistant.

## Features

- **DWD Open Data** as the radar source: RADOLAN RY precipitation rate, a new frame every 5 minutes, frames kept for up to 3 hours
- **Tile proxy** with an LRU cache for CARTO Voyager or OpenStreetMap basemap tiles, or a custom tile URL
- **REST API** under `/api/rain_radar_hub/` for the basemap tiles and, per region, the frame list, the frames and the color bar
- **Multi-region** support — each region has its own coordinator and frame cache
- **No internet on the client** — all data is served from the Home Assistant server

## Requirements

- Home Assistant 2024.12 or newer

The dashboard plugin that shows the frames on a map is still in development and not published yet. Until then, RainRadarHub provides the data through its REST API only.

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
2. Set up the hub: tile provider (or a custom tile URL) and tile cache size
3. Add RainRadarHub again for each region: name, location (latitude and longitude), radius and default zoom

The tile cache size can be changed later under **Configure** on the hub entry.

## Documentation

- Technical reference: [`TECHNICAL_REFERENCE.md`](TECHNICAL_REFERENCE.md)
- Release history: [`RELEASENOTES.md`](RELEASENOTES.md) or [Releases](https://github.com/moerk-o/rain_radar_hub/releases)

## Data Source

Radar data: [DWD Open Data](https://opendata.dwd.de/) — free to use, attribution required.
License: [DWD Open Data Terms](https://opendata.dwd.de/README.txt)

## License

MIT — see [`LICENSE`](LICENSE)
