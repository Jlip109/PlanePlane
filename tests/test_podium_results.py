from types import SimpleNamespace

import pygame

from race import RaceRoom,FINISH_Z
from scores import Scores
from test_features import make_game
from test_race import environment,state


def start_room(count):
    now=[0.]
    room=RaceRoom(clock=lambda:now[0])
    for i in range(count):room.join(str(i),'Pilot'+str(i))
    for i in range(count):room.ready(str(i),True)
    room.prepared(environment());now[0]=5;room.tick()
    return room,now


def test_podium_awards_bonus_points_once_in_finish_order():
    room,now=start_room(4)
    for i,(medal,bonus) in enumerate([('gold',1000),('silver',600),('bronze',300),(None,0)]):
        now[0]=100+i*5
        room.receive(str(i),state(z=FINISH_Z,speed=200))
        p=room.members[str(i)]
        assert p['medal']==medal and p['podium_bonus']==bonus and p['score']==bonus
        room.receive(str(i),state(z=FINISH_Z,speed=200))
        assert p['score']==bonus
    room.tick()
    assert room.phase=='results' and room.winners==['0']
    assert [p['score'] for p in room.records]==[1000,600,300,0]


def test_practice_and_dnf_do_not_receive_medals():
    solo,now=start_room(1)
    now[0]=20;solo.receive('0',state(z=FINISH_Z,speed=200))
    assert solo.members['0']['medal'] is None and solo.members['0']['podium_bonus']==0
    assert not solo.records
    room,now=start_room(2)
    now[0]=25;room.receive('0',state(crashed=True))
    assert room.members['0']['race_time']==20 and room.members['0']['medal'] is None


def test_medal_claims_persist_and_cannot_be_duplicated(tmp_path):
    path=tmp_path/'scores.json';scores=Scores(path)
    assert scores.claim_podium('race-one','gold')
    assert not scores.claim_podium('race-one','gold')
    other=Scores(path)
    assert not other.claim_podium('race-one','gold')
    assert other.claim_podium('race-two','silver')
    assert other.data['podium_medals']==dict(gold=1,silver=1,bronze=0)


def test_all_24_times_scores_and_dnf_are_on_the_results_board(atmosphere,fonts,tmp_path,monkeypatch):
    import ui
    room,now=start_room(24)
    now[0]=100
    room.receive('0',state(z=FINISH_Z,speed=200))
    for i in range(1,24):
        now[0]=100+i*.5
        room.receive(str(i),state(crashed=True))
    room.tick()
    game=make_game(atmosphere,fonts,tmp_path,'ffa')
    game.network=SimpleNamespace(player_id='0',race=room.snapshot(),status='Connected',lobby_id=1)
    game.mode.sync(atmosphere)
    labels=[]
    original=ui.text
    def capture(surface,value,*args,**kwargs):
        labels.append(str(value))
        return original(surface,value,*args,**kwargs)
    monkeypatch.setattr(ui,'text',capture)
    game.mode.draw_hud(pygame.Surface((1280,720),pygame.SRCALPHA),atmosphere,fonts)
    assert all('Pilot'+str(i) in labels for i in range(24))
    assert 'FINISHED · RACE RESULTS' in labels
    assert '95.00s' in labels and '106.50s' in labels
    assert '1,000' in labels and any('DNF' in text for text in labels)
    assert game.scores.data['podium_medals']['gold']==1
    game.mode.sync(atmosphere)
    assert game.scores.data['podium_medals']['gold']==1
