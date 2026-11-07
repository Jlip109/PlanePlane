import numpy as np
import pygame
import pytest

import main
import world
from cities import CityScene
from conftest import Keys


def test_building_exports_and_roof_collisions():
    scene = CityScene()
    assert len(scene.batches) == 3 and len(world.BUILDINGS) == 36
    for vertices,normals,colors in scene.models.values():
        assert len(vertices)%3 == 0 and len(vertices)//3 <= 2500
        assert np.isfinite(vertices).all() and np.isfinite(normals).all()
        assert colors.min() >= 0 and colors.max() <= 1
    building = world.BUILDINGS[0]
    assert world.obstacle_height(building['x'],building['z']) == pytest.approx(building['y']+building['height'])


def test_cities_are_distance_culled(atmosphere):
    scene = CityScene()
    atmosphere.position = np.array([100000.,100000.])
    assert scene.cpu_mesh(atmosphere) is None
    atmosphere.position = np.array(world.CITY_CENTERS[0])
    assert scene.cpu_mesh(atmosphere) is not None


def test_ws_climb_acceleration_is_gradual_and_ad_banks(atmosphere):
    initial = atmosphere.altitude
    atmosphere.update(.1,Keys({pygame.K_w:1,pygame.K_d:1}))
    assert 0 < atmosphere.vertical_speed <= atmosphere.vertical_acceleration*.1
    assert atmosphere.altitude-initial <= atmosphere.vertical_acceleration*.01+.001
    assert atmosphere.bank < 0 and atmosphere.heading > 0


def test_scaled_gpu_world_keeps_depth(monkeypatch,tmp_path):
    pygame.display.quit()
    monkeypatch.delenv('SDL_VIDEODRIVER',raising=False)
    original = main.open_window
    errors = []

    def scaled(pygame,args):
        renderer = original(pygame,args)
        renderer.scale = .75
        close = renderer.close

        def checked_close():
            errors.append(renderer.context.error)
            close()

        renderer.close = checked_close
        return renderer

    monkeypatch.setattr(main,'open_window',scaled)
    main.main(['--mode','free','--plane','f15','--renderer','gpu','--headless','--frames','3','--fps','0'])
    assert errors == ['GL_NO_ERROR']
