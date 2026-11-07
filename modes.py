"""Game modes. Each one gets the shared game context (radio, scores, sounds) and the atmosphere."""

import math

import numpy as np
import pygame

import characters
import ui
import world
from camera import SCREEN_SCALE, project
from units import FEET_PER_METRE, MPH_PER_MPS


def weather_words(atmosphere):
    if atmosphere.storm > 0.5:
        return 'thunderstorms in the area'
    if atmosphere.precipitation > 0.2:
        return 'light rain'
    if atmosphere.cover > 0.8:
        return 'overcast'
    if atmosphere.cover > 0.4:
        return 'broken cloud'
    return 'clear skies'


def plane_point(atmosphere):
    return atmosphere.position[0], atmosphere.altitude, atmosphere.position[1]


class Mode:
    name = ''
    key = ''
    description = ''

    def __init__(self, game):
        self.game = game
        self.finished = False
        self.summary = None
        self.time = 0.0

    def start(self, atmosphere):
        self.finished = False
        self.summary = None
        self.time = 0.0

    def target(self):
        """(x, y, z, label) the HUD should point at, or None."""
        return None

    def update(self, dt, atmosphere):
        self.time += dt

    def on_crash(self, atmosphere):
        pass

    def draw_world(self, surface, atmosphere):
        pass

    def draw_hud(self, surface, atmosphere, fonts):
        pass

    def best_text(self):
        return ''


class FreeFlight(Mode):
    name = 'Free Flight'
    key = 'free'
    description = ('Fly anywhere. Six cities, dozens of villages, weather that changes by the minute. '
                   'Every city’s tower says hello the first time you arrive, and you can refuel at any of them.')

    def start(self, atmosphere):
        super().start(atmosphere)
        self.current_city = world.city_at(atmosphere.position[0], atmosphere.position[1])
        callsign = self.game.pilot.role.title() if hasattr(self.game, 'pilot') else 'pilot'
        hour = atmosphere.hour
        greeting = 'Good morning' if 4 <= hour < 12 else 'Good afternoon' if hour < 18 else 'Good evening'
        nearest, distance = world.nearest_city(*atmosphere.position)
        name = world.CITIES[nearest][0]
        self.game.radio.say(characters.TOWERS[name], f'{greeting}, {callsign}. {name.title()} is '
                                                     f'{distance / 1609.344:.0f} miles out. W and S to climb and descend, A and D '
                                                     'to turn, Space to boost. Press H any time for the rest.')

    def update(self, dt, atmosphere):
        super().update(dt, atmosphere)
        city = world.city_at(atmosphere.position[0], atmosphere.position[1])
        if city is not None and city != self.current_city:
            name = world.CITIES[city][0]
            first = name not in self.game.scores.get('visited', [])
            self.game.scores.add_to_set('visited', name)
            tower = characters.TOWERS[name]
            if first:
                self.game.radio.say(tower, f'{name.title()} here, first time we’ve seen you. '
                                           f'{tower.flavor}')
                visited = len(self.game.scores.get('visited', []))
                if visited == len(world.CITIES):
                    self.game.radio.say(tower, 'That’s all six cities. Every tower in the state knows your callsign now.')
                    self.game.sound('record')
            else:
                self.game.radio.say(tower, f'{name.title()} here. Wind {atmosphere.wind * MPH_PER_MPS:.0f} miles per '
                                           f'hour, {weather_words(atmosphere)}. Fly low over the city to refuel.')
        self.current_city = city

    def best_text(self):
        return f'Cities discovered  {len(self.game.scores.get("visited", []))} / {len(world.CITIES)}'


class RingRun(Mode):
    name = 'Ring Run'
    key = 'rings'
    description = ('Thread the gold gates before the clock runs out. Each gate adds time; '
                   'clear them in a row to build a combo multiplier.')
    RADIUS = 70.0
    SPACING = 760.0
    START_TIME = 30.0
    BONUS = 9.0

    def __init__(self, game, seed=None):
        super().__init__(game)
        self.rng = np.random.default_rng(seed)
        self.rings = []
        self.active = False

    def start(self, atmosphere):
        super().start(atmosphere)
        self.active = True
        self.score = 0
        self.passed = 0
        self.combo = 1
        self.best_combo = 1
        self.time_left = self.START_TIME
        self.rings = []
        self.cursor = (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1], atmosphere.heading)
        self.add_ring(first=True)
        for _ in range(3):
            self.add_ring()
        self.side = self.ring_side(atmosphere, self.rings[0])
        self.game.radio.say(characters.TOWERS['TROY'], 'Course is hot. Gold gate first, white gates after. Go!', urgent=True)

    def add_ring(self, first=False):
        x, y, z, heading = self.cursor
        if not first:
            # Drift toward the nearest city now and then so courses wind over rooftops.
            city, _ = world.nearest_city(x, z)
            to_city = math.atan2(world.CITIES[city][1] - x, world.CITIES[city][2] - z)
            turn = (to_city - heading + math.pi) % math.tau - math.pi
            heading += float(np.clip(turn * 0.25, -0.3, 0.3)) + self.rng.uniform(-0.4, 0.4)
            y += self.rng.uniform(-130, 130)
        x += math.sin(heading) * self.SPACING
        z += math.cos(heading) * self.SPACING
        # Sample every building lot under the gate so even a skinny tower can't spear it.
        reach = range(-112, 113, 28)
        clearance = max(world.obstacle_height(x + dx, z + dz) for dx in reach for dz in reach) + self.RADIUS + 40
        y = float(np.clip(y, max(clearance, 300), 2600))
        self.cursor = (x, y, z, heading)
        self.rings.append((x, y, z, math.sin(heading), math.cos(heading)))

    def ring_side(self, atmosphere, ring):
        x, _, z, nx, nz = ring
        return (atmosphere.position[0] - x) * nx + (atmosphere.position[1] - z) * nz

    def target(self):
        if not self.active:
            return None
        x, y, z, _, _ = self.rings[0]
        return x, y, z, 'GATE'

    def update(self, dt, atmosphere):
        super().update(dt, atmosphere)
        if not self.active:
            return
        self.time_left -= dt
        ring = self.rings[0]
        side = self.ring_side(atmosphere, ring)
        if self.side < 0 <= side:
            x, y, z, _, _ = ring
            offset = math.dist((x, y, z), plane_point(atmosphere))
            if offset < self.RADIUS * 1.1:
                self.score += 100 * self.combo
                self.passed += 1
                self.time_left += self.BONUS
                self.combo = min(self.combo + 1, 5)
                self.best_combo = max(self.best_combo, self.combo)
                self.game.flash(f'+{self.BONUS:.0f}s   ×{self.combo}', ui.ACCENT)
                self.game.sound('ring')
            else:
                self.combo = 1
                self.game.flash('MISSED', ui.ALERT)
                self.game.sound('miss')
            self.rings.pop(0)
            self.add_ring()
            side = self.ring_side(atmosphere, self.rings[0])
        self.side = side
        if self.time_left <= 0:
            self.finish()

    def on_crash(self, atmosphere):
        if self.active:
            self.combo = 1
            self.time_left -= 5

    def finish(self):
        self.active = False
        self.finished = True
        record = self.game.scores.best('ring_best', self.score)
        self.summary = {'title': 'Run complete', 'score': self.score, 'record': record,
                        'lines': [('Gates cleared', f'{self.passed}'), ('Best combo', f'×{self.best_combo}'),
                                  ('Personal best', f'{max(self.score, self.game.scores.get("ring_best")):,}')]}

    def draw_world(self, surface, atmosphere):
        if not self.active:
            return
        size = surface.get_size()
        k = size[1] * SCREEN_SCALE
        for index in reversed(range(len(self.rings))):
            self.draw_ring(surface, atmosphere, self.rings[index], index, size, k)

    def draw_ring(self, surface, atmosphere, ring, index, size, k):
        x, y, z, nx, nz = ring
        center = project(atmosphere, (x, y, z), size)
        if center is None or center[2] > 6000:
            return
        hidden = atmosphere.cloud_cover_between((x, y, z))
        fade = (1 - min(1.0, max(0.0, (center[2] - 2500) / 3500))) * (1 - hidden * 0.85)
        if fade <= 0.02:
            return
        current = index == 0
        alpha = (1.0 if current else 0.5) * fade
        lit = 0.55 + 0.45 * (1 - atmosphere.phase)
        if current:
            band = tuple(int(c * (0.75 + 0.25 * lit)) for c in ui.ACCENT)
        else:
            band = tuple(int(c * lit) for c in (232, 236, 232))
        right = (nz, -nx)

        def ring_points(radius):
            points = []
            for step in range(49):
                angle = step / 48 * math.tau
                px = x + right[0] * math.cos(angle) * radius
                pz = z + right[1] * math.cos(angle) * radius
                points.append(project(atmosphere, (px, y + math.sin(angle) * radius, pz), size))
            return points

        def fill_band(inner, outer, color):
            # Quads between two concentric circles give the gate real perspective thickness.
            for a, b, c, d in zip(inner, inner[1:], outer[1:], outer):
                quad = [a, b, c, d]
                if any(q is None or abs(q[0]) > 20000 or abs(q[1]) > 20000 for q in quad):
                    continue
                pygame.draw.polygon(surface, color, [q[:2] for q in quad])

        fill_band(ring_points(self.RADIUS - 7), ring_points(self.RADIUS + 7), (*band, int(55 * alpha)))
        fill_band(ring_points(self.RADIUS - 2.5), ring_points(self.RADIUS + 2.5), (*band, int(240 * alpha)))
        if current:
            # running lights that chase around the gate
            for light in range(8):
                angle = light / 8 * math.tau + self.time * 1.5
                px = x + right[0] * math.cos(angle) * self.RADIUS
                pz = z + right[1] * math.cos(angle) * self.RADIUS
                spot = project(atmosphere, (px, y + math.sin(angle) * self.RADIUS, pz), size)
                if spot and abs(spot[0]) < 20000 and abs(spot[1]) < 20000:
                    pygame.draw.circle(surface, (255, 246, 220, int(255 * alpha)), spot[:2],
                                       max(2, int(2.2 * k / max(spot[2], 1))))

    def draw_hud(self, surface, atmosphere, fonts):
        if not self.active:
            return
        ui.panel(surface, (520, 100, 240, 62))
        ui.label(surface, 'Time', fonts.tiny, (540, 110))
        warn = ui.ALERT if self.time_left < 8 and int(self.time_left * 4) % 2 else ui.TEXT
        ui.text(surface, f'{max(0.0, self.time_left):04.1f}', fonts.mono, warn, (540, 126))
        ui.label(surface, 'Score', fonts.tiny, (630, 110))
        ui.text(surface, f'{self.score:,}', fonts.mono, ui.TEXT, (630, 126))
        ui.text(surface, f'×{self.combo}', fonts.h2, ui.ACCENT if self.combo > 1 else ui.DIM, (744, 131), 'midright')

    def best_text(self):
        best = self.game.scores.get('ring_best')
        return f'Best score  {best:,}' if best else 'No runs yet'


class SkyCourier(Mode):
    name = 'Sky Courier'
    key = 'courier'
    description = ('Five deliveries, six cities and a lot of people counting on you. Drop below about 1,500 ft '
                   'over a city to pick up or deliver. Faster means bigger tips.')
    JOBS = 5
    ZONE_HEIGHT = 450.0
    HOLD = 1.6

    def __init__(self, game, seed=None):
        super().__init__(game)
        self.rng = np.random.default_rng(seed)
        self.job = None

    def start(self, atmosphere):
        super().start(atmosphere)
        self.score = 0
        self.done = 0
        self.on_time = 0
        self.order = list(self.rng.permutation(len(characters.PASSENGERS)))
        self.hold = 0.0
        self.new_job(atmosphere, world.nearest_city(*atmosphere.position)[0])

    def new_job(self, atmosphere, origin):
        passenger = characters.PASSENGERS[self.order[self.done % len(self.order)]]
        ox, oz = world.CITIES[origin][1], world.CITIES[origin][2]
        options = [i for i in range(len(world.CITIES)) if i != origin]
        distances = [math.hypot(world.CITIES[i][1] - ox, world.CITIES[i][2] - oz) for i in options]
        weights = np.array([1.0 / (1 + (d / 9000) ** 2) for d in distances])
        destination = options[int(self.rng.choice(len(options), p=weights / weights.sum()))]
        leg = math.hypot(world.CITIES[destination][1] - ox, world.CITIES[destination][2] - oz)
        self.job = {'passenger': passenger, 'origin': origin, 'destination': destination, 'stage': 'pickup',
                    'par': leg / 105 + 25, 'clock': 0.0, 'damaged': False}
        tower = characters.TOWERS[world.CITIES[origin][0]]
        self.game.radio.say(tower, f'Courier, we have a pickup in {world.CITIES[origin][0].title()}. '
                                   f'{passenger.name} is waiting.')

    def target(self):
        if not self.job or self.finished:
            return None
        city = world.CITIES[self.job['origin' if self.job['stage'] == 'pickup' else 'destination']]
        return city[1], world.CITY_LEVELS[world.CITIES.index(city)] + 200, city[2], city[0]

    def zone_progress(self, atmosphere, city_index):
        _, cx, cz, radius, _, _ = world.CITIES[city_index]
        inside = math.hypot(atmosphere.position[0] - cx, atmosphere.position[1] - cz) < radius * 0.75
        low = atmosphere.altitude < world.CITY_LEVELS[city_index] + self.ZONE_HEIGHT
        return inside, low

    def update(self, dt, atmosphere):
        super().update(dt, atmosphere)
        if self.finished or not self.job:
            return
        job = self.job
        if job['stage'] == 'deliver':
            job['clock'] += dt
        city = job['origin'] if job['stage'] == 'pickup' else job['destination']
        inside, low = self.zone_progress(atmosphere, city)
        if inside and low and not atmosphere.crashed:
            self.hold += dt
            if self.hold >= self.HOLD:
                self.hold = 0.0
                self.complete_stage(atmosphere)
        else:
            self.hold = max(0.0, self.hold - dt * 2)

    def complete_stage(self, atmosphere):
        job = self.job
        passenger = job['passenger']
        destination = world.CITIES[job['destination']][0].title()
        if job['stage'] == 'pickup':
            job['stage'] = 'deliver'
            self.game.radio.say(passenger, passenger.ask.format(dest=destination), urgent=True)
            self.game.sound('pickup')
            return
        late = job['clock'] > job['par']
        tip = 0 if late else int(400 * (1 - job['clock'] / job['par']))
        earned = (250 if late else 500 + tip) - (150 if job['damaged'] else 0)
        self.score += max(earned, 50)
        self.done += 1
        self.on_time += not late
        self.game.flash(f'+{max(earned, 50)}' + ('   LATE' if late else '   ON TIME'), ui.ALERT if late else ui.GOOD)
        self.game.radio.say(passenger, passenger.thanks if not job['damaged'] else 'Bit of a rough ride, but we made it.',
                            urgent=True)
        self.game.sound('deliver')
        if self.done >= self.JOBS:
            self.finish()
        else:
            self.new_job(atmosphere, job['destination'])

    def on_crash(self, atmosphere):
        if self.job and self.job['stage'] == 'deliver' and not self.job['damaged']:
            self.job['damaged'] = True
            self.game.radio.say(self.job['passenger'], 'Whoa! Please tell me that was the landing gear.')

    def finish(self):
        self.finished = True
        record = self.game.scores.best('courier_best', self.score)
        self.summary = {'title': 'Shift complete', 'score': self.score, 'record': record,
                        'lines': [('Deliveries', f'{self.done}'), ('On time', f'{self.on_time} / {self.done}'),
                                  ('Personal best', f'{max(self.score, self.game.scores.get("courier_best")):,}')]}

    def draw_world(self, surface, atmosphere):
        """A light beam over the target city and the drop-zone circle on the ground."""
        if self.finished or not self.job:
            return
        index = self.job['origin' if self.job['stage'] == 'pickup' else 'destination']
        _, cx, cz, radius, _, _ = world.CITIES[index]
        level = world.CITY_LEVELS[index]
        size = surface.get_size()
        k = size[1] * SCREEN_SCALE
        pulse = 0.75 + 0.25 * math.sin(self.time * 3)
        base = project(atmosphere, (cx, level, cz), size)
        top = project(atmosphere, (cx, level + 900, cz), size)
        if base and top and base[2] < 30000:
            width = max(3, int(40 * k / base[2]))
            fade = 1 - min(1.0, max(0.0, (base[2] - 12000) / 18000))
            for scale, alpha in ((3.0, 40), (1.0, 120)):
                w = width * scale / 2
                pygame.draw.polygon(surface, (*ui.ACCENT, int(alpha * pulse * fade)),
                                    [(base[0] - w, base[1]), (base[0] + w, base[1]),
                                     (top[0] + w * 0.4, top[1]), (top[0] - w * 0.4, top[1])])
        zone = radius * 0.75
        points = []
        for step in range(73):
            angle = step / 72 * math.tau
            points.append(project(atmosphere, (cx + math.cos(angle) * zone, level + 4, cz + math.sin(angle) * zone), size))
        for n, (a, b) in enumerate(zip(points, points[1:])):
            if n % 2 or a is None or b is None or a[2] > 9000:
                continue
            if max(abs(a[0]), abs(a[1]), abs(b[0]), abs(b[1])) > 20000:
                continue
            pygame.draw.line(surface, (*ui.ACCENT, int(200 * pulse)), a[:2], b[:2], max(2, int(6 * k / a[2])))

    def draw_hud(self, surface, atmosphere, fonts):
        if self.finished or not self.job:
            return
        job = self.job
        pickup = job['stage'] == 'pickup'
        city_index = job['origin'] if pickup else job['destination']
        city = world.CITIES[city_index]
        distance = math.hypot(atmosphere.position[0] - city[1], atmosphere.position[1] - city[2])
        box = (24, 150, 300, 132)
        ui.panel(surface, box)
        surface.blit(job['passenger'].portrait(56), (40, 166))
        ui.label(surface, f'Job {self.done + 1} of {self.JOBS}  ·  {"Pick up" if pickup else "Deliver"}',
                 fonts.tiny, (110, 166), ui.ACCENT)
        ui.text(surface, job['passenger'].name, fonts.h2, ui.TEXT, (110, 182))
        ui.text(surface, f'{"at" if pickup else "to"} {city[0].title()}  ·  {ui.format_distance(distance)}',
                fonts.small, ui.MUTED, (110, 212))
        inside, low = self.zone_progress(atmosphere, city_index)
        if inside and not low:
            ceiling = (world.CITY_LEVELS[city_index] + self.ZONE_HEIGHT) * FEET_PER_METRE
            hint, color = f'Descend below {ceiling:,.0f} ft', ui.ACCENT
        elif self.hold > 0:
            hint, color = 'Hold steady…', ui.GOOD
        elif pickup:
            hint, color = 'Fly low over the city center', ui.DIM
        else:
            remaining = job['par'] - job['clock']
            hint = f'Tip clock  {max(0, remaining):.0f}s' if remaining > 0 else 'Running late'
            color = ui.MUTED if remaining > 0 else ui.ALERT
        ui.text(surface, hint, fonts.small, color, (40, 238))
        progress = self.hold / self.HOLD if self.hold > 0 else (
            0 if pickup else max(0.0, 1 - job['clock'] / job['par']))
        ui.bar(surface, (40, 262, 268, 4), progress, ui.GOOD if self.hold > 0 else ui.ACCENT)
        ui.label(surface, 'Earned', fonts.tiny, (1256, 104), anchor='topright', shadow=True)
        ui.text(surface, f'{self.score:,}', fonts.mono, ui.TEXT, (1256, 120), 'topright', shadow=True)

    def best_text(self):
        best = self.game.scores.get('courier_best')
        return f'Best shift  {best:,}' if best else 'No shifts yet'
