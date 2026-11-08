"""Client presentation of a server-owned Free for All race."""
import math
from pathlib import Path

import numpy as np
import pygame

import ui
from modes import RingRun
from race import START_Z,FINISH_Z,RUNWAY_Y


class OnlineRace(RingRun):
    name = 'Free for All'
    key = 'ffa'
    description = 'Two-minute online race. Everyone ready, five-second runway start. Highest score wins.'

    def __init__(self,game,seed=None):
        super().__init__(game,seed)
        self.round_id = -1
        self.snapshot = None
        self.local = None
        self.ready = False
        self.fuel_credit = 0
        self.scoring_count = 0
        self.scroll = 0
        self.ready_rect = pygame.Rect(500,580,280,44)
        self.runways = self.runway_mesh()

    def start(self,atmosphere):
        self.active = False
        self.finished = False
        atmosphere.race_frozen = True

    def runway_mesh(self):
        path=Path(__file__).parent/'assets'/'runway_mesh.npz'
        with np.load(path,allow_pickle=False) as mesh:
            p,n,c=(mesh[k].astype('f4') for k in ('positions','normals','colors'))
        pieces=[]
        for z in (START_Z,FINISH_Z):
            pieces.append((p+np.array([0,RUNWAY_Y+.08,z]),n,c))
            # Simple flat runway centre markings, over the supplied mesh.
            for dz in range(-800,801,100):
                quad=np.array([[-2,RUNWAY_Y+.12,z+dz],[2,RUNWAY_Y+.12,z+dz],
                               [2,RUNWAY_Y+.12,z+dz+40],[-2,RUNWAY_Y+.12,z+dz+40]],dtype='f4')
                positions=quad[[0,1,2,0,2,3]]
                pieces.append((positions,np.tile([0,1,0],(6,1)),np.tile([.9,.9,.85],(6,1))))
        return tuple(np.concatenate([v[i] for v in pieces]).astype('f4') for i in range(3))

    def sync(self,atmosphere):
        network=self.game.network
        if not network:
            atmosphere.race_frozen=True
            return
        data=network.race
        if not data:
            return
        self.snapshot=data
        self.local=next((p for p in data['players'] if p['id']==network.player_id),None)
        phase=data['phase']
        if data['round']!=self.round_id and self.local and 'spawn' in self.local:
            self.round_id=data['round']
            self.game.reset_flight()
            spawn=self.local['spawn']
            atmosphere.position=np.array([spawn['x'],spawn['z']])
            atmosphere.altitude=spawn['y']
            atmosphere.speed=0
            self.ready=False
            self.fuel_credit=0
            atmosphere.temperature_f=None
            atmosphere.hour=9
            atmosphere.cycle_paused=True
            atmosphere.weather_label='MAP REVEALS AT GO'
            atmosphere.wind=atmosphere.precipitation=atmosphere.storm=0
            atmosphere.cover=.35
        env=data.get('environment')
        if env:
            atmosphere.hour=env['hour']
            atmosphere.cycle_paused=True
            atmosphere.temperature_f=env.get('temperature_f',None)
            atmosphere.temperature_reference_altitude=RUNWAY_Y
            atmosphere.weather_condition=env.get('condition','')
            for key in ('cover','wind','wind_angle','precipitation','storm'):
                setattr(atmosphere,key,env[key])
            atmosphere.weather_label=('LIVE WEATHER ' if env['live'] else 'WEATHER UNAVAILABLE ')+env['label']
        else:
            atmosphere.temperature_f=None
            atmosphere.hour=9
            atmosphere.cycle_paused=True
            atmosphere.weather_label='MAP REVEALS AT GO'
            atmosphere.weather_condition=''
            atmosphere.wind=atmosphere.precipitation=atmosphere.storm=0
            atmosphere.cover=.35
        status=self.local['status'] if self.local else 'waiting'
        atmosphere.race_frozen=phase!='racing' or status!='racing' or not network.status.startswith('Connected')
        self.active=phase in ('countdown','racing')
        self.time=max(0,120-data['remaining']) if phase=='racing' else 0
        index=self.local.get('next_gate',0) if self.local else 0
        remaining=data['rings'][index:]
        self.scoring_count=len(remaining)
        collected=self.local.get('collected_fuel',[]) if self.local else []
        remaining=remaining+[r for r in data.get('fuel_rings',[]) if r['id'] not in collected]
        self.rings=[(r['x'],r['y'],r['z'],r['nx'],r['nz']) for r in remaining]
        self.ring_types={ring:r['kind'] for ring,r in zip(self.rings,remaining)}
        credit=self.local.get('fuel_credit',0) if self.local else 0
        if credit>self.fuel_credit:
            gained=credit-self.fuel_credit
            accepted=min(100-atmosphere.fuel,gained)
            atmosphere.fuel=min(100,atmosphere.fuel+gained)
            message=f'FUEL +{accepted/100*atmosphere.FUEL_CAPACITY_GALLONS:.1f} US GAL · NO POINTS' if accepted else 'FUEL FULL · NO POINTS'
            self.game.flash(message,ui.GOOD)
            self.fuel_credit=credit

    def update(self,dt,atmosphere):
        self.sync(atmosphere)

    def target(self):
        if not self.snapshot or self.snapshot['phase']!='racing':
            return None
        if self.active and self.scoring_count:
            return super().target()
        if self.active:
            return 0,RUNWAY_Y,FINISH_Z,'LAND FOR +500'

    def on_crash(self,atmosphere):
        atmosphere.race_frozen=True

    def world_mesh(self,atmosphere):
        gates=super().world_mesh(atmosphere)
        return self.runways if gates is None else tuple(np.concatenate((a,b)) for a,b in zip(gates,self.runways))

    def event(self,event):
        if event.type==pygame.MOUSEWHEEL:
            count=len(self.snapshot['players']) if self.snapshot else 0
            self.scroll=max(0,min(max(0,count-12),self.scroll-event.y))
        if not self.snapshot or self.snapshot['phase']!='lobby':
            return
        clicked=event.type==pygame.MOUSEBUTTONDOWN and event.button==1 and self.ready_rect.collidepoint(self.game.menu.to_hud(event.pos))
        enter=event.type==pygame.KEYDOWN and event.key==pygame.K_RETURN
        if clicked or enter:
            self.ready=not self.ready
            self.game.network.set_ready(self.ready)

    def draw_hud(self,surface,atmosphere,fonts):
        data=self.snapshot
        if not data:
            ui.text(surface,'Connecting to race lobby…',fonts.h1,ui.TEXT,(640,220),'midtop')
            return
        phase=data['phase']
        if phase=='racing':
            if self.local and self.local['status']=='waiting':
                ui.text(surface,'Waiting for the next round',fonts.h1,ui.ACCENT,(640,220),'midtop',shadow=True)
                return
            score=self.local['score'] if self.local else 0
            ui.text(surface,f"{data['remaining']:05.1f}s · {score} POINTS",fonts.h1,ui.TEXT,(640,110),'midtop',shadow=True)
            ui.text(surface,'BLUE +100 · RED +200 · GREEN +5 US GAL',fonts.small,ui.TEXT,(640,154),'midtop',shadow=True)
            ranked=sorted(data['players'],key=lambda p:(p['status']=='disqualified',-p['score']))
            for i,p in enumerate(ranked[self.scroll:self.scroll+8]):
                ui.text(surface,f"{p['name']}  {p['score']}"+(' · DQ' if p['status']=='disqualified' else ''),fonts.small,ui.TEXT,(1240,170+i*24),'topright',shadow=True)
            if self.local and self.local['status']=='disqualified':
                ui.text(surface,'DISQUALIFIED · '+self.local['reason'],fonts.h1,ui.ALERT,(640,220),'midtop',shadow=True)
            elif self.local and self.local['landed']:
                ui.text(surface,'LANDED · +500 POINTS',fonts.h1,ui.ACCENT,(640,220),'midtop',shadow=True)
            return
        ui.panel(surface,(350,100,580,550),(9,18,27,235))
        title={'lobby':'FREE FOR ALL · LOBBY','loading':'Waiting for the match to finalize',
               'countdown':f"STARTING IN {math.ceil(data['remaining'])}",'results':'RACE RESULTS'}[phase]
        ui.text(surface,title,fonts.h2,ui.ACCENT,(640,125),'midtop')
        if phase=='countdown':
            ui.text(surface,'Hold Space to accelerate · W or mouse up to take off',fonts.small,ui.TEXT,(640,168),'midtop')
            ui.text(surface,'Random location reveals at GO',fonts.small,ui.MUTED,(640,552),'midtop')
        elif phase=='lobby':
            ui.text(surface,'At least two pilots · Everyone must be READY',fonts.small,ui.TEXT,(640,168),'midtop')
        elif phase=='results':
            names=[p['name'] for p in data['players'] if p['id'] in data['winners']]
            ui.text(surface,'Winner: '+', '.join(names) if names else 'No eligible finishers',fonts.body,ui.TEXT,(640,168),'midtop')
        pilots=sorted(data['players'],key=lambda p:(p['status']=='disqualified',-p['score'])) if phase=='results' else data['players']
        for i,p in enumerate(pilots[self.scroll:self.scroll+12]):
            status=('READY' if p['ready'] else 'Not ready') if phase=='lobby' else f"{p['score']} · {p['status']}"
            ui.text(surface,p['name'],fonts.body,ui.TEXT,(380,210+i*27))
            ui.text(surface,status,fonts.small,ui.ACCENT if p['ready'] else ui.MUTED,(900,210+i*27),'topright')
        if phase=='lobby':
            pygame.draw.rect(surface,(45,100,120),self.ready_rect,border_radius=7)
            ui.text(surface,'UNREADY' if self.ready else 'READY',fonts.h2,ui.TEXT,self.ready_rect.center,'center')
        env=data.get('environment')
        if env:
            ui.text(surface,env['label']+' · '+env['local_time'],fonts.small,ui.MUTED,(640,636),'midbottom')
