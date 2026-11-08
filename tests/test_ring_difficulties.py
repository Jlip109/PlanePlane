import math

import numpy as np
import pygame
import pytest

from modes import RingRun
from test_features import fly_to, make_game, press
from units import FEET_PER_METRE


def test_red_and_blue_geometry_and_colors_match_collision(atmosphere, fake_game):
    run = RingRun(fake_game, seed=3)
    run.start(atmosphere)
    assert [run.ring_types[r] for r in run.rings] == ['blue', 'red', 'blue', 'red']
    for ring, radius in zip(run.rings[:2], (105, 45)):
        relative = run.gate_faces(ring)-np.array(ring[:3])
        local = relative @ run.gate_matrix(ring)
        assert np.max(np.linalg.norm(local[:,:,:2],axis=2)) == pytest.approx((70+3)*radius/70, abs=.001)
        assert set(np.round(local[:,:,2].ravel()).astype(int)) == {-4, 4}
    mesh = run.world_mesh(atmosphere)
    assert mesh[2][0,2] > mesh[2][0,0]  # First ring is blue.
    count = len(run.local_vertices)
    assert mesh[2][count,0] > mesh[2][count,2]  # Second ring is red.


@pytest.mark.parametrize('kind, passes', [('blue', True), ('red', False)])
def test_same_offset_fits_blue_but_misses_red(atmosphere, fake_game, kind, passes):
    run = RingRun(fake_game, seed=3)
    run.start(atmosphere)
    ring = run.rings[0]
    run.ring_types[ring] = kind
    x,y,z,nx,nz = ring
    for side in (-5, 5):
        fly_to(atmosphere, x+nx*side+nz*60, y, z+nz*side-nx*60, math.atan2(nx,nz))
        run.update(.016, atmosphere)
    assert run.passed == int(passes)
    assert run.score == (100 if passes else 0)


def test_route_has_gentle_continuous_changes(atmosphere, fake_game):
    atmosphere.altitude = 1800
    run = RingRun(fake_game, seed=12)
    run.start(atmosphere)
    for _ in range(80):
        before = run.rings[-1]
        run.rings.pop(0)
        run.add_ring()
        after = run.rings[-1]
        assert before[3]*after[3]+before[4]*after[4] >= math.cos(.16)
        assert abs(after[1]-before[1]) <= 60
        assert run.SPACING*.9 <= math.hypot(after[0]-before[0],after[2]-before[2]) <= run.SPACING*1.2
        assert len(run.ring_types) == len(run.rings)


def test_path_warning_resets_on_return_and_ends_after_five_seconds(atmosphere, fake_game):
    run = RingRun(fake_game, seed=4)
    run.start(atmosphere)
    start = np.array(run.path_anchor)
    atmosphere.position[0] = start[0]-run.path_range-100
    run.update(4.9, atmosphere)
    assert run.path_distance > run.path_range and run.off_path_time == 4.9
    assert not run.finished
    atmosphere.position[0] = start[0]
    run.update(.1, atmosphere)
    assert run.off_path_time == 0
    atmosphere.position[0] = start[0]-run.path_range-100
    run.update(4.9, atmosphere)
    assert not run.finished
    run.update(.11, atmosphere)
    assert run.finished and run.summary['title'] == 'Left the ring path'


def test_path_distance_includes_altitude_and_segment_interiors(atmosphere, fake_game):
    run = RingRun(fake_game, seed=4)
    run.start(atmosphere)
    middle = (np.array(run.path_anchor)+np.array(run.rings[0][:3]))/2
    atmosphere.position = middle[[0,2]].copy()
    atmosphere.altitude = middle[1]+30
    assert run.distance_to_path(atmosphere) == pytest.approx(30)


def test_range_slider_scaled_drag_persists_and_changes_boundary(atmosphere, fonts, tmp_path):
    game = make_game(atmosphere,fonts,tmp_path,'rings')
    press(game,pygame.K_ESCAPE)
    game.menu.draw(pygame.Surface((1280,720)),game.state)
    rect = dict(game.menu.slider_areas)['range']
    game.hud_transform = (1.5,20,10)
    def point(x):
        return round(x*1.5+20),round(rect.centery*1.5+10)
    game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=point(rect.left)))
    assert game.ring_range == 0 and game.mode.path_range*FEET_PER_METRE == pytest.approx(250)
    game.handle_event(pygame.event.Event(pygame.MOUSEMOTION,pos=point(rect.right),rel=(0,0),buttons=(1,0,0)))
    game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP,button=1,pos=point(rect.right)))
    assert game.ring_range == 100 and game.paused
    assert game.mode.path_range*FEET_PER_METRE == pytest.approx(5000)
    other = make_game(atmosphere,fonts,tmp_path,'rings')
    assert other.ring_range == 100
