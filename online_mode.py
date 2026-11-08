"""Client presentation of a server-owned Free for All race."""
import math
from pathlib import Path

import numpy as np
import pygame

import ui
from modes import RingRun
from race import START_Z,FINISH_Z,RUNWAY_Y
from rewards import PODIUM


class OnlineRace(RingRun):
    name = 'Free for All'
    key = 'ffa'
    description = 'Twisting high-altitude race. First finisher wins; everyone else has 30 seconds to finish.'

    def __init__(self,game,seed=None):
        super().__init__(game,seed)
        self.round_id = -1
        self.snapshot = None
        self.local = None
        self.ready = False
        self.fuel_credit = 0
        self.scoring_count = 0
        self.lobby_intent = None
        self.lobby_areas = []
        self.leave_rect=pygame.Rect(500,625,280,28)
        self.last_record=None
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
        self.game.set_online_tuning(self.key=='ffa')
        network=self.game.network
        if not network:
            atmosphere.race_frozen=True
            atmosphere.finish_rollout=False
            return
        data=network.race
        if not data:
            self.snapshot=self.local=None
            self.active=False
            self.rings=[]
            self.ring_types={}
            self.ready=False
            atmosphere.race_frozen=True
            atmosphere.finish_rollout=False
            return
        self.snapshot=data
        self.local=next((p for p in data['players'] if p['id']==network.player_id),None)
        phase=data['phase']
        identity=data.get('race_id',(getattr(network,'lobby_id',1),data['round']))
        if identity!=self.round_id and self.local and 'spawn' in self.local:
            self.round_id=identity
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
            atmosphere.weather_label='OFFLINE PRACTICE' if env.get('offline') else ('LIVE WEATHER ' if env['live'] else 'WEATHER UNAVAILABLE ')+env['label']
        else:
            atmosphere.temperature_f=None
            atmosphere.hour=9
            atmosphere.cycle_paused=True
            atmosphere.weather_label='MAP REVEALS AT GO'
            atmosphere.weather_condition=''
            atmosphere.wind=atmosphere.precipitation=atmosphere.storm=0
            atmosphere.cover=.35
        status=self.local['status'] if self.local else 'waiting'
        atmosphere.finish_rollout=status=='finished' and phase in ('racing','results') and network.status.startswith('Connected')
        atmosphere.race_frozen=phase!='racing' or status!='racing' or not network.status.startswith('Connected')
        self.active=phase in ('countdown','racing')
        self.time=data.get('elapsed',0) if phase=='racing' else 0
        if self.local and self.local['status']=='finished' and not data.get('practice',False) and self.last_record!=identity:
            self.game.scores.best('ffa_best_score',self.local['score'])
            self.game.scores.claim_podium(identity,self.local.get('medal'))
            finish_time=self.local['finish_time']
            best=self.game.scores.get('ffa_best_time',0.0)
            if not best or finish_time<best:
                self.game.scores.data['ffa_best_time']=float(finish_time)
                self.game.scores.save()
            self.last_record=identity
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
            return 0,RUNWAY_Y,FINISH_Z,'FINISH RUNWAY'

    def on_crash(self,atmosphere):
        atmosphere.race_frozen=True

    def world_mesh(self,atmosphere):
        gates=super().world_mesh(atmosphere)
        return self.runways if gates is None else tuple(np.concatenate((a,b)) for a,b in zip(gates,self.runways))

    def event(self,event):
        if event.type==pygame.MOUSEWHEEL:
            count=len(self.snapshot['players']) if self.snapshot else 0
            self.scroll=max(0,min(max(0,count-12),self.scroll-event.y))
        if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
            point=self.game.menu.to_hud(event.pos)
            if not self.snapshot:
                if pygame.Rect(370,150,250,42).collidepoint(point):self.lobby_intent='create'
                if pygame.Rect(660,150,250,42).collidepoint(point):self.lobby_intent='join'
                for rect,action,lobby in self.lobby_areas:
                    if rect.collidepoint(point):self.game.network.select_lobby(action,lobby)
            elif self.snapshot['phase']=='lobby' and self.leave_rect.collidepoint(point):
                self.game.network.select_lobby('leave')
                return
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
            self.draw_browser(surface,fonts)
            return
        phase=data['phase']
        if phase=='results':
            self.draw_results(surface,fonts,data)
            return
        if self.local and self.local['status']=='finished':
            self.draw_finished(surface,fonts,data)
            return
        if phase=='racing':
            if self.local and self.local['status']=='waiting':
                ui.text(surface,'Waiting for the next round',fonts.h1,ui.ACCENT,(640,220),'midtop',shadow=True)
                return
            score=self.local['score'] if self.local else 0
            ui.text(surface,f"TIME {data.get('elapsed',0):06.2f}s · {score} POINTS",fonts.h1,ui.TEXT,(640,110),'midtop',shadow=True)
            ui.text(surface,'BLUE +100 · RED +200 · GREEN +5 US GAL',fonts.small,ui.TEXT,(640,154),'midtop',shadow=True)
            cutoff=data.get('finish_cutoff')
            if cutoff is not None:
                ui.text(surface,f'FINISH WITHIN {cutoff:04.1f}s OR BE DISQUALIFIED',fonts.h2,ui.ALERT,(640,190),'midtop',shadow=True)
            if data.get('practice'):
                ui.text(surface,'PRACTICE · SCORES NOT RECORDED',fonts.small,ui.ACCENT,(640,76),'midtop',shadow=True)
            ranked=sorted(data['players'],key=lambda p:(p['status']=='disqualified',p.get('place') or 999,-p['next_gate']))
            for i,p in enumerate(ranked[self.scroll:self.scroll+8]):
                text=f"{p['name']} · {p['next_gate']}/{len(data['rings'])}"
                if p['status']=='finished':text=f"{p['place']}. {p['name']} · {p['finish_time']:.2f}s"
                elif p['status']=='disqualified':text=f"{p['name']} · DQ"
                ui.text(surface,text,fonts.small,ui.TEXT,(1240,170+i*24),'topright',shadow=True)
            if self.local and self.local['status']=='disqualified':
                ui.text(surface,'DISQUALIFIED · '+self.local['reason'],fonts.h1,ui.ALERT,(640,220),'midtop',shadow=True)
            elif self.local and self.local['landed']:
                ui.text(surface,'LANDED · +500 POINTS',fonts.h1,ui.ACCENT,(640,220),'midtop',shadow=True)
            return
        ui.panel(surface,(350,100,580,550),(9,18,27,235))
        title={'lobby':'FREE FOR ALL · LOBBY','loading':'Waiting for the match to finalize',
               'countdown':f"STARTING IN {math.ceil(data['remaining'])}",'results':'RACE RESULTS'}[phase]
        lobby=getattr(self.game.network,'lobby_id',None)
        if phase=='lobby':title=f'LOBBY {lobby or 1} · FREE FOR ALL'
        ui.text(surface,title,fonts.h2,ui.ACCENT,(640,125),'midtop')
        if phase=='countdown':
            ui.text(surface,'Hold Space to accelerate · W or mouse up to take off',fonts.small,ui.TEXT,(640,168),'midtop')
            ui.text(surface,'Random location reveals at GO',fonts.small,ui.MUTED,(640,552),'midtop')
        elif phase=='lobby':
            count=sum(p['connected'] for p in data['players'])
            hint='Solo practice · Scores will not be recorded' if count==1 else f'{count}/24 racers · Everyone must be READY'
            ui.text(surface,hint,fonts.small,ui.TEXT,(640,168),'midtop')
        elif phase=='results':
            names=[p['name'] for p in data['players'] if p['id'] in data['winners']]
            ui.text(surface,'Winner: '+', '.join(names) if names else 'No eligible finishers',fonts.body,ui.TEXT,(640,168),'midtop')
        pilots=sorted(data['players'],key=lambda p:(p['status']=='disqualified',p.get('place') or 999)) if phase=='results' else data['players']
        for i,p in enumerate(pilots[self.scroll:self.scroll+12]):
            status=('READY' if p['ready'] else 'Not ready') if phase=='lobby' else f"{p['score']} · {p['status']}"
            ui.text(surface,p['name'],fonts.body,ui.TEXT,(380,210+i*27))
            ui.text(surface,status,fonts.small,ui.ACCENT if p['ready'] else ui.MUTED,(900,210+i*27),'topright')
        if phase=='lobby':
            pygame.draw.rect(surface,(45,100,120),self.ready_rect,border_radius=7)
            label='UNREADY' if self.ready else 'START PRACTICE' if sum(p['connected'] for p in data['players'])==1 else 'READY'
            ui.text(surface,label,fonts.h2,ui.TEXT,self.ready_rect.center,'center')
            ui.text(surface,'BACK TO LOBBIES',fonts.small,ui.MUTED,self.leave_rect.center,'center')
        env=data.get('environment')
        if env:
            ui.text(surface,env['label']+' · '+env['local_time'],fonts.small,ui.MUTED,(640,636),'midbottom')

    def draw_browser(self,surface,fonts):
        self.lobby_areas=[]
        ui.panel(surface,(330,95,620,540),(9,18,27,240))
        ui.text(surface,'ONLINE LOBBIES',fonts.h1,ui.ACCENT,(640,112),'midtop')
        for rect,intent,label in ((pygame.Rect(370,150,250,42),'create','CREATE LOBBY'),(pygame.Rect(660,150,250,42),'join','JOIN LOBBY')):
            pygame.draw.rect(surface,(45,94,124) if self.lobby_intent==intent else (28,45,60),rect,border_radius=6)
            ui.text(surface,label,fonts.body,ui.TEXT,rect.center,'center')
        directory=getattr(self.game.network,'lobbies',[]) if self.game.network else []
        for index,item in enumerate(directory):
            rect=pygame.Rect(370,215+index*105,540,88)
            ui.panel(surface,rect,(24,40,54,245))
            ui.text(surface,item['name'],fonts.h2,ui.TEXT,(390,rect.top+12))
            detail=f"{item['count']}/24 racers · {item['phase']}" if item['exists'] else 'Available to create'
            ui.text(surface,detail,fonts.small,ui.MUTED,(390,rect.top+49))
            action='join' if item['exists'] else 'create'
            allowed=item['count']<24 and (self.lobby_intent in (None,action))
            label='FULL' if item['count']>=24 else action.upper()
            button=pygame.Rect(780,rect.top+22,110,42)
            pygame.draw.rect(surface,(45,100,120) if allowed else (45,50,55),button,border_radius=5)
            ui.text(surface,label,fonts.body,ui.TEXT if allowed else ui.DIM,button.center,'center')
            if allowed:self.lobby_areas.append((button,action,item['id']))
        error=getattr(self.game.network,'lobby_error','') if self.game.network else 'Connecting…'
        ui.text(surface,error or 'Solo practice is available in every lobby.',fonts.small,ui.ALERT if error else ui.MUTED,(640,570),'midtop')

    def draw_finished(self,surface,fonts,data):
        p=self.local
        ui.panel(surface,(350,140,580,410),(9,18,27,240))
        ui.text(surface,'FINISHED',fonts.display,ui.ACCENT,(640,170),'midtop')
        ui.text(surface,f"{p['finish_time']:.2f} SECONDS",fonts.h1,ui.TEXT,(640,255),'midtop')
        label='PRACTICE · SCORES NOT RECORDED' if data.get('practice') else f"PLACE {p['place']} · {p['score']} POINTS"
        ui.text(surface,label,fonts.h2,ui.TEXT,(640,325),'midtop')
        reward=PODIUM.get(p.get('place')) if p.get('medal') else None
        if reward:
            ui.text(surface,f"{reward['label'].upper()} MEDAL · +{p['podium_bonus']:,} PODIUM BONUS",fonts.body,reward['color'],(640,360),'midtop')
        if data['phase']=='racing':
            message=f"Other racers have {data.get('finish_cutoff',0):.1f}s to finish"
        else:message=f"Returning to lobby in {data['remaining']:.0f}s"
        if getattr(self.game.network,'offline',False):message='Esc → Restart to practise again'
        ui.text(surface,message,fonts.body,ui.MUTED,(640,395),'midtop')
        ui.text(surface,'E brakes · Runway contact is always safe',fonts.small,ui.MUTED,(640,480),'midtop')

    def draw_results(self,surface,fonts,data):
        """One screen for all 24 original participants, including DNF racers."""
        ui.panel(surface,(120,76,1040,612),(9,18,27,245))
        title='PRACTICE RESULTS' if data.get('practice') else 'RACE RESULTS'
        if self.local and self.local['status']=='finished':title='FINISHED · '+title
        ui.text(surface,title,fonts.h1,ui.ACCENT,(640,92),'midtop')
        for label,x,anchor in (('#',145,'topleft'),('PILOT',205,'topleft'),('TIME',735,'topright'),('SCORE',900,'topright'),('RESULT / REWARD',1135,'topright')):
            ui.label(surface,label,fonts.tiny,(x,149),ui.MUTED,anchor)
        pilots=[p for p in data['players'] if p.get('participated',p['status']!='waiting')]
        pilots.sort(key=lambda p:(p['status']!='finished',p.get('place') or 999,p.get('race_time') or 0))
        for index,p in enumerate(pilots[:24]):
            y=175+index*20
            reward=PODIUM.get(p.get('place')) if p.get('medal') else None
            color=reward['color'] if reward else ui.TEXT
            if reward:
                tint=tuple(15+int(channel*.12) for channel in color)
                pygame.draw.rect(surface,(*tint,255),(135,y-1,1010,20),border_radius=3)
            position=str(p['place']) if p.get('place') else '—'
            elapsed=p.get('finish_time') if p['status']=='finished' else p.get('race_time')
            time_text=f'{elapsed:.2f}s' if elapsed is not None else '—'
            result='FINISHED'
            if reward:result=f"{reward['label'].upper()} +{p['podium_bonus']:,}"
            elif p['status']=='disqualified':result='DNF · '+p.get('reason','Disqualified')
            elif p['status']!='finished':result=p['status'].upper()
            ui.text(surface,position,fonts.mono_small,color,(145,y))
            ui.text(surface,p['name'],fonts.mono_small,color,(205,y))
            ui.text(surface,time_text,fonts.mono_small,ui.TEXT,(735,y),'topright')
            ui.text(surface,f"{p['score']:,}",fonts.mono_small,ui.TEXT,(900,y),'topright')
            ui.text(surface,result,fonts.tiny,color if reward else ui.MUTED,(1135,y),'topright')
        ui.text(surface,'Scores include bonuses. DNF times show elapsed time before disqualification.',fonts.tiny,ui.MUTED,(145,667))
        footer='Esc → Restart' if getattr(self.game.network,'offline',False) else f"Lobby in {data['remaining']:.0f}s"
        ui.text(surface,footer,fonts.tiny,ui.ACCENT,(1135,667),'topright')
