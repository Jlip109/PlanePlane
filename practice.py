"""Offline practice using the same race rules, with no sockets or weather requests."""
import pygame

from online_mode import OnlineRace
from race import RaceRoom
import ui


class LocalSession:
    offline=True
    player_id='offline'
    lobby_id=1
    status='Connected'

    def __init__(self,seed,name,environment):
        self.time=0.
        self.room=RaceRoom(seed if seed is not None else 1,clock=lambda:self.time)
        self.room.join(self.player_id,name)
        self.room.ready(self.player_id,True)
        self.room.prepared(environment)
        self.race=self.room.snapshot()

    def advance(self,dt):
        if self.room.phase!='results':
            self.time+=dt
            self.room.tick()

    def publish(self,a):
        state=dict(x=float(a.position[0]),y=a.altitude,z=float(a.position[1]),heading=a.heading,
                   bank=a.bank,flight_pitch=a.flight_pitch,speed=a.speed,fuel=a.fuel,
                   crashed=a.crashed,left_match=a.left_match)
        self.room.receive(self.player_id,state)
        self.race=self.room.snapshot()

    def close(self):
        self.status='Disconnected'


class OfflinePractice(OnlineRace):
    name='Practice Ring Mode'
    key='practice'
    description='Practice the race offline: fly the course, collect fuel, and land at the finish runway. Scores are not recorded.'

    def __init__(self,game,seed=None):
        super().__init__(game,seed)
        self.seed=seed

    def start(self,a):
        self.round_id=-1
        self.last_record=None
        minutes=int(a.hour*60)%1440
        env=dict(label='Offline Practice',hour=a.hour,local_time=f'{minutes//60:02d}:{minutes%60:02d}',
                 cover=a.cover,wind=a.wind,wind_angle=a.wind_angle,precipitation=a.precipitation,
                 storm=a.storm,live=False,offline=True)
        self.game.network=LocalSession(self.seed,self.game.scores.get('username','Pilot'),env)
        super().start(a)
        self.sync(a)

    def update(self,dt,a):
        self.game.network.advance(dt)
        self.game.network.publish(a)
        self.sync(a)

    def event(self,event):
        if event.type==pygame.MOUSEWHEEL:self.scroll=0

    def draw_hud(self,surface,a,fonts):
        super().draw_hud(surface,a,fonts)
        if self.snapshot and self.snapshot['phase']=='results' and self.local['status']!='finished':
            ui.text(surface,'Esc → Restart to practise again',fonts.body,ui.ACCENT,(640,580),'midtop')
