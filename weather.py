"""Live weather from Open-Meteo (free, no API key). Network calls run on a background thread."""

import json
import math
import threading
import time
import urllib.parse
import urllib.request

import pygame

GEOCODE_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
DEFAULT_CITY = 'Troy, NY'
TIMEOUT = 8
MAX_BYTES = 256 * 1024
REFRESH_SECONDS = 600
RETRY_SECONDS = 60


def fetch_json(url, params):
    request = urllib.request.Request(f'{url}?{urllib.parse.urlencode(params)}',
                                     headers={'User-Agent': 'PlanePlane (HackRPI 2026)'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('weather response too large')
    return json.loads(body)


def number(data, key, low, high):
    value = data.get(key) if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'weather data has a bad {key!r}')
    return min(max(float(value), low), high)


def clean(text, limit=24):
    return ''.join(char for char in str(text) if char.isprintable())[:limit].upper()


def geocode(city):
    city = city.strip()
    if not 0 < len(city) <= 80:
        raise ValueError('city name must be 1-80 characters')
    name, _, region = city.partition(',')
    data = fetch_json(GEOCODE_URL, {'name': name.strip(), 'count': 10, 'language': 'en', 'format': 'json'})
    results = data.get('results') if isinstance(data, dict) else None
    places = [place for place in results if isinstance(place, dict)] if isinstance(results, list) else []
    if not places:
        raise ValueError(f'no place called {name.strip()!r}')
    region = region.strip().lower()
    match = places[0]
    for place in places:
        where = ' '.join(str(place.get(key, '')) for key in ('admin1', 'country', 'country_code')).lower()
        initials = ''.join(word[0] for word in str(place.get('admin1', '')).split()).lower()  # "New York" -> "ny"
        if region and (region in where or region == initials):
            match = place
            break
    label = clean(f"{match.get('name', name)}, {match.get('country_code', '')}".strip(', '))
    return label, number(match, 'latitude', -90, 90), number(match, 'longitude', -180, 180)


def rain_from_code(code):
    # WMO weather codes: 51-57 drizzle, 61-67 rain, 71-77 snow, 80-86 showers, 95-99 thunderstorm.
    if code >= 95 or code in (65, 67, 82):
        return 1.0
    if code in (63, 66, 81):
        return 0.7
    if code in (61, 80):
        return 0.45
    if 71 <= code <= 77 or code in (85, 86):
        return 0.35
    if 51 <= code <= 57:
        return 0.25
    return 0.0


def current_weather(latitude, longitude):
    data = fetch_json(FORECAST_URL, {
        'latitude': latitude, 'longitude': longitude, 'timezone': 'auto', 'wind_speed_unit': 'ms',
        'current': 'cloud_cover,wind_speed_10m,wind_direction_10m,precipitation,weather_code',
    })
    current = data.get('current') if isinstance(data, dict) else None
    code = int(number(current, 'weather_code', 0, 99))
    offset = number(data, 'utc_offset_seconds', -14 * 3600, 14 * 3600)
    rain = max(rain_from_code(code), number(current, 'precipitation', 0, 100) / 4)
    return {
        'cover': number(current, 'cloud_cover', 0, 100) / 100,
        'wind': number(current, 'wind_speed_10m', 0, 45),
        # Meteorological direction is where wind comes from; clouds drift the opposite way.
        'wind_angle': math.radians(number(current, 'wind_direction_10m', 0, 360) + 180),
        'precipitation': min(rain, 1.0),
        'storm': 1.0 if code >= 95 else 0.0,
        'hour': (time.time() + offset) % 86400 / 3600,
    }


class LiveWeather:
    help = 'L live weather (start with --city "Your City")'

    def __init__(self, city=None):
        self.city = city or DEFAULT_CITY
        self.enabled = False
        self.start_now = city is not None
        self.lock = threading.Lock()
        self.thread = None
        self.result = None
        self.error = None
        self.place = None
        self.current = None
        self.saved = None
        self.next_fetch = 0.0

    def set_enabled(self, enabled, atmosphere, restore=True):
        if enabled:
            self.saved = (atmosphere.cover, atmosphere.wind, atmosphere.wind_angle,
                          atmosphere.precipitation, atmosphere.storm, atmosphere.day_length)
            self.current = None
            self.next_fetch = 0.0
            atmosphere.weather_label = f'LIVE WEATHER  {clean(self.city)}  LOADING'
        elif self.saved:
            atmosphere.day_length = self.saved[5]
            if restore:
                (atmosphere.cover, atmosphere.wind, atmosphere.wind_angle,
                 atmosphere.precipitation, atmosphere.storm) = self.saved[:5]
        if not enabled:
            atmosphere.weather_label = 'SIMULATED WEATHER'
        self.enabled = enabled

    def handle_event(self, event, atmosphere):
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_l:
            self.set_enabled(not self.enabled, atmosphere)
        elif self.enabled and event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
            # Picking a preset means the player wants simulated weather again.
            self.set_enabled(False, atmosphere, restore=False)

    def fetch(self):
        try:
            if self.place is None:
                self.place = geocode(self.city)
            label, latitude, longitude = self.place
            weather = current_weather(latitude, longitude)
            weather['label'] = label
            with self.lock:
                self.result = weather
        except Exception as error:  # offline, timeout, bad city or bad data: the sim keeps running
            with self.lock:
                self.error = error

    def update(self, dt, atmosphere):
        if self.start_now:
            self.start_now = False
            self.set_enabled(True, atmosphere)
        if not self.enabled:
            return
        now = time.monotonic()
        if now >= self.next_fetch and (self.thread is None or not self.thread.is_alive()):
            self.next_fetch = now + RETRY_SECONDS
            self.thread = threading.Thread(target=self.fetch, daemon=True)
            self.thread.start()
        with self.lock:
            result, error, self.result, self.error = self.result, self.error, None, None
        if result:
            self.current = result
            self.next_fetch = now + REFRESH_SECONDS
            atmosphere.hour = result['hour']
            atmosphere.day_length = 86400.0
            atmosphere.cycle_paused = False
            atmosphere.weather_label = f"LIVE WEATHER  {result['label']}"
        if error:
            print(f'Live weather unavailable: {error}')
            status = 'STALE' if self.current else 'OFFLINE'
            atmosphere.weather_label = f'LIVE WEATHER  {clean(self.city)}  {status}'
        if self.current:
            ease = min(1.0, dt * 0.8)
            for name in ('cover', 'wind', 'precipitation', 'storm'):
                value = getattr(atmosphere, name)
                setattr(atmosphere, name, value + (self.current[name] - value) * ease)
            atmosphere.wind_angle = self.current['wind_angle']
