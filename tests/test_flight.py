import math

import numpy as np
import pygame
import pytest

from camera import project, view_origin
from conftest import Keys


def test_boost_trades_control_and_fuel_for_speed(atmosphere, pg):
    from main import Atmosphere

    cruise = Atmosphere(pg)
    boost_keys = Keys({pygame.K_SPACE: 1, pygame.K_d: 1, pygame.K_w: 1})
    cruise_keys = Keys({pygame.K_d: 1, pygame.K_w: 1})
    for _ in range(60):
        atmosphere.update(1 / 60, boost_keys)
        cruise.update(1 / 60, cruise_keys)
    assert atmosphere.speed > cruise.speed
    assert atmosphere.fuel < cruise.fuel
    assert atmosphere.heading < cruise.heading
    assert atmosphere.altitude < cruise.altitude
    peak_speed = atmosphere.speed
    atmosphere.update(0.1, Keys())
    assert not atmosphere.boosting and 75 <= atmosphere.speed < peak_speed
    for _ in range(300):
        atmosphere.update(1 / 60, Keys())
    assert atmosphere.speed == pytest.approx(75)


def test_empty_tank_prevents_boost_and_climb(atmosphere):
    atmosphere.fuel = 0.0
    altitude = atmosphere.altitude
    atmosphere.update(0.1, Keys({pygame.K_SPACE: 1, pygame.K_w: 1}))
    assert not atmosphere.boosting and atmosphere.fuel == 0
    assert atmosphere.speed < 75 and atmosphere.altitude < altitude


@pytest.mark.parametrize('yaw,pitch', [(0, 0.03), (1.2, -0.4), (-2.0, 1.2)])
def test_orbit_keeps_plane_in_view_without_changing_flight(atmosphere, yaw, pitch):
    atmosphere.third_person = True
    atmosphere.look_yaw, atmosphere.pitch = yaw, pitch
    point = (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1])
    origin = view_origin(atmosphere)
    assert math.dist(point, origin) > 40
    x, y, depth = project(atmosphere, point, (1280, 720))
    assert 0 < x < 1280 and 0 < y < 720 and depth > 0
    heading = atmosphere.heading
    atmosphere.mouse_look((100, -20))
    assert atmosphere.heading == heading


def test_runtime_mesh_is_finite_and_triangular():
    from plane import PlaneModel

    mesh = PlaneModel()
    assert len(mesh.positions) > 0 and len(mesh.positions) % 3 == 0
    assert mesh.positions.shape == mesh.normals.shape == mesh.colors.shape
    assert np.isfinite(mesh.positions).all() and np.isfinite(mesh.normals).all()
    assert mesh.colors.min() >= 0 and mesh.colors.max() <= 1


def test_boost_reaches_and_holds_mach_five(atmosphere):
    held = Keys({pygame.K_SPACE: 1})
    for _ in range(600):
        atmosphere.update(0.05, held)
        assert atmosphere.speed <= atmosphere.MAX_SPEED
    assert atmosphere.mach == pytest.approx(5)
    atmosphere.update(0.1, Keys())
    assert atmosphere.mach < 5


@pytest.mark.parametrize('fraction,at_limit', [(0.9999, False), (1.0, True)])
def test_imperial_hud_and_mach_five_limit(atmosphere, fonts, monkeypatch, fraction, at_limit):
    import ui
    from hud import Hud
    from units import FEET_PER_METRE, MPH_PER_MPS

    labels = []
    real_render = ui.render
    monkeypatch.setattr(ui, 'render', lambda text, *args, **kwargs: labels.append(text) or real_render(text, *args, **kwargs))
    atmosphere.speed = atmosphere.MAX_SPEED * fraction
    atmosphere.boosting = True
    Hud(fonts).draw_readouts(pygame.Surface((1280, 720), pygame.SRCALPHA), atmosphere)
    text = '\n'.join(labels)
    assert 'ft' in labels and 'mph' in labels and '20.0 US gal' in labels
    assert ('MACH 5 - SPEED LIMIT' in text) == at_limit
    assert ('5.00' in labels) == at_limit
    assert FEET_PER_METRE == pytest.approx(3.280839895)
    assert atmosphere.MAX_SPEED * MPH_PER_MPS == pytest.approx(3806.0, abs=0.2)


def test_mach_readout_keeps_speed_of_sound_reference(atmosphere):
    from units import SPEED_OF_SOUND_MPS
    atmosphere.speed = SPEED_OF_SOUND_MPS
    assert atmosphere.mach == pytest.approx(1)
