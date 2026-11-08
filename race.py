"""Multiplayer Ring Race: the seeded gate course and the server-side race director.

No pygame here, so the online server (requirements-server.txt) can run it. Every client builds the
same course from the round seed the server sends; the server runs the round cycle
waiting -> countdown -> racing -> results -> countdown ... and is authoritative on progress and times.
"""

import math
import random

import numpy as np

import world
from units import MAX_FLIGHT_SPEED_MPS

GATES = 12
RADIUS = 70.0
SPACING = 760.0
START = (0.0, 700.0, -900.0, 0.0)  # x, altitude, z, heading of the start line (the game's spawn)
COUNTDOWN = 5.0
RESULTS = 12.0
RACE_LIMIT = 300.0
FINISH_GRACE = 45.0
GATE_REACH = 400.0  # a reported pass must come from within this distance of the gate centre
FINISH_SLACK = 1.0  # how much earlier than the server heard it a client may say it finished
PHASES = ('waiting', 'countdown', 'racing', 'results')


def next_gate(cursor, rng, first=False):
    """Advance a (x, y, z, heading) cursor one gate along a course; returns (cursor, ring)."""
    x, y, z, heading = cursor
    if not first:
        heading += rng.uniform(-0.4, 0.4)
        y += rng.uniform(-130, 130)
    x += math.sin(heading) * SPACING
    z += math.cos(heading) * SPACING
    # Keep every gate above the highest terrain under its opening.
    reach = range(-112, 113, 28)
    clearance = max(world.obstacle_height(x + dx, z + dz) for dx in reach for dz in reach) + RADIUS + 40
    y = float(np.clip(y, max(clearance, 300), 2600))
    return (x, y, z, heading), (x, y, z, math.sin(heading), math.cos(heading))


def course(seed, gates=GATES):
    """The race gates (x, y, z, nx, nz) for a round seed: identical on every machine."""
    rng = np.random.default_rng(seed)
    cursor, rings = START, []
    for index in range(gates):
        cursor, ring = next_gate(cursor, rng, first=index == 0)
        rings.append(ring)
    return rings


def minimum_times(rings):
    """Fastest physically possible arrival at each gate: straight lines at the Mach 5 limit."""
    point, distance, times = START[:3], 0.0, []
    for ring in rings:
        distance += math.dist(point, ring[:3])
        point = ring[:3]
        times.append(distance / MAX_FLIGHT_SPEED_MPS)
    return times


def grid_slot(slot):
    """Starting-grid position (x, altitude, z, heading): rows of four behind the start line."""
    row, column = divmod(slot, 4)
    return START[0] + (column - 1.5) * 36, START[1] + row * 6, START[2] - 70 - row * 50, START[3]


def ordinal(place):
    suffix = 'th' if 10 <= place % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(place % 10, 'th')
    return f'{place}{suffix}'


class RaceDirector:
    """Server-side round cycle. Call tick() regularly and report() with each validated state."""

    def __init__(self, seed=1, countdown=COUNTDOWN, results=RESULTS, limit=RACE_LIMIT, grace=FINISH_GRACE,
                 gates=GATES):
        self.random = random.Random(seed)
        self.countdown, self.results, self.limit, self.grace, self.gates = countdown, results, limit, grace, gates
        self.phase = 'waiting'
        self.round = 0
        self.seed = 0
        self.start = self.ends = 0.0
        self.rings = []
        self.min_times = []
        self.racers = {}
        self.rejected = 0

    # ------------------------------------------------------------------ cycle

    def tick(self, now, peers):
        """peers: {player_id: (name, wants_to_race)} for everyone currently connected."""
        for player_id, racer in self.racers.items():
            if player_id in peers:
                racer['name'] = peers[player_id][0]
        wanting = [player_id for player_id, (_, racing) in peers.items() if racing]
        if self.phase == 'countdown':
            for player_id in list(self.racers):
                if not peers.get(player_id, ('', False))[1]:
                    del self.racers[player_id]
            for player_id in wanting:
                if player_id not in self.racers:
                    self.add_racer(player_id, peers[player_id][0])
            if not self.racers:
                self.phase = 'waiting'
            elif now >= self.start:
                self.phase = 'racing'
        elif self.phase == 'racing':
            for player_id, racer in self.racers.items():
                if racer['finish'] is None and not peers.get(player_id, ('', False))[1]:
                    racer['left'] = True
            active = [r for r in self.racers.values() if r['finish'] is None and not r['left']]
            finishes = [r['finish'] for r in self.racers.values() if r['finish'] is not None]
            if (not active or now >= self.start + self.limit
                    or (finishes and now >= self.start + min(finishes) + self.grace)):
                self.phase = 'results'
                self.ends = now + self.results
        elif self.phase == 'results' and now >= self.ends:
            self.phase = 'waiting'
        if self.phase == 'waiting' and wanting:
            self.begin(now, {player_id: peers[player_id][0] for player_id in wanting})

    def begin(self, now, names):
        self.round += 1
        self.seed = self.random.randrange(1, 2**31)
        self.rings = course(self.seed, self.gates)
        self.min_times = minimum_times(self.rings)
        self.phase = 'countdown'
        self.start = now + self.countdown
        self.ends = self.start + self.limit
        self.racers = {}
        for player_id, name in names.items():
            self.add_racer(player_id, name)

    def add_racer(self, player_id, name):
        used = {racer['slot'] for racer in self.racers.values()}
        slot = next(index for index in range(len(used) + 1) if index not in used)
        self.racers[player_id] = {'name': name, 'slot': slot, 'times': [], 'finish': None, 'left': False}

    def remove(self, player_id):
        """A pilot disconnected: drop them before the start, mark them DNF during the race."""
        racer = self.racers.get(player_id)
        if racer is None:
            return
        if self.phase == 'countdown':
            del self.racers[player_id]
        else:
            racer['left'] = True

    # ------------------------------------------------------------------ progress

    def report(self, player_id, state, now):
        """Apply a client's progress claim; returns False when the claim is impossible and ignored."""
        racer = self.racers.get(player_id)
        if (racer is None or self.phase != 'racing' or racer['left'] or racer['finish'] is not None
                or not state.get('racing') or state.get('round') != self.round):
            return True
        gates, passed = state.get('gates', 0), len(racer['times'])
        if gates == passed:
            return True
        elapsed = now - self.start
        ring = self.rings[passed] if passed < len(self.rings) else None
        if (gates != passed + 1 or ring is None or elapsed < self.min_times[passed]
                or math.dist((state['x'], state['y'], state['z']), ring[:3]) > GATE_REACH):
            self.rejected += 1
            return False
        racer['times'].append(elapsed)
        if gates == len(self.rings):
            claimed = state.get('finish')
            plausible = (claimed is not None and self.min_times[-1] <= claimed <= elapsed
                         and claimed >= elapsed - FINISH_SLACK)
            racer['finish'] = claimed if plausible else elapsed
            racer['times'][-1] = racer['finish']
        return True

    def standings(self):
        """Live order: finishers by time, then by gates and when the last gate was reached, then DNFs."""
        def key(item):
            racer = item[1]
            if racer['finish'] is not None:
                return (0, racer['finish'], 0)
            if racer['left']:
                return (2, -len(racer['times']), 0)
            return (1, -len(racer['times']), racer['times'][-1] if racer['times'] else 0.0)
        ordered = sorted(self.racers.items(), key=lambda item: (key(item), item[1]['name'], item[0]))
        leader = ordered[0][1] if ordered else None
        result, previous, place = [], None, 0
        for index, (player_id, racer) in enumerate(ordered):
            rank = key((player_id, racer))
            place = place if rank == previous else index + 1
            previous = rank
            gates = len(racer['times'])
            gap = None
            counted = racer['finish'] is not None or not racer['left']  # finishers keep their gap if they leave
            if racer is not leader and gates and len(leader['times']) >= gates and counted:
                gap = round(racer['times'][gates - 1] - leader['times'][gates - 1], 3)
            status = 'finished' if racer['finish'] is not None else ('dnf' if racer['left'] else 'racing')
            result.append({'id': player_id, 'name': racer['name'], 'place': place, 'gates': gates,
                           'finish': None if racer['finish'] is None else round(racer['finish'], 3),
                           'gap': gap, 'slot': racer['slot'], 'status': status})
        return result

    def snapshot(self, now):
        info = {'phase': self.phase, 'round': self.round, 'seed': self.seed, 'gates': len(self.rings),
                'start': self.start, 'ends': self.ends, 'standings': []}
        if self.phase != 'waiting':
            info['standings'] = self.standings()
        return info
