"""Server-owned FFA course, lobby, scoring and two-minute round lifecycle."""
import math
import random
import time

import world

RUNWAY_Y = 240.0
START_Z = -4000.0
FINISH_Z = 14000.0
RACE_SECONDS = 120.0
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
    rings = []
    z = START_Z+1400
    index = 0
    while z < FINISH_Z-1500:
        x = math.sin(index*.62)*1500
        y = 500 + 260*math.sin(index*.73) + rng.uniform(-70,70)
        y = max(y,world.obstacle_height(x,z)+180)
        rings.append(dict(x=x,y=y,z=z,radius=105 if index%2==0 else 45,
                          kind='blue' if index%2==0 else 'red'))
        z += rng.uniform(650,1450)
        index += 1
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

    def join(self, player_id, name):
        self.members[player_id] = dict(id=player_id,name=name,ready=False,connected=True,
                                      score=0,next_gate=0,status='waiting',reason='',landed=False,previous=None,
                                      fuel_credit=0,collected_fuel=[])

    def leave(self, player_id):
        player = self.members.get(player_id)
        if not player:
            return
        player['connected'] = False
        if self.phase in ('countdown','racing') and player['status']=='racing':
            self.disqualify(player,'Left the match')
        elif self.phase in ('lobby','loading'):
            self.members.pop(player_id,None)
            self.phase = 'lobby'

    def ready(self, player_id, value):
        if self.phase != 'lobby' or player_id not in self.members:
            return
        self.members[player_id]['ready'] = bool(value)
        pilots = [p for p in self.members.values() if p['connected']]
        if len(pilots)>=2 and all(p['ready'] for p in pilots):
            self.phase = 'loading'

    def prepared(self, environment):
        if self.phase != 'loading':
            return
        self.round += 1
        self.rings = course(self.seed+self.round)
        self.fuel_rings = fuel_course(self.rings)
        self.environment = environment
        self.winners = []
        for index,p in enumerate(p for p in self.members.values() if p['connected']):
            p.update(status='racing',score=0,next_gate=0,reason='',landed=False,previous=None,
                     spawn=spawn_for(index),ready=False,fuel_credit=0,collected_fuel=[])
        self.phase = 'countdown'
        self.deadline = self.clock()+COUNTDOWN_SECONDS

    def disqualify(self, player, reason):
        player.update(status='disqualified',reason=reason)

    def receive(self, player_id, state):
        p = self.members.get(player_id)
        if not p or self.phase != 'racing' or p['status']!='racing':
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
        previous = p['previous']
        p['previous'] = dict(state)
        index = p['next_gate']
        if previous and index<len(self.rings):
            ring = self.rings[index]
            angle = (self.clock()-(self.deadline-RACE_SECONDS))*.35+(ring['x']+ring['z'])*.0001
            inside=ring_crossing(previous,state,ring,angle)
            if inside is not None:
                if inside:
                    p['score'] += 200 if ring['kind']=='red' else 100
                p['next_gate'] += 1
        if previous:
            for ring in self.fuel_rings:
                if ring['id'] in p['collected_fuel']:
                    continue
                angle=(self.clock()-(self.deadline-RACE_SECONDS))*.35+(ring['x']+ring['z'])*.0001
                if ring_crossing(previous,state,ring,angle):
                    p['collected_fuel'].append(ring['id'])
                    p['fuel_credit']+=FUEL_RING_REFILL
        if p['next_gate']==len(self.rings) and abs(state['x'])<=90 and abs(state['z']-FINISH_Z)<=900 and state['y']<=RUNWAY_Y+4:
            if state['speed']<=55 and abs(state['bank'])<.3 and abs(state['flight_pitch'])<.3:
                p.update(score=p['score']+LANDING_BONUS,landed=True,status='finished')

    def tick(self):
        now = self.clock()
        if self.phase=='countdown' and now>=self.deadline:
            self.phase = 'racing'
            self.deadline = now+RACE_SECONDS
        elif self.phase=='racing' and now>=self.deadline:
            eligible = [p for p in self.members.values() if p['status'] in ('racing','finished')]
            top = max((p['score'] for p in eligible),default=None)
            self.winners = [p['id'] for p in eligible if p['score']==top]
            self.phase = 'results'
            self.deadline = now+15
        elif self.phase=='results' and now>=self.deadline:
            self.members = {k:p for k,p in self.members.items() if p['connected']}
            for p in self.members.values():
                p.update(ready=False,status='waiting',previous=None)
            self.phase = 'lobby'

    def snapshot(self):
        revealed=self.phase in ('racing','results')
        return dict(phase=self.phase,round=self.round,remaining=max(0,self.deadline-self.clock()),
                    rings=self.rings if revealed else [],fuel_rings=self.fuel_rings if revealed else [],
                    environment=self.environment if revealed else None,winners=self.winners,
                    players=[{k:v for k,v in p.items() if k!='previous'} for p in self.members.values()])
