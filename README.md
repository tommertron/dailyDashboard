# Daily Dashboard

A personal dashboard for daily information display - weather, calendar, tasks, and more.

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/tommertron/dailyDashboard/main/install.sh | bash
```

Then open http://localhost:8000 in your browser.

### Install Options

```bash
# Custom port
curl -fsSL .../install.sh | bash -s -- --port 8080

# Custom directory
curl -fsSL .../install.sh | bash -s -- --dir /opt/dashboard

# Update existing installation
cd ~/.daily-dashboard && ./install.sh --update

# Uninstall
cd ~/.daily-dashboard && ./install.sh --uninstall
```

## Requirements

- Docker and Docker Compose
- That's it!

## First-Time Setup

1. Open http://localhost:8000
2. Click the Settings gear icon
3. Go to **API Keys** tab
4. Add your API keys:
   - **OpenWeatherMap** (free): Get one at [openweathermap.org/api](https://openweathermap.org/api)
   - **OpenAI** (optional): For AI daily summaries
   - **Home Assistant** (optional): For smart home integration
   - **TMDB** (optional): For TV show posters

## Features

### Panels

| Panel | Description | Requires |
|-------|-------------|----------|
| Weather | Current weather + tomorrow's forecast | OpenWeatherMap API key |
| Schedule | Today's calendar events | calendar.json |
| Tasks | Todo list from Things | todos.json |
| Bills | Upcoming bills | money.txt |
| Wisdom | Daily wisdom quote | wisdom.json |
| Read Later | Saved articles | readlater.json |
| TV Shows | Upcoming episodes | TMDB API key + sequelEpisodes.json |
| Home/Shed | Home Assistant controls | Home Assistant setup |
| Pi Status | Raspberry Pi monitoring | Pi Monitor service |
| Anybox | Random saved links | anyboxStats.json + daily-links.json |

### Themes

- **Default**: Clean, light theme
- **LCARS**: Star Trek-inspired dark theme

Switch themes using the buttons in the header.

## Data Files

The dashboard reads from JSON files that can be updated by external scripts or shortcuts.

### Required Format

<details>
<summary>calendar.json</summary>

```json
{
  "events": "{\"calendar\":\"Work\",\"title\":\"Meeting\",\"start\":\"Jan 1, 2026 at 9:00 AM\",\"end\":\"Jan 1, 2026 at 10:00 AM\",\"allday\":\"No\"}\n{\"calendar\":\"Family\",\"title\":\"Dinner\",\"start\":\"Jan 1, 2026 at 6:00 PM\",\"end\":\"Jan 1, 2026 at 8:00 PM\",\"allday\":\"No\"}"
}
```
</details>

<details>
<summary>todos.json</summary>

```json
{
  "todos": [
    {"status": "Open", "title": "Task name", "notes": "", "tags": {}},
    {"status": "Completed", "title": "Done task", "notes": "", "tags": {}}
  ]
}
```
</details>

<details>
<summary>location.json</summary>

```json
{
  "city": "Toronto",
  "lat": "43.6532",
  "long": "-79.3832",
  "updated": "Jan 1, 2026 at 12:00 AM"
}
```
</details>

<details>
<summary>Other files</summary>

- `daily-summary.json` - AI-generated summary
- `money.txt` - Plain text bills/financial notes
- `wisdom.json` - Daily wisdom quote
- `readlater.json` - Read later articles
- `sequelEpisodes.json` - Upcoming TV episodes
- `anyboxStats.json` - Anybox link statistics
- `daily-links.json` - Links saved today
- `starredLinks.json` - Starred/favorite links
</details>

## Commands

```bash
# Start dashboard
cd ~/.daily-dashboard && docker compose up -d

# Stop dashboard
cd ~/.daily-dashboard && docker compose down

# View logs
cd ~/.daily-dashboard && docker compose logs -f

# Update to latest version
cd ~/.daily-dashboard && git pull && docker compose up -d --build

# Restart (after editing mounted files)
cd ~/.daily-dashboard && docker compose restart
```

## Configuration

### Settings

All settings are configurable through the in-app Settings panel:
- Panel visibility toggles
- Home Assistant entity configuration
- API URLs for integrations
- Theme preference
- Auto-refresh interval

### Environment Variables

Set timezone in docker-compose.yml:
```yaml
environment:
  - TZ=America/Toronto
```

## Development

```bash
# Clone repo
git clone https://github.com/tommertron/dailyDashboard.git
cd dailyDashboard

# Create data files
echo '[]' > todos.json calendar.json
echo '{}' > config.json settings.json

# Run with Docker
docker compose up -d --build

# Or run directly (Python 3.12+)
python server.py
```

## License

MIT
