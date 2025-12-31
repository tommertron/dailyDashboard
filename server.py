#!/usr/bin/env python3
import http.server
import json
import os
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

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

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # Add no-cache headers for HTML and JSON files to prevent mobile Safari caching
        if self.path.endswith(('.html', '.json')) or self.path == '/':
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        if self.path == '/api/home-assistant/shed':
            self.get_shed_status()
        elif self.path == '/api/home-assistant/home':
            self.get_home_status()
        elif self.path == '/api/pi/status':
            self.get_pi_status()
        elif self.path == '/api/money':
            self.get_money()
        elif self.path == '/api/tv/shows':
            self.get_tv_shows()
        else:
            super().do_GET()

    def get_tv_shows(self):
        """Get combined TV shows from Channels DVR and Sequel episodes."""
        try:
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

                # Sort by CreatedAt descending and get top recordings
                sorted_files = sorted(files, key=lambda x: x.get('CreatedAt', 0), reverse=True)

                for f in sorted_files[:10]:  # Check more to allow for deduplication
                    airing = f.get('Airing', {})
                    title = airing.get('Title', '')
                    if not title or title.lower() in seen_shows:
                        continue

                    seen_shows.add(title.lower())
                    episode_title = airing.get('EpisodeTitle', '')
                    season = airing.get('SeasonNumber')
                    episode = airing.get('EpisodeNumber')

                    # For talk shows, use recording date instead of OriginalDate
                    # (guide data often shows series premiere date for talk shows)
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

                    # Handle typo in key name ("episoes" vs "episodes")
                    episodes = sequel_data.get('episodes', sequel_data.get('episoes', []))

                    for ep in episodes:
                        title = ep.get('show', '')
                        if not title or title.lower() in seen_shows:
                            continue

                        seen_shows.add(title.lower())
                        season = ep.get('season', '')
                        episode_num = ep.get('episodeNumber', '')
                        episode_title = ep.get('episodeTitle', '')
                        release_date = ep.get('releaseDate', '')

                        # Try to get description from TMDB if we have an API key
                        description = ''
                        if tmdb_api_key and season and episode_num:
                            series_id = get_tmdb_series_id(title, tmdb_api_key)
                            if series_id:
                                description = get_tmdb_episode_description(
                                    series_id, season, episode_num, tmdb_api_key
                                )

                        shows.append({
                            'title': title,
                            'season': season,
                            'episodeNumber': episode_num,
                            'episodeTitle': episode_title,
                            'description': description,
                            'poster': ep.get('poster', ''),
                            'releaseDate': release_date,
                            'source': 'sequel'
                        })
            except Exception as e:
                print(f"Error reading Sequel episodes: {e}")

            # Limit to 6 total shows
            shows = shows[:6]

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'shows': shows,
                'disk': disk_info
            }).encode())
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
        """Get Pi UPS status, system stats, and recent power outages."""
        try:
            # Fetch UPS status
            ups_req = urllib.request.Request(f"{PI_MONITOR_URL}/api/ups/status")
            with urllib.request.urlopen(ups_req, timeout=10) as response:
                ups_status = json.loads(response.read().decode('utf-8'))

            # Fetch system stats (CPU, memory)
            system_stats = None
            try:
                system_req = urllib.request.Request(f"{PI_MONITOR_URL}/api/system")
                with urllib.request.urlopen(system_req, timeout=10) as response:
                    system_stats = json.loads(response.read().decode('utf-8'))
            except Exception as e:
                print(f"Error fetching system stats: {e}")

            # Fetch healthchecks status
            healthcheck = None
            try:
                hc_req = urllib.request.Request(HEALTHCHECKS_BADGE_URL)
                with urllib.request.urlopen(hc_req, timeout=5) as response:
                    healthcheck = json.loads(response.read().decode('utf-8'))
            except Exception as e:
                print(f"Error fetching healthcheck: {e}")

            # Fetch power outages
            outages_req = urllib.request.Request(f"{PI_MONITOR_URL}/api/ups/outages")
            with urllib.request.urlopen(outages_req, timeout=10) as response:
                outages_data = json.loads(response.read().decode('utf-8'))

            # Handle nested outages structure
            outages = outages_data.get('outages', []) if isinstance(outages_data, dict) else outages_data

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'ups': ups_status,
                'system': system_stats,
                'healthcheck': healthcheck,
                'outages': outages
            }).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_shed_status(self):
        """Get all shed-related Home Assistant states."""
        try:
            entities = [
                'sensor.temperature_sensor_2',
                'input_boolean.shed_motion_override',
                'climate.shed_thermostat',
            ]
            states = {}
            for entity in entities:
                state = ha_request('GET', f'states/{entity}')
                states[entity] = state

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'states': states}).encode())
        except urllib.error.HTTPError as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': f'HTTP {e.code}: {e.reason}'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def get_home_status(self):
        """Get home-related Home Assistant states (Ecobee, locks, door sensors)."""
        try:
            entities = [
                'climate.my_ecobee',
                'lock.back_door_lock',
                'binary_sensor.contact_sensor_2',  # Shed door sensor
                'binary_sensor.contact_sensor',    # Garage door sensor
            ]
            states = {}
            for entity in entities:
                state = ha_request('GET', f'states/{entity}')
                states[entity] = state

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'states': states}).encode())
        except urllib.error.HTTPError as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': f'HTTP {e.code}: {e.reason}'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def do_POST(self):
        if self.path == '/api/refresh-todos':
            self.refresh_todos()
        elif self.path == '/api/refresh-summary':
            self.refresh_summary()
        elif self.path == '/api/home-assistant/scene/heat_shed_in_morning':
            self.activate_scene('scene.heat_shed_in_morning')
        elif self.path == '/api/home-assistant/scene/shed_unoccupied':
            self.activate_scene('scene.shed_unoccupied')
        elif self.path == '/api/home-assistant/toggle/shed_motion_override':
            self.toggle_input_boolean('input_boolean.shed_motion_override')
        elif self.path == '/api/home-assistant/lock/back_door':
            self.toggle_lock('lock.back_door_lock')
        elif self.path == '/api/refresh-money':
            self.refresh_money()
        else:
            self.send_error(404, 'Not Found')

    def refresh_money(self):
        try:
            result = subprocess.run(
                ['ssh', 'tomrobertson@toms-mac-mini.local', 'shortcuts run "dailyMoney"'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'message': 'Money refreshed'}).encode())
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

    def refresh_todos(self):
        try:
            result = subprocess.run(
                ['ssh', 'tomrobertson@toms-mac-mini.local', 'shortcuts run "Things Today"'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'message': 'Todos refreshed'}).encode())
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

if __name__ == '__main__':
    with http.server.HTTPServer(('', PORT), DashboardHandler) as httpd:
        print(f'Dashboard server running at http://localhost:{PORT}')
        httpd.serve_forever()
