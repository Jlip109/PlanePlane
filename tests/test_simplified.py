import math

import pygame
import pytest

import main
import menu
import modes
from conftest import Keys
from test_features import make_game, press


def test_two_modes_and_wireframe_toggle(atmosphere, fonts, tmp_path):
    game = make_game(atmosphere, fonts, tmp_path)
    assert set(game.modes) == {'free', 'rings','practice'}
    assert [key for key, _ in menu.TITLE_ITEMS] == ['free', 'rings','practice', 'aircraft', 'quit']
    assert not hasattr(game, 'radio')
    press(game, pygame.K_F5)
    assert atmosphere.wireframe
    press(game, pygame.K_F5)
    assert not atmosphere.wireframe


def test_vertical_motion_eases_in_and_out(atmosphere):
    atmosphere.update(0.1, Keys({pygame.K_UP: 1}))
    first = atmosphere.vertical_speed
    assert 0 < first < atmosphere.climb_rate
    atmosphere.update(0.1, Keys({pygame.K_UP: 1}))
    second = atmosphere.vertical_speed
    assert first < second < atmosphere.climb_rate
    atmosphere.update(0.1, Keys())
    assert 0 < atmosphere.vertical_speed < second
    atmosphere.update(0.1, Keys({pygame.K_DOWN: 1}))
    assert atmosphere.vertical_speed < second


def test_arrow_keys_bank_and_turn_without_changing_clock(atmosphere):
    atmosphere.cycle_paused = True
    hour, pitch = atmosphere.hour, atmosphere.pitch
    atmosphere.update(0.1, Keys({pygame.K_RIGHT: 1}))
    assert atmosphere.bank < 0 and atmosphere.heading > 0
    assert atmosphere.hour == hour and atmosphere.pitch == pitch
    bank = abs(atmosphere.bank)
    atmosphere.update(0.1, Keys())
    assert abs(atmosphere.bank) < bank


def test_gate_is_an_extruded_decagon(atmosphere, fake_game, monkeypatch):
    gate = modes.RingRun(fake_game, seed=4)
    gate.start(atmosphere)
    ring = gate.rings[0]
    faces = []
    monkeypatch.setattr(modes, 'project_polygon', lambda atmosphere, points, size: faces.append(points) or [])
    gate.draw_ring(pygame.Surface((1280,720),pygame.SRCALPHA), atmosphere, ring, 0, (1280,720), 665)
    assert len(faces) == 40
    x,y,z,nx,nz = ring
    angles, depths = [], set()
    for face in faces:
        for px,py,pz in face:
            side = (px-x)*nz - (pz-z)*nx
            angles.append(math.atan2(py-y,side)%math.tau)
            depths.add(round((px-x)*nx+(pz-z)*nz,5))
    # Inner/outer vertices share directions within float32 precision; rounding
    # at a decimal boundary can otherwise split one corner into two groups.
    directions=[]
    for angle in sorted(angles):
        if not directions or angle-directions[-1]>1e-5:directions.append(angle)
    if len(directions)>1 and directions[0]+math.tau-directions[-1]<1e-5:directions.pop()
    assert len(directions) == 10 and depths == {-4,4}


def test_map_remains_visible_without_location_labels(atmosphere, fonts):
    from hud import Hud
    surface = pygame.Surface((1280,720),pygame.SRCALPHA)
    Hud(fonts).draw_radar(surface,atmosphere,None)
    assert surface.get_bounding_rect().width > 100


def test_removed_mode_is_rejected():
    with pytest.raises(SystemExit):
        main.parse_args(['--mode','courier'])


def test_frame_limit_cycles_in_pause_and_flight(atmosphere, fonts, tmp_path):
    game = make_game(atmosphere, fonts, tmp_path, 'free')
    assert game.frame_limit == 0
    press(game, pygame.K_F7)
    assert game.frame_limit == 60
    press(game, pygame.K_F7)
    assert game.frame_limit == 120
    press(game, pygame.K_ESCAPE)
    game.menu.pause_index = next(i for i, item in enumerate(menu.PAUSE_ITEMS) if item[0] == 'frame_limit')
    press(game, pygame.K_LEFT)
    assert game.frame_limit == 60


def test_drag_buttons_share_camera_capture(pg):
    controls = main.DisplayControls(pg)
    controls.set_look_button(1, True)
    assert controls.mouse_looking
    controls.set_look_button(3, True)
    controls.set_look_button(1, False)
    assert controls.mouse_looking
    controls.set_look_button(3, False)
    assert not controls.mouse_looking
    controls.set_look_button(1, True)
    controls.grab_mouse(False)
    assert not controls.mouse_looking and not controls.look_buttons


def test_gate_rotation_changes_world_geometry(atmosphere, fake_game):
    gate = modes.RingRun(fake_game, seed=4)
    gate.start(atmosphere)
    before = gate.world_mesh(atmosphere)[0]
    gate.update(1, atmosphere)
    after = gate.world_mesh(atmosphere)[0]
    assert before.shape == after.shape
    assert abs(float((before-after).max())) > 1


def test_left_drag_aims_camera_in_running_game(monkeypatch):
    from test_app import run_scripted

    movements = []
    original = main.Atmosphere.mouse_look

    def record(self, relative):
        movements.append(relative)
        original(self, relative)

    monkeypatch.setattr(main.Atmosphere, 'mouse_look', record)
    run_scripted(monkeypatch, {
        1: [pygame.K_RETURN],
        3: [(pygame.MOUSEBUTTONDOWN, {'button': 1, 'pos': (100,100)}),
            (pygame.MOUSEMOTION, {'rel': (40,-20), 'pos': (140,80), 'buttons': (1,0,0)})],
        4: [(pygame.MOUSEBUTTONUP, {'button': 1, 'pos': (140,80)})],
    }, 8)
    assert (40,-20) in movements
