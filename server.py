#!/usr/bin/env python3
import http.server
import json
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

PORT = 8000
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
    """Return default settings structure."""
    return {
        "version": 1,
        "panels": {
            "weather": {"visible": True},
            "schedule": {"visible": True},
            "tasks": {"visible": True},
            "shed": {"visible": True},
            "home": {"visible": True},
            "piStatus": {"visible": True},
            "bills": {"visible": True},
            "readLater": {"visible": True},
            "tvShows": {"visible": True},
            "anybox": {"visible": True}
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

def load_settings():
    """Load settings from settings.json or return defaults."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return get_default_settings()

def save_settings(settings):
    """Save settings to settings.json."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def load_config():
    config_path = os.path.join(DIRECTORY, 'config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

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

PI_MONITOR_URL = "http://100.125.128.51:5001"
CHANNELS_DVR_URL = "http://100.127.232.39:8089"
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

    return {'success': True, 'panel': panel_config, 'states': states}


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

    def do_GET(self):
        # Generic HA panel endpoint: /api/home-assistant/panel/{panelId}
        if self.path.startswith('/api/home-assistant/panel/'):
            panel_id = self.path.split('/api/home-assistant/panel/')[1]
            self.get_ha_panel_status(panel_id)
        # Backward compatibility for old endpoints
        elif self.path == '/api/home-assistant/shed':
            self.get_ha_panel_status('shed')
        elif self.path == '/api/home-assistant/home':
            self.get_ha_panel_status('home')
        elif self.path == '/api/pi/status':
            self.get_pi_status()
        elif self.path == '/api/money':
            self.get_money()
        elif self.path == '/api/tv/shows':
            self.get_tv_shows()
        elif self.path == '/api/settings':
            self.get_settings()
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
        # Generic refresh endpoint: /api/refresh/{shortcutId}
        if self.path.startswith('/api/refresh/'):
            shortcut_id = self.path.split('/api/refresh/')[1]
            self.run_refresh_shortcut(shortcut_id)
        # Backward compatibility: map old endpoints to new system
        elif self.path == '/api/refresh-todos':
            self.run_refresh_shortcut('tasks')
        elif self.path == '/api/refresh-money':
            self.run_refresh_shortcut('bills')
        elif self.path == '/api/refresh-summary':
            self.refresh_summary()
        elif self.path == '/api/home-assistant/scene/heat_shed_in_morning':
            self.activate_scene('scene.heat_shed_in_morning')
        elif self.path == '/api/home-assistant/scene/shed_unoccupied':
            self.activate_scene('scene.shed_unoccupied')
        elif self.path == '/api/home-assistant/toggle/working_from_home':
            self.toggle_input_boolean('input_boolean.working_from_home')
        elif self.path == '/api/home-assistant/lock/back_door':
            self.toggle_lock('lock.back_door_lock')
        elif self.path == '/api/home-assistant/toggle/shed_desk_lamp':
            self.toggle_light('light.smart_rgb_bulb_2208114772038152050448e1e9a17678')
        elif self.path == '/api/home-assistant/toggle/shed_shelf_light':
            self.toggle_light('light.govee_h617a_501b')
        elif self.path == '/api/settings':
            self.post_settings()
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
            if not config or 'openaiApiKey' not in config:
                raise Exception('OpenAI API key not found in config')

            daily_data = generate_summary.gather_daily_data()
            summary = generate_summary.call_openai(config['openaiApiKey'], daily_data)

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
                raise Exception('Failed to generate summary from OpenAI')
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

    with http.server.HTTPServer(('', PORT), DashboardHandler) as httpd:
        print(f'Dashboard server running at http://localhost:{PORT}')
        httpd.serve_forever()
