import json
import math

import numpy as np
import pygame
import pytest

import game
import weather
from effects import WeatherEffects
from game import RingRun

GEO = {'results': [
    {'name': 'Troy', 'latitude': 42.6, 'longitude': -83.1, 'country_code': 'US', 'admin1': 'Michigan'},
    {'name': 'Troy', 'latitude': 42.73, 'longitude': -73.69, 'country_code': 'US', 'admin1': 'New York'},
]}
CURRENT = {'cloud_cover': 75, 'wind_speed_10m': 6.5, 'wind_direction_10m': 270, 'precipitation': 0.4, 'weather_code': 95}
FORECAST = {'utc_offset_seconds': -18000, 'current': CURRENT}


def fake_api(geo=GEO, forecast=FORECAST):
    return lambda url, params: geo if 'geocoding' in url else forecast


def test_current_weather_maps_fields(monkeypatch):
    monkeypatch.setattr(weather, 'fetch_json', fake_api())
    result = weather.current_weather(42.7, -73.7)
    assert result['cover'] == 0.75 and result['wind'] == 6.5
    assert result['storm'] == 1.0 and result['precipitation'] == 1.0
    assert result['wind_angle'] == pytest.approx(math.radians(450))
    assert 0 <= result['hour'] < 24


@pytest.mark.parametrize('bad', [
    {}, [], {'current': 'x', 'utc_offset_seconds': 0},
    {'utc_offset_seconds': 0, 'current': {**CURRENT, 'cloud_cover': 'lots'}},
    {'utc_offset_seconds': 0, 'current': {**CURRENT, 'weather_code': True}},
    json.loads('{"utc_offset_seconds": 0, "current": {"cloud_cover": NaN}}'),
    {'current': CURRENT},
])
def test_bad_forecast_data_is_rejected(monkeypatch, bad):
    monkeypatch.setattr(weather, 'fetch_json', fake_api(forecast=bad))
    with pytest.raises(ValueError):
        weather.current_weather(0, 0)


def test_out_of_range_values_are_clamped(monkeypatch):
    wild = {'utc_offset_seconds': 10 ** 9, 'current': {**CURRENT, 'cloud_cover': 900, 'wind_speed_10m': -5}}
    monkeypatch.setattr(weather, 'fetch_json', fake_api(forecast=wild))
    result = weather.current_weather(0, 0)
    assert result['cover'] == 1.0 and result['wind'] == 0.0


def test_geocode_prefers_matching_region_and_cleans_label(monkeypatch):
    monkeypatch.setattr(weather, 'fetch_json', fake_api())
    label, latitude, longitude = weather.geocode('Troy, NY')
    assert (label, latitude, longitude) == ('TROY, US', 42.73, -73.69)
    sneaky = {'results': [{'name': 'Bad\nName\x1b[31m' + 'x' * 99, 'latitude': 1, 'longitude': 2}]}
    monkeypatch.setattr(weather, 'fetch_json', fake_api(geo=sneaky))
    label, _, _ = weather.geocode('Bad')
    assert label.isprintable() and len(label) <= 24


@pytest.mark.parametrize('city, geo', [('', GEO), ('x' * 81, GEO), ('Nowhere', {}), ('Nowhere', {'results': 'no'})])
def test_geocode_rejects_bad_input(monkeypatch, city, geo):
    monkeypatch.setattr(weather, 'fetch_json', fake_api(geo=geo))
    with pytest.raises(ValueError):
        weather.geocode(city)


def run_live(live, atmosphere, steps=1):
    for _ in range(steps):
        live.update(0.5, atmosphere)
        if live.thread:
            live.thread.join(5)
    live.update(0.5, atmosphere)


def test_live_weather_applies_and_turns_off(monkeypatch, atmosphere):
    monkeypatch.setattr(weather, 'fetch_json', fake_api())
    live = weather.LiveWeather('Troy, NY')
    run_live(live, atmosphere, steps=8)
    assert 'TROY' in atmosphere.weather_label
    assert atmosphere.cover > 0.58 and atmosphere.storm > 0.5 and atmosphere.day_length == 86400
    live.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_l, mod=0), atmosphere)
    assert atmosphere.weather_label == 'SIMULATED WEATHER' and atmosphere.day_length == 240


def test_live_weather_offline_keeps_flying(monkeypatch, atmosphere, capsys):
    def offline(url, params):
        raise OSError('no network')

    monkeypatch.setattr(weather, 'fetch_json', offline)
    live = weather.LiveWeather('Troy')
    run_live(live, atmosphere)
    assert 'OFFLINE' in atmosphere.weather_label and atmosphere.cover == 0.58
    assert 'no network' in capsys.readouterr().out


def test_ring_run_scores_and_ends(atmosphere):
    run = RingRun(seed=3, start_now=True)
    run.update(0.016, atmosphere)
    x, y, z, _, _ = run.rings[0]
    atmosphere.position, atmosphere.altitude = np.array([x, z]), y
    run.update(0.016, atmosphere)
    assert run.score == 1 and run.time_left > game.START_TIME
    run.update(1000, atmosphere)
    assert not run.active and run.best == 1


def test_missed_ring_moves_on(atmosphere):
    run = RingRun(seed=4, start_now=True)
    run.update(0.016, atmosphere)
    x, y, z, nx, nz = run.rings[0]
    atmosphere.position, atmosphere.altitude = np.array([x + nx * 400, z + nz * 400]), y
    run.update(0.016, atmosphere)
    assert run.score == 0 and run.rings[0][:3] != (x, y, z) and run.message == 'MISSED'


@pytest.mark.parametrize('size', [(1, 1), (3, 2), (1280, 720), (3840, 1080)])
@pytest.mark.parametrize('turn', [0.0, 1.6, 3.14])
def test_overlays_draw_at_any_size_and_angle(atmosphere, size, turn):
    run, effects = RingRun(seed=5, start_now=True), WeatherEffects(seed=5)
    atmosphere.precipitation = atmosphere.storm = 1.0
    atmosphere.altitude = 500.0
    for system in (run, effects):
        system.update(0.016, atmosphere)
    atmosphere.look_yaw = turn
    surface = pygame.Surface(size, pygame.SRCALPHA)
    hud = pygame.Surface((1280, 720), pygame.SRCALPHA)
    font = pygame.font.SysFont('consolas', 14)
    for system in (effects, run):
        system.draw_world(surface, atmosphere)
    run.draw_hud(hud, atmosphere, (font, font, font))


def test_storm_makes_lightning_and_rain_stops_above_clouds(atmosphere):
    effects = WeatherEffects(seed=6)
    atmosphere.storm = atmosphere.precipitation = 1.0
    atmosphere.altitude = 400.0
    flashes = 0
    for _ in range(600):
        effects.update(1 / 30, atmosphere)
        flashes += atmosphere.flash == 1.0
    assert flashes >= 1 and effects.rain == 1.0
    atmosphere.altitude = 2500.0
    effects.update(1 / 30, atmosphere)
    assert effects.rain == 0.0
