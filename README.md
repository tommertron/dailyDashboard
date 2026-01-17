# Daily Dashboard

A customizable personal dashboard that displays your daily information at a glance — weather, calendar, tasks, and more. Designed to run locally and be fed data from any source you choose.

![Daily Dashboard](Daily%20Dashboard.png)

![Dashboard with Weather, Schedule, and Tasks](Screenshot%20-%20Daily%20Dashboard%20Weather%20Schedule%20Tasks.png)

## Quick Install

**Requirements:** Docker and Docker Compose

```bash
curl -fsSL https://raw.githubusercontent.com/tommertron/dailyDashboard/main/install.sh | bash
```

Then open **http://localhost:8000** in your browser.

### Install Options

```bash
# Custom port
curl -fsSL https://raw.githubusercontent.com/tommertron/dailyDashboard/main/install.sh | bash -s -- --port 8080

# Custom directory
curl -fsSL https://raw.githubusercontent.com/tommertron/dailyDashboard/main/install.sh | bash -s -- --dir /opt/dashboard

# Update existing installation
cd ~/.daily-dashboard && ./install.sh --update

# Uninstall
cd ~/.daily-dashboard && ./install.sh --uninstall
```

## What It Does

Daily Dashboard is a local web app that aggregates your personal data into a single view. It displays:

- **Weather** — Current conditions and forecast for your location
- **Schedule** — Today's calendar events with a smart timeline view
- **Tasks** — Your todo list
- **Bills** — Upcoming financial obligations
- **Wisdom** — A daily quote or thought
- **Read Later** — Saved articles
- **TV Shows** — Upcoming episodes from shows you follow
- **Smart Home** — Home Assistant integration for lights, thermostats, etc.

**The key idea:** You feed data to the dashboard by updating JSON files. How you populate those files is up to you — Apple Shortcuts, cron jobs, scripts, APIs, whatever works for your setup.

## First-Time Setup

### 1. Add Your Weather API Key

Weather is the only feature that requires an API key to work out of the box.

1. Get a free API key at [openweathermap.org/api](https://openweathermap.org/api)
2. Open the dashboard at http://localhost:8000
3. Click the **Settings** gear icon
4. Go to the **API Keys** tab
5. Enter your OpenWeatherMap API key

### 2. Set Your Location

Create or update `~/.daily-dashboard/location.json`:

```json
{
  "city": "Toronto",
  "lat": "43.6532",
  "long": "-79.3832"
}
```

### 3. Configure Panel Visibility

In Settings, toggle which panels you want visible. Hide any panels you don't plan to use.

## Feeding Data to the Dashboard

The dashboard reads from JSON files in the install directory (`~/.daily-dashboard/`). You can update these files however you like:

- **Apple Shortcuts** — Run shortcuts that export data and write to the JSON files
- **Cron jobs** — Schedule scripts to pull from APIs and update files
- **Manual updates** — Edit files directly when needed
- **Webhooks** — Set up services to POST data that gets written to files

When files are updated, the dashboard picks up changes automatically (or on the next refresh).

### Data File Formats

All data files live in `~/.daily-dashboard/`. Here's the expected format for each:

---

#### `calendar.json` — Calendar Events

```json
{
  "events": "{\"calendar\":\"Work\",\"title\":\"Team Meeting\",\"start\":\"Jan 17, 2026 at 9:00 AM\",\"end\":\"Jan 17, 2026 at 10:00 AM\",\"allday\":\"No\"}\n{\"calendar\":\"Personal\",\"title\":\"Dentist\",\"start\":\"Jan 17, 2026 at 2:00 PM\",\"end\":\"Jan 17, 2026 at 3:00 PM\",\"allday\":\"No\"}"
}
```

The `events` field contains newline-delimited JSON objects (NDJSON). Each event has:

| Field | Description |
|-------|-------------|
| `calendar` | Calendar name (used for color coding) |
| `title` | Event title |
| `start` | Start time in format `MMM D, YYYY at H:MM AM/PM` |
| `end` | End time in same format |
| `allday` | `"Yes"` or `"No"` |

---

#### `todos.json` — Tasks

```json
{
  "todos": [
    {
      "status": "Open",
      "title": "Review pull request",
      "notes": "Check the API changes",
      "tags": {}
    },
    {
      "status": "Open",
      "title": "Buy groceries",
      "notes": "",
      "tags": {}
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `status` | `"Open"` or `"Completed"` |
| `title` | Task title |
| `notes` | Optional notes/description |
| `tags` | Optional tags object |

---

#### `location.json` — Your Location

```json
{
  "city": "Toronto",
  "state": "ON",
  "lat": "43.6532",
  "long": "-79.3832",
  "address": "123 Main St\nToronto ON\nCanada",
  "updated": "Jan 17, 2026 at 8:00 AM"
}
```

Used for weather forecasts. Only `city`, `lat`, and `long` are required.

---

#### `money.txt` — Bills / Financial Notes

Plain text file, one item per line:

```
$500 - Rent due Jan 20
$150 - Electric bill
$45 - Subscription renewal
```

---

#### `wisdom.json` — Daily Wisdom

```json
{
  "wisdom": "The best time to plant a tree was 20 years ago. The second best time is now.",
  "source": "Chinese Proverb"
}
```

---

#### `readlater.json` — Saved Articles

```json
{
  "links": [
    {
      "id": "unique-id-1",
      "title": "How to Build a Personal Dashboard",
      "url": "https://example.com/article",
      "summary": "A guide to building your own dashboard..."
    }
  ]
}
```

---

#### `daily-links.json` — Links Saved Today

```json
{
  "links": [
    {
      "title": "Interesting Article",
      "url": "https://example.com",
      "comment": "Found this on HN"
    }
  ]
}
```

---

#### `sequelEpisodes.json` — Upcoming TV Episodes

```json
{
  "episodes": [
    {
      "show": "Severance",
      "season": "2",
      "episodeNumber": "3",
      "episodeTitle": "Episode Title",
      "releaseDate": "Jan 17, 2026 at 9:00 PM",
      "poster": "https://image.tmdb.org/t/p/w500/poster.jpg"
    }
  ]
}
```

---

#### `anyboxStats.json` — Link Statistics

```json
{
  "all": 500,
  "last7": 12,
  "untagged": 5
}
```

---

#### `daily-summary.json` — AI Summary

```json
{
  "summary": "Good morning! You have 3 meetings today...",
  "generated_at": "2026-01-17 06:00:00",
  "date": "2026-01-17"
}
```

This is generated by the built-in AI summary feature if you configure an OpenAI/Anthropic/Gemini API key.

---

## Optional Features

### AI Daily Summary

Generate a personalized daily briefing using AI:

1. In Settings > API Keys, add an OpenAI, Anthropic, or Google Gemini API key
2. In Settings > AI Settings, choose your provider and customize the prompt
3. Click "Generate Summary" or set up automation to trigger it

### Home Assistant Integration

Control smart home devices directly from the dashboard:

1. In Settings > API Keys, add your Home Assistant URL and Long-Lived Access Token
2. In Settings > Home Assistant, configure entities you want to display
3. Supports: switches, lights, sensors, thermostats, locks, scenes

### TV Shows Panel

Display upcoming episodes:

1. Get a free API key at [themoviedb.org](https://www.themoviedb.org/settings/api)
2. Add the key in Settings > API Keys
3. Populate `sequelEpisodes.json` with your shows

## Themes

Two themes are included:

- **Default** — Clean, light theme
- **LCARS** — Star Trek-inspired dark theme

Switch themes using the buttons in the header.

## Commands

```bash
# Start dashboard
cd ~/.daily-dashboard && docker compose up -d

# Stop dashboard
cd ~/.daily-dashboard && docker compose down

# View logs
cd ~/.daily-dashboard && docker compose logs -f

# Restart (picks up file changes)
cd ~/.daily-dashboard && docker compose restart

# Update to latest version
cd ~/.daily-dashboard && git pull && docker compose up -d --build
```

## Configuration Files

### `config.json` — API Keys

```json
{
  "name": "Your Name",
  "openWeatherApiKey": "your-key",
  "openaiApiKey": "sk-...",
  "anthropicApiKey": "sk-ant-...",
  "geminiApiKey": "...",
  "homeAssistantApiKey": "your-token",
  "homeAssistantUrl": "http://homeassistant.local:8123",
  "tmdbApiKey": "your-key"
}
```

### `settings.json` — App Settings

Managed through the in-app Settings panel. Controls:
- Panel visibility
- Home Assistant entity configuration
- Auto-refresh interval
- Theme preference
- AI prompt customization

## Architecture

```
~/.daily-dashboard/
├── server.py           # Python HTTP server (runs in Docker)
├── index.html          # Main dashboard UI
├── themes/             # CSS themes
├── config.json         # API keys (you edit this)
├── settings.json       # App settings (managed via UI)
└── *.json / *.txt      # Data files (you populate these)
```

The server is a simple Python HTTP server with no external dependencies. It serves the static files and proxies API requests to weather services, Home Assistant, etc.

Data files are mounted as Docker volumes, so you can update them from outside the container and changes appear immediately.

## Troubleshooting

### Dashboard won't start
```bash
cd ~/.daily-dashboard && docker compose logs
```

### Weather not loading
- Check that your OpenWeatherMap API key is correct in Settings > API Keys
- Verify `location.json` has valid lat/long coordinates

### Data not updating
- Files must be valid JSON (use a linter to check)
- Check file permissions: `chmod 644 ~/.daily-dashboard/*.json`

### Port already in use
```bash
# Use a different port
cd ~/.daily-dashboard
docker compose down
# Edit docker-compose.yml to change the port, or reinstall with --port
```

## Development

```bash
# Clone repo
git clone https://github.com/tommertron/dailyDashboard.git
cd dailyDashboard

# Create required data files
for f in todos.json calendar.json daily-links.json starredLinks.json sequelEpisodes.json readlater.json; do
  echo '[]' > "$f"
done
echo '{}' > config.json
echo '{}' > settings.json

# Run with Docker
docker compose up -d --build

# Or run directly (Python 3.12+)
python server.py
```

## License

MIT
