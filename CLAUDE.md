# Daily Dashboard - Development Guide

## Project Overview

Personal data aggregation dashboard running on a Raspberry Pi in Docker. Displays weather, calendar, tasks, smart home controls, media info, financial data, and AI-generated daily summaries. Single-page vanilla HTML/CSS/JS frontend with a pure Python stdlib HTTP server backend (the dashboard container itself has no pip dependencies).

**Tech Stack:** Python 3.12 HTTP server, vanilla HTML/CSS/JS, Docker, Home Assistant, OpenWeatherMap, OpenAI/Anthropic/Gemini, TMDB, Raindrop.io, Readwise Reader, Todoist, Channels DVR

**Port:** The server listens on **1234** (HTTPS when Tailscale certs are present in `certs/`, otherwise plain HTTP — see bottom of `server.py`). The container publishes `1234:1234`. Playwright tests target `http://localhost:1234`.

**Companion service:** TV/Movies/Books/Games data comes from a **separate `mediatracker` FastAPI service** (its own repo at `/home/tommertron/code/mediatracker`, its own container on port 8100). The dashboard proxies to it — see the "Companion Service: Media Tracker" section below.

## LCARS Theme (Deprecated)

**`lcars.html` is deprecated and should NOT be updated.** The code is preserved but the theme is hidden from the UI. When making changes to the dashboard, only update `index.html` - do not mirror changes to `lcars.html`.

---

## File Structure

### Backend (Python)
- **`server.py`** (~3,560 lines) - Main HTTP server on port 1234. Handles all API proxying, Home Assistant integration, caching, SSH shortcut execution, static file serving, and proxying to the mediatracker service. Uses `http.server.ThreadingHTTPServer` (stdlib only, no pip deps). Service URLs are hardcoded constants near the top (`PI_MONITOR_URL`, `CHANNELS_DVR_URL`, `MEDIATRACKER_URL`, etc.).
- **`generate_summary.py`** (~800 lines) - AI summary generator. Gathers all dashboard data, applies persona/rules from settings, calls OpenAI/Anthropic/Gemini, saves to `daily-summary.json`. Pulls bills from the Remaining API (`http://100.125.128.51:8111/api/summary`).
- **`update_wisdom.py`** (~86 lines) - Selects random wisdom quotes from `wisdom/wisdom.md`, saves to `wisdom.json`.
- **`config.json`** - API keys (not version controlled). Contains: `name`, `openWeatherApiKey`, `openaiApiKey`, `homeAssistantApiKey`, `homeAssistantUrl`, `tmdbApiKey`, `todoistApiKey`, `raindropApiKey`, `readerApiKey` (Readwise Reader). Note: `readeckApiKey`/`readeckUrl` are vestigial/unused; `anthropicApiKey`/`geminiApiKey` may be present if those AI providers are selected.

### Frontend
- **`index.html`** (~4,400 lines) - Entire dashboard UI including all JS logic (~150+ functions). No build step, no bundler.
- **`themes/default.css`** (~4,100 lines) - Light/dark theme with CSS custom properties. Dark mode via `prefers-color-scheme`.

### Data Files (JSON/Text, volume-mounted, updated by external shortcuts or automations)
- `calendar.json` - Calendar events in NDJSON format inside a JSON wrapper
- `location.json` - Current lat/long
- `daily-summary.json` - AI-generated briefing
- `money.txt` - Bills/financial data (plain text, one per line)
- `wisdom.json` - Current daily wisdom quote
- `settings.json` - User preferences (v3 schema)
- `heater_history.json` / `home_heater_history.json` - Shed/home heater runtime history (30 days)
- `heater_rates.json` / `home_heater_rates.json` - Heating cost rate config (read-only mounts)

**Mostly superseded by live API calls** (the dashboard now fetches links/tasks/media directly rather than from these files, but mounts may remain): `daily-links.json`, `starredLinks.json` (Anybox → now Raindrop), `sequelEpisodes.json` / `new_releases.json` (Sequel → now mediatracker service), `anyboxStats.json` (now Raindrop stats), `readlater.json` (GoodLinks → now Readwise Reader API). When in doubt, trust the endpoint, not the file.

---

## Container Architecture

This dashboard runs in a Docker container. **Any changes you make to the code require container management.**

### Key Rules

1. **Rebuild after changes to**: `server.py`, `generate_summary.py` (copied into container at build time):
   ```bash
   docker compose down && docker compose up -d --build
   ```

2. **Volume-mounted files** (`index.html`, `themes/*.css`, all `*.json` and `*.txt`): These do NOT require a rebuild, but **bind mounts on this Raspberry Pi do not always sync live**. After editing any volume-mounted file, always run:
   ```bash
   docker compose restart
   ```

3. **Adding new data files**: Add volume mount to `docker-compose.yml`, `chmod 644 filename.json`, rebuild

### Container Commands

```bash
docker compose down && docker compose up -d --build   # Rebuild and restart
docker logs dailydashboard-dashboard-1                 # View logs
docker compose restart                                 # Restart (mounted file changes only)
docker ps --filter "name=dailydashboard"               # Check status
```

### Verification Before Calling Work Done

After any change, **always verify** before declaring it complete:

1. **Confirm the container has the latest file** — checksums must match:
   ```bash
   md5sum /home/tommertron/code/dailyDashboard/<file> && docker exec dailydashboard-dashboard-1 md5sum /app/<file>
   ```

2. **Check server logs for errors**:
   ```bash
   docker logs dailydashboard-dashboard-1 2>&1 | grep -i "error\|exception" | tail -20
   ```

3. **Test API endpoints directly from inside the container**:
   ```bash
   docker exec dailydashboard-dashboard-1 python3 -c "
   import urllib.request, json
   with urllib.request.urlopen('http://localhost:1234/api/ENDPOINT') as r:
       print(r.status, json.loads(r.read()))"
   ```

4. **When changing a JS data format** (e.g. an API response changes from array to object): search `index.html` for ALL usages of the affected variable (e.g. `grep "_todos" index.html`) and update every callsite — not just the obvious render function. Missing one will cause a silent JS error caught by an unrelated catch block, showing a misleading error message.

---

## Server Endpoints (server.py)

### GET Endpoints
| Endpoint | Purpose | Source |
|----------|---------|--------|
| `/api/weather?lat=X&lon=Y` | Weather proxy | OpenWeatherMap |
| `/api/forecast?lat=X&lon=Y` | 5-day forecast | OpenWeatherMap |
| `/api/config` | API keys (masked) | config.json |
| `/api/settings` | User preferences | settings.json |
| `/api/tv/shows` | TV shows & DVR recordings | Channels DVR + mediatracker + TMDB |
| `/api/pi/status` | Pi system health | Pi Monitor + Healthchecks |
| `/api/home-assistant/panel/{panelId}` | Smart home panel data | Home Assistant |
| `/api/home-assistant/shed` | Shed status (legacy) | Home Assistant |
| `/api/home-assistant/home` | Home status (legacy) | Home Assistant |
| `/api/money` | Bills data | money.txt |
| `/api/wisdom/random` | Daily wisdom quote | wisdom.md |
| `/api/heat-timeline` | Combined heating timeline | HA history API |
| `/api/heater-history` | Shed heating chart data (30 days) | HA history API |
| `/api/home-heater-history` | Home heating chart data | HA history API |
| `/api/todoist/tasks` | Tasks | Todoist API |
| `/api/raindrop/links` | Saved links | Raindrop.io API |
| `/api/raindrop/stats` | Link counts/stats | Raindrop.io API |
| `/api/raindrop/favorites` | Favourited links | Raindrop.io API |
| `/api/raindrop/latest` | Most recent links | Raindrop.io API |
| `/api/reader` | Read-later articles (inbox/later) | Readwise Reader API |
| `/api/notes/inbox` | Unorganized notes | notes-dashboard service |
| `/api/notes/favorites` | Favourited notes | notes-dashboard service |
| `/api/notes/note?path=` | Full note incl. body markdown | notes-dashboard service |
| `/api/notes/list?q=` | Search note summaries (relate picker) | notes-dashboard service |
| `/api/home-assistant/outdoor-temp` | Outdoor temperature | Home Assistant |

### POST Endpoints
| Endpoint | Purpose |
|----------|---------|
| `/api/config` | Save API keys |
| `/api/settings` | Save user preferences |
| `/api/refresh/{shortcutId}` | Run Apple Shortcut via SSH to Mac Mini |
| `/api/refresh-todos` | Refresh tasks shortcut |
| `/api/refresh-money` | Refresh bills shortcut |
| `/api/refresh-summary` | Generate AI summary |
| `/api/refresh-new-releases` | Fetch new media releases (SSH) |
| `/api/home-assistant/toggle/working_from_home` | Toggle WFH boolean |
| `/api/home-assistant/scene/{scene}` | Activate HA scene |
| `/api/home-assistant/toggle/{entity}` | Toggle light/boolean |
| `/api/home-assistant/climate/set` | Set thermostat temp/mode |
| `/api/home-assistant/lock/back_door` | Toggle door lock |
| `/api/automation/wfh-check` | Run WFH automation (calendar check) |
| `/api/todoist/tasks/add` | Create a task |
| `/api/todoist/tasks/punt` | Reschedule task(s) |
| `/api/todoist/tasks/{id}/close` | Complete a task |
| `/api/raindrop/favorite/{id}` | Favourite a link |
| `/api/raindrop/unfavorite/{id}` | Unfavourite a link |
| `/api/reader/update` | Update a Reader document (e.g. mark moved) |
| `/api/notes/capture` | Quick-capture a note to the inbox (proxied to notes-dashboard) |
| `/api/notes/state` | Set favorite/organized/archived flag (proxied to notes-dashboard) |
| `/api/notes/update` | Replace a note's body markdown (light edit, proxied to notes-dashboard) |
| `/api/notes/relate` | Add a belongs_to/related_to wikilink (proxied to notes-dashboard) |
| `/api/notes/suggest` | AI-suggested belongs_to/related_to links (proxied to notes-dashboard; needs an Anthropic API key in that service) |
| `/api/notes/delete` | Permanently delete a note file (proxied to notes-dashboard) |
| `/api/media/watched` | Mark media watched (proxied to mediatracker) |
| `/api/media/refresh` | Refresh media data (proxied to mediatracker) |
| `/api/test/{service}` | Test API key connectivity |

### Caching
- TV shows, Pi status, HA panels: 5-minute TTL with background refresh thread
- Cache invalidated after any HA control action
- Weather: no cache (fetched on demand)

---

## Smart Home Integration (Home Assistant)

### Shed Entities
- `climate.shed_thermostat` - Thermostat (heat/off, target temp)
- `sensor.temperature_sensor_2` - Current shed temperature (°C)
- `input_boolean.working_from_home` - WFH toggle (controls pre-heating automation)
- `light.smart_rgb_bulb_2208...` - Desk lamp
- `light.govee_h617a_501b` - Shelf light
- `scene.heat_shed_in_morning` - Pre-heat scene
- `scene.shed_unoccupied` - Shutdown scene

### Home Entities
- `climate.my_ecobee` - Ecobee thermostat
- `lock.back_door_lock` - Door lock
- `input_boolean.422_occupancy` - Occupancy toggle
- `binary_sensor.contact_sensor_2` - Shed door sensor
- `binary_sensor.contact_sensor` - Garage door sensor

### WFH Automation (`run_wfh_automation()` in server.py ~line 2120)

A cron-triggered automation that decides whether to turn off the WFH toggle. Called via `POST /api/automation/wfh-check`.

**Logic:**
1. **Weekend (Saturday/Sunday)** → turn WFH OFF
2. **Today's calendar has any of these phrases** (case-insensitive, checked against event titles): `in office`, `tom office`, `tom in office`, `out of office`, `away`, `holiday`, `vacation` → turn WFH OFF
3. **Otherwise** → no change (WFH stays in its current state)

**How it works with shed heating:** When WFH is ON, a Home Assistant automation pre-heats the shed on workday mornings. The WFH-check cron runs daily and turns WFH OFF if calendar events or weekends indicate the user won't be working from the shed.

### Shed Heat Banner (`updateShedHeatBanner()` in index.html)

A prominent banner between the header and content that predicts whether the shed will be heated tomorrow. It simulates what the WFH automation would do if it ran at 12:01am tomorrow:

1. **Tomorrow is Saturday or Sunday** → "WON'T be heated" (weekend)
2. **Tomorrow's calendar has a no-WFH phrase** (same list as automation) → "WON'T be heated" (shows event title)
3. **WFH toggle is currently ON** → "WILL be heated"
4. **WFH toggle is currently OFF** → "WON'T be heated"

The banner updates whenever calendar data or shed status refreshes. Both the banner and the automation use the same phrase list so they stay in sync.

---

## Dashboard Panels (index.html)

### Layout
```
Header: Greeting, AI Summary, Starred Links, Theme Switcher, Settings, Date
Shed Heat Banner (between header and content)
Dense Top Row (3 columns): Weather+Tasks | Smart Schedule | Bills+Wisdom
Three-Column Grid: Calendar | Shed+Home+Pi | TV+Movies+Books+Games+Links
```

### Panel List
| Panel | Data Source | Key Function |
|-------|------------|--------------|
| Weather | OpenWeatherMap | `loadWeather()` |
| Smart Schedule | calendar.json | `renderSmartSchedule()` - timeline view |
| Calendar | calendar.json | `renderCalendar()` - grouped by today/tomorrow/week |
| Tasks | Todoist API | `loadTodos()` |
| Bills | money.txt | via `/api/money` |
| Wisdom | wisdom.json | `loadWisdom()` - 6hr rotation |
| Shed | Home Assistant | `loadShedStatus()` / `renderShedStatus()` |
| Home | Home Assistant | `loadHomeStatus()` |
| Pi Status | Pi Monitor + Healthchecks | `loadPiStatus()` |
| TV/Movies/Books/Games | mediatracker service + Channels DVR + TMDB | `loadTvShows()` etc. |
| Links | Raindrop.io API (`/api/raindrop/*`) | `loadLinks()` |
| Read Later | Readwise Reader API (`/api/reader`) | inbox + later sections, top 3 each |
| Notes | notes-dashboard service (`/api/notes/*`) | `loadNotes()` + note editor modal (`openNoteModal()`): quick-capture; inbox items have a ✓ organize quick-action (organizing removes them from the inbox); click to open/edit body, toggle organize/unorganize, favourite, archive/unarchive, add belongs_to/related_to via search picker or AI suggest, delete (with a confirmation modal), and **create a Todoist task** from the note (`noteToTodoist()` — first body line minus `#` headers becomes the task title, the rest the description; lands in the Todoist inbox via `/api/todoist/tasks/add`). A favourited inbox note shows in the inbox only (deduped in `loadNotes`). |

---

## AI Summary System (generate_summary.py)

### Persona System
- **"picard"** - Captain Picard (eloquent, measured)
- **"merlin-mann"** - Merlin Mann (verbose, curmudgeonly, warm)
- **"default"** - Friendly assistant

### Data Gathering (`gather_daily_data()`)
Compiles: todos, calendar (with relative dates), weather + tomorrow's forecast, location, links, bills (from Remaining API at http://100.125.128.51:8111), anybox stats, TV shows, read-later articles, wisdom, shed/home state, heater runtime, Pi/UPS status, backup status

### Rules System (in settings.json)
Extensive prompt rules covering: priority alerts (unlocked doors, power outages), weather, calendar, tasks, shed heating logic, WFH toggle state, TV releases, anybox stats, read-later suggestions, UPS/backup status, wisdom integration

---

## External Services

### APIs
- **OpenWeatherMap** - Weather & forecast
- **OpenAI / Anthropic / Gemini** - AI summary generation (configurable)
- **TMDB** - TV episode details and posters
- **Home Assistant** - Smart home control (local network)
- **Healthchecks.io** - Backup/service monitoring
- **Raindrop.io** - Bookmarks/links panel (replaced Anybox)
- **Readwise Reader** (`readwise.io/api/v3`) - Read-later articles (replaced Instapaper/GoodLinks)
- **Todoist** - Tasks panel (replaced the Things-via-SSH shortcut)

### Local Network Services (Tailscale IPs)
- **mediatracker** (`http://172.17.0.1:8100`, the `MEDIATRACKER_URL` constant) - Companion service for TV/Movies/Books/Games. See section below.
- **Channels DVR** (http://100.127.232.39:8089) - DVR recordings, disk status
- **Pi Monitor** (http://100.115.42.106:5001, the `PI_MONITOR_URL` constant) - UPS, system info
- **Remaining** (http://100.125.128.51:8111) - Bill tracking (used by `generate_summary.py`)

### Apple Shortcuts (via SSH to Mac Mini at 192.168.4.242)
Legacy refresh mechanism, largely superseded by direct API calls. Still wired for: dailyMoney (bills), daily calendar. Things/Anybox/GoodLinks shortcuts are deprecated in favour of Todoist/Raindrop/Reader APIs.

---

## Companion Service: Media Tracker

The TV/Movies/Books/Games panels are powered by a **separate FastAPI service** in its own repo and container — NOT by `server.py`. This is a second working directory: `/home/tommertron/code/mediatracker`.

- **Stack:** Python 3.13, FastAPI + uvicorn, `requests`, `beautifulsoup4` (has pip deps, unlike the dashboard). Runs on **port 8100**, container name `mediatracker`.
- **Data sources:** **Trakt** (watchlist/history/up-next), **Channels DVR** (unwatched recordings), **TMDB** (posters), **Fox Theatre Toronto** (scraped screenings matched to watchlist), and optionally Sonarr/Radarr.
- **Key files:** `app.py` (~2,500 lines, all routes + logic), `index.html` (its own couch-friendly web UI), `config.json` (Trakt/TMDB keys), `poster_cache.json`, `watch_queue.json`, `static_media.json`.
- **How the dashboard talks to it:** `server.py` proxies `/api/media/watched` and `/api/media/refresh` to the service via `proxy_media_tracker()` → `MEDIATRACKER_URL`. The dashboard's `/api/tv/shows` endpoint and the mediatracker both contribute to the media panels.
- **Cross-mount:** the mediatracker container bind-mounts the dashboard repo at `/dailydashboard`, so it can write data files the dashboard reads.

**When changing media features, check whether the logic lives in `mediatracker/app.py` rather than `server.py`.** The two are deployed independently — rebuilding the dashboard container does NOT rebuild mediatracker (`cd /home/tommertron/code/mediatracker && docker compose up -d --build`).

---

## Companion Service: Notes Dashboard

The Notes panel is powered by a **separate Node/Express service** in its own repo and container — NOT by `server.py`. Working directory: `/home/tommertron/code/notes-dashboard`.

- **Stack:** Node 20, Express, `gray-matter` (has npm deps). Runs on **port 4319**, container name `notes-dashboard`, bound to `0.0.0.0`. `MEDIATRACKER_URL`-style constant in `server.py` is `NOTES_URL = "http://172.17.0.1:4319"`.
- **Vault:** reads/writes a [Tolaria/inText](https://github.com/refactoringhq/tolaria) markdown vault at `/home/tommertron/notes` (mounted into the container at `/notes`). State and relationships live in YAML frontmatter: `_organized` / `_archived` / `_favorite` (booleans; "off" = key absent), and `belongs_to` / `related_to` (quoted `[[wikilinks]]`, scalar or YAML list). Frontmatter keys starting with `_` are Tolaria-managed — leave them alone. See `~/notes/AGENTS.md`.
- **Key files:** `server.js` (routes), `lib/vault.js` (read/parse/mutate notes — `getNote`, `setFlag` (favouriting also writes `_favorite_index`), `addRelationship`, `appendToBody`, `updateBody`, `capture`, `deleteNote`), `lib/ai.js` (Claude relationship suggestions), `lib/chat.js`, `public/` (its own UI). Its native API is `/api/note*`; the dashboard proxies these under `/api/notes/*` via `proxy_notes()`.
- **How the dashboard talks to it:** the dashboard's Notes panel (`loadNotes()` + the note editor modal in `index.html`) calls `/api/notes/{inbox,favorites,note,list,update,relate,state,capture,suggest}`, all proxied to `NOTES_URL`.
- **AI suggest** (`/api/notes/suggest`) needs an **Anthropic API key** in the notes-dashboard container (`ANTHROPIC_API_KEY` env or `ANTHROPIC_KEY_FILE`). Without it the endpoint returns 503 and the UI shows the error; the manual search picker still works.

**When changing notes features, the read/write logic usually lives in `notes-dashboard/lib/vault.js`, not `server.py`.** The two are deployed independently — rebuilding the dashboard container does NOT rebuild notes-dashboard (`cd /home/tommertron/code/notes-dashboard && docker compose up -d --build`).

---

## Calendar Event Format (calendar.json)

Events stored as NDJSON inside a JSON wrapper:
```json
{
  "events": "{\"calendar\":\"Work\",\"title\":\"Meeting\",\"start\":\"Feb 11, 2026 at 9:00 AM\",\"end\":\"Feb 11, 2026 at 10:00 AM\",\"allday\":\"No\"}\n..."
}
```

Date format is always: `Mon DD, YYYY at H:MM AM/PM` (e.g., "Feb 11, 2026 at 9:00 AM")

---

## Adding New Features

1. Create the JSON file with proper structure
2. Add volume mount to `docker-compose.yml`
3. Set permissions: `chmod 644 filename.json`
4. Add HTML panel to `index.html`
5. Add CSS styles to `themes/default.css`
6. Add JS load function and call it in `init()`
7. If backend changes needed, update `server.py`
8. Rebuild: `docker compose down && docker compose up -d --build`
9. **Write or update Playwright tests** (see Testing section below)

---

## Testing with Playwright

Tests live in `tests/dashboard.spec.js`. The test suite uses `@playwright/test` (installed via `npm install` from `package.json`).

### Running Tests

```bash
# Run all tests (headless)
npx playwright test

# Run a single test by name
npx playwright test -g "wisdom refresh button"

# Run headed (useful for debugging)
npx playwright test --headed

# Show full test report
npx playwright show-report
```

Tests target `http://localhost:1234`. The container must be running.

### Test Structure

**`tests/dashboard.spec.js`** contains:
- **Page load** — date badge visible, AI summary present, shed heat banner present
- **Panel visibility** — all 10 main panels render (via `data-panel` attribute)
- **Content checks** — weather and wisdom containers are non-empty after data loads
- **Settings modal** — opens, has expected panes, closes on Escape
- **Refresh buttons** — wisdom, tasks, bills buttons are clickable
- **Add task form** — opens and cancels correctly
- **Thermostat modal** — opens when thermostat button is clicked (skipped if shed data unavailable)
- **No JS errors** — asserts zero uncaught JS exceptions on load

### When to Write/Update Tests

**After adding a new panel:**
- Add it to the `panels` array in the spec so visibility is asserted automatically
- Add a content check if the panel loads async data

**After adding a new interactive element (button, modal, form):**
- Write a test that clicks it and asserts the expected UI response

**After fixing a bug:**
- Add a regression test that would have caught the bug

**Selector conventions:**
- Use `data-panel="{name}"` for panel roots
- Use `#container-id` for content containers
- Use `#btn-id` for buttons
- Avoid brittle text selectors; prefer IDs and data attributes

### Verifying After Changes

Always run `npx playwright test` before declaring a feature complete. If a test fails unexpectedly, check:
1. Is the container running? (`docker ps --filter "name=dailydashboard"`)
2. Did `data-panel` attribute or element ID change in `index.html`?
3. Check container logs for backend errors
