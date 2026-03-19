#!/usr/bin/env python3
"""Generate a daily AI summary by analyzing all dashboard JSON files."""

import json
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote
from update_wisdom import select_random_wisdom

DIRECTORY = os.path.dirname(os.path.abspath(__file__))

def load_json_file(filename):
    """Load a JSON file and return its contents, or None if it fails."""
    filepath = os.path.join(DIRECTORY, filename)
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load {filename}: {e}")
        return None


def fetch_ha_states(ha_url, ha_key, entities):
    """Fetch states from Home Assistant for given entities."""
    states = {}
    for entity in entities:
        try:
            url = f'{ha_url}/api/states/{entity}'
            req = Request(url, headers={
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            })
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                states[entity] = {
                    'state': data.get('state'),
                    'attributes': data.get('attributes', {})
                }
        except Exception as e:
            print(f"Error fetching {entity}: {e}")
    return states


def fetch_shed_state(ha_url, ha_key):
    """Fetch shed state from Home Assistant."""
    entities = [
        'sensor.temperature_sensor_2',
        'climate.shed_thermostat',
        'input_boolean.working_from_home',
        'light.smart_rgb_bulb_2208114772038152050448e1e9a17678',
        'light.govee_h617a_501b',
    ]
    return fetch_ha_states(ha_url, ha_key, entities)


def fetch_home_state(ha_url, ha_key):
    """Fetch home state from Home Assistant (doors, locks, thermostat)."""
    entities = [
        'climate.my_ecobee',
        'lock.back_door_lock',
        'binary_sensor.contact_sensor_2',  # Shed door
        'binary_sensor.contact_sensor',     # Garage door
    ]
    return fetch_ha_states(ha_url, ha_key, entities)


def fetch_heater_runtime(ha_url, ha_key):
    """Fetch how long the shed heater has been running in heat mode for today and yesterday."""
    if not ha_url or not ha_key:
        return None

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    def get_runtime_for_period(start_time, end_time):
        """Calculate runtime in seconds for a given period."""
        try:
            start_str = start_time.strftime('%Y-%m-%dT%H:%M:%S')
            end_str = end_time.strftime('%Y-%m-%dT%H:%M:%S')

            url = f"{ha_url}/api/history/period/{start_str}?end_time={end_str}&filter_entity_id=climate.shed_thermostat&minimal_response"
            req = Request(url, headers={
                'Authorization': f'Bearer {ha_key}',
                'Content-Type': 'application/json',
            })
            with urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data or len(data) == 0 or len(data[0]) == 0:
                return 0

            history = data[0]
            total_seconds = 0

            for i, state_change in enumerate(history):
                state = state_change.get('state')
                if state != 'heat':
                    continue

                last_changed = state_change.get('last_changed', '')
                if not last_changed:
                    continue

                state_start = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                state_start = state_start.replace(tzinfo=None)

                if i + 1 < len(history):
                    next_change = history[i + 1].get('last_changed', '')
                    if next_change:
                        state_end = datetime.fromisoformat(next_change.replace('Z', '+00:00'))
                        state_end = state_end.replace(tzinfo=None)
                    else:
                        state_end = end_time
                else:
                    state_end = min(end_time, now)

                state_start = max(state_start, start_time)
                state_end = min(state_end, end_time)

                if state_end > state_start:
                    total_seconds += (state_end - state_start).total_seconds()

            return int(total_seconds)

        except Exception as e:
            print(f"Error fetching heater runtime: {e}")
            return 0

    today_runtime = get_runtime_for_period(today_start, now)
    yesterday_runtime = get_runtime_for_period(yesterday_start, today_start)

    return {
        'today_minutes': today_runtime // 60,
        'yesterday_minutes': yesterday_runtime // 60
    }


PI_MONITOR_URL = "http://100.115.42.106:5001"
BACKUP_STATUS_FILE = "/mnt/ssd/backupJobs/backup_status.json"
BACKUP_HEALTHCHECKS_URL = "https://healthchecks.io/b/2/fc90bb64-b594-4db2-98f3-f48020b1d2f1.json"


def fetch_backup_status():
    """Fetch backup status from local file and healthchecks."""
    result = {}

    # Read local backup status
    try:
        with open(BACKUP_STATUS_FILE, 'r') as f:
            backup_data = json.load(f)
            result['last_backup'] = {
                'status': backup_data.get('status'),
                'timestamp': backup_data.get('timestamp'),
                'failed_jobs': backup_data.get('failed_jobs', [])
            }
    except Exception as e:
        print(f"Error reading backup status: {e}")

    # Fetch healthchecks status
    try:
        req = Request(BACKUP_HEALTHCHECKS_URL)
        with urlopen(req, timeout=5) as response:
            hc_data = json.loads(response.read().decode('utf-8'))
            result['healthcheck'] = hc_data.get('status')
    except Exception as e:
        print(f"Error fetching backup healthcheck: {e}")

    return result if result else None


def fetch_pi_ups_status():
    """Fetch Pi UPS status and recent outages."""
    try:
        # Fetch UPS status
        ups_req = Request(f"{PI_MONITOR_URL}/api/ups/status")
        with urlopen(ups_req, timeout=10) as response:
            ups_status = json.loads(response.read().decode('utf-8'))

        # Fetch power outages
        outages_req = Request(f"{PI_MONITOR_URL}/api/ups/outages")
        with urlopen(outages_req, timeout=10) as response:
            outages_data = json.loads(response.read().decode('utf-8'))

        # Handle nested outages structure
        outages = outages_data.get('outages', []) if isinstance(outages_data, dict) else outages_data

        return {
            'battery_percent': ups_status.get('battery_percent'),
            'on_ac_power': ups_status.get('on_ac_power'),
            'voltage': ups_status.get('voltage'),
            'recent_outages': outages[:4] if outages else []
        }
    except Exception as e:
        print(f"Error fetching Pi UPS status: {e}")
        return None

def load_config():
    """Load the config file."""
    return load_json_file('config.json')


def load_ai_settings():
    """Load AI prompt settings from settings.json."""
    settings = load_json_file('settings.json')
    if not settings:
        return None

    ai_prompts = settings.get('aiPrompts', {})
    active_persona = ai_prompts.get('activePersona', 'picard')
    active_template = ai_prompts.get('activeTemplate', 'default')

    personas = ai_prompts.get('personas', {})
    templates = ai_prompts.get('templates', {})
    rules = ai_prompts.get('rules', {})

    persona = personas.get(active_persona, {})
    template = templates.get(active_template, {})
    rule_text = rules.get('default', '') if isinstance(rules, dict) else rules

    return {
        'provider': ai_prompts.get('provider', 'openai'),
        'model': ai_prompts.get('model', 'gpt-4o-mini'),
        'persona_name': persona.get('name', 'AI Assistant'),
        'system_prompt': persona.get('systemPrompt', ''),
        'intro_prompt': template.get('introPrompt', ''),
        'rules': rule_text
    }

def gather_daily_data():
    """Gather all daily data from JSON files."""
    now = datetime.now()
    hour = now.hour
    is_weekday = now.weekday() < 5  # Monday=0, Sunday=6
    is_workday_hours = is_weekday and hour < 16
    tomorrow = now + timedelta(days=1)
    tomorrow_is_workday = tomorrow.weekday() < 5
    data = {
        'current_time': now.strftime("%H:%M"),
        'day_of_week': now.strftime("%A"),
        'tomorrow_day_of_week': tomorrow.strftime("%A"),
        'tomorrow_is_workday': tomorrow_is_workday,
        'is_workday_hours': is_workday_hours,
        'is_evening': hour >= 17,
    }

    # Load todos from Todoist API
    config = load_json_file('config.json') or {}
    todoist_key = config.get('todoistApiKey', '')
    if todoist_key:
        try:
            req = Request(
                'https://api.todoist.com/api/v1/tasks',
                headers={'Authorization': f'Bearer {todoist_key}'}
            )
            with urlopen(req, timeout=10) as resp:
                todoist_data = json.loads(resp.read().decode())
            today = datetime.now().strftime('%Y-%m-%d')
            todoist_tasks = [
                t for t in todoist_data.get('results', [])
                if t.get('due') and t['due']['date'][:10] <= today
            ]
            data['todos'] = [{'title': t['content'], 'status': 'Open'} for t in todoist_tasks]
        except Exception as e:
            print(f"Warning: Could not fetch Todoist tasks: {e}")

    # Load calendar
    calendar_data = load_json_file('calendar.json')
    if calendar_data and 'events' in calendar_data:
        try:
            events = [json.loads(line) for line in calendar_data['events'].split('\n') if line.strip()]
            # Filter out Focus Time events
            events = [e for e in events if e.get('title') != 'Focus Time']
            # Add relative day info to help AI with date context
            today = now.date()
            for event in events:
                start_str = event.get('start', '')
                try:
                    # Parse date like "Jan 12, 2026 at 12:00 AM"
                    event_date = datetime.strptime(start_str.split(' at ')[0], '%b %d, %Y').date()
                    days_diff = (event_date - today).days
                    if days_diff == 0:
                        event['relative_day'] = 'today'
                    elif days_diff == 1:
                        event['relative_day'] = 'tomorrow'
                    elif days_diff == 2:
                        event['relative_day'] = 'in 2 days'
                    elif days_diff < 7:
                        event['relative_day'] = f'in {days_diff} days'
                    else:
                        event['relative_day'] = f'on {event_date.strftime("%A, %b %d")}'
                except (ValueError, IndexError):
                    pass
            data['calendar_events'] = events
        except json.JSONDecodeError:
            data['calendar_events'] = []

    # Load location
    location_data = load_json_file('location.json')
    if location_data:
        data['location'] = {
            'city': location_data.get('city'),
            'state': location_data.get('state'),
            'updated': location_data.get('updated')
        }

    # Load daily links
    links_data = load_json_file('daily-links.json')
    if links_data:
        links = links_data.get('links', [])[:5]
        data['anybox_links'] = [{'title': l.get('title'), 'comment': l.get('comment')} for l in links]

    # Load money/bills info from Remaining API
    try:
        req = Request('http://100.125.128.51:8111/api/summary')
        with urlopen(req, timeout=10) as response:
            remaining_data = json.loads(response.read().decode('utf-8'))
            data['remaining'] = {
                'spending_money_left': remaining_data.get('spending_money_left'),
                'checking_balance': remaining_data.get('checking_balance'),
                'total_due': remaining_data.get('total_due'),
                'days_until_payday': remaining_data.get('days_until_payday'),
                'bills_due_before_payday': remaining_data.get('bills_due_before_payday', [])
            }
    except Exception as e:
        print(f"Error fetching Remaining data: {e}")

    # Load Anybox stats
    anybox_stats = load_json_file('anyboxStats.json')
    if anybox_stats:
        data['anybox_stats'] = {
            'total_links': anybox_stats.get('all'),
            'added_last_7_days': anybox_stats.get('last7'),
            'untagged': anybox_stats.get('untagged')
        }

    # Load TV shows from Sequel
    sequel_data = load_json_file('sequelEpisodes.json')
    if sequel_data:
        episodes = sequel_data.get('episodes', sequel_data.get('episoes', []))
        data['upcoming_tv_shows'] = [
            {
                'show': ep.get('show'),
                'season': ep.get('season'),
                'episode': ep.get('episodeNumber'),
                'title': ep.get('episodeTitle'),
                'release_date': ep.get('releaseDate')
            }
            for ep in episodes[:5]
        ]

    # Load read later items from GoodLinks
    readlater_data = load_json_file('readlater.json')
    if readlater_data:
        links = readlater_data.get('links', [])[:5]
        data['read_later'] = [
            {
                'title': l.get('title'),
                'summary': l.get('summary', '')
            }
            for l in links
        ]

    # Load current wisdom from Merlin Mann's Wisdom Project
    wisdom_data = load_json_file('wisdom.json')
    if wisdom_data:
        data['current_wisdom'] = wisdom_data.get('wisdom')

    return data


def fetch_weather(lat, lon, api_key):
    """Fetch current weather from OpenWeatherMap."""
    try:
        url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={api_key}'
        req = Request(url)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Weather fetch error: {e}")
        return None


def fetch_forecast(lat, lon, api_key):
    """Fetch weather forecast from OpenWeatherMap."""
    try:
        url = f'https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units=metric&appid={api_key}'
        req = Request(url)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Forecast fetch error: {e}")
        return None


def get_tomorrow_forecast(forecast_data):
    """Extract tomorrow's forecast from the 5-day forecast data."""
    if not forecast_data or 'list' not in forecast_data:
        return None

    tomorrow = datetime.now() + timedelta(days=1)
    tomorrow_date = tomorrow.date()

    # Filter forecasts for tomorrow
    tomorrow_forecasts = [
        f for f in forecast_data['list']
        if datetime.fromtimestamp(f['dt']).date() == tomorrow_date
    ]

    if not tomorrow_forecasts:
        return None

    # Get midday forecast for description
    midday_forecast = None
    for f in tomorrow_forecasts:
        hour = datetime.fromtimestamp(f['dt']).hour
        if 12 <= hour <= 15:
            midday_forecast = f
            break
    if not midday_forecast:
        midday_forecast = tomorrow_forecasts[len(tomorrow_forecasts) // 2]

    # Calculate high/low
    temps = [f['main']['temp'] for f in tomorrow_forecasts]

    return {
        'high': round(max(temps)),
        'low': round(min(temps)),
        'description': midday_forecast['weather'][0]['description']
    }

def build_prompt(daily_data, ai_settings):
    """Build the prompt from AI settings."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    if ai_settings and ai_settings.get('intro_prompt') and ai_settings.get('system_prompt'):
        intro_prompt = ai_settings['intro_prompt']
        rules = ai_settings['rules']
        system_prompt = ai_settings['system_prompt']

        prompt = intro_prompt.replace('{date}', today)
        prompt = prompt.replace('{data}', json.dumps(daily_data, indent=2))
        prompt = prompt.replace('{rules}', rules)
    else:
        prompt = f"""Based on the following data from my dashboard for {today}, give me a friendly 2-3 sentence summary.

Dashboard Data:
{json.dumps(daily_data, indent=2)}

IMPORTANT: Do NOT start with any greeting like "Good morning" or "Good afternoon" - the dashboard already shows a greeting. Just dive straight into the briefing.

Write in second person ("You have...", "Your day..."). Keep it concise - 2-3 sentences max."""
        system_prompt = "You are a helpful assistant providing daily briefings."

    return system_prompt, prompt


def call_openai(api_key, model, system_prompt, prompt):
    """Call OpenAI API to generate a summary."""
    # o1 models don't support system messages, temperature, or max_tokens
    is_reasoning_model = model.startswith('o1')

    if is_reasoning_model:
        # For o1 models: combine system prompt with user message, use max_completion_tokens
        # o1 uses reasoning tokens internally, so we need a larger limit (reasoning + output)
        combined_prompt = f"{system_prompt}\n\n{prompt}"
        request_body = json.dumps({
            "model": model,
            "messages": [
                {"role": "user", "content": combined_prompt}
            ],
            "max_completion_tokens": 4000
        }).encode('utf-8')
    else:
        request_body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 300,
            "temperature": 0.7
        }).encode('utf-8')

    req = Request(
        'https://api.openai.com/v1/chat/completions',
        data=request_body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
    )

    try:
        with urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content']
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        print(f"OpenAI API error: {e.code} - {error_body}")
        return None
    except URLError as e:
        print(f"Network error: {e.reason}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response: {e}")
        return None


def call_anthropic(api_key, model, system_prompt, prompt):
    """Call Anthropic API to generate a summary."""
    request_body = json.dumps({
        "model": model,
        "max_tokens": 300,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }).encode('utf-8')

    req = Request(
        'https://api.anthropic.com/v1/messages',
        data=request_body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01'
        }
    )

    try:
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            # Anthropic returns content as an array of content blocks
            return result['content'][0]['text']
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        print(f"Anthropic API error: {e.code} - {error_body}")
        return None
    except URLError as e:
        print(f"Network error: {e.reason}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response: {e}")
        return None


def call_gemini(api_key, model, system_prompt, prompt):
    """Call Google Gemini API to generate a summary."""
    # Gemini uses system instructions differently - we combine them with the prompt
    full_prompt = f"{system_prompt}\n\n{prompt}"

    request_body = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.7
        }
    }).encode('utf-8')

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = Request(
        url,
        data=request_body,
        headers={
            'Content-Type': 'application/json'
        }
    )

    try:
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            # Gemini returns candidates array with content parts
            return result['candidates'][0]['content']['parts'][0]['text']
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        print(f"Gemini API error: {e.code} - {error_body}")
        return None
    except URLError as e:
        print(f"Network error: {e.reason}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response: {e}")
        return None


def call_ai(config, ai_settings, daily_data):
    """Call the configured AI provider to generate a summary."""
    provider = ai_settings.get('provider', 'openai') if ai_settings else 'openai'
    model = ai_settings.get('model', 'gpt-4o-mini') if ai_settings else 'gpt-4o-mini'

    system_prompt, prompt = build_prompt(daily_data, ai_settings)

    if provider == 'anthropic':
        api_key = config.get('anthropicApiKey')
        if not api_key:
            print("Error: Anthropic API key not configured")
            return None
        print(f"Using Anthropic ({model})")
        return call_anthropic(api_key, model, system_prompt, prompt)
    elif provider == 'gemini':
        api_key = config.get('geminiApiKey')
        if not api_key:
            print("Error: Gemini API key not configured")
            return None
        print(f"Using Gemini ({model})")
        return call_gemini(api_key, model, system_prompt, prompt)
    else:
        api_key = config.get('openaiApiKey')
        if not api_key:
            print("Error: OpenAI API key not configured")
            return None
        print(f"Using OpenAI ({model})")
        return call_openai(api_key, model, system_prompt, prompt)

def save_summary(summary):
    """Save the summary to a JSON file."""
    filepath = os.path.join(DIRECTORY, 'daily-summary.json')
    data = {
        'summary': summary,
        'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'date': datetime.now().strftime("%Y-%m-%d")
    }
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Summary saved to {filepath}")

def main():
    print("Generating daily summary...")

    config = load_config()
    if not config:
        print("Error: config.json not found")
        return 1

    ai_settings = load_ai_settings()
    provider = ai_settings.get('provider', 'openai') if ai_settings else 'openai'

    # Check for appropriate API key based on provider
    if provider == 'anthropic' and not config.get('anthropicApiKey'):
        print("Error: Anthropic API key not found in config.json")
        return 1
    elif provider == 'gemini' and not config.get('geminiApiKey'):
        print("Error: Gemini API key not found in config.json")
        return 1
    elif provider == 'openai' and not config.get('openaiApiKey'):
        print("Error: OpenAI API key not found in config.json")
        return 1

    daily_data = gather_daily_data()

    # Fetch weather if we have location and API key
    if daily_data.get('location') and config.get('openWeatherApiKey'):
        location_data = load_json_file('location.json')
        if location_data:
            weather = fetch_weather(
                location_data.get('lat'),
                location_data.get('long'),
                config['openWeatherApiKey']
            )
            if weather and 'main' in weather:
                daily_data['weather'] = {
                    'temp': round(weather['main']['temp']),
                    'feels_like': round(weather['main']['feels_like']),
                    'description': weather['weather'][0]['description'] if weather.get('weather') else 'unknown'
                }

            # Fetch tomorrow's forecast
            forecast = fetch_forecast(
                location_data.get('lat'),
                location_data.get('long'),
                config['openWeatherApiKey']
            )
            tomorrow_forecast = get_tomorrow_forecast(forecast)
            if tomorrow_forecast:
                daily_data['tomorrow_weather'] = tomorrow_forecast

    # Fetch shed state if we have Home Assistant config
    if config.get('homeAssistantApiKey') and config.get('homeAssistantUrl'):
        shed_states = fetch_shed_state(
            config['homeAssistantUrl'],
            config['homeAssistantApiKey']
        )
        if shed_states:
            temp_state = shed_states.get('sensor.temperature_sensor_2', {})
            thermostat_state = shed_states.get('climate.shed_thermostat', {})
            working_from_home = shed_states.get('input_boolean.working_from_home', {})
            desk_lamp = shed_states.get('light.smart_rgb_bulb_2208114772038152050448e1e9a17678', {})
            shelf_light = shed_states.get('light.govee_h617a_501b', {})
            daily_data['shed'] = {
                'temperature': temp_state.get('state'),
                'thermostat_status': thermostat_state.get('state'),
                'thermostat_target': thermostat_state.get('attributes', {}).get('temperature'),
                'working_from_home': working_from_home.get('state'),
                'desk_lamp': desk_lamp.get('state'),
                'shelf_light': shelf_light.get('state')
            }

            # Add heater runtime to shed data
            heater_runtime = fetch_heater_runtime(
                config['homeAssistantUrl'],
                config['homeAssistantApiKey']
            )
            if heater_runtime:
                daily_data['shed']['heater_runtime_today_minutes'] = heater_runtime['today_minutes']
                daily_data['shed']['heater_runtime_yesterday_minutes'] = heater_runtime['yesterday_minutes']

        # Fetch home state
        home_states = fetch_home_state(
            config['homeAssistantUrl'],
            config['homeAssistantApiKey']
        )
        if home_states:
            ecobee = home_states.get('climate.my_ecobee', {})
            lock = home_states.get('lock.back_door_lock', {})
            shed_door = home_states.get('binary_sensor.contact_sensor_2', {})
            garage_door = home_states.get('binary_sensor.contact_sensor', {})
            daily_data['home'] = {
                'temperature': ecobee.get('attributes', {}).get('current_temperature'),
                'humidity': ecobee.get('attributes', {}).get('current_humidity'),
                'hvac_state': ecobee.get('state'),
                'hvac_action': ecobee.get('attributes', {}).get('hvac_action'),
                'back_door_lock': lock.get('state'),
                'shed_door': 'open' if shed_door.get('state') == 'on' else 'closed',
                'garage_door': 'open' if garage_door.get('state') == 'on' else 'closed'
            }

    # Fetch Pi UPS status
    pi_ups = fetch_pi_ups_status()
    if pi_ups:
        daily_data['pi_ups'] = pi_ups

    # Fetch backup status
    backup_status = fetch_backup_status()
    if backup_status:
        daily_data['backup'] = backup_status

    print(f"Gathered data: {len(daily_data.get('todos', []))} todos, "
          f"{len(daily_data.get('calendar_events', []))} events, "
          f"weather: {'yes' if 'weather' in daily_data else 'no'}, "
          f"shed: {'yes' if 'shed' in daily_data else 'no'}, "
          f"home: {'yes' if 'home' in daily_data else 'no'}, "
          f"pi_ups: {'yes' if 'pi_ups' in daily_data else 'no'}, "
          f"backup: {'yes' if 'backup' in daily_data else 'no'}, "
          f"read_later: {len(daily_data.get('read_later', []))}")

    summary = call_ai(config, ai_settings, daily_data)

    if summary:
        save_summary(summary)
        print(f"Summary: {summary}")
    else:
        print("Failed to generate summary")

    select_random_wisdom()

    return 0 if summary else 1

if __name__ == '__main__':
    exit(main())
