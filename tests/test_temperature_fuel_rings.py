from types import SimpleNamespace

import pytest
import pygame

import main
import temperature
from conftest import Keys
from test_features import make_game
from test_race import prepared,state
from race import path_distance,AREA_RANGE,FUEL_RING_REFILL


def test_temperature_lapse_is_anchored_to_surface_observation():
    assert temperature.at_altitude(68,240,240)==68
    assert temperature.at_altitude(68,1240,240)==pytest.approx(56.3)
    assert temperature.at_altitude(68,2240,240)<temperature.at_altitude(68,1240,240)
    assert temperature.at_altitude(None,2000) is None


def test_warm_air_uses_slightly_more_fuel_and_altitude_cools_it(pg):
    remaining=[]
    for surface in (32,100):
        a=main.Atmosphere(pg)
        a.temperature_f=surface
        a.temperature_reference_altitude=a.altitude
        a.update(.1,Keys({pygame.K_SPACE:1}))
        remaining.append(a.fuel)
    assert remaining[1]<remaining[0]
    assert temperature.fuel_multiplier(100)==pytest.approx(1.0615)
    assert temperature.fuel_multiplier(-100)>=.94
    assert temperature.fuel_multiplier(200)<=1.12


def test_course_and_weather_are_hidden_until_go():
    room,now=prepared()
    hidden=room.snapshot()
    assert hidden['environment'] is None and hidden['rings']==[] and hidden['fuel_rings']==[]
    now[0]=5;room.tick()
    shown=room.snapshot()
    assert shown['environment'] and shown['rings'] and shown['fuel_rings']


def test_fuel_rings_are_detours_give_fuel_without_points_and_only_once():
    room,now=prepared();now[0]=5;room.tick()
    ring=room.fuel_rings[0]
    assert 180<path_distance(ring,room.rings)<AREA_RANGE
    player=room.members['a']
    for _ in range(2):
        for side in (-5,5):
            room.receive('a',state(x=ring['x']+ring['nx']*side,y=ring['y'],z=ring['z']+ring['nz']*side,fuel=20))
    assert player['score']==0
    assert player['fuel_credit']==FUEL_RING_REFILL
    assert player['collected_fuel']==[ring['id']]


def test_client_applies_fuel_credit_once_and_caps_tank(atmosphere,fonts,tmp_path):
    room,now=prepared();now[0]=5;room.tick()
    game=make_game(atmosphere,fonts,tmp_path,'ffa')
    network=SimpleNamespace(player_id='a',race=room.snapshot(),status='Connected')
    game.network=network
    game.mode.sync(atmosphere)
    atmosphere.fuel=30
    room.members['a']['fuel_credit']=25
    room.members['a']['collected_fuel']=[room.fuel_rings[0]['id']]
    network.race=room.snapshot()
    game.mode.sync(atmosphere)
    assert atmosphere.fuel==55
    game.mode.sync(atmosphere)
    assert atmosphere.fuel==55
    room.members['a']['fuel_credit']=100
    network.race=room.snapshot()
    game.mode.sync(atmosphere)
    assert atmosphere.fuel==100
    assert atmosphere.temperature_f==68
    altitude=atmosphere.altitude
    atmosphere.altitude+=1000
    assert atmosphere.air_temperature_f==pytest.approx(temperature.at_altitude(68,altitude+1000,240))
