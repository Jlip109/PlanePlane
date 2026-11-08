import math

import pygame
import pytest

import main
from conftest import Keys
from network import clean_state


def fly_input(pg, yaw=0, pitch=0, keys=None, mouse=True):
    a = main.Atmosphere(pg)
    a.flight_tuning.update(climb=100, steering=100)
    a.set_mouse_steering(mouse)
    a.look_yaw = yaw
    a.pitch = main.DEFAULT_PITCH + pitch
    a.fly(1/60, Keys(keys or {}).__getitem__)
    return a


@pytest.mark.parametrize('key,yaw,pitch,attribute', [
    (pygame.K_d, .4, 0, 'heading'),
    (pygame.K_a, -.4, 0, 'heading'),
    (pygame.K_w, 0, 1.1, 'vertical_speed'),
    (pygame.K_s, 0, -1.1, 'vertical_speed'),
])
def test_matching_keyboard_and_mouse_double_steering(pg, key, yaw, pitch, attribute):
    mouse = fly_input(pg, yaw, pitch)
    keyboard = fly_input(pg, keys={key: 1}, mouse=False)
    combined = fly_input(pg, yaw, pitch, {key: 1})
    assert getattr(keyboard, attribute) == pytest.approx(getattr(mouse, attribute))
    assert getattr(combined, attribute) == pytest.approx(getattr(mouse, attribute)*2)
    assert combined.fuel < mouse.fuel


@pytest.mark.parametrize('key,yaw,pitch,attribute', [
    (pygame.K_a, .4, 0, 'heading'),
    (pygame.K_d, -.4, 0, 'heading'),
    (pygame.K_s, 0, 1.1, 'vertical_speed'),
    (pygame.K_w, 0, -1.1, 'vertical_speed'),
])
def test_opposing_commands_cancel_but_keys_cost_fuel(pg, key, yaw, pitch, attribute):
    opposing = fly_input(pg, yaw, pitch, {key: 1})
    idle = fly_input(pg)
    assert getattr(opposing, attribute) == pytest.approx(0)
    assert idle.fuel-opposing.fuel == pytest.approx(.18*main.FUEL_USAGE_SCALE/60)


def test_keyboard_cost_is_per_axis_and_stops_on_release(pg):
    a = fly_input(pg, keys={pygame.K_d: 1, pygame.K_s: 1})
    idle = fly_input(pg)
    assert idle.fuel-a.fuel == pytest.approx(.36*main.FUEL_USAGE_SCALE/60)
    before = a.fuel
    a.fly(1/60, Keys().__getitem__)
    assert before-a.fuel == pytest.approx(.08*main.FUEL_USAGE_SCALE/60)


def test_right_mouse_look_does_not_add_steering(pg):
    a = fly_input(pg, .4, 1.1, mouse=False)
    assert a.heading == 0 and a.vertical_speed == 0


def test_online_keeps_emergency_bank_angle():
    state = dict(x=0., y=700., z=0., heading=0., bank=2., flight_pitch=0.,
                 speed=75., fuel=100., model='classic')
    assert clean_state(state)['bank'] == 2
    state['bank'] = 100
    assert clean_state(state)['bank'] == math.pi
