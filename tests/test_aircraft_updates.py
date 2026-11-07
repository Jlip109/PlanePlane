import numpy as np
import pygame
import pytest

import main
from audio import Audio
from conftest import Keys
from plane import PlaneModel
from test_features import make_game, press


def test_mouse_aim_moves_camera_and_plane_smoothly(atmosphere):
    atmosphere.set_mouse_steering(True)
    atmosphere.mouse_look((200,-100))
    assert atmosphere.look_yaw == 0
    target = atmosphere.look_target_yaw
    atmosphere.update(.05,Keys())
    assert 0 < atmosphere.look_yaw < target
    for _ in range(120):
        atmosphere.update(1/60,Keys())
    assert atmosphere.heading > .1 and atmosphere.vertical_speed > 0
    assert abs(atmosphere.look_yaw) < target
    assert atmosphere.flight_pitch > 0
    atmosphere.set_mouse_steering(False)
    offset = abs(atmosphere.look_yaw)
    for _ in range(60):
        atmosphere.update(1/60,Keys())
    assert abs(atmosphere.look_yaw) < offset


@pytest.mark.parametrize('model_id',['classic','f15'])
def test_shadow_softens_and_fades_with_altitude(atmosphere,model_id):
    model = PlaneModel(model_id)
    atmosphere.hour = 12
    atmosphere.cover = 0
    atmosphere.update_lighting()
    values = np.linspace(-35,35,120)
    x,z = np.meshgrid(values,values)
    atmosphere.altitude = 105
    near = model.shadow_at(x,z,atmosphere)
    atmosphere.altitude = 700
    far = model.shadow_at(x,z,atmosphere)
    assert near.max() > far.max() > 0
    assert np.max(np.abs(np.diff(near,axis=0))) > np.max(np.abs(np.diff(far,axis=0)))


def test_models_are_selectable_and_persist(atmosphere,fonts,tmp_path):
    game = make_game(atmosphere,fonts,tmp_path)
    press(game,pygame.K_F8)
    assert atmosphere.plane_id == 'f15'
    other = main.Atmosphere(pygame)
    make_game(other,fonts,tmp_path)
    assert other.plane_id == 'f15'
    assert len(PlaneModel('f15').positions) > len(PlaneModel('classic').positions)


def test_audio_is_disabled_even_when_requested():
    audio = Audio(pygame,enabled=True)
    audio.play('engine')
    audio.play('ring')
    assert not audio.enabled and audio.muted
