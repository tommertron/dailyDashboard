# Daily Dashboard - Development Notes

## Container Architecture

This dashboard runs in a Docker container. **Any changes you make to the code require container management.**

### Key Points

1. **Rebuild after changes**: When modifying files that are copied into the container at build time (e.g., `server.py`, `generate_summary.py`), you must rebuild:
   ```bash
   docker compose down && docker compose up -d --build
   ```

2. **Mounted files auto-update**: Files mounted as volumes in `docker-compose.yml` update automatically without rebuild:
   - HTML files: `index.html`, `lcars.html`
   - CSS files: `themes/*.css`
   - Data files: `*.json`, `*.txt`

3. **Adding new data files**: When adding new JSON/data files:
   - Add the volume mount to `docker-compose.yml`
   - Set proper permissions: `chmod 644 filename.json`
   - Rebuild the container

4. **File permissions**: Ensure data files are readable (644) so the container can serve them:
   ```bash
   chmod 644 newfile.json
   ```

### Container Commands

```bash
# Rebuild and restart
docker compose down && docker compose up -d --build

# View logs
docker logs dailydashboard-dashboard-1

# Restart without rebuild (for mounted file changes)
docker compose restart

# Check container status
docker ps --filter "name=dailydashboard"
```

### Volume Mounts (docker-compose.yml)

Data files that can be updated by external shortcuts:
- `todos.json` - Tasks from Things app
- `calendar.json` - Calendar events
- `location.json` - Current location
- `daily-links.json` - Anybox links
- `daily-summary.json` - AI-generated summary
- `money.txt` - Bills data
- `starredLinks.json` - Starred links from Anybox
- `sequelEpisodes.json` - TV shows from Sequel
- `anyboxStats.json` - Anybox statistics
- `readlater.json` - GoodLinks read later articles

Read-only mounts (require rebuild if Dockerfile COPY changes):
- `index.html`, `lcars.html` - Dashboard HTML
- `themes/` - CSS theme files
- `config.json` - API keys and settings
- `server.py`, `generate_summary.py` - Backend scripts

### Adding New Features

When adding a new data source:
1. Create the JSON file with proper structure
2. Add volume mount to `docker-compose.yml`
3. Set permissions: `chmod 644 filename.json`
4. Add HTML panel to `index.html` and `lcars.html`
5. Add CSS styles to `themes/default.css` (and LCARS inline styles)
6. Add JS load function and call it in `init()`
7. Rebuild: `docker compose down && docker compose up -d --build`
