import socket
import urllib.request

import numpy as np
import pygame
import pytest

import main
from launcher import Profile
from modes import RingRun
from race import FINISH_Z,RUNWAY_Y,course,touches_finish
from test_features import make_game
from test_race import prepared,state


def test_touching_finish_with_missed_rings_finishes_and_shows_screen(atmosphere,fonts,tmp_path):
    room,now=prepared();now[0]=5;room.tick()
    assert room.members['a']['next_gate']==0
    room.receive('a',state(z=FINISH_Z,y=RUNWAY_Y+4.5,speed=300))
    assert room.members['a']['status']=='finished'
    assert room.members['a']['place']==1


def test_finish_contact_is_swept_and_flying_above_does_not_finish():
    assert touches_finish(state(x=-150,z=FINISH_Z,y=243),state(x=150,z=FINISH_Z,y=243))
    assert not touches_finish(state(x=-150,z=FINISH_Z,y=300),state(x=150,z=FINISH_Z,y=300))
    room,now=prepared();now[0]=5;room.tick()
    room.receive('a',state(x=-150,z=FINISH_Z,y=243,speed=1000))
    room.receive('a',state(x=150,z=FINISH_Z,y=243,speed=1000))
    assert room.members['a']['status']=='finished'


def test_ring_spacing_is_moderately_increased():
    rings=course(123)
    assert len(rings)==40 and RingRun.SPACING==900
    distances=[np.linalg.norm(np.array([b[k]-a[k] for k in ('x','y','z')])) for a,b in zip(rings,rings[1:])]
    assert np.mean(distances)>800


def test_offline_practice_runs_finishes_and_restarts_without_network(atmosphere,fonts,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Offline practice attempted network access')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(urllib.request,'urlopen',forbidden)
    game=make_game(atmosphere,fonts,tmp_path,'practice')
    assert game.network.offline and game.mode.snapshot['phase']=='countdown'
    for _ in range(51):game.update(.1,.1)
    assert game.mode.snapshot['phase']=='racing'
    atmosphere.position=np.array([0.,FINISH_Z])
    atmosphere.altitude=RUNWAY_Y+3
    atmosphere.speed=200
    game.update(.016,.016)
    assert game.mode.local['status']=='finished' and atmosphere.finish_rollout
    assert 'ffa_best_score' not in game.scores.data and 'ffa_best_time' not in game.scores.data
    canvas=pygame.Surface((1280,720),pygame.SRCALPHA)
    game.mode.draw_hud(canvas,atmosphere,fonts)
    assert canvas.get_bounding_rect().width>500
    game.act('restart')
    assert game.mode.snapshot['phase']=='countdown' and not atmosphere.finish_rollout
    game.to_title();game.start('practice')
    assert not atmosphere.left_match and game.network.offline


def test_practice_launcher_button_never_connects(pg):
    args=main.parse_args([]);profile=Profile(args);profile.values[0]='OfflinePilot'
    assert any(action=='practice' for _,action,_ in profile.buttons)
    assert profile.select('practice') and args.mode=='practice' and args.connect is None


def test_offline_practice_pauses_its_clock(atmosphere,fonts,tmp_path):
    game=make_game(atmosphere,fonts,tmp_path,'practice')
    game.state='paused'
    before=game.network.time
    game.update(1.,0.)
    assert game.network.time==before
