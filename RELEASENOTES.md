### ✨ New Features
- **Initial release** — RainRadarHub is live!
- **DWD radar pipeline**: Fetches, decodes and reprojects RW (past) and RV (nowcast) radar data from DWD Open Data every 5 minutes
- **Tile proxy**: LRU-cached basemap tiles (CARTO Voyager, OSM Standard or custom URL) served locally — no internet access needed on clients
- **REST API**: `/api/rain_radar_hub/` endpoints for manifest, frames, tiles and colorbar
- **Config Flow**: Hub setup (tile provider, cache size) + region setup (name, coordinates, radius, zoom)
- **Multi-region**: Unlimited regions, each with its own coordinator and frame cache

### 🔮 What's Next
- Lovelace plugin `ha-map-card-plugin-rain-radar` for animated time slider in dashboards
- Options Flow for tile provider change without Hub re-setup

**Full Changelog**: https://github.com/moerk-o/rain_radar_hub/commits/v0.1.0
