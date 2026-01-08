# Settings Panel Implementation Plan

## Overview
Add a settings panel modal to the dashboard for configuring HA entity IDs, panel visibility, API URLs, refresh intervals, and theme preference. Settings button in header next to theme switcher.

## Files to Modify

| File | Changes |
|------|---------|
| `settings.json` | **NEW** - User settings storage |
| `docker-compose.yml` | Add settings.json volume mount |
| `server.py` | Add GET/POST `/api/settings` endpoints |
| `index.html` | Add settings button, modal HTML, JavaScript |
| `themes/default.css` | Add modal and form styles |
| `lcars.html` | Port settings functionality |

## Settings Structure

```json
{
  "version": 1,
  "panels": {
    "weather": { "visible": true },
    "schedule": { "visible": true },
    "tasks": { "visible": true },
    "shed": { "visible": true },
    "home": { "visible": true },
    "piStatus": { "visible": true },
    "bills": { "visible": true },
    "readLater": { "visible": true },
    "tvShows": { "visible": true },
    "anybox": { "visible": true }
  },
  "homeAssistant": {
    "url": "http://172.17.0.1:8123",
    "entities": {
      "ecobee": "climate.my_ecobee",
      "backDoorLock": "lock.back_door_lock",
      "shedDoorSensor": "binary_sensor.shed_door_sensor",
      "garageDoorSensor": "binary_sensor.contact_sensor"
    }
  },
  "apiUrls": {
    "channelsDvr": "http://100.127.232.39:8089",
    "piMonitor": "http://100.125.128.51:5001"
  },
  "refreshIntervals": {
    "autoRefresh": 300000
  },
  "theme": {
    "preference": "default"
  }
}
```

## UI Design

### Modal with 4 tabs:
1. **Panels** - Toggle visibility for each dashboard panel
2. **Home Assistant** - Entity ID text inputs (ecobee, lock, door sensors)
3. **API URLs** - HA URL, Channels DVR URL, Pi Monitor URL
4. **Preferences** - Auto-refresh interval dropdown, theme radio buttons

### Button location
Gear icon in header, next to theme switcher buttons

## Implementation Steps

### 1. Create settings.json with defaults
Create the file with the structure above.

### 2. Update docker-compose.yml
Add volume mount:
```yaml
- ./settings.json:/app/settings.json
```

### 3. Backend (server.py)

Add helper functions:
```python
SETTINGS_FILE = os.path.join(DIRECTORY, 'settings.json')

def load_settings():
    """Load settings from settings.json or return defaults."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return get_default_settings()

def get_default_settings():
    """Return default settings structure."""
    return {
        "version": 1,
        "panels": { ... },
        "homeAssistant": { ... },
        # etc
    }

def save_settings(settings):
    """Save settings to settings.json."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)
```

Add routes in `do_GET`:
```python
elif self.path == '/api/settings':
    self.get_settings()
```

Add routes in `do_POST`:
```python
elif self.path == '/api/settings':
    self.save_settings_endpoint()
```

Update `get_home_status()` to read entity IDs from settings instead of hardcoded values.

### 4. Frontend (index.html)

**Settings button in header:**
```html
<button class="settings-btn-header" onclick="openSettings()" title="Settings">
  <svg><!-- gear icon --></svg>
</button>
```

**Modal HTML (before </body>):**
```html
<div class="settings-overlay" id="settings-overlay">
  <div class="settings-modal">
    <div class="settings-header">
      <h2>Settings</h2>
      <button class="settings-close-btn" onclick="closeSettings()">X</button>
    </div>
    <div class="settings-body">
      <!-- Tab navigation -->
      <div class="settings-tabs">
        <button class="settings-tab active" data-tab="panels">Panels</button>
        <button class="settings-tab" data-tab="home-assistant">Home Assistant</button>
        <button class="settings-tab" data-tab="api-urls">API URLs</button>
        <button class="settings-tab" data-tab="preferences">Preferences</button>
      </div>
      <!-- Tab content areas with form inputs -->
    </div>
    <div class="settings-footer">
      <button onclick="closeSettings()">Cancel</button>
      <button onclick="saveSettings()">Save Changes</button>
    </div>
  </div>
</div>
```

**Add data-panel attributes to panels:**
```html
<div class="panel" data-panel="weather">
<div class="panel" data-panel="schedule">
<!-- etc -->
```

**JavaScript functions:**
- `loadSettings()` - Fetch from `/api/settings`, apply to UI
- `saveSettings()` - Collect form values, POST to `/api/settings`
- `openSettings()` - Show modal, populate form
- `closeSettings()` - Hide modal
- `applySettings()` - Apply panel visibility, setup auto-refresh

**Update init():**
```javascript
async function init() {
  await loadSettings();  // Add this
  loadAiSummary();
  loadWeather();
  // ...
}
```

### 5. Styles (themes/default.css)

Add styles for:
- `.settings-overlay` - Fixed overlay with backdrop blur
- `.settings-modal` - White rounded card, flex column
- `.settings-tabs` / `.settings-tab` - Tab navigation
- `.settings-input` / `.settings-select` - Form inputs
- `.settings-toggle-item` - Toggle switches for panels
- `.settings-btn-primary` / `.settings-btn-secondary` - Buttons
- Responsive styles for mobile

### 6. LCARS theme (lcars.html)

Port the same functionality with LCARS-appropriate styling:
- LCARS-style button for settings
- Modal with LCARS colors/borders

### 7. Rebuild container

```bash
docker compose down && docker compose up -d --build
```

## Key Details

- **API keys stay in config.json** (read-only) - settings.json only stores non-sensitive config
- **Defaults from code** when settings.json missing - graceful fallback
- **Panel visibility** via `data-panel` attribute + `display: none`
- **Theme change** triggers page navigation (index.html <-> lcars.html)
- **Auto-refresh** uses `setInterval` with configurable interval
- **Escape key** and overlay click close the modal

## Future Enhancements

- Drag-and-drop panel reordering
- Entity ID validation (check if entity exists in HA)
- Settings export/import
- Per-panel refresh intervals
