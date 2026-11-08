import math

import pygame

from flight_settings import ONLINE_FLIGHT_TUNING
from race import MIN_RING_SPACING,course
from test_features import make_game


def test_random_course_spacing_is_wide_repeatable_and_varied():
    layouts=[]
    for seed in range(30):
        rings=course(seed)
        points=[tuple(r[k] for k in ('x','y','z')) for r in rings]
        gaps=[math.dist(a,b) for a,b in zip(points,points[1:])]
        assert min(gaps)>=MIN_RING_SPACING
        assert sum(gaps)/len(gaps)>1100
        assert max(gaps)-min(gaps)>150
        assert rings==course(seed)
        layouts.append(rings)
    assert all(a!=b for a,b in zip(layouts,layouts[1:]))


def test_online_controls_lock_without_overwriting_offline_preferences(atmosphere,fonts,tmp_path):
    custom={'climb':37,'acceleration':62,'steering':14}
    atmosphere.flight_tuning.update(custom)
    game=make_game(atmosphere,fonts,tmp_path,'ffa')
    assert atmosphere.flight_tuning==ONLINE_FLIGHT_TUNING
    game.set_tuning('climb',0);game.set_tuning('acceleration',100);game.set_tuning('steering',0)
    assert atmosphere.flight_tuning==ONLINE_FLIGHT_TUNING
    game.menu.draw(pygame.Surface((1280,720)),'paused')
    assert game.menu.slider_areas==[]
    atmosphere.flight_tuning['climb']=0
    game.mode.sync(atmosphere)
    assert atmosphere.flight_tuning==ONLINE_FLIGHT_TUNING
    assert 'flight_tuning' not in game.scores.data
    game.to_title()
    assert atmosphere.flight_tuning==custom
    game.start('practice')
    game.set_tuning('climb',72)
    assert atmosphere.flight_tuning['climb']==72 and not game.online_locked


def test_offline_restart_generates_a_new_course(atmosphere,fonts,tmp_path):
    game=make_game(atmosphere,fonts,tmp_path,'practice')
    first=game.network.room.rings
    game.act('restart')
    assert game.network.room.rings!=first
