### ✨ New Features
- **Initial release** of RainRadarHub
- **DWD radar frames**: Downloads the RADOLAN RW composite from DWD Open Data, reprojects it for each region and keeps the frames as PNG files for up to 3 hours
- **Tile proxy**: Basemap tiles (CARTO Voyager, OpenStreetMap or a custom URL) are cached with LRU eviction and served by Home Assistant — clients need no internet access
- **REST API**: Endpoints under `/api/rain_radar_hub/` for the basemap tiles and, per region, the frame list, the frames and the color bar
- **Config flow**: One hub entry (tile provider, tile cache size) plus one entry per region (name, location, radius, default zoom); the tile cache size can be changed later
- **Multi-region**: Each region has its own coordinator and frame cache

### 🔮 What's Next
- Dashboard plugin for ha-map-card with an animated time slider
- Changing the tile provider without setting up the hub again

**Full Changelog**: https://github.com/moerk-o/rain_radar_hub/commits/v0.1.0
