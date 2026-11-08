import math
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

import main
from conftest import Keys
from race import FINISH_Z,RUNWAY_Y
from test_features import make_game
from test_race import prepared,state


def test_middle_mouse_orbits_without_mouse_steering_and_restores_view(atmosphere):
    a=atmosphere
    a.third_person=False
    controls=main.DisplayControls(pygame)
    controls.set_look_button(1,True)
    controls.sync_mouse_mode(a,True)
    assert a.mouse_steering
    controls.set_look_button(2,True)
    a.mouse_look((200,-100))
    target=a.look_target_yaw
    controls.sync_mouse_mode(a,True)
    assert controls.freecam_active and a.third_person and not a.mouse_steering
    assert a.look_target_yaw==target
    a.update(.1,Keys())
    assert a.look_yaw>0 and a.heading==0 and a.vertical_speed==0
    controls.set_look_button(2,False)
    controls.sync_mouse_mode(a,True)
    assert not a.third_person and a.mouse_steering and controls.mouse_looking
    controls.grab_mouse(False)
    controls.sync_mouse_mode(a,True)
    assert not a.mouse_steering and not controls.look_buttons


def test_middle_mouse_events_work_in_running_game(monkeypatch):
    from test_app import run_scripted
    observed=[]
    original=main.DisplayControls.sync_mouse_mode
    def track(self,a,flying):
        original(self,a,flying)
        observed.append((self.freecam_active,a.mouse_steering))
    monkeypatch.setattr(main.DisplayControls,'sync_mouse_mode',track)
    run_scripted(monkeypatch,{
        1:[pygame.K_RETURN],
        2:[(pygame.MOUSEBUTTONDOWN,dict(button=2,pos=(100,100))),
           (pygame.MOUSEMOTION,dict(pos=(200,80),rel=(100,-20),buttons=(0,1,0)))],
        4:[(pygame.MOUSEBUTTONUP,dict(button=2,pos=(200,80)))],
    },7)
    assert (True,False) in observed and observed[-1]==(False,False)


@pytest.mark.parametrize('heading',[0,math.pi/2,math.pi,-math.pi/2])
@pytest.mark.parametrize('speed',[75,main.Atmosphere.MAX_SPEED])
def test_finished_plane_decelerates_and_stays_on_runway(atmosphere,heading,speed):
    a=atmosphere
    a.position=np.array([0.,FINISH_Z+879.])
    a.altitude=RUNWAY_Y+3
    a.heading=heading
    a.speed=speed
    a.race_frozen=a.finish_rollout=True
    fuel=a.fuel
    for _ in range(180):
        before=a.speed
        a.update(1/60,Keys({pygame.K_SPACE:1,pygame.K_w:1,pygame.K_d:1}))
        assert 0<=a.speed<=before
        assert abs(a.position[0])<=80.001 and abs(a.position[1]-FINISH_Z)<=880.001
        assert a.altitude==RUNWAY_Y+3 and not a.crashed
    assert a.speed==0 and a.fuel==fuel and not a.boosting


def test_server_finish_starts_rollout_without_changing_finish_time(atmosphere,fonts,tmp_path):
    room,now=prepared();now[0]=5;room.tick()
    game=make_game(atmosphere,fonts,tmp_path,'ffa')
    game.network=SimpleNamespace(player_id='a',race=room.snapshot(),status='Connected',lobby_id=1)
    game.mode.sync(atmosphere)
    atmosphere.position=np.array([0.,FINISH_Z])
    atmosphere.altitude=RUNWAY_Y+3
    atmosphere.speed=200
    room.members['a']['next_gate']=len(room.rings)
    now[0]=125;room.receive('a',state(z=FINISH_Z,speed=200))
    game.network.race=room.snapshot()
    game.mode.sync(atmosphere)
    assert atmosphere.finish_rollout and atmosphere.speed==200
    atmosphere.update(.1,Keys())
    assert 0<atmosphere.speed<200
    assert room.members['a']['finish_time']==120


def test_starting_new_flight_clears_finished_and_frozen_state(atmosphere,fonts,tmp_path):
    game=make_game(atmosphere,fonts,tmp_path,'free')
    atmosphere.finish_rollout=atmosphere.race_frozen=True
    game.start('free')
    assert not atmosphere.finish_rollout and not atmosphere.race_frozen
    before=atmosphere.position.copy()
    atmosphere.update(.1,Keys())
    assert not np.array_equal(atmosphere.position,before)


@pytest.mark.parametrize('fps',[30,60,120])
def test_empty_tank_slows_to_zero_and_falls_fast_despite_climb_input(atmosphere,fps):
    a=atmosphere
    a.altitude=4000
    a.fuel=0
    a.flight_tuning['climb']=100
    initial=a.altitude
    for _ in range(5*fps):a.update(1/fps,Keys({pygame.K_SPACE:1,pygame.K_w:1}))
    assert a.speed==0 and not a.boosting
    assert a.vertical_speed==pytest.approx(-49.05,abs=.01)
    assert initial-a.altitude>120 and not a.crashed


def test_empty_fuel_fall_is_capped_and_finish_rollout_is_safe(atmosphere):
    a=atmosphere
    a.fuel=0
    a.vertical_speed=-500
    a.altitude=4000
    a.update(.1,Keys())
    assert a.vertical_speed==-main.MAX_FALL_SPEED
    a.position=np.array([0.,FINISH_Z])
    a.altitude=RUNWAY_Y+3
    a.finish_rollout=a.race_frozen=True
    a.update(.1,Keys())
    assert not a.crashed and a.vertical_speed==0 and a.altitude==RUNWAY_Y+3


def test_refuelling_recovers_engine_power(atmosphere):
    a=atmosphere
    a.fuel=0
    a.update(.1,Keys({pygame.K_SPACE:1}))
    assert not a.boosting
    a.fuel=25
    before=a.speed
    a.update(.1,Keys({pygame.K_SPACE:1}))
    assert a.boosting and a.speed>before
