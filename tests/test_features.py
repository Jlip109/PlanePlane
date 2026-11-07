import json
import math

import numpy as np
import pygame
import pytest

import characters
import modes
import weather
import world
from audio import Audio
from effects import WeatherEffects
from game import Game
from life import SkyLife
from scores import Scores

GEO = {'results': [
    {'name': 'Troy', 'latitude': 42.6, 'longitude': -83.1, 'country_code': 'US', 'admin1': 'Michigan'},
    {'name': 'Troy', 'latitude': 42.73, 'longitude': -73.69, 'country_code': 'US', 'admin1': 'New York'},
]}
CURRENT = {'cloud_cover': 75, 'wind_speed_10m': 6.5, 'wind_direction_10m': 270, 'precipitation': 0.4, 'weather_code': 95}
FORECAST = {'utc_offset_seconds': -18000, 'current': CURRENT}


def fake_api(geo=GEO, forecast=FORECAST):
    return lambda url, params: geo if 'geocoding' in url else forecast


# ------------------------------------------------------------------ live weather

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


# ------------------------------------------------------------------ ring run

def fly_to(atmosphere, x, y, z, heading):
    atmosphere.position = np.array([x, z])
    atmosphere.altitude = y
    atmosphere.heading = heading


def test_ring_run_scores_gates_and_finishes(atmosphere, fake_game):
    run = modes.RingRun(fake_game, seed=3)
    run.start(atmosphere)
    assert run.rings[0][1] == pytest.approx(atmosphere.altitude, abs=1) or run.rings[0][1] >= 300
    for passed in range(3):
        x, y, z, nx, nz = run.rings[0]
        fly_to(atmosphere, x - nx * 5, y, z - nz * 5, math.atan2(nx, nz))
        run.update(0.016, atmosphere)
        fly_to(atmosphere, x + nx * 5, y, z + nz * 5, math.atan2(nx, nz))
        run.update(0.016, atmosphere)
        assert run.passed == passed + 1
    assert run.combo == 4 and run.score == 100 + 200 + 300
    assert 'ring' in fake_game.sounds
    x, y, z, nx, nz = run.rings[0]
    side_x, side_z = nz * 300, -nx * 300  # 300 m to the side of the gate
    fly_to(atmosphere, x - nx * 5 + side_x, y, z - nz * 5 + side_z, 0)
    run.update(0.016, atmosphere)
    fly_to(atmosphere, x + nx * 5 + side_x, y, z + nz * 5 + side_z, 0)
    run.update(0.016, atmosphere)
    assert run.combo == 1 and 'MISSED' in fake_game.flashes
    run.update(1000, atmosphere)
    assert run.finished and run.summary['record'] and fake_game.scores.get('ring_best') == 600


def test_ring_gates_stay_clear_of_buildings(atmosphere, fake_game):
    run = modes.RingRun(fake_game, seed=7)
    run.start(atmosphere)
    for _ in range(80):
        run.rings.pop(0)
        run.add_ring()
        x, y, z, _, _ = run.rings[-1]
        assert y - run.RADIUS > world.obstacle_height(x, z) + 20


def test_crash_costs_time_in_ring_run(atmosphere, fake_game):
    run = modes.RingRun(fake_game, seed=3)
    run.start(atmosphere)
    before = run.time_left
    run.on_crash(atmosphere)
    assert run.time_left == before - 5 and run.combo == 1


# ------------------------------------------------------------------ courier

def hover_over(atmosphere, city_index, courier, seconds=2.0):
    _, cx, cz, _, _, _ = world.CITIES[city_index]
    fly_to(atmosphere, cx, world.CITY_LEVELS[city_index] + 300, cz, 0)
    for _ in range(int(seconds / 0.1)):
        courier.update(0.1, atmosphere)


def test_courier_shift_from_pickup_to_payday(atmosphere, fake_game):
    courier = modes.SkyCourier(fake_game, seed=5)
    fly_to(atmosphere, 0, 700, -900, 0)
    courier.start(atmosphere)
    assert courier.job['origin'] == 0  # Troy is nearest to the start
    for delivered in range(courier.JOBS):
        job = courier.job
        hover_over(atmosphere, job['origin'], courier)
        assert job['stage'] == 'deliver'
        if delivered == 1:
            courier.on_crash(atmosphere)
            assert job['damaged']
        hover_over(atmosphere, job['destination'], courier)
        assert courier.done == delivered + 1
    assert courier.finished and courier.summary['score'] > 0
    assert fake_game.scores.get('courier_best') == courier.score
    assert fake_game.sounds.count('deliver') == courier.JOBS


def test_courier_needs_you_to_fly_low(atmosphere, fake_game):
    courier = modes.SkyCourier(fake_game, seed=5)
    fly_to(atmosphere, 0, 700, -900, 0)
    courier.start(atmosphere)
    _, cx, cz, _, _, _ = world.CITIES[0]
    fly_to(atmosphere, cx, world.CITY_LEVELS[0] + 900, cz, 0)
    for _ in range(50):
        courier.update(0.1, atmosphere)
    assert courier.job['stage'] == 'pickup'


def test_free_flight_greets_each_city_once(atmosphere, fake_game):
    free = modes.FreeFlight(fake_game)
    fly_to(atmosphere, 0, 700, -900, 0)
    free.start(atmosphere)
    fly_to(atmosphere, 0, 700, 3400, 0)
    free.update(0.1, atmosphere)
    assert fake_game.scores.get('visited', []) == ['TROY']
    calls = [call[1] for call in fake_game.radio.queue]
    assert any('first time' in call for call in calls)
    fly_to(atmosphere, 0, 700, -900, 0)
    free.update(0.1, atmosphere)
    fly_to(atmosphere, 0, 700, 3400, 0)
    free.update(0.1, atmosphere)
    later = [call[1] for call in fake_game.radio.queue]
    assert sum('first time' in call for call in later) == 1 and 'miles per hour' in later[-1]


# ------------------------------------------------------------------ the game director

def make_game(atmosphere, fonts, tmp_path, mode='menu'):
    return Game(atmosphere, fonts, Audio(pygame, enabled=False), mode, None, 1, Scores(tmp_path / 's.json'))


def press(game, key):
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=''))


def test_game_state_machine(atmosphere, fonts, tmp_path):
    game = make_game(atmosphere, fonts, tmp_path)
    assert game.state == 'title' and atmosphere.autopilot
    for _ in range(3):
        press(game, pygame.K_DOWN)
    press(game, pygame.K_RETURN)
    assert game.state == 'pilots'
    press(game, pygame.K_RIGHT)
    press(game, pygame.K_RETURN)
    assert game.state == 'title' and game.pilot_index == 1 and game.scores.get('pilot') == 1
    assert atmosphere.speed_scale == characters.PILOTS[1].speed
    press(game, pygame.K_UP)
    press(game, pygame.K_RETURN)
    assert game.state == 'flying' and game.mode.key == 'courier' and not atmosphere.autopilot
    press(game, pygame.K_ESCAPE)
    assert game.paused
    press(game, pygame.K_ESCAPE)
    assert game.flying
    game.mode.finish()
    game.update(0.1, 0.1)
    assert game.state == 'results'
    press(game, pygame.K_RETURN)
    assert game.flying and game.mode.done == 0
    press(game, pygame.K_ESCAPE)
    for _ in range(2):
        press(game, pygame.K_DOWN)
    press(game, pygame.K_RETURN)
    assert game.state == 'title' and game.mode is None
    press(game, pygame.K_ESCAPE)
    assert game.quit_requested


@pytest.mark.parametrize('mode', ['free', 'rings', 'courier'])
def test_hud_and_menus_draw_in_every_state(atmosphere, fonts, tmp_path, mode):
    game = make_game(atmosphere, fonts, tmp_path, mode)
    surface = pygame.Surface((1280, 720), pygame.SRCALPHA)
    overlay = pygame.Surface((333, 187), pygame.SRCALPHA)
    game.hud.city_banner(2)
    game.flash('+9s', (255, 255, 255))
    game.radio.say(characters.TOWERS['TROY'], 'Testing, one two.')
    for state in ('flying', 'paused', 'results', 'title', 'pilots', 'controls'):
        game.state = state
        if state == 'results' and hasattr(game.mode, 'finish'):
            game.mode.finish()
        game.hud.show_help = state == 'flying'
        atmosphere.crash_timer = 1.0 if state == 'paused' else 0.0
        for _ in range(3):
            game.update(0.2, 0.2)
            game.draw_world(overlay)
            game.draw_hud(surface, 59.6, 'GPU')
        assert surface.get_bounding_rect().width > 100


def test_menu_mouse_hover_and_click(atmosphere, fonts, tmp_path):
    game = make_game(atmosphere, fonts, tmp_path)
    game.hud_transform = (1.5, 0, 0)  # a 1920x1080 window
    surface = pygame.Surface((1280, 720), pygame.SRCALPHA)
    game.draw_hud(surface, 60, 'GPU')
    ring_run = [rect for index, rect, kind in game.menu.hit_areas if kind == 'title' and index == 1][0]
    pos = (ring_run.centerx * 1.5, ring_run.centery * 1.5)
    game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))
    assert game.menu.title_index == 1
    game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    assert game.flying and game.mode.key == 'rings'


# ------------------------------------------------------------------ world overlays, characters, sound, saves

@pytest.mark.parametrize('size', [(1, 1), (3, 2), (1280, 720), (3840, 1080)])
@pytest.mark.parametrize('turn', [0.0, 1.6, 3.14])
def test_overlays_draw_at_any_size_and_angle(atmosphere, fake_game, size, turn):
    run, effects, life = modes.RingRun(fake_game, seed=5), WeatherEffects(seed=5), SkyLife(seed=5)
    run.start(atmosphere)
    atmosphere.precipitation = atmosphere.storm = 1.0
    atmosphere.altitude = 500.0
    life.time = 30
    for _ in range(40):
        for system in (effects, life):
            system.update(0.1, atmosphere)
        run.update(0.016, atmosphere)
    atmosphere.look_yaw = turn
    surface = pygame.Surface(size, pygame.SRCALPHA)
    for system in (effects, life, run):
        system.draw_world(surface, atmosphere)


def test_balloons_show_up_near_cities(atmosphere):
    life = SkyLife(seed=1)
    balloon = life.balloons[0]
    x, y, z = balloon.position(0.0)
    fly_to(atmosphere, x, y, z - 400, 0)
    atmosphere.cover = 0.0
    surface = pygame.Surface((1280, 720), pygame.SRCALPHA)
    life.draw_world(surface, atmosphere)
    assert surface.get_bounding_rect().width > 20


def test_storm_makes_lightning_and_rain_stops_above_clouds(atmosphere):
    effects = WeatherEffects(seed=6)
    atmosphere.storm = atmosphere.precipitation = 1.0
    atmosphere.altitude = 400.0
    flashes = 0
    for _ in range(600):
        effects.update(1 / 30, atmosphere)
        flashes += atmosphere.flash == 1.0
    assert flashes >= 1 and effects.rain == 1.0
    assert any(name == 'lightning' for name, _ in atmosphere.events)
    atmosphere.altitude = 2500.0
    effects.update(1 / 30, atmosphere)
    assert effects.rain == 0.0


def test_every_character_has_a_portrait(pg):
    people = characters.PILOTS + list(characters.TOWERS.values()) + characters.PASSENGERS
    for person in people:
        image = person.portrait(64)
        assert image.get_size() == (64, 64)
        assert image.get_at((0, 0)).a == 0 and image.get_at((32, 32)).a == 255
    assert set(characters.TOWERS) == {city[0] for city in world.CITIES}
    for passenger in characters.PASSENGERS:
        assert '{dest}' in passenger.ask and passenger.thanks


def test_radio_queues_and_interrupts(fonts):
    radio = characters.Radio()
    tower = characters.TOWERS['TROY']
    radio.say(tower, 'first')
    radio.say(tower, 'first')  # duplicates are dropped
    radio.say(tower, 'second')
    radio.update(0.0)
    assert radio.current[1] == 'first' and len(radio.queue) == 1
    radio.say(tower, 'urgent', urgent=True)
    assert radio.current[1] == 'urgent' and not radio.queue
    surface = pygame.Surface((1280, 720), pygame.SRCALPHA)
    for _ in range(100):
        radio.update(0.1)
        radio.draw(surface, fonts)
    assert radio.current is None


def test_audio_is_safe_with_or_without_a_device(atmosphere):
    for enabled in (False, True):
        audio = Audio(pygame, enabled=enabled)
        atmosphere.emit('lightning')
        atmosphere.emit('crash')
        for _ in range(10):
            audio.update(0.1, atmosphere, True)
        audio.play('ring')
        audio.toggle_mute()
        audio.play('ring')
        audio.close()


def test_scores_survive_damage_and_missing_folders(tmp_path):
    path = tmp_path / 'deep' / 'folder' / 'scores.json'
    scores = Scores(path)
    assert scores.best('ring_best', 500) and not scores.best('ring_best', 100)
    assert Scores(path).get('ring_best') == 500
    path.write_text('{not json')
    assert Scores(path).get('ring_best') == 0
    path.write_text('[1, 2]')
    assert Scores(path).get('ring_best') == 0
    path.write_text('{"ring_best": "lots"}')
    assert Scores(path).get('ring_best') == 0
    blocked = tmp_path / 'file_not_folder'
    blocked.write_text('x')
    Scores(blocked / 'scores.json').best('ring_best', 10)  # cannot save: reports, does not crash
