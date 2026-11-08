import asyncio
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

import main
import world
from conftest import Keys
from launcher import Profile,rgb
from network import NetworkClient,RoomServer
from race import RaceRoom,COUNTDOWN_SECONDS,RACE_SECONDS,RUNWAY_Y,FINISH_Z,LANDING_BONUS,course,spawn_for
from trees import tree_sites


def environment():
    return dict(label='Los Angeles, California',hour=18+5/60,local_time='18:05',cover=.2,wind=5,
                wind_angle=1,precipitation=0,storm=0,temperature_f=68,live=True)


def prepared():
    now=[0.0]
    room=RaceRoom(clock=lambda:now[0])
    room.join('a','Alpha');room.join('b','Beta')
    room.ready('a',True)
    assert room.phase=='lobby'
    room.ready('b',True)
    assert room.phase=='loading'
    room.prepared(environment())
    assert room.phase=='countdown'
    return room,now


def state(**changes):
    s=dict(x=0.,y=RUNWAY_Y+3,z=-4500.,heading=0.,bank=0.,flight_pitch=0.,speed=0.,fuel=100.,model='classic')
    s.update(changes)
    return s


def test_countdown_two_minutes_winner_and_next_lobby():
    room,now=prepared()
    now[0]=4.99;room.tick()
    assert room.phase=='countdown'
    now[0]=5;room.tick()
    assert room.phase=='racing' and room.snapshot()['remaining']==RACE_SECONDS
    room.members['a']['score']=300
    room.members['b']['score']=500
    now[0]+=RACE_SECONDS;room.tick()
    assert room.phase=='results' and room.winners==['b']
    now[0]+=15;room.tick()
    assert room.phase=='lobby' and not any(p['ready'] for p in room.members.values())


def test_single_pilot_never_starts():
    room=RaceRoom();room.join('a','Alpha');room.ready('a',True)
    assert room.phase=='lobby'


@pytest.mark.parametrize('cause', ['crashed','left_match','area','disconnect'])
def test_disqualified_cannot_win(cause):
    room,now=prepared();now[0]=5;room.tick()
    room.members['a']['score']=10000
    if cause=='disconnect':room.leave('a')
    else:room.receive('a',state(**({'x':10000} if cause=='area' else {cause:True})))
    assert room.members['a']['status']=='disqualified'
    now[0]+=120;room.tick()
    assert room.winners==['b']


def test_server_scores_each_gate_once_and_safe_finish_bonus():
    room,now=prepared();now[0]=5;room.tick()
    for ring in room.rings:
        for side in (-5,5):
            room.receive('a',state(x=ring['x']+ring['nx']*side,y=ring['y'],z=ring['z']+ring['nz']*side,speed=75))
    p=room.members['a']
    expected=sum(200 if r['kind']=='red' else 100 for r in room.rings)
    assert p['score']==expected and p['next_gate']==len(room.rings)
    room.receive('a',state(z=FINISH_Z,y=RUNWAY_Y+3,speed=50))
    assert p['score']==expected+LANDING_BONUS and p['landed']
    room.receive('a',state(z=FINISH_Z,y=RUNWAY_Y+3,speed=50))
    assert p['score']==expected+LANDING_BONUS


def test_course_varies_altitude_spacing_and_is_deterministic():
    rings=course(123)
    assert rings==course(123) and rings!=course(124)
    assert len({round(r['y']) for r in rings})>5
    assert len({round(b['z']-a['z']) for a,b in zip(rings,rings[1:])})>5


def test_runway_is_safe_at_any_speed_and_brakes(atmosphere):
    spawn=spawn_for(0)
    atmosphere.position=np.array([spawn['x'],spawn['z']])
    atmosphere.altitude=RUNWAY_Y-20
    atmosphere.speed=atmosphere.MAX_SPEED
    atmosphere.vertical_speed=-300
    atmosphere.update(.016,Keys())
    assert not atmosphere.crashed and atmosphere.altitude>=RUNWAY_Y+3
    for _ in range(20):atmosphere.update(.016,Keys())
    assert not atmosphere.crashed and atmosphere.speed<atmosphere.MAX_SPEED


@pytest.mark.parametrize('temp,column',[(110,0),(100,0),(96.875,1),(32,21),(31,22),(0,31),(-10,31)])
def test_temperature_columns(temp,column):
    assert world.temperature_column(temp)==column


@pytest.mark.parametrize('temperature', [20,70])
def test_trees_and_building_footprints_are_on_land(atmosphere,temperature):
    atmosphere.temperature_f=temperature
    sites=tree_sites(atmosphere)
    assert sites
    for x,y,z,species,height in sites:
        assert world.raw_terrain(x,z)>world.WATER and not world.on_runway(x,z)
        assert species==2 if temperature<32 else species in (0,1)
    for b in world.BUILDINGS:
        assert all(world.raw_terrain(b['x']+dx,b['z']+dz)>world.WATER for dx in (-b['width']/2,0,b['width']/2) for dz in (-b['depth']/2,0,b['depth']/2))


def test_profile_validates_username_rgb_and_defaults(pg):
    args=main.parse_args([])
    assert args.fps==0
    profile=Profile(args)
    profile.values[0]=''
    assert not profile.select('ffa')
    profile.values[0]='Alpha'
    profile.values[1]='255, 0, 0'
    assert profile.select('ffa') and args.color=='255,0,0' and args.mode=='ffa'
    assert rgb('0,255,123')==(0,255,123)
    with pytest.raises(ValueError):rgb('256,0,0')


def test_real_clients_ready_lobby_names_released_and_shared_weather(monkeypatch):
    import climate
    monkeypatch.setattr(climate,'race_environment',lambda seed:environment())
    async def scenario():
        room=RoomServer()
        port=await room.start_websocket('127.0.0.1',0)
        clients=[]
        try:
            a=await asyncio.to_thread(NetworkClient,f'ws://127.0.0.1:{port}','Alpha','odd','ffa',(255,0,0));clients.append(a)
            with pytest.raises(ValueError,match='already online'):
                await asyncio.to_thread(NetworkClient,f'ws://127.0.0.1:{port}','alpha','classic','ffa')
            b=await asyncio.to_thread(NetworkClient,f'ws://127.0.0.1:{port}','Beta','f15','ffa');clients.append(b)
            a.set_ready(True)
            await asyncio.sleep(.2)
            assert room.race.phase=='lobby'
            b.set_ready(True)
            for _ in range(30):
                await asyncio.sleep(.05)
                if a.race and a.race['phase']=='countdown':break
            assert a.race['phase']=='countdown' and a.race['environment'] is None
            assert a.race['rings']==[]
            room.race.deadline=room.race.clock()-.01
            for _ in range(30):
                await asyncio.sleep(.05)
                if a.race['phase']=='racing':break
            assert a.race['environment']['local_time']=='18:05'
            assert {p['name'] for p in a.race['players']}=={'Alpha','Beta'}
            assert b.players()[0]['color']==[255,0,0]
            await asyncio.to_thread(a.close)
            await asyncio.sleep(.15)
            again=await asyncio.to_thread(NetworkClient,f'ws://127.0.0.1:{port}','Alpha','odd','ffa');clients.append(again)
            assert again.player_id!=a.player_id
        finally:
            for c in clients:await asyncio.to_thread(c.close)
            await room.close()
    asyncio.run(scenario())
