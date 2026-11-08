import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

import main
from conftest import Keys
from launcher import Profile
from network import NetworkClient,RoomServer
from race import RaceRoom,FINISH_Z,RUNWAY_Y,course,MAX_RACE_SECONDS
from test_features import make_game
from test_race import environment,prepared,state


def test_three_lobbies_cap_24_and_empty_slot_reuse():
    server=RoomServer()
    for number in range(1,26):
        key=str(number)
        server.peers[key]=dict(name='Pilot'+key,lobby=None,state=state(),mode='ffa')
        if number<=24:server.join_lobby(key,'create' if number==1 else 'join',1)
    with pytest.raises(ValueError,match='24 racers'):server.join_lobby('25','join',1)
    server.join_lobby('25','create',2)
    server.peers['26']=dict(name='Third',lobby=None,state=state(),mode='ffa')
    server.join_lobby('26','create',3)
    assert [p['count'] for p in server.directory()]==[24,1,1]
    with pytest.raises(ValueError):server.join_lobby('26','create',4)
    with pytest.raises(ValueError,match='already exists'):server.join_lobby('26','create',1)
    server.leave_lobby('25')
    assert not server.directory()[1]['exists']
    server.join_lobby('25','create',2)
    assert server.directory()[1]['count']==1


@pytest.mark.parametrize('delay,finishes',[(29.99,True),(30,False)])
def test_first_finish_starts_exact_thirty_second_cutoff(delay,finishes):
    room,now=prepared();now[0]=5;room.tick()
    now[0]+=100
    room.members['a']['next_gate']=len(room.rings)
    room.receive('a',state(z=FINISH_Z,speed=500))
    assert room.members['a']['status']=='finished'
    assert room.members['a']['finish_time']==100 and room.members['a']['place']==1
    assert room.snapshot()['finish_cutoff']==30
    now[0]+=delay
    room.members['b']['next_gate']=len(room.rings)
    room.receive('b',state(z=FINISH_Z,speed=500))
    assert (room.members['b']['status']=='finished')==finishes
    room.tick()
    assert room.phase=='results' and room.winners==['a']


def test_solo_practice_does_not_record_server_or_local_scores(atmosphere,fonts,tmp_path):
    now=[0.]
    room=RaceRoom(clock=lambda:now[0]);room.join('solo','Solo');room.ready('solo',True)
    room.prepared(environment());now[0]=5;room.tick()
    room.members['solo']['next_gate']=len(room.rings)
    now[0]=125;room.receive('solo',state(z=FINISH_Z,speed=40))
    assert room.practice and room.members['solo']['status']=='finished'
    assert not room.records and not room.members['solo']['recorded']
    game=make_game(atmosphere,fonts,tmp_path,'ffa')
    game.network=SimpleNamespace(player_id='solo',race=room.snapshot(),status='Connected',lobby_id=1)
    game.mode.sync(atmosphere)
    assert atmosphere.race_frozen
    assert 'ffa_best_score' not in game.scores.data and 'ffa_best_time' not in game.scores.data
    canvas=pygame.Surface((1280,720),pygame.SRCALPHA)
    game.mode.draw_hud(canvas,atmosphere,fonts)
    assert canvas.get_bounding_rect().width>500


def test_competitive_finish_records_time_once(atmosphere,fonts,tmp_path):
    room,now=prepared();now[0]=5;room.tick()
    now[0]=130;room.members['a']['next_gate']=len(room.rings)
    room.receive('a',state(z=FINISH_Z,speed=40))
    game=make_game(atmosphere,fonts,tmp_path,'ffa')
    game.network=SimpleNamespace(player_id='a',race=room.snapshot(),status='Connected',lobby_id=1)
    game.mode.sync(atmosphere)
    assert game.scores.data['ffa_best_time']==125
    assert game.scores.data['ffa_best_score']==room.members['a']['score']
    assert len(room.records)==1
    game.mode.sync(atmosphere)
    assert len(room.records)==1


def test_missed_ring_cannot_advance_the_race():
    room,now=prepared();now[0]=5;room.tick()
    ring=room.rings[0]
    for side in (-5,5):
        room.receive('a',state(x=ring['x']+ring['nx']*side+ring['nz']*200,
                               z=ring['z']+ring['nz']*side-ring['nx']*200,y=ring['y']))
    assert room.members['a']['next_gate']==0
    room.receive('a',state(z=FINISH_Z,speed=10))
    assert room.members['a']['status']=='racing'


def test_high_course_is_about_two_minutes_and_ends_at_runway():
    rings=course(123)
    points=[(0,RUNWAY_Y,-4650)]+[(r['x'],r['y'],r['z']) for r in rings]+[(0,RUNWAY_Y,FINISH_Z)]
    length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    assert 115<length/300<125
    assert max(r['y'] for r in rings)>3800
    assert rings[-1]['y']<400 and abs(rings[-1]['x'])<1
    headings=[math.atan2(r['nx'],r['nz']) for r in rings]
    assert min(headings)<-.5 and max(headings)>.5


def test_late_join_waits_and_does_not_turn_practice_into_ranked():
    room=RaceRoom();room.join('a','Alpha');room.ready('a',True)
    room.join('late','Late');room.prepared(environment())
    assert room.practice and room.members['late']['status']=='waiting'


def test_e_brakes_overrides_space_and_empty_tank_cannot_boost(atmosphere):
    atmosphere.speed=300
    atmosphere.update(.1,Keys({pygame.K_e:1,pygame.K_SPACE:1}))
    assert atmosphere.braking and not atmosphere.boosting and atmosphere.speed<=276.001
    atmosphere.fuel=0
    before=atmosphere.speed
    atmosphere.update(.1,Keys({pygame.K_SPACE:1}))
    assert not atmosphere.boosting and atmosphere.speed<before


def test_fuel_burn_is_four_times_faster_at_idle_and_boost(pg):
    for keys,expected in [(Keys(),.32),(Keys({pygame.K_SPACE:1}),2.24)]:
        a=main.Atmosphere(pg)
        for _ in range(60):a.update(1/60,keys)
        assert 100-a.fuel==pytest.approx(expected)


def test_ad_acceleration_reaches_steep_bank_quickly(atmosphere):
    for _ in range(15):atmosphere.update(1/60,Keys({pygame.K_d:1}))
    assert abs(atmosphere.bank)>.5*.75


def test_launcher_exposes_create_and_join(pg):
    args=main.parse_args([]);profile=Profile(args)
    assert {button[1] for button in profile.buttons}>={'create','join'}
    profile.values[0]='Alpha'
    assert profile.select('create')
    assert args.lobby_action=='browse' and args.lobby_intent=='create'


def test_real_clients_can_browse_create_join_and_race_in_isolation(monkeypatch):
    import climate
    monkeypatch.setattr(climate,'race_environment',lambda seed:environment())
    async def wait_until(test):
        for _ in range(80):
            if test():return
            await asyncio.sleep(.025)
        assert test()
    async def scenario():
        server=RoomServer();port=await server.start_websocket('127.0.0.1',0)
        clients=[]
        async def connect(name):
            c=await asyncio.to_thread(NetworkClient,f'ws://127.0.0.1:{port}',name,'classic','ffa',(220,220,220),1,'browse')
            clients.append(c)
            return c
        try:
            a=await connect('Alpha');b=await connect('Beta');c=await connect('Gamma')
            await wait_until(lambda:len(a.lobbies)==3)
            assert not any(item['exists'] for item in a.lobbies)
            a.select_lobby('create',1)
            await wait_until(lambda:a.lobby_id==1)
            b.select_lobby('join',1)
            c.select_lobby('create',2)
            await wait_until(lambda:b.lobby_id==1 and c.lobby_id==2)
            await wait_until(lambda:len(a.players())==1)
            assert {p['name'] for p in a.players()}=={'Beta'}
            assert c.players()==[]
            c.set_ready(True)
            await wait_until(lambda:c.race and c.race['phase']=='countdown')
            assert c.race['practice'] and a.race['phase']=='lobby'
            a.set_ready(True);b.set_ready(True)
            await wait_until(lambda:a.race['phase']=='countdown')
            assert not a.race['practice']
            server.rooms[1].deadline=server.rooms[1].clock()-.1
            await wait_until(lambda:a.race['phase']=='racing')
            assert c.race['phase']=='countdown'
            b.select_lobby('create',2)
            await wait_until(lambda:bool(b.lobby_error))
            assert b.status=='Connected' and b.lobby_id==1
        finally:
            for client in clients:await asyncio.to_thread(client.close)
            await server.close()
    asyncio.run(scenario())
