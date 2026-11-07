import pygame
import pytest

import main
from conftest import Keys
from test_features import make_game, press


def test_slider_drag_scales_clamps_and_persists(atmosphere, fonts, tmp_path):
    game = make_game(atmosphere, fonts, tmp_path, 'free')
    press(game, pygame.K_ESCAPE)
    game.hud_transform = (1.5, 20, 10)
    game.menu.draw(pygame.Surface((1280, 720)), game.state)
    assert len(game.menu.slider_areas) == 4

    def screen(x, y):
        return round(x*1.5+20), round(y*1.5+10)

    for key, rect in game.menu.slider_areas:
        if key == 'range':
            continue
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                          button=1, pos=screen(rect.centerx, rect.centery)))
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
                          pos=screen(rect.left+rect.width*.8, rect.centery),
                          rel=(0, 0), buttons=(1, 0, 0)))
        assert atmosphere.flight_tuning[key] == 80
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
                          pos=screen(rect.right+100, rect.centery),
                          rel=(0, 0), buttons=(1, 0, 0)))
        assert atmosphere.flight_tuning[key] == 100
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP,
                          button=1, pos=screen(rect.right, rect.centery)))
        assert game.menu.dragging_slider is None and game.paused
    other = main.Atmosphere(pygame)
    make_game(other, fonts, tmp_path)
    assert other.flight_tuning == dict.fromkeys(('climb', 'acceleration', 'steering'), 100)


@pytest.mark.parametrize('setting, keys, attribute', [
    ('climb', {pygame.K_w: 1}, 'vertical_speed'),
    ('acceleration', {pygame.K_SPACE: 1}, 'speed'),
    ('steering', {pygame.K_d: 1}, 'heading'),
])
def test_each_slider_changes_flight_response(pg, setting, keys, attribute):
    values = []
    for tuning in (0, 100):
        a = main.Atmosphere(pg)
        a.autopilot = False
        a.flight_tuning[setting] = tuning
        for _ in range(30):
            a.update(1/60, Keys(keys))
        values.append(getattr(a, attribute))
    assert values[1] > values[0]*1.1


@pytest.mark.parametrize('fps', [30, 60, 120])
@pytest.mark.parametrize('key, direction', [(pygame.K_w, 1), (pygame.K_s, -1)])
def test_ws_endpoints_change_motion_nose_and_release(pg, fps, key, direction):
    results = []
    for value in (0, 100):
        a = main.Atmosphere(pg)
        a.flight_tuning['climb'] = value
        for _ in range(round(fps*.2)):
            a.update(1/fps, Keys({key: 1}))
        speed = a.vertical_speed*direction
        pitch = a.flight_pitch*direction
        for _ in range(round(fps*.2)):
            a.update(1/fps, Keys())
        results.append((speed, pitch, abs(a.vertical_speed)/speed))
    slow, fast = results
    assert slow[0] < main.CLIMB_RATE*.15
    assert fast[0] > main.CLIMB_RATE*3*.95
    assert fast[1] > slow[1]*10
    assert slow[2] > .85 and fast[2] < .05


def test_ws_response_increases_across_entire_slider(pg):
    rates = []
    for value in (0, 25, 50, 75, 100):
        a = main.Atmosphere(pg)
        a.flight_tuning['climb'] = value
        for _ in range(12):
            a.update(1/60, Keys({pygame.K_w: 1}))
        rates.append(a.vertical_speed)
    assert all(low < high for low, high in zip(rates, rates[1:]))


@pytest.mark.parametrize('key, direction', [(pygame.K_w, 1), (pygame.K_s, -1)])
def test_ws_100_has_triple_movement(pg, key, direction):
    a = main.Atmosphere(pg)
    a.flight_tuning['climb'] = 100
    for _ in range(60):
        a.update(1/60, Keys({key: 1}))
    assert a.vertical_speed*direction == pytest.approx(main.CLIMB_RATE*3, rel=.001)


@pytest.mark.parametrize('setting, drag, keys, attribute', [
    ('climb', (0, -150), {}, 'vertical_speed'),
    ('steering', (150, 0), {}, 'heading'),
    ('acceleration', (0, 0), {pygame.K_SPACE: 1}, 'speed'),
])
def test_tuning_applies_while_mouse_steering(pg, setting, drag, keys, attribute):
    results = []
    for value in (0, 100):
        a = main.Atmosphere(pg)
        a.flight_tuning[setting] = value
        a.set_mouse_steering(True)
        a.mouse_look(drag)
        for _ in range(30):
            a.update(1/60, Keys(keys))
        results.append(getattr(a, attribute))
    assert results[1] > results[0]*1.1


def test_mouse_climb_100_has_triple_movement_for_same_aim(pg):
    results = []
    for value in (0, 100):
        a = main.Atmosphere(pg)
        a.flight_tuning['climb'] = value
        a.set_mouse_steering(True)
        a.mouse_look((0, -100))
        for _ in range(1200):
            a.update(1/60, Keys())
        results.append(a.vertical_speed)
    assert results[1] == pytest.approx(results[0]*3, rel=.001)
