#!/usr/bin/env python3
import base64
import hashlib
import hmac
import http.server
import json
import os
import ssl
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

PORT = 8443
CACHE_TTL = 300  # 5 minutes in seconds

# Global cache storage
_api_cache = {
    'tv_shows': {'data': None, 'updated_at': None},
    'pi_status': {'data': None, 'updated_at': None},
    'ha_panels': {}  # Keyed by panel_id
}
_cache_lock = threading.Lock()
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(DIRECTORY, 'settings.json')

def get_default_settings():
    """Return default settings structure for new installs."""
    return {
        "version": 3,
        "panels": {
            # ON by default - universal features that work out of the box
            "weather": {"visible": True},
            "schedule": {"visible": True},
            "tasks": {"visible": True},
            "bills": {"visible": True},
            "readLater": {"visible": True},
            "wisdom": {"visible": True},
            # OFF by default - require specific setup
            "piStatus": {"visible": False},   # Requires Pi Monitor setup
            "shed": {"visible": False},       # Requires Home Assistant
            "home": {"visible": False},       # Requires Home Assistant
            "tvShows": {"visible": False},    # Requires Channels DVR
            "anybox": {"visible": False}      # Requires Anybox app + shortcut
        },
        "homeAssistant": {
            "url": "",
            "panels": {}
        },
        "apiUrls": {
            "channelsDvr": "",
            "piMonitor": ""
        },
        "refreshIntervals": {
            "autoRefresh": 300000
        },
        "refreshCommands": {
            "ssh": {
                "host": "",
                "user": "",
                "timeout": 30
            },
            "shortcuts": {
                "tasks": {"enabled": False, "shortcutName": "", "description": "Sync tasks from Things app"},
                "bills": {"enabled": False, "shortcutName": "", "description": "Fetch upcoming bills"},
                "calendar": {"enabled": False, "shortcutName": "", "description": "Sync calendar events"},
                "anybox": {"enabled": False, "shortcutName": "", "description": "Export links from Anybox"},
                "sequel": {"enabled": False, "shortcutName": "", "description": "Fetch upcoming TV episodes"},
                "goodlinks": {"enabled": False, "shortcutName": "", "description": "Export read later articles"}
            }
        },
        "aiPrompts": {
            "activePersona": "default",
            "activeTemplate": "default",
            "personas": {
                "default": {
                    "name": "Friendly Assistant",
                    "description": "Helpful and concise daily briefings",
                    "systemPrompt": "You are a friendly assistant delivering daily briefings. Be concise, helpful, and highlight important items that need attention."
                }
            },
            "templates": {
                "default": {
                    "name": "Daily Briefing",
                    "description": "Standard daily summary format",
                    "introPrompt": "Based on the following data from my dashboard for {date}, give me a friendly 2-3 sentence summary highlighting what's important today.\n\nDashboard Data:\n{data}\n\n{rules}"
                }
            },
            "rules": {
                "default": """Include in your summary:
- Current weather (temperature, conditions)
- Tomorrow's weather forecast (high/low temps, conditions)
- Calendar events for today and tomorrow (use the "relative_day" field)
- Pending tasks that need attention
- If there are interesting saved links, briefly mention one worth checking out
- Any upcoming bills due in the next 7 days

Keep it concise - 2-3 sentences max. Write in second person ("You have...", "Your day...").

Add your own custom rules here for smart home devices, routines, or other personal automations."""
            }
        },
        "theme": {
            "preference": "default"
        },
        "useGenericRenderer": {
            "wisdom": False,
            "tasks": False,
            "readLater": False
        },
        "customPanels": {}
    }


def migrate_settings(settings):
    """Migrate settings from older versions to the current version."""
    version = settings.get('version', 1)
    migrated = False

    if version < 2:
        # Migrate v1 to v2
        settings['version'] = 2
        migrated = True

        # Add wisdom panel if missing
        if 'wisdom' not in settings.get('panels', {}):
            settings.setdefault('panels', {})['wisdom'] = {"visible": True}

        # Convert old flat homeAssistant.entities to panels structure
        ha_config = settings.get('homeAssistant', {})
        old_entities = ha_config.get('entities', {})

        if old_entities and 'panels' not in ha_config:
            # Create a 'home' panel from the old entity structure
            entities_list = []
            if old_entities.get('ecobee'):
                entities_list.append({
                    "entityId": old_entities['ecobee'],
                    "displayName": "Thermostat",
                    "type": "climate"
                })
            if old_entities.get('backDoorLock'):
                entities_list.append({
                    "entityId": old_entities['backDoorLock'],
                    "displayName": "Back Door Lock",
                    "type": "lock"
                })
            if old_entities.get('shedDoorSensor'):
                entities_list.append({
                    "entityId": old_entities['shedDoorSensor'],
                    "displayName": "Shed Door",
                    "type": "door"
                })
            if old_entities.get('garageDoorSensor'):
                entities_list.append({
                    "entityId": old_entities['garageDoorSensor'],
                    "displayName": "Garage Door",
                    "type": "door"
                })

            ha_config['panels'] = {
                'home': {
                    'name': 'Home',
                    'visible': True,
                    'entities': entities_list,
                    'scenes': []
                }
            }
            # Remove old entities key
            if 'entities' in ha_config:
                del ha_config['entities']

        # Ensure panels structure exists even if no old entities
        if 'panels' not in ha_config:
            ha_config['panels'] = {}

        settings['homeAssistant'] = ha_config

        # Add refreshCommands if missing
        if 'refreshCommands' not in settings:
            settings['refreshCommands'] = {
                "ssh": {"host": "", "user": "", "timeout": 30},
                "shortcuts": {}
            }

        # Add aiPrompts if missing
        if 'aiPrompts' not in settings:
            settings['aiPrompts'] = get_default_settings()['aiPrompts']

    # Migrate v2 to v3 - add generic panel system fields
    if version < 3:
        settings['version'] = 3
        migrated = True

        # Add useGenericRenderer if missing
        if 'useGenericRenderer' not in settings:
            settings['useGenericRenderer'] = {
                "wisdom": False,
                "tasks": False,
                "readLater": False
            }

        # Add customPanels if missing
        if 'customPanels' not in settings:
            settings['customPanels'] = {}

    return settings, migrated

def load_settings():
    """Load settings from settings.json, migrate if needed, or return defaults."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
        # Migrate if needed
        settings, migrated = migrate_settings(settings)
        if migrated:
            save_settings(settings)
            print(f"Settings migrated to version {settings.get('version')}")
        return settings
    except (FileNotFoundError, json.JSONDecodeError):
        return get_default_settings()

def save_settings(settings):
    """Save settings to settings.json."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

CONFIG_FILE = os.path.join(DIRECTORY, 'config.json')

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(config):
    """Save config to config.json."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def mask_key(key):
    """Return masked version of API key for display (shows last 4 chars)."""
    if not key or len(key) < 8:
        return ''
    return '••••••••' + key[-4:]

def ha_request(method, endpoint, data=None):
    """Make a request to Home Assistant API."""
    config = load_config()
    ha_url = config.get('homeAssistantUrl', 'http://localhost:8123')
    ha_key = config.get('homeAssistantApiKey', '')

    url = f"{ha_url}/api/{endpoint}"
    headers = {
        'Authorization': f'Bearer {ha_key}',
        'Content-Type': 'application/json',
    }

    req = urllib.request.Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode('utf-8')

    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))

PI_MONITOR_URL = "http://100.115.42.106:5001"
CHANNELS_DVR_URL = "http://100.127.232.39:8089"
MEDIATRACKER_URL = "http://172.17.0.1:8100"
TMDB_API_URL = "https://api.themoviedb.org/3"
HEALTHCHECKS_BADGE_URL = "https://healthchecks.io/b/2/76534796-6135-419b-ab51-fa35e8581f10.json"
BACKUP_HEALTHCHECKS_URL = "https://healthchecks.io/b/2/fc90bb64-b594-4db2-98f3-f48020b1d2f1.json"
BACKUP_STATUS_FILE = "/mnt/ssd/backupJobs/backup_status.json"

# Cache for TMDB series IDs to avoid repeated lookups
_tmdb_series_cache = {}

def get_tmdb_series_id(show_name, api_key):
    """Search TMDB for a series and return its ID."""
    if show_name in _tmdb_series_cache:
        return _tmdb_series_cache[show_name]

    try:
        encoded_name = urllib.parse.quote(show_name)
        url = f"{TMDB_API_URL}/search/tv?api_key={api_key}&query={encoded_name}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('results'):
                series_id = data['results'][0]['id']
                _tmdb_series_cache[show_name] = series_id
                return series_id
    except Exception as e:
        print(f"TMDB search error for {show_name}: {e}")
    return None

def get_tmdb_episode_description(series_id, season, episode, api_key):
    """Fetch episode description from TMDB."""
    try:
        url = f"{TMDB_API_URL}/tv/{series_id}/season/{season}/episode/{episode}?api_key={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('overview', '')
    except Exception as e:
        print(f"TMDB episode fetch error: {e}")
    return ''


# =============================================================================
# Data Fetching Functions (used by cache and endpoints)
# =============================================================================

def fetch_tv_shows_data():
    """Fetch TV shows from Channels DVR and Sequel episodes."""
    shows = []
    seen_shows = set()
    disk_info = None

    # Fetch DVR status including disk info
    try:
        req = urllib.request.Request(f"{CHANNELS_DVR_URL}/dvr")
        with urllib.request.urlopen(req, timeout=10) as response:
            dvr_status = json.loads(response.read().decode('utf-8'))
            disk_info = dvr_status.get('disk')
    except Exception as e:
        print(f"Error fetching DVR status: {e}")

    # Fetch recent recordings from Channels DVR
    try:
        req = urllib.request.Request(f"{CHANNELS_DVR_URL}/dvr/files")
        with urllib.request.urlopen(req, timeout=10) as response:
            files = json.loads(response.read().decode('utf-8'))

        sorted_files = sorted(files, key=lambda x: x.get('CreatedAt', 0), reverse=True)

        for f in sorted_files[:10]:
            airing = f.get('Airing', {})
            title = airing.get('Title', '')
            if not title or title.lower() in seen_shows:
                continue

            seen_shows.add(title.lower())
            episode_title = airing.get('EpisodeTitle', '')
            season = airing.get('SeasonNumber')
            episode = airing.get('EpisodeNumber')

            genres = airing.get('Genres', [])
            release_date = airing.get('OriginalDate', '')
            if 'Talk' in genres:
                created_at = f.get('CreatedAt')
                if created_at:
                    release_date = datetime.fromtimestamp(created_at).strftime('%Y-%m-%d')

            shows.append({
                'title': title,
                'season': season,
                'episodeNumber': episode,
                'episodeTitle': episode_title,
                'description': airing.get('Summary', ''),
                'poster': airing.get('Image', ''),
                'releaseDate': release_date,
                'source': 'channels'
            })

            if len(shows) >= 3:
                break
    except Exception as e:
        print(f"Error fetching Channels DVR: {e}")

    # Read Sequel episodes
    try:
        sequel_path = os.path.join(DIRECTORY, 'sequelEpisodes.json')
        config = load_config()
        tmdb_api_key = config.get('tmdbApiKey', '')

        if os.path.exists(sequel_path):
            with open(sequel_path, 'r') as f:
                sequel_data = json.load(f)

            episodes = sequel_data.get('episodes', sequel_data.get('episoes', []))

            sequel_shows = []
            for ep in episodes:
                title = ep.get('show', '')
                if not title or title.lower() in seen_shows:
                    continue
                seen_shows.add(title.lower())
                sequel_shows.append(ep)

            def fetch_tmdb_description(ep):
                title = ep.get('show', '')
                season = ep.get('season', '')
                episode_num = ep.get('episodeNumber', '')
                description = ''
                if tmdb_api_key and season and episode_num:
                    series_id = get_tmdb_series_id(title, tmdb_api_key)
                    if series_id:
                        description = get_tmdb_episode_description(
                            series_id, season, episode_num, tmdb_api_key
                        )
                return ep, description

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(fetch_tmdb_description, ep) for ep in sequel_shows]
                for future in as_completed(futures):
                    ep, description = future.result()
                    shows.append({
                        'title': ep.get('show', ''),
                        'season': ep.get('season', ''),
                        'episodeNumber': ep.get('episodeNumber', ''),
                        'episodeTitle': ep.get('episodeTitle', ''),
                        'description': description,
                        'poster': ep.get('poster', ''),
                        'releaseDate': ep.get('releaseDate', ''),
                        'source': 'sequel'
                    })
    except Exception as e:
        print(f"Error reading Sequel episodes: {e}")

    return {'success': True, 'shows': shows[:6], 'disk': disk_info}


def fetch_pi_status_data():
    """Fetch Pi UPS status, system stats, and health checks."""
    results = {}

    def fetch_ups():
        req = urllib.request.Request(f"{PI_MONITOR_URL}/api/ups/status")
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))

    def fetch_system():
        req = urllib.request.Request(f"{PI_MONITOR_URL}/api/system")
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))

    def fetch_healthcheck():
        req = urllib.request.Request(HEALTHCHECKS_BADGE_URL)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))

    def fetch_outages():
        req = urllib.request.Request(f"{PI_MONITOR_URL}/api/ups/outages")
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))

    def fetch_backup_healthcheck():
        req = urllib.request.Request(BACKUP_HEALTHCHECKS_URL)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))

    def read_backup_status():
        with open(BACKUP_STATUS_FILE, 'r') as f:
            return json.load(f)

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_ups): 'ups',
            executor.submit(fetch_system): 'system',
            executor.submit(fetch_healthcheck): 'healthcheck',
            executor.submit(fetch_outages): 'outages',
            executor.submit(fetch_backup_healthcheck): 'backup_healthcheck',
            executor.submit(read_backup_status): 'backup_status',
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"Error fetching {key}: {e}")
                results[key] = None

    outages_data = results.get('outages')
    outages = outages_data.get('outages', []) if isinstance(outages_data, dict) else (outages_data or [])

    return {
        'success': True,
        'ups': results.get('ups'),
        'system': results.get('system'),
        'healthcheck': results.get('healthcheck'),
        'outages': outages,
        'backup_healthcheck': results.get('backup_healthcheck'),
        'backup_status': results.get('backup_status')
    }


def fetch_heater_runtime():
    """Fetch how long the shed heater has been actively heating for today and yesterday."""
    config = load_config()
    ha_url = config.get('homeAssistantUrl', 'http://localhost:8123')
    ha_key = config.get('homeAssistantApiKey', '')

    if not ha_url or not ha_key:
        return {'today': 0, 'yesterday': 0}

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    def get_runtime_for_period(start_time, end_time):
        """Calculate runtime in seconds for a given period. Returns (total_seconds, sessions)."""
        try:
            # Format as ISO 8601
            start_str = start_time.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = end_time.strftime('%Y-%m-%dT%H:%M:%S')

            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=climate.shed_thermostat"
            headers = {
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            }

            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0 or len(data[0]) == 0:
                return 0, []

            history = data[0]
            total_seconds = 0
            sessions = []

            for i, state_change in enumerate(history):
                hvac_action = state_change.get('attributes', {}).get('hvac_action')
                if hvac_action != 'heating':
                    continue

                # Parse the timestamp
                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue

                # Parse ISO format timestamp and convert to local time
                state_start = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                state_start = state_start.astimezone().replace(tzinfo=None)  # Convert to local time

                # Find when this state ended (next state change or end of period)
                if i + 1 < len(history):
                    next_change = history[i + 1].get('last_changed', '')
                    if next_change:
                        state_end = datetime.fromisoformat(next_change.replace('Z', '+00:00'))
                        state_end = state_end.astimezone().replace(tzinfo=None)  # Convert to local time
                    else:
                        state_end = end_time
                else:
                    # Last state - if still heating, count until end_time or now
                    state_end = min(end_time, now)

                # Clamp to period boundaries
                state_start = max(state_start, start_time)
                state_end = min(state_end, end_time)

                if state_end > state_start:
                    total_seconds += (state_end - state_start).total_seconds()
                    sessions.append((state_start, state_end))

            return int(total_seconds), sessions

        except Exception as e:
            print(f"Error fetching heater runtime: {e}")
            return 0, []

    today_runtime, today_sessions = get_runtime_for_period(today_start, now)

    # Yesterday's runtime by the same time (for comparison)
    yesterday_same_time = yesterday_start + (now - today_start)
    yesterday_by_same_time, yesterday_same_sessions = get_runtime_for_period(yesterday_start, yesterday_same_time)

    # Yesterday's full day total (to know if it was zero all day)
    yesterday_total, yesterday_sessions = get_runtime_for_period(yesterday_start, today_start)

    # Calculate costs
    rates_config = load_heater_rates()
    today_cost = calculate_heating_cost(today_sessions, today_start, rates_config)
    yesterday_cost = calculate_heating_cost(yesterday_sessions, yesterday_start, rates_config)
    yesterday_by_same_time_cost = calculate_heating_cost(yesterday_same_sessions, yesterday_start, rates_config)

    return {
        'today': today_runtime,
        'yesterday': yesterday_total,
        'yesterday_by_same_time': yesterday_by_same_time,
        'today_cost': today_cost,
        'yesterday_cost': yesterday_cost,
        'yesterday_by_same_time_cost': yesterday_by_same_time_cost
    }


HEATER_HISTORY_FILE = 'heater_history.json'

def load_heater_history_cache():
    """Load cached heater history from file."""
    try:
        with open(HEATER_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_heater_history_cache(cache):
    """Save heater history cache to file."""
    try:
        with open(HEATER_HISTORY_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Error saving heater history cache: {e}")

HEATER_RATES_FILE = 'heater_rates.json'

def load_heater_rates():
    """Load TOU electricity rates from config file."""
    try:
        with open(HEATER_RATES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading heater rates: {e}")
        return None

def get_tou_rate_for_hour(hour, season, rates):
    """Return the TOU $/kWh rate for a given hour on a weekday.
    Ontario TOU schedule:
      Winter (Nov-Apr): on-peak 7-11 & 17-19, mid-peak 11-17, off-peak rest
      Summer (May-Oct): on-peak 11-17, mid-peak 7-11 & 17-19, off-peak rest
    """
    season_rates = rates.get(season, rates.get('winter'))
    if season == 'winter':
        if (7 <= hour < 11) or (17 <= hour < 19):
            return season_rates['on_peak']
        elif 11 <= hour < 17:
            return season_rates['mid_peak']
        else:
            return season_rates['off_peak']
    else:  # summer
        if 11 <= hour < 17:
            return season_rates['on_peak']
        elif (7 <= hour < 11) or (17 <= hour < 19):
            return season_rates['mid_peak']
        else:
            return season_rates['off_peak']

def split_session_cost(start, end, is_off_peak_day, season, rates_config):
    """Calculate cost for one heating session, splitting at TOU boundary hours."""
    adder = rates_config.get('delivery_regulatory_adder', 0)
    kw = rates_config.get('heater_watts', 1500) / 1000.0
    off_peak_rate = rates_config.get(season, rates_config.get('winter', {})).get('off_peak', 0.098)

    total_cost = 0.0
    current = start

    while current < end:
        if is_off_peak_day:
            rate = off_peak_rate
            segment_end = end
        else:
            rate = get_tou_rate_for_hour(current.hour, season, rates_config)
            # Find next TOU boundary
            boundaries = [7, 11, 17, 19]
            next_boundary = None
            for b in boundaries:
                boundary_time = current.replace(hour=b, minute=0, second=0, microsecond=0)
                if boundary_time > current:
                    next_boundary = boundary_time
                    break
            if next_boundary is None:
                # Next boundary is 7am tomorrow
                next_boundary = (current + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
            segment_end = min(end, next_boundary)

        hours = (segment_end - current).total_seconds() / 3600.0
        total_cost += hours * (rate + adder) * kw
        current = segment_end

    return total_cost

def calculate_heating_cost(sessions, date, rates_config):
    """Calculate total electricity cost for heating sessions on a given date.
    date: a datetime or date object for determining season/weekend/holiday.
    sessions: list of (start_datetime, end_datetime) tuples.
    """
    if not rates_config or not sessions:
        return 0.0

    # Determine season: winter = Nov-Apr, summer = May-Oct
    month = date.month
    season = 'winter' if month >= 11 or month <= 4 else 'summer'

    # Check if off-peak day (weekend or statutory holiday)
    weekday = date.weekday()  # 0=Mon, 6=Sun
    is_weekend = weekday >= 5

    date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
    year_str = date_str[:4]
    holidays = rates_config.get('holidays', {}).get(year_str, [])
    is_holiday = date_str in holidays

    is_off_peak_day = is_weekend or is_holiday

    total_cost = 0.0
    for start, end in sessions:
        total_cost += split_session_cost(start, end, is_off_peak_day, season, rates_config)

    return round(total_cost, 4)

def fetch_heater_history(days=30):
    """Fetch heater runtime history for the past N days, plus outdoor temperature.
    Uses local cache for historical data, only fetches recent days from HA."""
    config = load_config()
    ha_url = config.get('homeAssistantUrl', 'http://localhost:8123')
    ha_key = config.get('homeAssistantApiKey', '')

    if not ha_url or not ha_key:
        return {'success': False, 'error': 'Home Assistant not configured'}

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.strftime('%Y-%m-%d')

    # Load existing cache
    cache = load_heater_history_cache()
    history_data = []

    def get_runtime_for_day(day_start, day_end):
        """Calculate runtime in seconds for a given day. Returns (seconds, was_enabled, sessions, target_temp)."""
        try:
            start_str = day_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = day_end.strftime('%Y-%m-%dT%H:%M:%S')

            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=climate.shed_thermostat"
            headers = {
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            }

            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0 or len(data[0]) == 0:
                return 0, False, [], None

            history = data[0]
            total_seconds = 0
            was_enabled = False
            sessions = []
            target_temp = None

            for i, state_change in enumerate(history):
                hvac_action = state_change.get('attributes', {}).get('hvac_action')
                if hvac_action == 'heating':
                    was_enabled = True
                    # Capture target temp from first heating state change
                    if target_temp is None:
                        try:
                            t = state_change.get('attributes', {}).get('temperature')
                            if t is not None:
                                target_temp = float(t)
                        except (ValueError, TypeError):
                            pass
                if hvac_action != 'heating':
                    continue

                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue

                state_start = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                state_start = state_start.astimezone().replace(tzinfo=None)

                if i + 1 < len(history):
                    next_change = history[i + 1].get('last_changed', '')
                    if next_change:
                        state_end = datetime.fromisoformat(next_change.replace('Z', '+00:00'))
                        state_end = state_end.astimezone().replace(tzinfo=None)
                    else:
                        state_end = day_end
                else:
                    state_end = min(day_end, now)

                state_start = max(state_start, day_start)
                state_end = min(state_end, day_end)

                if state_end > state_start:
                    total_seconds += (state_end - state_start).total_seconds()
                    sessions.append((state_start, state_end))

            return int(total_seconds), was_enabled, sessions, target_temp

        except Exception as e:
            print(f"Error fetching shed heater runtime for {day_start.date()}: {e}")
            return 0, False, [], None

    def get_wfh_status_for_day(day_start, day_end):
        """Check if WFH toggle was on for majority of the day."""
        try:
            start_str = day_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = day_end.strftime('%Y-%m-%dT%H:%M:%S')

            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=input_boolean.working_from_home&minimal_response"
            headers = {
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            }

            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0 or len(data[0]) == 0:
                return False

            history = data[0]
            on_seconds = 0
            total_seconds = (min(day_end, now) - day_start).total_seconds()

            for i, state_change in enumerate(history):
                state = state_change.get('state')
                if state != 'on':
                    continue

                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue

                state_start = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                state_start = state_start.astimezone().replace(tzinfo=None)  # Convert to local time

                if i + 1 < len(history):
                    next_change = history[i + 1].get('last_changed', '')
                    if next_change:
                        state_end = datetime.fromisoformat(next_change.replace('Z', '+00:00'))
                        state_end = state_end.astimezone().replace(tzinfo=None)  # Convert to local time
                    else:
                        state_end = min(day_end, now)
                else:
                    state_end = min(day_end, now)

                state_start = max(state_start, day_start)
                state_end = min(state_end, day_end)

                if state_end > state_start:
                    on_seconds += (state_end - state_start).total_seconds()

            # Consider WFH if toggle was on for more than 4 hours
            return on_seconds > 4 * 3600

        except Exception as e:
            print(f"Error fetching WFH status for {day_start.date()}: {e}")
            return False

    def get_outdoor_temp_for_day(day_start, day_end):
        """Get average outdoor temperature for a day from weather sensor."""
        try:
            start_str = day_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = day_end.strftime('%Y-%m-%dT%H:%M:%S')

            # Try common outdoor temperature entity IDs
            outdoor_entities = [
                'sensor.openweathermap_temperature',
                'sensor.outdoor_temperature',
                'weather.home',
            ]

            for entity_id in outdoor_entities:
                try:
                    url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id={entity_id}&minimal_response"
                    headers = {
                        'Authorization': f'Bearer {ha_key}',
                        'Content-Type': 'application/json',
                    }

                    req = urllib.request.Request(url, headers=headers, method='GET')
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read().decode('utf-8'))

                    if data and len(data) > 0 and len(data[0]) > 0:
                        temps = []
                        for state in data[0]:
                            try:
                                # For weather entity, temp is in attributes
                                if entity_id.startswith('weather.'):
                                    temp = state.get('attributes', {}).get('temperature')
                                else:
                                    temp = float(state.get('state', 0))
                                if temp and -50 < temp < 60:  # Sanity check
                                    temps.append(temp)
                            except (ValueError, TypeError):
                                continue

                        if temps:
                            return round(sum(temps) / len(temps), 1)
                except Exception:
                    continue

            return None

        except Exception as e:
            print(f"Error fetching outdoor temp for {day_start.date()}: {e}")
            return None

    def get_indoor_temp_history(range_start, range_end):
        """Query indoor temp sensor history from HA for a time window.
        Returns [(datetime, float), ...] sorted by time."""
        try:
            start_str = range_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = range_end.strftime('%Y-%m-%dT%H:%M:%S')
            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=sensor.temperature_sensor_2&minimal_response"
            headers = {
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            }
            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0 or len(data[0]) == 0:
                return []

            readings = []
            for state in data[0]:
                try:
                    temp = float(state.get('state', ''))
                    if -20 < temp < 50:  # Sanity check for indoor temps
                        last_changed = state.get('last_changed', '')
                        if last_changed:
                            ts = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                            ts = ts.astimezone().replace(tzinfo=None)
                            readings.append((ts, temp))
                except (ValueError, TypeError):
                    continue
            return sorted(readings, key=lambda x: x[0])
        except Exception as e:
            print(f"Error fetching indoor temp history: {e}")
            return []

    def get_temp_at_time(readings, target_time, max_gap_minutes=30):
        """Find closest reading to a timestamp from a pre-fetched list.
        Returns temp float or None if nearest reading is >max_gap_minutes away."""
        if not readings:
            return None
        closest = min(readings, key=lambda r: abs((r[0] - target_time).total_seconds()))
        gap = abs((closest[0] - target_time).total_seconds()) / 60
        if gap > max_gap_minutes:
            return None
        return closest[1]

    def get_outdoor_temp_at_time(target_time):
        """Query outdoor temp sensors in a 30-min window around a specific timestamp.
        Returns single closest reading or None."""
        try:
            window_start = target_time - timedelta(minutes=30)
            window_end = target_time + timedelta(minutes=30)
            start_str = window_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = window_end.strftime('%Y-%m-%dT%H:%M:%S')

            outdoor_entities = [
                'sensor.openweathermap_temperature',
                'sensor.outdoor_temperature',
            ]

            for entity_id in outdoor_entities:
                try:
                    url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id={entity_id}&minimal_response"
                    headers = {
                        'Authorization': f'Bearer {ha_key}',
                        'Content-Type': 'application/json',
                    }
                    req = urllib.request.Request(url, headers=headers, method='GET')
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read().decode('utf-8'))

                    if data and len(data) > 0 and len(data[0]) > 0:
                        readings = []
                        for state in data[0]:
                            try:
                                temp = float(state.get('state', ''))
                                if -50 < temp < 60:
                                    last_changed = state.get('last_changed', '')
                                    if last_changed:
                                        ts = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                                        ts = ts.astimezone().replace(tzinfo=None)
                                        readings.append((ts, temp))
                            except (ValueError, TypeError):
                                continue
                        if readings:
                            closest = min(readings, key=lambda r: abs((r[0] - target_time).total_seconds()))
                            return round(closest[1], 1)
                except Exception:
                    continue
            return None
        except Exception as e:
            print(f"Error fetching outdoor temp at time: {e}")
            return None

    def find_target_reached(indoor_readings, heating_start, target_temp):
        """Scan indoor readings after heating start, returns (reached_time, actual_temp)
        when temp first hits target. Returns (None, None) if not reached."""
        if not indoor_readings or target_temp is None:
            return None, None
        for ts, temp in indoor_readings:
            if ts >= heating_start and temp >= target_temp:
                return ts, temp
        return None, None

    # Load heater rates for cost calculation
    rates_config = load_heater_rates()

    # Determine date range: use cache's earliest date or N days ago
    if cache:
        earliest_cached = min(cache.keys())
        earliest_date = datetime.strptime(earliest_cached, '%Y-%m-%d')
        # Use whichever is earlier: cache start or N days ago
        start_date = min(earliest_date, today_start - timedelta(days=days - 1))
    else:
        start_date = today_start - timedelta(days=days - 1)

    # Fetch data for each day from start_date to today
    # Only fetch from HA if not in cache or if it's today
    current_date = start_date
    while current_date <= today_start:
        day_start = current_date
        day_end = day_start + timedelta(days=1)
        date_str = day_start.strftime('%Y-%m-%d')

        # Check if we have cached data for this day (and it's not today)
        # Re-fetch if cached entry is missing 'cost' or 'indoor_start_temp' (cache migration)
        if date_str in cache and date_str != today_str and 'cost' in cache[date_str] and 'indoor_start_temp' in cache[date_str]:
            # Use cached data
            history_data.append(cache[date_str])
            current_date += timedelta(days=1)
            continue

        # For today, end at current time
        if date_str == today_str:
            day_end = now

        # Fetch fresh data from HA
        runtime_seconds, thermostat_enabled, sessions, target_temp = get_runtime_for_day(day_start, day_end)
        outdoor_temp = get_outdoor_temp_for_day(day_start, day_end)
        is_wfh = get_wfh_status_for_day(day_start, day_end)
        weekday = day_start.weekday()  # 0=Monday, 6=Sunday

        # Calculate cost for this day
        day_cost = calculate_heating_cost(sessions, day_start, rates_config)

        # Time-to-target tracking
        heating_start_time = None
        indoor_start_temp = None
        outdoor_start_temp = None
        target_reached_time = None
        time_to_target_minutes = None
        target_reached = None

        if thermostat_enabled and sessions:
            heating_start = sessions[0][0]
            heating_start_time = heating_start.strftime('%H:%M')

            try:
                # Query indoor temp history from 30 min before heating start through end of day
                indoor_query_start = heating_start - timedelta(minutes=30)
                indoor_readings = get_indoor_temp_history(indoor_query_start, day_end)

                indoor_start_temp = get_temp_at_time(indoor_readings, heating_start)
                if indoor_start_temp is not None:
                    indoor_start_temp = round(indoor_start_temp, 1)

                outdoor_start_temp = get_outdoor_temp_at_time(heating_start)

                reached_time, _ = find_target_reached(indoor_readings, heating_start, target_temp)
                if reached_time is not None:
                    target_reached = True
                    target_reached_time = reached_time.strftime('%H:%M')
                    time_to_target_minutes = int((reached_time - heating_start).total_seconds() / 60)
                else:
                    # Only mark as not reached if the day is complete (not today)
                    if date_str != today_str:
                        target_reached = False
                    else:
                        target_reached = None  # Still in progress
            except Exception as e:
                print(f"Error computing time-to-target for {date_str}: {e}")

        day_data = {
            'date': date_str,
            'day_label': day_start.strftime('%b %d'),
            'day_of_week': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][weekday],
            'is_weekend': weekday >= 5,
            'is_wfh': is_wfh,
            'thermostat_enabled': thermostat_enabled,
            'runtime_hours': round(runtime_seconds / 3600, 2),
            'runtime_seconds': runtime_seconds,
            'outdoor_temp': outdoor_temp,
            'cost': day_cost,
            'heating_start_time': heating_start_time,
            'target_temp': target_temp,
            'indoor_start_temp': indoor_start_temp,
            'outdoor_start_temp': outdoor_start_temp,
            'target_reached_time': target_reached_time,
            'time_to_target_minutes': time_to_target_minutes,
            'target_reached': target_reached
        }

        history_data.append(day_data)

        # Cache completed days (not today, since it's still accumulating)
        if date_str != today_str:
            cache[date_str] = day_data

        current_date += timedelta(days=1)

    # Save updated cache
    save_heater_history_cache(cache)

    return {
        'success': True,
        'days': history_data,
        'generated_at': now.isoformat()
    }


# Home heater tracking (Ecobee)
HOME_HEATER_RATES_FILE = 'home_heater_rates.json'
HOME_HEATER_HISTORY_FILE = 'home_heater_history.json'

def load_home_heater_rates():
    """Load home heater rates (gas + electricity) from config file."""
    try:
        with open(HOME_HEATER_RATES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading home heater rates: {e}")
        return None

def _build_heat_pump_elec_rates(rates_config):
    """Build a rates_config compatible with split_session_cost for heat pump electricity."""
    elec = rates_config.get('electricity', {})
    return {
        'heater_watts': rates_config.get('heat_pump_kw', 3.7) * 1000,
        'delivery_regulatory_adder': elec.get('delivery_regulatory_adder', 0.028),
        'winter': elec.get('winter', {}),
        'summer': elec.get('summer', {}),
        'holidays': elec.get('holidays', {}),
    }

def split_sessions_by_aux(heat_sessions, aux_states):
    """Split heat sessions into aux (gas) and heat pump (electricity) sub-sessions.
    aux_states: list of (timestamp, is_aux_on) sorted by timestamp from HA history.
    Falls back to treating all heat as aux if aux_states is empty.
    Returns (aux_sessions, hp_sessions).
    """
    if not aux_states:
        return heat_sessions, []

    aux_sessions = []
    hp_sessions = []

    for session_start, session_end in heat_sessions:
        # Determine aux state in effect at session start (last known state <= session_start)
        current_aux = aux_states[0][1]
        for ts, is_on in aux_states:
            if ts <= session_start:
                current_aux = is_on
            else:
                break

        current_time = session_start
        for ts, is_on in aux_states:
            if ts <= session_start:
                continue
            if ts >= session_end:
                break
            # Aux state changed during this session - record the segment before the change
            if ts > current_time:
                if current_aux:
                    aux_sessions.append((current_time, ts))
                else:
                    hp_sessions.append((current_time, ts))
            current_time = ts
            current_aux = is_on

        # Record the remaining portion of the session
        if current_time < session_end:
            if current_aux:
                aux_sessions.append((current_time, session_end))
            else:
                hp_sessions.append((current_time, session_end))

    return aux_sessions, hp_sessions


def calculate_home_heating_cost(heat_sessions, cool_sessions, date, rates_config, aux_states=None):
    """Calculate cost for home HVAC sessions using historical aux state.
    Heating sessions are split by aux_states history: aux portions use gas rate,
    non-aux (heat pump) portions use electricity rate.
    Cooling: always uses heat pump electricity.
    aux_states: list of (timestamp, is_aux_on) tuples from HA history.
    If None/empty, all heat is treated as aux (gas) — safe fallback.
    """
    if not rates_config:
        return 0.0

    total_cost = 0.0

    # Split heating sessions into gas (aux) and electricity (heat pump) portions
    aux_heat_sessions, hp_heat_sessions = split_sessions_by_aux(heat_sessions, aux_states or [])

    # Gas cost for aux heat portions
    if aux_heat_sessions:
        furnace_m3 = rates_config.get('furnace_m3_per_hour', 1.33)
        gas_rate = rates_config.get('gas_rate_per_m3', 0.24)
        for start, end in aux_heat_sessions:
            hours = (end - start).total_seconds() / 3600.0
            total_cost += hours * furnace_m3 * gas_rate

    # Electricity cost for heat pump heating portions
    if hp_heat_sessions:
        elec_rates = _build_heat_pump_elec_rates(rates_config)
        total_cost += calculate_heating_cost(hp_heat_sessions, date, elec_rates)

    # Cooling cost - always heat pump electricity
    if cool_sessions:
        elec_rates = _build_heat_pump_elec_rates(rates_config)
        total_cost += calculate_heating_cost(cool_sessions, date, elec_rates)

    return round(total_cost, 4)

def get_home_aux_state():
    """Get current state of input_boolean.ecobee_aux from Home Assistant."""
    try:
        state = ha_request('GET', 'states/input_boolean.ecobee_aux')
        if state:
            return state.get('state', 'off') == 'on'
    except Exception as e:
        print(f"Error fetching ecobee_aux state: {e}")
    return True  # Default to aux/gas if can't determine

def load_home_heater_history_cache():
    """Load cached home heater history from file."""
    try:
        with open(HOME_HEATER_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_home_heater_history_cache(cache):
    """Save home heater history cache to file."""
    try:
        with open(HOME_HEATER_HISTORY_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Error saving home heater history cache: {e}")

def fetch_home_heater_runtime():
    """Fetch home heater runtime (active heating) for today and yesterday, with cost."""
    config = load_config()
    ha_url = config.get('homeAssistantUrl', 'http://localhost:8123')
    ha_key = config.get('homeAssistantApiKey', '')

    if not ha_url or not ha_key:
        return {'today': 0, 'yesterday': 0}

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    def get_runtime_for_period(start, end):
        """Calculate runtime in seconds for a given period.
        Returns (total_seconds, heat_sessions, cool_sessions, aux_states)
        where aux_states is a list of (timestamp, is_aux_on) from HA history."""
        try:
            start_str = start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = end.strftime('%Y-%m-%dT%H:%M:%S')

            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=climate.my_ecobee,input_boolean.ecobee_aux"
            headers = {
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            }

            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0:
                return 0, [], [], []

            # Separate ecobee climate history from aux boolean history by entity_id
            ecobee_history = []
            aux_history = []
            for entity_data in data:
                if not entity_data:
                    continue
                eid = entity_data[0].get('entity_id', '')
                if eid == 'climate.my_ecobee':
                    ecobee_history = entity_data
                elif eid == 'input_boolean.ecobee_aux':
                    aux_history = entity_data

            if not ecobee_history:
                return 0, [], [], []

            # Parse aux state changes into (timestamp, is_on) list
            aux_states = []
            for state_change in aux_history:
                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue
                ts = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                ts = ts.astimezone().replace(tzinfo=None)
                aux_states.append((ts, state_change.get('state') == 'on'))

            history = ecobee_history
            total_seconds = 0
            heat_sessions = []
            cool_sessions = []

            for i, state_change in enumerate(history):
                hvac_action = state_change.get('attributes', {}).get('hvac_action')
                if hvac_action not in ('heating', 'cooling'):
                    continue

                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue

                state_start = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                state_start = state_start.astimezone().replace(tzinfo=None)

                if i + 1 < len(history):
                    next_change = history[i + 1].get('last_changed', '')
                    if next_change:
                        state_end = datetime.fromisoformat(next_change.replace('Z', '+00:00'))
                        state_end = state_end.astimezone().replace(tzinfo=None)
                    else:
                        state_end = end
                else:
                    state_end = min(end, now)

                state_start = max(state_start, start)
                state_end = min(state_end, end)

                if state_end > state_start:
                    total_seconds += (state_end - state_start).total_seconds()
                    if hvac_action == 'heating':
                        heat_sessions.append((state_start, state_end))
                    else:
                        cool_sessions.append((state_start, state_end))

            return int(total_seconds), heat_sessions, cool_sessions, aux_states

        except Exception as e:
            print(f"Error fetching home heater runtime: {e}")
            return 0, [], [], []

    today_runtime, today_heat, today_cool, today_aux = get_runtime_for_period(today_start, now)

    yesterday_same_time = yesterday_start + (now - today_start)
    yesterday_by_same_time, yesterday_same_heat, yesterday_same_cool, yesterday_same_aux = get_runtime_for_period(yesterday_start, yesterday_same_time)

    yesterday_total, yesterday_heat, yesterday_cool, yesterday_aux = get_runtime_for_period(yesterday_start, today_start)

    # Calculate costs using per-period aux history so gas vs electricity is correct
    rates_config = load_home_heater_rates()
    today_cost = calculate_home_heating_cost(today_heat, today_cool, today_start, rates_config, today_aux)
    yesterday_cost = calculate_home_heating_cost(yesterday_heat, yesterday_cool, yesterday_start, rates_config, yesterday_aux)
    yesterday_by_same_time_cost = calculate_home_heating_cost(yesterday_same_heat, yesterday_same_cool, yesterday_start, rates_config, yesterday_same_aux)

    return {
        'today': today_runtime,
        'yesterday': yesterday_total,
        'yesterday_by_same_time': yesterday_by_same_time,
        'today_cost': today_cost,
        'yesterday_cost': yesterday_cost,
        'yesterday_by_same_time_cost': yesterday_by_same_time_cost
    }


def fetch_home_heater_history(days=30):
    """Fetch home heater runtime history for the past N days, plus outdoor temperature.
    Uses local cache for historical data, only fetches recent days from HA."""
    config = load_config()
    ha_url = config.get('homeAssistantUrl', 'http://localhost:8123')
    ha_key = config.get('homeAssistantApiKey', '')

    if not ha_url or not ha_key:
        return {'success': False, 'error': 'Home Assistant not configured'}

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.strftime('%Y-%m-%d')

    cache = load_home_heater_history_cache()
    history_data = []

    def get_runtime_for_day(day_start, day_end):
        """Calculate runtime in seconds for a given day.
        Returns (seconds, was_enabled, heat_sessions, cool_sessions, aux_states)
        where aux_states is a list of (timestamp, is_aux_on) from HA history."""
        try:
            start_str = day_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = day_end.strftime('%Y-%m-%dT%H:%M:%S')

            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=climate.my_ecobee,input_boolean.ecobee_aux"
            headers = {
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            }

            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0:
                return 0, False, [], [], []

            # Separate ecobee climate history from aux boolean history by entity_id
            ecobee_history = []
            aux_history = []
            for entity_data in data:
                if not entity_data:
                    continue
                eid = entity_data[0].get('entity_id', '')
                if eid == 'climate.my_ecobee':
                    ecobee_history = entity_data
                elif eid == 'input_boolean.ecobee_aux':
                    aux_history = entity_data

            # Parse aux state changes into (timestamp, is_on) list
            aux_states = []
            for state_change in aux_history:
                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue
                ts = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                ts = ts.astimezone().replace(tzinfo=None)
                aux_states.append((ts, state_change.get('state') == 'on'))

            if not ecobee_history:
                return 0, False, [], [], aux_states

            history = ecobee_history
            total_seconds = 0
            was_enabled = False
            heat_sessions = []
            cool_sessions = []

            for i, state_change in enumerate(history):
                hvac_action = state_change.get('attributes', {}).get('hvac_action')
                if hvac_action in ('heating', 'cooling'):
                    was_enabled = True
                else:
                    continue

                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue

                state_start = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                state_start = state_start.astimezone().replace(tzinfo=None)

                if i + 1 < len(history):
                    next_change = history[i + 1].get('last_changed', '')
                    if next_change:
                        state_end = datetime.fromisoformat(next_change.replace('Z', '+00:00'))
                        state_end = state_end.astimezone().replace(tzinfo=None)
                    else:
                        state_end = day_end
                else:
                    state_end = min(day_end, now)

                state_start = max(state_start, day_start)
                state_end = min(state_end, day_end)

                if state_end > state_start:
                    total_seconds += (state_end - state_start).total_seconds()
                    if hvac_action == 'heating':
                        heat_sessions.append((state_start, state_end))
                    else:
                        cool_sessions.append((state_start, state_end))

            return int(total_seconds), was_enabled, heat_sessions, cool_sessions, aux_states

        except Exception as e:
            print(f"Error fetching home heater runtime for {day_start.date()}: {e}")
            return 0, False, [], [], []

    def get_outdoor_temp_for_day(day_start, day_end):
        """Get average outdoor temperature for a day."""
        try:
            start_str = day_start.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = day_end.strftime('%Y-%m-%dT%H:%M:%S')

            outdoor_entities = [
                'sensor.openweathermap_temperature',
                'sensor.outdoor_temperature',
                'weather.home',
            ]

            for entity_id in outdoor_entities:
                try:
                    url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id={entity_id}&minimal_response"
                    headers = {
                        'Authorization': f'Bearer {ha_key}',
                        'Content-Type': 'application/json',
                    }

                    req = urllib.request.Request(url, headers=headers, method='GET')
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read().decode('utf-8'))

                    if data and len(data) > 0 and len(data[0]) > 0:
                        temps = []
                        for state in data[0]:
                            try:
                                if entity_id.startswith('weather.'):
                                    temp = state.get('attributes', {}).get('temperature')
                                else:
                                    temp = float(state.get('state', 0))
                                if temp and -50 < temp < 60:
                                    temps.append(temp)
                            except (ValueError, TypeError):
                                continue

                        if temps:
                            return round(sum(temps) / len(temps), 1)
                except Exception:
                    continue

            return None

        except Exception as e:
            print(f"Error fetching outdoor temp for {day_start.date()}: {e}")
            return None

    # Load rates for cost calculation
    rates_config = load_home_heater_rates()

    # Determine date range
    if cache:
        earliest_cached = min(cache.keys())
        earliest_date = datetime.strptime(earliest_cached, '%Y-%m-%d')
        start_date = min(earliest_date, today_start - timedelta(days=days - 1))
    else:
        start_date = today_start - timedelta(days=days - 1)

    current_date = start_date
    while current_date <= today_start:
        day_start = current_date
        day_end = day_start + timedelta(days=1)
        date_str = day_start.strftime('%Y-%m-%d')

        yesterday_str = (today_start - timedelta(days=1)).strftime('%Y-%m-%d')
        if date_str in cache and date_str != today_str and date_str != yesterday_str:
            history_data.append(cache[date_str])
            current_date += timedelta(days=1)
            continue

        if date_str == today_str:
            day_end = now

        runtime_seconds, thermostat_enabled, heat_sessions, cool_sessions, day_aux_states = get_runtime_for_day(day_start, day_end)
        outdoor_temp = get_outdoor_temp_for_day(day_start, day_end)
        weekday = day_start.weekday()

        # Calculate cost using per-day aux history for correct gas vs electricity split
        day_cost = calculate_home_heating_cost(heat_sessions, cool_sessions, day_start, rates_config, day_aux_states)

        day_data = {
            'date': date_str,
            'day_label': day_start.strftime('%b %d'),
            'day_of_week': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][weekday],
            'is_weekend': weekday >= 5,
            'thermostat_enabled': thermostat_enabled,
            'runtime_hours': round(runtime_seconds / 3600, 2),
            'runtime_seconds': runtime_seconds,
            'outdoor_temp': outdoor_temp,
            'cost': day_cost
        }

        history_data.append(day_data)

        # Always write to cache — today gets a last_updated so consumers know how fresh it is
        if date_str == today_str:
            day_data['last_updated'] = now.isoformat()
        cache[date_str] = day_data

        current_date += timedelta(days=1)

    save_home_heater_history_cache(cache)

    return {
        'success': True,
        'days': history_data,
        'generated_at': now.isoformat()
    }


def fetch_ha_panel_data(panel_id):
    """Fetch Home Assistant states for a panel."""
    settings = load_settings()
    panels = settings.get('homeAssistant', {}).get('panels', {})
    panel_config = panels.get(panel_id)

    if not panel_config:
        return {'success': False, 'error': f'Panel not found: {panel_id}'}

    entities = [e['entityId'] for e in panel_config.get('entities', [])]

    if not entities:
        return {'success': True, 'panel': panel_config, 'states': {}}

    states = {}

    def fetch_entity(entity):
        return entity, ha_request('GET', f'states/{entity}')

    with ThreadPoolExecutor(max_workers=len(entities)) as executor:
        futures = {executor.submit(fetch_entity, e): e for e in entities}
        for future in as_completed(futures):
            try:
                entity, state = future.result()
                states[entity] = state
            except Exception as e:
                entity = futures[future]
                print(f"Error fetching HA entity {entity}: {e}")
                states[entity] = None

    result = {'success': True, 'panel': panel_config, 'states': states}

    # For shed panel, include heater runtime data
    if panel_id == 'shed':
        result['heater_runtime'] = fetch_heater_runtime()

    # For home panel, include home heater runtime data
    if panel_id == 'home':
        result['heater_runtime'] = fetch_home_heater_runtime()

    return result


# =============================================================================
# Background Cache Refresh
# =============================================================================

def refresh_all_caches():
    """Refresh all cached API data."""
    print(f"[{datetime.now().isoformat()}] Refreshing API caches...")

    # Refresh TV shows
    try:
        tv_data = fetch_tv_shows_data()
        with _cache_lock:
            _api_cache['tv_shows'] = {
                'data': tv_data,
                'updated_at': datetime.now().isoformat()
            }
        print("  - TV shows cache updated")
    except Exception as e:
        print(f"  - TV shows cache error: {e}")

    # Refresh Pi status
    try:
        pi_data = fetch_pi_status_data()
        with _cache_lock:
            _api_cache['pi_status'] = {
                'data': pi_data,
                'updated_at': datetime.now().isoformat()
            }
        print("  - Pi status cache updated")
    except Exception as e:
        print(f"  - Pi status cache error: {e}")

    # Refresh HA panels (shed, home)
    settings = load_settings()
    panel_ids = list(settings.get('homeAssistant', {}).get('panels', {}).keys())
    for panel_id in panel_ids:
        try:
            panel_data = fetch_ha_panel_data(panel_id)
            with _cache_lock:
                _api_cache['ha_panels'][panel_id] = {
                    'data': panel_data,
                    'updated_at': datetime.now().isoformat()
                }
            print(f"  - HA panel '{panel_id}' cache updated")
        except Exception as e:
            print(f"  - HA panel '{panel_id}' cache error: {e}")

    # Refresh heater history (shed + home)
    try:
        fetch_heater_history(days=30)
        print("  - Shed heater history cache updated")
    except Exception as e:
        print(f"  - Shed heater history cache error: {e}")

    try:
        fetch_home_heater_history(days=30)
        print("  - Home heater history cache updated")
    except Exception as e:
        print(f"  - Home heater history cache error: {e}")

    print(f"[{datetime.now().isoformat()}] Cache refresh complete")


def cache_refresh_loop():
    """Background thread that periodically refreshes caches."""
    while True:
        try:
            refresh_all_caches()
        except Exception as e:
            print(f"Cache refresh loop error: {e}")
        time.sleep(CACHE_TTL)


def invalidate_ha_cache():
    """Invalidate all HA panel caches (called after actions)."""
    with _cache_lock:
        for panel_id in _api_cache['ha_panels']:
            _api_cache['ha_panels'][panel_id]['data'] = None


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # Add no-cache headers for HTML and JSON files to prevent mobile Safari caching
        if self.path.endswith(('.html', '.json')) or self.path == '/':
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        elif self.path.endswith('.css'):
            # Allow CSS to be cached for 5 minutes - it rarely changes
            self.send_header('Cache-Control', 'public, max-age=300')
        super().end_headers()

    def send_json_response(self, status_code, data):
        """Send a JSON response with the given status code."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        # Config and API key management
        if self.path == '/api/config':
            self.get_config()
        # Connection tests
        elif self.path == '/api/test/openweather':
            self.test_openweather()
        elif self.path == '/api/test/openai':
            self.test_openai()
        elif self.path == '/api/test/anthropic':
            self.test_anthropic()
        elif self.path == '/api/test/gemini':
            self.test_gemini()
        elif self.path == '/api/test/homeassistant':
            self.test_homeassistant()
        elif self.path == '/api/test/tmdb':
            self.test_tmdb()
        # Weather proxy (security - don't expose API key to frontend)
        elif self.path.startswith('/api/weather?'):
            self.get_weather_proxy()
        elif self.path.startswith('/api/forecast?'):
            self.get_forecast_proxy()
        # Generic HA panel endpoint: /api/home-assistant/panel/{panelId}
        elif self.path.startswith('/api/home-assistant/panel/'):
            panel_id = self.path.split('/api/home-assistant/panel/')[1]
            self.get_ha_panel_status(panel_id)
        # Backward compatibility for old endpoints
        elif self.path == '/api/home-assistant/shed':
            self.get_ha_panel_status('shed')
        elif self.path == '/api/home-assistant/home':
            self.get_ha_panel_status('home')
        elif self.path == '/api/pi/status' or self.path.startswith('/api/pi/status?'):
            self.get_pi_status()
        elif self.path == '/api/money':
            self.get_money()
        elif self.path == '/api/tv/shows':
            self.get_tv_shows()
        elif self.path == '/api/settings':
            self.get_settings()
        elif self.path == '/api/wisdom/random':
            self.get_random_wisdom()
        elif self.path == '/api/heater-history':
            self.get_heater_history()
        elif self.path == '/api/home-heater-history':
            self.get_home_heater_history()
        elif self.path == '/api/todoist/tasks':
            self.get_todoist_tasks()
        elif self.path == '/api/raindrop/links':
            self.get_raindrop_links()
        elif self.path == '/api/raindrop/stats':
            self.get_raindrop_stats()
        elif self.path == '/api/raindrop/favorites':
            self.get_raindrop_favorites()
        elif self.path == '/api/raindrop/latest':
            self.get_raindrop_latest()
        elif self.path == '/api/reader':
            self.get_reader_articles()
        else:
            super().do_GET()

    def get_tv_shows(self):
        """Get combined TV shows from cache or fetch live."""
        try:
            with _cache_lock:
                cached = _api_cache['tv_shows']

            if cached['data']:
                response = cached['data'].copy()
                response['cached_at'] = cached['updated_at']
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            else:
                # Fallback to live fetch if cache is empty
                data = fetch_tv_shows_data()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_todoist_tasks(self):
        """Get today's tasks from Todoist API."""
        try:
            config = load_config()
            api_key = config.get('todoistApiKey', '')
            if not api_key:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Todoist API key not configured'}).encode())
                return

            all_tasks = []
            next_cursor = None
            while True:
                url = 'https://api.todoist.com/api/v1/tasks'
                if next_cursor:
                    url += f'?cursor={next_cursor}'
                req = urllib.request.Request(
                    url,
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    }
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                all_tasks.extend(data.get('results', []))
                next_cursor = data.get('next_cursor')
                if not next_cursor:
                    break

            # Find inbox project ID
            proj_req = urllib.request.Request(
                'https://api.todoist.com/api/v1/projects',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
            )
            with urllib.request.urlopen(proj_req, timeout=10) as proj_resp:
                proj_data = json.loads(proj_resp.read().decode())
            projects = proj_data.get('results', [])
            inbox_id = next(
                (p['id'] for p in projects if p.get('name', '').lower() == 'inbox'),
                None
            )

            today = datetime.now().strftime('%Y-%m-%d')
            today_tasks = [
                t for t in all_tasks
                if t.get('due') and t['due']['date'][:10] <= today
            ]
            inbox_tasks = [
                t for t in all_tasks
                if inbox_id and t.get('project_id') == inbox_id and not t.get('due')
            ]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'today': today_tasks, 'inbox': inbox_tasks}).encode())
        except Exception as e:
            print(f"Error fetching Todoist tasks: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def close_todoist_task(self, task_id):
        """Close (complete) a Todoist task."""
        try:
            config = load_config()
            api_key = config.get('todoistApiKey', '')
            if not api_key:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Todoist API key not configured'}).encode())
                return

            req = urllib.request.Request(
                f'https://api.todoist.com/api/v1/tasks/{task_id}/close',
                method='POST',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
        except Exception as e:
            print(f"Error closing Todoist task {task_id}: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def create_todoist_task(self):
        """Create a new task in the Todoist inbox."""
        try:
            config = load_config()
            api_key = config.get('todoistApiKey', '')
            if not api_key:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Todoist API key not configured'}).encode())
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8')) if post_data else {}
            content = data.get('content', '').strip()
            if not content:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Task content is required'}).encode())
                return

            task_body = {'content': content}
            description = data.get('description', '').strip()
            if description:
                task_body['description'] = description
            payload = json.dumps(task_body).encode()
            req = urllib.request.Request(
                'https://api.todoist.com/api/v1/tasks',
                data=payload,
                method='POST',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                task = json.loads(resp.read().decode())

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'task': task}).encode())
        except Exception as e:
            print(f"Error creating Todoist task: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def punt_todoist_tasks(self):
        """Reschedule all given tasks to tomorrow via Todoist Sync API."""
        try:
            config = load_config()
            api_key = config.get('todoistApiKey', '')
            if not api_key:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Todoist API key not configured'}).encode())
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            body = json.loads(post_data.decode('utf-8')) if post_data else {}
            task_ids = body.get('task_ids', [])

            if not task_ids:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'No task IDs provided'}).encode())
                return

            import uuid
            tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            commands = []
            for tid in task_ids:
                commands.append({
                    'type': 'item_update',
                    'uuid': str(uuid.uuid4()),
                    'args': {
                        'id': tid,
                        'due': {'date': tomorrow}
                    }
                })

            payload = json.dumps({'commands': commands}).encode()
            req = urllib.request.Request(
                'https://api.todoist.com/api/v1/sync',
                data=payload,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'punted': len(task_ids)}).encode())
        except Exception as e:
            print(f"Error punting Todoist tasks: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def _raindrop_request(self, path, params=None):
        """Make an authenticated request to the Raindrop.io API."""
        config = load_config()
        api_key = config.get('raindropApiKey', '')
        if not api_key:
            return None, 'Raindrop API key not configured'
        url = f'https://api.raindrop.io/rest/v1{path}'
        if params:
            url += '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {api_key}'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), None

    def _raindrop_put(self, path, body):
        """Make an authenticated PUT request to the Raindrop.io API."""
        config = load_config()
        api_key = config.get('raindropApiKey', '')
        if not api_key:
            return None, 'Raindrop API key not configured'
        url = f'https://api.raindrop.io/rest/v1{path}'
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method='PUT',
                                     headers={'Authorization': f'Bearer {api_key}',
                                              'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), None

    def get_raindrop_links(self):
        """Fetch random raindrops for the links panel."""
        try:
            import random
            # Get total count first
            count_data, err = self._raindrop_request('/raindrops/0', {'perpage': 1})
            if err:
                self.send_json_response(400, {'success': False, 'error': err})
                return
            total = count_data.get('count', 0)
            # Pick a random page (fetch 20 per page, pick random offset)
            per_page = 20
            max_page = max(0, (total - per_page) // per_page)
            page = random.randint(0, max_page)
            data, err2 = self._raindrop_request('/raindrops/0', {'perpage': per_page, 'page': page})
            if err2:
                self.send_json_response(400, {'success': False, 'error': err2})
                return
            links = [
                {
                    'id': item.get('_id'),
                    'collectionId': item.get('collection', {}).get('$id'),
                    'url': item.get('link', ''),
                    'title': item.get('title', 'Untitled'),
                    'tags': ', '.join(item.get('tags', [])),
                    'comment': item.get('note', ''),
                    'important': item.get('important', False),
                    'added': self._format_raindrop_date(item.get('created', '')),
                }
                for item in data.get('items', [])
                if item.get('link')
            ]
            self.send_json_response(200, {'success': True, 'links': links})
        except Exception as e:
            print(f"Error fetching Raindrop links: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def get_raindrop_stats(self):
        """Fetch Raindrop.io collection stats."""
        try:
            all_data, err = self._raindrop_request('/raindrops/0', {'perpage': 1})
            if err:
                self.send_json_response(400, {'success': False, 'error': err})
                return
            unsorted_data, _ = self._raindrop_request('/raindrops/-1', {'perpage': 1})
            total = all_data.get('count', 0)
            unsorted = unsorted_data.get('count', 0) if unsorted_data else 0
            self.send_json_response(200, {'success': True, 'total': total, 'unsorted': unsorted})
        except Exception as e:
            print(f"Error fetching Raindrop stats: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def get_raindrop_favorites(self):
        """Fetch favorited raindrops for the starred links header."""
        try:
            data, err = self._raindrop_request('/raindrops/0', {'search': 'important:true', 'perpage': 10})
            if err:
                self.send_json_response(400, {'success': False, 'error': err})
                return
            links = [
                {
                    'id': item.get('_id'),
                    'collectionId': item.get('collection', {}).get('$id'),
                    'url': item.get('link', ''),
                    'title': item.get('title', 'Untitled'),
                }
                for item in data.get('items', [])
                if item.get('link')
            ]
            self.send_json_response(200, {'success': True, 'links': links})
        except Exception as e:
            print(f"Error fetching Raindrop favorites: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def _format_raindrop_date(self, created_str):
        """Format a Raindrop ISO date string to 'Mon D' (e.g. 'Mar 5')."""
        if not created_str:
            return ''
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            return dt.strftime('%b ') + str(dt.day)
        except Exception:
            return ''

    def get_raindrop_latest(self):
        """Fetch the 10 most recently added raindrops."""
        try:
            data, err = self._raindrop_request('/raindrops/0', {'sort': '-created', 'perpage': 10})
            if err:
                self.send_json_response(400, {'success': False, 'error': err})
                return
            links = [
                {
                    'id': item.get('_id'),
                    'collectionId': item.get('collection', {}).get('$id'),
                    'url': item.get('link', ''),
                    'title': item.get('title', 'Untitled'),
                    'tags': ', '.join(item.get('tags', [])),
                    'comment': item.get('note', ''),
                    'important': item.get('important', False),
                    'added': self._format_raindrop_date(item.get('created', '')),
                }
                for item in data.get('items', [])
                if item.get('link')
            ]
            self.send_json_response(200, {'success': True, 'links': links})
        except Exception as e:
            print(f"Error fetching Raindrop latest: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def _instapaper_sign(self, method, url, params, consumer_secret, token_secret=''):
        """Generate OAuth 1.0a HMAC-SHA1 signature."""
        encoded = '&'.join(
            f'{urllib.parse.quote(k, safe="")}={urllib.parse.quote(str(params[k]), safe="")}'
            for k in sorted(params.keys())
        )
        base_string = f'{method}&{urllib.parse.quote(url, safe="")}&{urllib.parse.quote(encoded, safe="")}'
        signing_key = f'{urllib.parse.quote(consumer_secret, safe="")}&{urllib.parse.quote(token_secret, safe="")}'
        raw = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        return base64.b64encode(raw).decode()

    def _instapaper_xauth(self, consumer_key, consumer_secret, username, password):
        """Exchange username/password for an Instapaper OAuth access token via xAuth."""
        url = 'https://www.instapaper.com/api/1/oauth/access_token'
        params = {
            'oauth_consumer_key': consumer_key,
            'oauth_nonce': uuid.uuid4().hex,
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_version': '1.0',
            'x_auth_mode': 'client_auth',
            'x_auth_password': password,
            'x_auth_username': username,
        }
        params['oauth_signature'] = self._instapaper_sign('POST', url, params, consumer_secret)
        body = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=body, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode()
        parsed = dict(pair.split('=', 1) for pair in response_body.split('&'))
        return parsed['oauth_token'], parsed['oauth_token_secret']

    def get_reader_articles(self):
        """Fetch articles from Readwise Reader API (inbox/new location)."""
        try:
            config = load_config()
            token = config.get('readerApiKey', '')
            if not token:
                self.send_json_response(400, {'success': False, 'error': 'readerApiKey not configured'})
                return

            url = 'https://readwise.io/api/v3/list/?location=new&withHtmlContent=false'
            req = urllib.request.Request(url, headers={'Authorization': f'Token {token}'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            articles = [
                {
                    'title': doc.get('title') or doc.get('source_url', 'Untitled'),
                    'reader_url': doc.get('url', ''),
                    'source_url': doc.get('source_url') or doc.get('url', ''),
                }
                for doc in data.get('results', [])
                if doc.get('url') or doc.get('source_url')
            ][:10]
            self.send_json_response(200, {'success': True, 'articles': articles})
        except Exception as e:
            print(f"Error fetching Reader articles: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def unfavorite_raindrop(self, raindrop_id):
        """Remove the important flag from a raindrop."""
        try:
            data, err = self._raindrop_put(f'/raindrop/{raindrop_id}', {'important': False})
            if err:
                self.send_json_response(400, {'success': False, 'error': err})
                return
            self.send_json_response(200, {'success': True})
        except Exception as e:
            print(f"Error unfavoriting raindrop: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def favorite_raindrop(self, raindrop_id):
        """Set the important flag on a raindrop."""
        try:
            data, err = self._raindrop_put(f'/raindrop/{raindrop_id}', {'important': True})
            if err:
                self.send_json_response(400, {'success': False, 'error': err})
                return
            self.send_json_response(200, {'success': True})
        except Exception as e:
            print(f"Error favouriting raindrop: {e}")
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def get_money(self):
        """Get money/bills data from money.txt."""
        try:
            money_path = os.path.join(DIRECTORY, 'money.txt')
            bills = []
            if os.path.exists(money_path):
                with open(money_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            bills.append(line)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'bills': bills
            }).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_pi_status(self):
        """Get Pi UPS status from cache or fetch live."""
        try:
            # Check for ?live=true to bypass cache
            use_live = 'live=true' in self.path

            if use_live:
                # Fetch live data directly
                data = fetch_pi_status_data()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
                return

            with _cache_lock:
                cached = _api_cache['pi_status']

            if cached['data']:
                response = cached['data'].copy()
                response['cached_at'] = cached['updated_at']
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            else:
                # Fallback to live fetch if cache is empty
                data = fetch_pi_status_data()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_ha_panel_status(self, panel_id):
        """Get Home Assistant states from cache or fetch live."""
        try:
            with _cache_lock:
                cached = _api_cache['ha_panels'].get(panel_id, {'data': None, 'updated_at': None})

            if cached['data']:
                response = cached['data'].copy()
                response['cached_at'] = cached['updated_at']
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            else:
                # Fallback to live fetch if cache is empty
                data = fetch_ha_panel_data(panel_id)
                if not data.get('success', True):
                    self.send_response(404)
                else:
                    self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_settings(self):
        """Get current settings."""
        try:
            settings = load_settings()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'settings': settings}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_heater_history(self):
        """Get heater runtime history for the past 30 days."""
        try:
            data = fetch_heater_history(days=30)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_home_heater_history(self):
        """Serve home heater history from the local cache file.
        HA polling only happens in the background refresh thread (every 5 min)."""
        try:
            cache = load_home_heater_history_cache()
            if not cache:
                # Cache not yet populated (first startup) — do a live fetch
                data = fetch_home_heater_history(days=30)
            else:
                days = [cache[d] for d in sorted(cache.keys())]
                data = {
                    'success': True,
                    'days': days,
                    'generated_at': datetime.now().isoformat()
                }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_random_wisdom(self):
        """Get a random wisdom quote with rotation limits and history tracking."""
        try:
            import re
            import random
            import hashlib

            wisdom_file = os.path.join(DIRECTORY, 'wisdom', 'wisdom.md')
            wisdom_json_file = os.path.join(DIRECTORY, 'wisdom.json')
            history_file = os.path.join(DIRECTORY, 'wisdom_history.json')

            ROTATION_HOURS = 6
            HISTORY_DAYS = 7

            # Load current wisdom and check if rotation is needed
            current_wisdom = {}
            if os.path.exists(wisdom_json_file):
                with open(wisdom_json_file, 'r', encoding='utf-8') as f:
                    current_wisdom = json.load(f)

            # Check if we should rotate (6 hours since last update)
            if current_wisdom.get('updated_at'):
                last_update = datetime.strptime(current_wisdom['updated_at'], '%Y-%m-%d %H:%M:%S')
                hours_since = (datetime.now() - last_update).total_seconds() / 3600
                if hours_since < ROTATION_HOURS:
                    # Return current wisdom without rotating
                    self.send_json_response(200, {
                        'success': True,
                        'wisdom': current_wisdom.get('wisdom', ''),
                        'source': current_wisdom.get('source', ''),
                        'total_wisdoms': current_wisdom.get('total_wisdoms', 0),
                        'next_rotation_hours': round(ROTATION_HOURS - hours_since, 1)
                    })
                    return

            # Load history of shown wisdoms
            history = []
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)

            # Clean up old history entries (older than 7 days)
            cutoff = datetime.now().timestamp() - (HISTORY_DAYS * 24 * 3600)
            history = [h for h in history if h.get('shown_at', 0) > cutoff]
            shown_hashes = {h['hash'] for h in history}

            # Parse wisdoms from file
            wisdoms = []
            with open(wisdom_file, 'r', encoding='utf-8') as f:
                content = f.read()

            sections = [
                ('## The Wisdom So Far', '## Kevin Kelly', "Merlin Mann's Wisdom Project"),
                ('## Kevin Kelly', '## Works Cited', "Kevin Kelly's Excellent Advice for Living"),
            ]

            for start_header, end_header, source in sections:
                start_match = re.search(re.escape(start_header) + r'.*?\n', content)
                if not start_match:
                    continue

                end_match = re.search(re.escape(end_header), content)
                if end_match:
                    section_content = content[start_match.end():end_match.start()]
                else:
                    section_content = content[start_match.end():]

                for line in section_content.split('\n'):
                    line = line.strip()
                    if line.startswith('- '):
                        wisdom = line[2:].strip()
                        if len(wisdom) > 10:
                            # Clean up markdown formatting
                            wisdom = re.sub(r'\*\*(.+?)\*\*', r'\1', wisdom)
                            wisdom = re.sub(r'\*(.+?)\*', r'\1', wisdom)
                            wisdom = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', wisdom)

                            # Strip "Related:" prefix from Merlin's wisdoms
                            if source == "Merlin Mann's Wisdom Project":
                                wisdom = re.sub(r'^Related\s*(?:corollary)?:\s*', '', wisdom, flags=re.IGNORECASE)

                            # Create hash for deduplication
                            wisdom_hash = hashlib.md5(wisdom.encode()).hexdigest()[:12]
                            wisdoms.append({'text': wisdom, 'source': source, 'hash': wisdom_hash})

            if not wisdoms:
                self.send_json_response(404, {'success': False, 'error': 'No wisdoms found'})
                return

            # Filter out recently shown wisdoms
            available = [w for w in wisdoms if w['hash'] not in shown_hashes]

            # If we've shown everything, reset history
            if not available:
                history = []
                available = wisdoms

            selected = random.choice(available)

            # Add to history
            history.append({
                'hash': selected['hash'],
                'shown_at': datetime.now().timestamp()
            })

            # Save history
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f)

            # Save current wisdom to wisdom.json
            wisdom_data = {
                'wisdom': selected['text'],
                'source': selected['source'],
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_wisdoms': len(wisdoms)
            }
            with open(wisdom_json_file, 'w', encoding='utf-8') as f:
                json.dump(wisdom_data, f, indent=2)

            self.send_json_response(200, {
                'success': True,
                'wisdom': selected['text'],
                'source': selected['source'],
                'total_wisdoms': len(wisdoms),
                'available_wisdoms': len(available)
            })
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    # =========================================================================
    # Config and API Key Management
    # =========================================================================

    def get_config(self):
        """Get config with masked API keys for frontend display."""
        try:
            config = load_config()
            # Return safe keys in full, mask sensitive keys
            safe_config = {
                'name': config.get('name', ''),
                'hasOpenWeatherKey': bool(config.get('openWeatherApiKey')),
                'hasOpenaiKey': bool(config.get('openaiApiKey')),
                'hasAnthropicKey': bool(config.get('anthropicApiKey')),
                'hasGeminiKey': bool(config.get('geminiApiKey')),
                'hasHomeAssistantKey': bool(config.get('homeAssistantApiKey')),
                'hasTmdbKey': bool(config.get('tmdbApiKey')),
                'hasRaindropKey': bool(config.get('raindropApiKey')),
                'homeAssistantUrl': config.get('homeAssistantUrl', ''),
                # Masked versions for display
                'openWeatherApiKeyMasked': mask_key(config.get('openWeatherApiKey', '')),
                'openaiApiKeyMasked': mask_key(config.get('openaiApiKey', '')),
                'anthropicApiKeyMasked': mask_key(config.get('anthropicApiKey', '')),
                'geminiApiKeyMasked': mask_key(config.get('geminiApiKey', '')),
                'homeAssistantApiKeyMasked': mask_key(config.get('homeAssistantApiKey', '')),
                'tmdbApiKeyMasked': mask_key(config.get('tmdbApiKey', '')),
                'raindropApiKeyMasked': mask_key(config.get('raindropApiKey', '')),
            }
            self.send_json_response(200, {'success': True, 'config': safe_config})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def post_config(self):
        """Update config values (individual key updates)."""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            updates = json.loads(post_data.decode('utf-8'))

            config = load_config()

            # Only update provided keys (don't require all keys)
            allowed_keys = ['name', 'openWeatherApiKey', 'openaiApiKey', 'anthropicApiKey',
                           'geminiApiKey', 'homeAssistantApiKey', 'homeAssistantUrl', 'tmdbApiKey',
                           'raindropApiKey']

            for key in allowed_keys:
                if key in updates and updates[key]:  # Only update if value provided
                    config[key] = updates[key]

            save_config(config)
            self.send_json_response(200, {'success': True, 'message': 'Config updated'})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    # =========================================================================
    # Connection Test Endpoints
    # =========================================================================

    def test_openweather(self, provided_key=None):
        """Test OpenWeatherMap API key."""
        try:
            # Use provided key or fall back to config
            if provided_key:
                key = provided_key
            else:
                config = load_config()
                key = config.get('openWeatherApiKey')

            if not key:
                self.send_json_response(400, {'success': False, 'error': 'No API key configured'})
                return

            # Test with a simple weather request (Toronto coordinates)
            url = f"https://api.openweathermap.org/data/2.5/weather?lat=43.65&lon=-79.38&appid={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                self.send_json_response(200, {'success': True, 'message': 'Connection successful'})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.send_json_response(401, {'success': False, 'error': 'Invalid API key'})
            else:
                self.send_json_response(e.code, {'success': False, 'error': str(e)})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def test_openai(self):
        """Test OpenAI API key."""
        try:
            config = load_config()
            key = config.get('openaiApiKey')
            if not key:
                self.send_json_response(400, {'success': False, 'error': 'No API key configured'})
                return

            url = "https://api.openai.com/v1/models"
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {key}'})
            with urllib.request.urlopen(req, timeout=10) as response:
                self.send_json_response(200, {'success': True, 'message': 'Connection successful'})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.send_json_response(401, {'success': False, 'error': 'Invalid API key'})
            else:
                self.send_json_response(e.code, {'success': False, 'error': str(e)})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def test_anthropic(self):
        """Test Anthropic API key."""
        try:
            config = load_config()
            key = config.get('anthropicApiKey')
            if not key:
                self.send_json_response(400, {'success': False, 'error': 'No API key configured'})
                return

            # Test by calling the models endpoint
            url = "https://api.anthropic.com/v1/messages"
            data = json.dumps({
                "model": "claude-3-5-haiku-latest",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Hi"}]
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={
                'x-api-key': key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            })
            with urllib.request.urlopen(req, timeout=15) as response:
                self.send_json_response(200, {'success': True, 'message': 'Connection successful'})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.send_json_response(401, {'success': False, 'error': 'Invalid API key'})
            else:
                self.send_json_response(e.code, {'success': False, 'error': str(e)})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def test_gemini(self):
        """Test Google Gemini API key."""
        try:
            config = load_config()
            key = config.get('geminiApiKey')
            if not key:
                self.send_json_response(400, {'success': False, 'error': 'No API key configured'})
                return

            # Test by calling the Gemini API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
            data = json.dumps({
                "contents": [{"parts": [{"text": "Hi"}]}]
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={
                'content-type': 'application/json'
            })
            with urllib.request.urlopen(req, timeout=15) as response:
                self.send_json_response(200, {'success': True, 'message': 'Connection successful'})
        except urllib.error.HTTPError as e:
            if e.code == 400:
                self.send_json_response(400, {'success': False, 'error': 'Invalid API key'})
            elif e.code == 403:
                self.send_json_response(403, {'success': False, 'error': 'API key not authorized'})
            else:
                self.send_json_response(e.code, {'success': False, 'error': str(e)})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def test_homeassistant(self):
        """Test Home Assistant API connection."""
        try:
            config = load_config()
            ha_url = config.get('homeAssistantUrl')
            ha_key = config.get('homeAssistantApiKey')

            if not ha_url:
                self.send_json_response(400, {'success': False, 'error': 'No Home Assistant URL configured'})
                return
            if not ha_key:
                self.send_json_response(400, {'success': False, 'error': 'No Home Assistant token configured'})
                return

            url = f"{ha_url}/api/"
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {ha_key}'})
            with urllib.request.urlopen(req, timeout=10) as response:
                self.send_json_response(200, {'success': True, 'message': 'Connection successful'})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.send_json_response(401, {'success': False, 'error': 'Invalid token'})
            else:
                self.send_json_response(e.code, {'success': False, 'error': str(e)})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def test_tmdb(self):
        """Test TMDB API key."""
        try:
            config = load_config()
            key = config.get('tmdbApiKey')
            if not key:
                self.send_json_response(400, {'success': False, 'error': 'No API key configured'})
                return

            url = f"https://api.themoviedb.org/3/configuration?api_key={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                self.send_json_response(200, {'success': True, 'message': 'Connection successful'})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.send_json_response(401, {'success': False, 'error': 'Invalid API key'})
            else:
                self.send_json_response(e.code, {'success': False, 'error': str(e)})
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    # =========================================================================
    # Weather Proxy (security - keeps API key server-side)
    # =========================================================================

    def get_weather_proxy(self):
        """Proxy weather requests through backend to hide API key."""
        try:
            # Parse query parameters
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            lat = params.get('lat', [None])[0]
            lon = params.get('lon', [None])[0]

            if not lat or not lon:
                self.send_json_response(400, {'success': False, 'error': 'Missing lat/lon parameters'})
                return

            config = load_config()
            key = config.get('openWeatherApiKey')
            if not key:
                self.send_json_response(400, {'success': False, 'error': 'Weather API key not configured'})
                return

            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                self.send_json_response(200, data)
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def get_forecast_proxy(self):
        """Proxy forecast requests through backend to hide API key."""
        try:
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            lat = params.get('lat', [None])[0]
            lon = params.get('lon', [None])[0]

            if not lat or not lon:
                self.send_json_response(400, {'success': False, 'error': 'Missing lat/lon parameters'})
                return

            config = load_config()
            key = config.get('openWeatherApiKey')
            if not key:
                self.send_json_response(400, {'success': False, 'error': 'Weather API key not configured'})
                return

            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units=metric&appid={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                self.send_json_response(200, data)
        except Exception as e:
            self.send_json_response(500, {'success': False, 'error': str(e)})

    def post_settings(self):
        """Save updated settings."""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            new_settings = json.loads(post_data.decode('utf-8'))
            save_settings(new_settings)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'message': 'Settings saved'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def do_POST(self):
        # Config management
        if self.path == '/api/config':
            self.post_config()
        # Generic refresh endpoint: /api/refresh/{shortcutId}
        elif self.path.startswith('/api/refresh/'):
            shortcut_id = self.path.split('/api/refresh/')[1]
            self.run_refresh_shortcut(shortcut_id)
        # Backward compatibility: map old endpoints to new system
        elif self.path == '/api/refresh-todos':
            self.run_refresh_shortcut('tasks')
        elif self.path == '/api/refresh-money':
            self.run_refresh_shortcut('bills')
        elif self.path == '/api/refresh-summary':
            self.refresh_summary()
        elif self.path == '/api/refresh-new-releases':
            self.refresh_new_releases()
        elif self.path == '/api/home-assistant/scene/heat_shed_in_morning':
            self.activate_scene('scene.heat_shed_in_morning')
        elif self.path == '/api/home-assistant/scene/shed_unoccupied':
            self.activate_scene('scene.shed_unoccupied')
        elif self.path == '/api/home-assistant/toggle/working_from_home':
            self.toggle_input_boolean('input_boolean.working_from_home')
        elif self.path == '/api/automation/wfh-check':
            self.run_wfh_automation()
        elif self.path == '/api/home-assistant/lock/back_door':
            self.toggle_lock('lock.back_door_lock')
        elif self.path == '/api/home-assistant/toggle/shed_desk_lamp':
            self.toggle_light('light.smart_rgb_bulb_2208114772038152050448e1e9a17678')
        elif self.path == '/api/home-assistant/toggle/shed_shelf_light':
            self.toggle_light('light.govee_h617a_501b')
        elif self.path == '/api/home-assistant/toggle/home_occupancy':
            self.toggle_input_boolean('input_boolean.422_occupancy')
        elif self.path == '/api/home-assistant/toggle/ecobee_aux':
            self.toggle_input_boolean('input_boolean.ecobee_aux')
        elif self.path == '/api/home-assistant/climate/set':
            self.set_climate()
        elif self.path == '/api/settings':
            self.post_settings()
        elif self.path == '/api/media/watched':
            self.proxy_media_tracker('/api/watched')
        elif self.path == '/api/media/refresh':
            self.proxy_media_tracker('/api/refresh')
        elif self.path == '/api/todoist/tasks/punt':
            self.punt_todoist_tasks()
        elif self.path == '/api/todoist/tasks/add':
            self.create_todoist_task()
        elif self.path.startswith('/api/todoist/tasks/') and self.path.endswith('/close'):
            task_id = self.path.split('/api/todoist/tasks/')[1].rsplit('/close', 1)[0]
            self.close_todoist_task(task_id)
        elif self.path.startswith('/api/raindrop/unfavorite/'):
            raindrop_id = self.path.split('/api/raindrop/unfavorite/')[1]
            self.unfavorite_raindrop(raindrop_id)
        elif self.path.startswith('/api/raindrop/favorite/'):
            raindrop_id = self.path.split('/api/raindrop/favorite/')[1]
            self.favorite_raindrop(raindrop_id)
        # Test endpoints with provided key
        elif self.path == '/api/test/openweather':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8')) if post_data else {}
            self.test_openweather(provided_key=data.get('key'))
        else:
            self.send_error(404, 'Not Found')

    def run_refresh_shortcut(self, shortcut_id):
        """Run a refresh shortcut via SSH based on settings configuration."""
        try:
            settings = load_settings()
            refresh_config = settings.get('refreshCommands', {})
            ssh_config = refresh_config.get('ssh', {})
            shortcuts = refresh_config.get('shortcuts', {})

            # Check if shortcut exists and is enabled
            shortcut_config = shortcuts.get(shortcut_id)
            if not shortcut_config:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': f'Unknown shortcut: {shortcut_id}'}).encode())
                return

            if not shortcut_config.get('enabled', False):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': f'Shortcut {shortcut_id} is not enabled'}).encode())
                return

            shortcut_name = shortcut_config.get('shortcutName', '')
            if not shortcut_name:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': f'No shortcut name configured for {shortcut_id}'}).encode())
                return

            # Build SSH command from settings
            ssh_host = ssh_config.get('host', 'toms-mac-mini.local')
            ssh_user = ssh_config.get('user', 'tomrobertson')
            ssh_timeout = ssh_config.get('timeout', 30)

            ssh_command = f'{ssh_user}@{ssh_host}'
            shortcuts_command = f'shortcuts run "{shortcut_name}"'

            result = subprocess.run(
                ['ssh', ssh_command, shortcuts_command],
                capture_output=True,
                text=True,
                timeout=ssh_timeout
            )

            if result.returncode == 0:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'message': f'{shortcut_id} refreshed via {shortcut_name}'}).encode())
            else:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': result.stderr}).encode())
        except subprocess.TimeoutExpired:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': 'SSH timeout'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def refresh_new_releases(self):
        """Refresh new releases via the Media Tracker service."""
        self.proxy_media_tracker('/api/refresh')

    def proxy_media_tracker(self, path):
        """Proxy a POST request to the Media Tracker service."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else b''

            req = urllib.request.Request(
                f"{MEDIATRACKER_URL}{path}",
                data=body if body else None,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                result = response.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(result)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(error_body.encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def activate_scene(self, scene_id):
        """Activate a Home Assistant scene."""
        try:
            ha_request('POST', 'services/scene/turn_on', {'entity_id': scene_id})
            invalidate_ha_cache()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'message': f'Scene {scene_id} activated'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def set_climate(self):
        """Set climate entity mode and temperature."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8')) if post_data else {}

            entity_id = data.get('entity_id')
            hvac_mode = data.get('hvac_mode')
            temperature = data.get('temperature')

            if not entity_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'entity_id required'}).encode())
                return

            # Set HVAC mode
            if hvac_mode:
                ha_request('POST', 'services/climate/set_hvac_mode', {
                    'entity_id': entity_id,
                    'hvac_mode': hvac_mode
                })

            # Set temperature (only if mode is not off and temperature is provided)
            if temperature is not None and hvac_mode != 'off':
                ha_request('POST', 'services/climate/set_temperature', {
                    'entity_id': entity_id,
                    'temperature': temperature
                })

            invalidate_ha_cache()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'message': f'Climate {entity_id} set to {hvac_mode}' + (f' at {temperature}°' if temperature else '')
            }).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def toggle_input_boolean(self, entity_id):
        """Toggle an input_boolean."""
        try:
            ha_request('POST', 'services/input_boolean/toggle', {'entity_id': entity_id})
            invalidate_ha_cache()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'message': f'{entity_id} toggled'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def set_input_boolean(self, entity_id, state):
        """Set an input_boolean to on or off."""
        try:
            service = 'turn_on' if state else 'turn_off'
            ha_request('POST', f'services/input_boolean/{service}', {'entity_id': entity_id})
            invalidate_ha_cache()
            return True
        except Exception as e:
            print(f"Error setting {entity_id} to {state}: {e}")
            return False

    def run_wfh_automation(self):
        """Check calendar and day of week to set WFH status."""
        try:
            now = datetime.now()
            today_str = now.strftime('%b %-d, %Y')  # e.g., "Feb 3, 2026"
            weekday = now.weekday()  # 0=Monday, 6=Sunday

            reasons = []
            should_turn_off = False

            # Check if Saturday (5) or Sunday (6) - no WFH on weekends
            if weekday == 5:
                should_turn_off = True
                reasons.append("Saturday")
            elif weekday == 6:
                should_turn_off = True
                reasons.append("Sunday")

            # Check calendar for phrases that indicate not working from home
            no_wfh_phrases = ['in office', 'tom office', 'tom in office', 'out of office', 'away', 'holiday', 'vacation']
            try:
                with open('calendar.json', 'r') as f:
                    cal_data = json.load(f)
                events_str = cal_data.get('events', '')
                for line in events_str.strip().split('\n'):
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        title = event.get('title', '').lower()
                        start = event.get('start', '')
                        # Check if event is today and title matches any no-WFH phrase
                        if today_str in start:
                            if any(phrase in title for phrase in no_wfh_phrases):
                                should_turn_off = True
                                reasons.append(f"Calendar: {event.get('title')}")
                                break
                    except json.JSONDecodeError:
                        continue
            except Exception as e:
                print(f"Error reading calendar: {e}")

            result = {
                'date': now.strftime('%Y-%m-%d'),
                'day_of_week': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][weekday],
                'should_turn_off_wfh': should_turn_off,
                'reasons': reasons,
                'action_taken': None
            }

            if should_turn_off:
                success = self.set_input_boolean('input_boolean.working_from_home', False)
                result['action_taken'] = 'turned_off' if success else 'failed'
            else:
                result['action_taken'] = 'no_change'

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, **result}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def toggle_light(self, entity_id):
        """Toggle a light on/off."""
        try:
            ha_request('POST', 'services/light/toggle', {'entity_id': entity_id})
            invalidate_ha_cache()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'message': f'{entity_id} toggled'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def toggle_lock(self, entity_id):
        """Toggle a lock (lock if unlocked, unlock if locked)."""
        try:
            # Get current state
            state = ha_request('GET', f'states/{entity_id}')
            current_state = state.get('state', 'unknown')

            # Toggle based on current state
            if current_state == 'locked':
                ha_request('POST', 'services/lock/unlock', {'entity_id': entity_id})
                new_state = 'unlocked'
            else:
                ha_request('POST', 'services/lock/lock', {'entity_id': entity_id})
                new_state = 'locked'

            invalidate_ha_cache()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'message': f'{entity_id} {new_state}', 'state': new_state}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def refresh_summary(self):
        try:
            import generate_summary
            # Reload module to pick up any changes
            import importlib
            importlib.reload(generate_summary)

            config = generate_summary.load_config()
            if not config:
                raise Exception('config.json not found')

            ai_settings = generate_summary.load_ai_settings()
            provider = ai_settings.get('provider', 'openai') if ai_settings else 'openai'

            # Check for appropriate API key based on provider
            if provider == 'anthropic' and not config.get('anthropicApiKey'):
                raise Exception('Anthropic API key not configured')
            elif provider == 'gemini' and not config.get('geminiApiKey'):
                raise Exception('Gemini API key not configured')
            elif provider == 'openai' and not config.get('openaiApiKey'):
                raise Exception('OpenAI API key not configured')

            daily_data = generate_summary.gather_daily_data()
            summary = generate_summary.call_ai(config, ai_settings, daily_data)

            if summary:
                generate_summary.save_summary(summary)
                summary_data = generate_summary.load_json_file('daily-summary.json')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'summary': summary_data['summary'],
                    'generated_at': summary_data['generated_at']
                }).encode())
            else:
                raise Exception(f'Failed to generate summary from {provider}')
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

if __name__ == '__main__':
    # Populate cache before starting server
    print("Populating initial cache...")
    refresh_all_caches()

    # Start background cache refresh thread
    cache_thread = threading.Thread(target=cache_refresh_loop, daemon=True)
    cache_thread.start()
    print(f"Cache refresh thread started (TTL: {CACHE_TTL}s)")

    # Use ThreadingHTTPServer for concurrent request handling
    with http.server.ThreadingHTTPServer(('', PORT), DashboardHandler) as httpd:
        # Wrap socket with SSL for HTTPS
        cert_dir = os.path.join(DIRECTORY, 'certs')
        cert_file = os.path.join(cert_dir, 'shedpi2.forest-fujita.ts.net.crt')
        key_file = os.path.join(cert_dir, 'shedpi2.forest-fujita.ts.net.key')
        if os.path.exists(cert_file) and os.path.exists(key_file):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            print(f'Dashboard server running at https://localhost:{PORT}')
        else:
            print(f'WARNING: SSL certs not found, running without HTTPS at http://localhost:{PORT}')
        httpd.serve_forever()
