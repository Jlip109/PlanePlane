"""Server-owned FFA course, lobby, scoring and two-minute round lifecycle."""
import math
import random
import time
import uuid

import world
from rewards import podium_reward

RUNWAY_Y = 240.0
START_Z = -4000.0
FINISH_Z = 14000.0
RACE_SECONDS = 120.0
MAX_RACE_SECONDS = 600.0
FINISH_GRACE_SECONDS = 30.0
TARGET_COURSE_SPEED = 300.0
MIN_RING_SPACING = 900.0
COUNTDOWN_SECONDS = 5.0
LANDING_BONUS = 500
FUEL_RING_REFILL = 25.0
AREA_RANGE = 1800.0


def runway_at(x, z):
    return world.on_runway(x,z)


def spawn_for(slot):
    return dict(x=((slot%10)-4.5)*16, y=RUNWAY_Y+3, z=START_Z-650+(slot//10)*45)


def course(seed):
    rng = random.Random(seed)
    count = 401
    mirror = rng.choice((-1,1))
    phase = rng.uniform(-.4,.4)
    frequency = rng.uniform(1.85,2.15)
    points=[]
    for index in range(count):
        t=index/(count-1)
        u=t+.018*math.sin(t*math.tau*3+phase)*math.sin(math.pi*t)
        x=mirror*math.sin(u*math.tau*frequency)*math.sin(math.pi*u)
        z=START_Z+1100+u*(FINISH_Z-START_Z-1800)
        y=max(360,300+4400*math.sin(math.pi*u)**2*(.78+.22*math.sin(u*math.tau+phase)))
        points.append((x,y,z))
    def length(amplitude):
        p=[(0,RUNWAY_Y,START_Z-650)]+[(x*amplitude,y,z) for x,y,z in points]+[(0,RUNWAY_Y,FINISH_Z)]
        return sum(math.dist(a,b) for a,b in zip(p,p[1:]))
    low,high=0.0,8000.0
    for _ in range(32):
        middle=(low+high)/2
        if length(middle)<RACE_SECONDS*TARGET_COURSE_SPEED*1.02:low=middle
        else:high=middle
    path=[(x*high,max(y,world.obstacle_height(x*high,z)+120),z) for x,y,z in points]
    chosen=[path[0]]
    gap=rng.uniform(1000,1400)
    travelled=0.
    for previous,point in zip(path,path[1:-1]):
        travelled+=math.dist(previous,point)
        if travelled>=gap and math.dist(chosen[-1],point)>=MIN_RING_SPACING:
            chosen.append(point)
            travelled=0.
            gap=rng.uniform(1000,1400)
    while len(chosen)>1 and math.dist(chosen[-1],path[-1])<MIN_RING_SPACING:
        chosen.pop()
    chosen.append(path[-1])
    rings=[]
    for index,(x,y,z) in enumerate(chosen):
        kind='red' if index%2 else 'blue'
        rings.append(dict(x=x,y=y,z=z,radius=105 if kind=='blue' else 45,kind=kind))
    for i,ring in enumerate(rings):
        previous = rings[i-1] if i else dict(x=0,y=RUNWAY_Y,z=START_Z)
        length = math.hypot(ring['x']-previous['x'],ring['z']-previous['z'])
        ring['nx'] = (ring['x']-previous['x'])/length
        ring['nz'] = (ring['z']-previous['z'])/length
    return rings


def path_distance(state, rings):
    points = [(0,RUNWAY_Y,START_Z-900)] + [(r['x'],r['y'],r['z']) for r in rings] + [(0,RUNWAY_Y,FINISH_Z+900)]
    best = float('inf')
    p = (state['x'],state['y'],state['z'])
    for a,b in zip(points,points[1:]):
        d = [b[i]-a[i] for i in range(3)]
        t = max(0,min(1,sum((p[i]-a[i])*d[i] for i in range(3))/sum(v*v for v in d)))
        best = min(best,math.sqrt(sum((p[i]-a[i]-t*d[i])**2 for i in range(3))))
    return best


def fuel_course(rings):
    result=[]
    for index in range(1,len(rings)-1,3):
        a,b=rings[index:index+2]
        for offset in (340,540,740):
            offset *= -1 if index%2 else 1
            x=(a['x']+b['x'])/2+b['nz']*offset
            z=(a['z']+b['z'])/2-b['nx']*offset
            y=max((a['y']+b['y'])/2+90,world.obstacle_height(x,z)+140)
            if 180<path_distance(dict(x=x,y=y,z=z),rings)<AREA_RANGE-150:
                result.append(dict(id=f'fuel-{index}',x=x,y=y,z=z,nx=b['nx'],nz=b['nz'],radius=60,kind='fuel'))
                break
    return result


def ring_crossing(previous,current,ring,angle):
    side=lambda s:(s['x']-ring['x'])*ring['nx']+(s['z']-ring['z'])*ring['nz']
    a,b=side(previous),side(current)
    if not a<0<=b:
        return None
    t=-a/(b-a)
    cross={k:previous[k]+t*(current[k]-previous[k]) for k in ('x','y','z')}
    h=(cross['x']-ring['x'])*ring['nz']-(cross['z']-ring['z'])*ring['nx']
    v=cross['y']-ring['y']
    apothem=(70-3)*ring['radius']/70*math.cos(math.pi/10)
    return all(h*math.cos((i+.5)*math.tau/10+angle)+v*math.sin((i+.5)*math.tau/10+angle)<=apothem for i in range(10))


def touches_finish(previous, current):
    """Surface contact, including crossing the runway between network updates."""
    bounds={'x':(-90.,90.),'y':(RUNWAY_Y-2,RUNWAY_Y+5),'z':(FINISH_Z-900,FINISH_Z+900)}
    if all(low<=current[key]<=high for key,(low,high) in bounds.items()):return True
    if previous is None:return False
    entry,exit=0.,1.
    for key,(low,high) in bounds.items():
        start=previous[key];delta=current[key]-start
        if abs(delta)<1e-9:
            if not low<=start<=high:return False
        else:
            a,b=sorted(((low-start)/delta,(high-start)/delta))
            entry=max(entry,a);exit=min(exit,b)
            if entry>exit:return False
    return True


class RaceRoom:
    def __init__(self, seed=1, clock=time.monotonic):
        self.clock = clock
        self.seed = seed
        self.round = 0
        self.phase = 'lobby'
        self.deadline = 0
        self.members = {}
        self.rings = course(seed)
        self.fuel_rings = fuel_course(self.rings)
        self.environment = None
        self.winners = []
        self.started_at = None
        self.first_finish_at = None
        self.practice = False
        self.records = []
        self.room_id=uuid.uuid4().hex[:12]
        self.pending_players=set()
        self.ended_at=None

    def join(self, player_id, name):
        self.members[player_id] = dict(id=player_id,name=name,ready=False,connected=True,
                                      score=0,next_gate=0,status='waiting',reason='',landed=False,previous=None,
                                      fuel_credit=0,collected_fuel=[],finish_time=None,place=None,recorded=False,
                                      race_time=None,medal=None,podium_bonus=0,participated=False)

    def leave(self, player_id):
        player = self.members.get(player_id)
        if not player:
            return
        player['connected'] = False
        if self.phase in ('countdown','racing','results') and not player.get('participated',False):
            self.members.pop(player_id,None)
            return
        if self.phase in ('countdown','racing') and player['status']=='racing':
            self.disqualify(player,'Left the match')
        elif self.phase in ('lobby','loading'):
            self.members.pop(player_id,None)
            if self.phase=='loading' and player_id in self.pending_players:self.phase='lobby'
        self.pending_players.discard(player_id)

    def ready(self, player_id, value):
        if self.phase != 'lobby' or player_id not in self.members:
            return
        self.members[player_id]['ready'] = bool(value)
        pilots = [p for p in self.members.values() if p['connected']]
        if pilots and all(p['ready'] for p in pilots):
            self.pending_players={p['id'] for p in pilots}
            self.phase = 'loading'

    def prepared(self, environment):
        if self.phase != 'loading':
            return
        self.round += 1
        self.rings = course(self.seed+self.round)
        self.fuel_rings = fuel_course(self.rings)
        self.environment = environment
        self.winners = []
        self.started_at = self.first_finish_at = self.ended_at = None
        participants=[p for p in self.members.values() if p['connected'] and p['id'] in self.pending_players]
        self.practice = len(participants)==1
        for index,p in enumerate(participants):
            p.update(status='racing',score=0,next_gate=0,reason='',landed=False,previous=None,
                     spawn=spawn_for(index),ready=False,fuel_credit=0,collected_fuel=[],
                     finish_time=None,place=None,recorded=False,race_time=None,
                     medal=None,podium_bonus=0,participated=True)
        self.phase = 'countdown'
        self.deadline = self.clock()+COUNTDOWN_SECONDS

    def disqualify(self, player, reason):
        elapsed=max(0,self.clock()-self.started_at) if self.started_at is not None else None
        player.update(status='disqualified',reason=reason,race_time=elapsed)

    def receive(self, player_id, state):
        self.tick()
        p = self.members.get(player_id)
        if not p or self.phase != 'racing' or p['status']!='racing':
            return
        previous = p['previous']
        if not state.get('left_match') and touches_finish(previous,state):
            if state['speed']<=55 and abs(state['bank'])<.3 and abs(state['flight_pitch'])<.3:
                p['score']+=LANDING_BONUS
            self.finish_player(p)
            return
        if state.get('crashed'):
            self.disqualify(p,'Crashed')
            return
        if state.get('left_match'):
            self.disqualify(p,'Left the match')
            return
        if path_distance(state,self.rings)>AREA_RANGE:
            self.disqualify(p,'Left the race area')
            return
        floor = world.obstacle_height(state['x'],state['z'])
        if state['y'] <= floor+1.5 and not runway_at(state['x'],state['z']):
            self.disqualify(p,'Crashed')
            return
        p['previous'] = dict(state)
        index = p['next_gate']
        if previous and index<len(self.rings):
            ring = self.rings[index]
            angle = (self.clock()-self.started_at)*.35+(ring['x']+ring['z'])*.0001
            inside=ring_crossing(previous,state,ring,angle)
            if inside is not None:
                if inside:
                    p['score'] += 200 if ring['kind']=='red' else 100
                p['next_gate'] += 1
        if previous:
            for ring in self.fuel_rings:
                if ring['id'] in p['collected_fuel']:
                    continue
                angle=(self.clock()-self.started_at)*.35+(ring['x']+ring['z'])*.0001
                if ring_crossing(previous,state,ring,angle):
                    p['collected_fuel'].append(ring['id'])
                    p['fuel_credit']+=FUEL_RING_REFILL

    def finish_player(self, player):
        if player['status']!='racing':return
        now=self.clock()
        place=1+sum(p['status']=='finished' for p in self.members.values())
        reward=podium_reward(place,self.practice)
        player.update(landed=True,status='finished',finish_time=max(0,now-self.started_at),
                      place=place,recorded=not self.practice,medal=reward['medal'],
                      podium_bonus=reward['bonus'],race_time=max(0,now-self.started_at))
        player['score']+=reward['bonus']
        if self.first_finish_at is None:
            self.first_finish_at=now
            self.deadline=now+FINISH_GRACE_SECONDS
        if not self.practice:
            self.records.append(dict(name=player['name'],score=player['score'],time=player['finish_time'],round=self.round,
                                     medal=player['medal'],podium_bonus=player['podium_bonus']))
            self.records=self.records[-240:]

    def complete(self):
        finishers=sorted((p for p in self.members.values() if p['status']=='finished'),key=lambda p:p['place'])
        self.winners=[finishers[0]['id']] if finishers and not self.practice else []
        self.phase='results'
        self.ended_at=self.clock()
        self.deadline=self.ended_at+15

    def tick(self):
        now = self.clock()
        if self.phase=='countdown' and now>=self.deadline:
            self.phase = 'racing'
            self.started_at=now
            self.deadline = now+MAX_RACE_SECONDS
        elif self.phase=='racing':
            if now>=self.deadline:
                for p in self.members.values():
                    if p['status']=='racing':self.disqualify(p,'Did not finish in time')
                self.complete()
            elif not any(p['status']=='racing' for p in self.members.values()):
                self.complete()
        elif self.phase=='results' and now>=self.deadline:
            self.members = {k:p for k,p in self.members.items() if p['connected']}
            for p in self.members.values():
                p.update(ready=False,status='waiting',previous=None)
            self.phase = 'lobby'

    def snapshot(self):
        revealed=self.phase in ('racing','results')
        now=self.ended_at if self.ended_at is not None else self.clock()
        elapsed=max(0,now-self.started_at) if self.started_at is not None else 0.0
        return dict(phase=self.phase,round=self.round,remaining=max(0,self.deadline-self.clock()),
                    race_id=f'{self.room_id}-{self.round}',
                    elapsed=elapsed,practice=self.practice,
                    finish_cutoff=max(0,self.deadline-self.clock()) if self.first_finish_at is not None else None,
                    rings=self.rings if revealed else [],fuel_rings=self.fuel_rings if revealed else [],
                    environment=self.environment if revealed else None,winners=self.winners,
                    players=[{k:v for k,v in p.items() if k!='previous'} for p in self.members.values()])
