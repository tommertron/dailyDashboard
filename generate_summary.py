#!/usr/bin/env python3
"""Generate a daily AI summary by analyzing all dashboard JSON files."""

import json
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

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


def fetch_shed_state(ha_url, ha_key):
    """Fetch shed state from Home Assistant."""
    entities = [
        'sensor.temperature_sensor_2',
        'climate.shed_thermostat',
    ]
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


PI_MONITOR_URL = "http://100.125.128.51:5001"

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

def gather_daily_data():
    """Gather all daily data from JSON files."""
    now = datetime.now()
    hour = now.hour
    is_weekday = now.weekday() < 5  # Monday=0, Sunday=6
    is_workday_hours = is_weekday and hour < 16
    data = {
        'current_time': now.strftime("%H:%M"),
        'day_of_week': now.strftime("%A"),
        'is_workday_hours': is_workday_hours,
        'is_evening': hour >= 17,
    }

    # Load todos
    todos_data = load_json_file('todos.json')
    if todos_data:
        data['todos'] = todos_data.get('todos', [])

    # Load calendar
    calendar_data = load_json_file('calendar.json')
    if calendar_data and 'events' in calendar_data:
        try:
            events = [json.loads(line) for line in calendar_data['events'].split('\n') if line.strip()]
            # Filter out Focus Time events
            events = [e for e in events if e.get('title') != 'Focus Time']
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

    # Load money/bills info
    money_path = os.path.join(DIRECTORY, 'money.txt')
    try:
        with open(money_path, 'r') as f:
            money_content = f.read().strip()
            if money_content:
                data['money_and_bills'] = money_content
    except FileNotFoundError:
        pass

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

def call_openai(api_key, daily_data):
    """Call OpenAI API to generate a summary."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    day_of_week = datetime.now().strftime("%A")

    prompt = f"""Based on the following data from my dashboard for {today}, give me a friendly 2-3 sentence summary.

Dashboard Data:
{json.dumps(daily_data, indent=2)}

CALENDAR EVENTS (next 24 hours):
- The calendar_events list contains events for the next 24 hours, which may include both today and tomorrow
- Parse the "start" field (e.g., "Dec 30, 2025 at 9:00 AM") to determine if each event is today or tomorrow
- If is_evening is TRUE (after 5pm), focus more on tomorrow's events as a "preview of tomorrow"
- In the evening, lead with tomorrow's schedule (e.g., "Tomorrow you have..." or "Looking ahead to tomorrow...")
- During the day, focus on today's remaining events

Include in your summary:
- Current weather (temperature, conditions)
- Tomorrow's weather forecast (from tomorrow_weather field: high/low temps and conditions) - mention briefly, especially if notably different from today
- Calendar events (today's events during the day, tomorrow's preview in the evening)
- My pending tasks from Things (what needs to be done)
- If there are interesting saved links in Anybox, briefly mention one worth checking out
- Any upcoming bills due in the next 7 days (mention amount and due date)

ANYBOX STATS (reading list):
- Check anybox_stats for total links saved, links added in the last 7 days, and untagged count
- If untagged count is high (10+), you might gently suggest organizing some links
- If added_last_7_days is notably high or low, you can mention it casually (e.g., "You've been saving lots of articles lately!")
- Don't always mention these stats - only if there's something notable

TV SHOWS (upcoming_tv_shows):
- Check upcoming_tv_shows for new episodes releasing soon
- If there's an episode releasing TODAY, mention it as something to look forward to (e.g., "New episode of [Show] drops today!")
- If is_evening is TRUE and there's a show releasing today, it's a great evening activity suggestion
- Don't list multiple shows - just highlight one if it's releasing today or tomorrow

UPCOMING BILLS/MONEY:
- Check the money_and_bills field for any upcoming bills or financial info
- If there are upcoming bills or payments due soon, mention them briefly
- If no relevant financial info, no need to mention it

SHED HEATING (check is_workday_hours and is_evening booleans in the data):
- The shed is my home office where I work from home
- IMPORTANT: When mentioning temperature, use the EXACT value from shed.temperature (e.g., if it says "1.9", say "1.9°C" - never round!)
- If is_workday_hours is TRUE:
  → If shed.temperature is below 15 AND shed.thermostat_status is "off", mention the exact temp and suggest turning on heat
  → If shed is already heating or temp >= 15°C, no need to mention
- If is_workday_hours is FALSE:
  → Do NOT suggest turning on the shed heat - the workday is done
  → BUT if is_evening is TRUE and shed.thermostat_status is "heat", suggest turning it off to save energy
- Skip shed entirely if calendar shows I'm at the office

PI UPS STATUS:
- If there was a recent power outage (in the last 24 hours), mention it (e.g., "There was a power blip yesterday evening")
- If currently running on battery power (on_ac_power is false), definitely mention this - it's important
- If battery_percent is below 50%, mention the low battery level
- Otherwise, no need to mention the Pi/UPS status - it's just background info

IMPORTANT: Do NOT start with any greeting like "Good morning" or "Good afternoon" - the dashboard already shows a greeting. Just dive straight into the summary.

Write in second person ("You have...", "Your day..."). Be warm and conversational. Keep it concise - 2-3 sentences max."""

    request_body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that summarizes daily schedules in a friendly, concise way."},
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
        with urlopen(req, timeout=30) as response:
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
    if not config or 'openaiApiKey' not in config:
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
            daily_data['shed'] = {
                'temperature': temp_state.get('state'),
                'thermostat_status': thermostat_state.get('state'),
                'thermostat_target': thermostat_state.get('attributes', {}).get('temperature')
            }

    # Fetch Pi UPS status
    pi_ups = fetch_pi_ups_status()
    if pi_ups:
        daily_data['pi_ups'] = pi_ups

    print(f"Gathered data: {len(daily_data.get('todos', []))} todos, "
          f"{len(daily_data.get('calendar_events', []))} events, "
          f"weather: {'yes' if 'weather' in daily_data else 'no'}, "
          f"shed: {'yes' if 'shed' in daily_data else 'no'}, "
          f"pi_ups: {'yes' if 'pi_ups' in daily_data else 'no'}, "
          f"anybox_stats: {'yes' if 'anybox_stats' in daily_data else 'no'}, "
          f"tv_shows: {len(daily_data.get('upcoming_tv_shows', []))}")

    summary = call_openai(config['openaiApiKey'], daily_data)

    if summary:
        save_summary(summary)
        print(f"Summary: {summary}")
        return 0
    else:
        print("Failed to generate summary")
        return 1

if __name__ == '__main__':
    exit(main())
