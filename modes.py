"""Game modes. Each one gets the shared scores and sound context and the atmosphere."""

import math

import numpy as np
import pygame

import race
import ui
import world
from camera import SCREEN_SCALE, project, project_polygon, view_origin



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

    def progress(self):
        """Race progress to report to the server, or None when this mode is not racing."""
        return None


class FreeFlight(Mode):
    name = 'Free Roam'
    key = 'free'
    description = 'Explore the landscape and clouds at your own pace.'


class RingRun(Mode):
    name = 'Ring Mode'
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
        faces = []
        for i in range(10):
            angles = (i * math.tau / 10, (i+1) * math.tau / 10)
            corners = []
            for depth in (-4,4):
                for radius in (self.RADIUS-3,self.RADIUS+3):
                    corners.append([(math.cos(a)*radius,math.sin(a)*radius,depth) for a in angles])
            inner,outer,inner_back,outer_back = corners
            faces.extend([(inner[0],inner[1],outer[1],outer[0]),
                          (inner_back[0],outer_back[0],outer_back[1],inner_back[1]),
                          (outer[0],outer[1],outer_back[1],outer_back[0]),
                          (inner[0],inner_back[0],inner_back[1],inner[1])])
        self.local_faces = np.asarray(faces,dtype='f4')
        self.local_vertices = self.local_faces[:,[0,1,2,0,2,3],:].reshape(-1,3)
        normals = np.cross(self.local_faces[:,1]-self.local_faces[:,0],self.local_faces[:,2]-self.local_faces[:,0])
        normals /= np.linalg.norm(normals,axis=1,keepdims=True)
        self.local_normals = np.repeat(normals,6,axis=0)

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
        self.previous_position = plane_point(atmosphere)

    def add_ring(self, first=False):
        # Shared with the multiplayer race so both build courses the same way.
        self.cursor, ring = race.next_gate(self.cursor, self.rng, first)
        self.rings.append(ring)

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
            if self.through_gate(atmosphere, ring, side):
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
        self.previous_position = plane_point(atmosphere)
        if self.time_left <= 0:
            self.finish()

    def through_gate(self, atmosphere, ring, side):
        """After the plane crossed a gate's plane this frame: did it pass inside the opening?"""
        x, y, z, nx, nz = ring
        fraction = -self.side / (side - self.side)
        current = np.array(plane_point(atmosphere))
        crossing = np.array(self.previous_position) + fraction * (current - self.previous_position)
        horizontal = (crossing[0] - x) * nz - (crossing[2] - z) * nx
        vertical = crossing[1] - y
        apothem = (self.RADIUS - 3) * math.cos(math.pi / 10)
        return all(horizontal * math.cos((i + 0.5) * math.tau / 10 + self.gate_rotation(ring))
                   + vertical * math.sin((i + 0.5) * math.tau / 10 + self.gate_rotation(ring)) <= apothem for i in range(10))

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

    def gate_rotation(self, ring):
        return self.time * 0.35 + (ring[0] + ring[2]) * 0.0001

    def gate_matrix(self, ring):
        nx,nz = ring[3:]
        angle = self.gate_rotation(ring)
        c,s = math.cos(angle),math.sin(angle)
        return np.array([[nz*c,-nz*s,nx],[s,c,0],[-nx*c,nx*s,nz]],dtype='f4')

    def gate_faces(self, ring):
        return self.local_faces @ self.gate_matrix(ring).T + np.array(ring[:3])

    def world_mesh(self, atmosphere):
        positions, normals, colors = [], [], []
        if not self.active:
            return None
        for index, ring in enumerate(self.rings):
            if math.dist(plane_point(atmosphere), ring[:3]) > 6000:
                continue
            base = np.array(ui.ACCENT if index == 0 else (232,236,232), dtype=float) / 255
            rotation = self.gate_matrix(ring)
            vertices = self.local_vertices @ rotation.T + np.array(ring[:3])
            normal = self.local_normals @ rotation.T
            shade = 0.65 + 0.35 * np.abs(normal @ atmosphere.sun_direction)
            positions.append(vertices)
            normals.append(normal)
            colors.append(base * shade[:,None])
        if not positions:
            return None
        return tuple(np.concatenate(values).astype('f4') for values in (positions, normals, colors))

    def draw_world(self, surface, atmosphere):
        if self.active:
            size = surface.get_size()
            for index in reversed(range(len(self.rings))):
                self.draw_ring(surface, atmosphere, self.rings[index], index, size, size[1] * SCREEN_SCALE)

    def draw_ring(self, surface, atmosphere, ring, index, size, k):
        faces = []
        eye = np.array(view_origin(atmosphere))
        base = np.array(ui.ACCENT if index == 0 else (232,236,232))
        for quad in self.gate_faces(ring):
            points = project_polygon(atmosphere, quad, size)
            if len(points) >= 3:
                distance = float(np.linalg.norm(np.mean(quad, axis=0)-eye))
                faces.append((distance, points))
        for _, points in sorted(faces, key=lambda face: face[0], reverse=True):
            pygame.draw.polygon(surface, tuple(int(v) for v in base), points, 1 if atmosphere.wireframe else 0)

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


def race_clock(seconds):
    seconds = max(0.0, seconds)
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


class RaceMode(RingRun):
    """Online Ring Race: the server runs the rounds, every client flies the same seeded course."""
    name = 'Ring Race'
    key = 'race'
    description = ('Race everyone in the room through the same gold gates. Rounds start on a shared '
                   'countdown; miss a gate and you must turn back for it. First through them all wins.')
    UNCONFIRMED = 2.5  # seconds the server may lag behind a local gate pass before we roll back

    def __init__(self, game):
        super().__init__(game, 0)
        self.info = None
        self.me = self.racer = None
        self.round = None
        self.course = []

    def start(self, atmosphere):
        Mode.start(self, atmosphere)
        self.active = True
        self.score, self.passed, self.combo, self.best_combo = 0, 0, 1, 1
        self.time_left = 0.0
        self.info, self.me, self.racer, self.round = None, None, None, None
        self.course, self.rings = [], []
        self.finish_time = None
        self.clock = 0.0
        self.unconfirmed = 0.0
        self.placed = False
        self.side = -1.0
        self.previous_position = plane_point(atmosphere)

    @property
    def phase(self):
        return self.info['phase'] if self.info else 'connecting'

    @property
    def started(self):
        """The race is on: the server says so, or its clock has reached the start already."""
        return self.phase == 'racing' or (self.phase == 'countdown' and self.clock >= 0)

    def connection_problem(self):
        network = self.game.network
        if network is None or not network.status.startswith('Connected'):
            return 'Disconnected from the race server', network.status if network else ''
        if getattr(network, 'version', 2) < 2:
            return 'This server is an older PlanePlane version', 'Free flight works; update the server for Ring Race.'
        return None

    def load_round(self, info, atmosphere):
        self.round = info['round']
        self.course = race.course(info['seed'], info['gates'])
        self.passed = 0
        self.finish_time = None
        self.unconfirmed = 0.0
        self.placed = False
        self.aim(atmosphere)

    def aim(self, atmosphere):
        """Measure which side of the next gate we are on; needed whenever the next gate changes."""
        if self.passed < len(self.course):
            self.side = self.ring_side(atmosphere, self.course[self.passed])
        self.previous_position = plane_point(atmosphere)

    def update(self, dt, atmosphere):
        Mode.update(self, dt, atmosphere)
        network = self.game.network
        self.info = info = network.race_state() if network and not self.connection_problem() else None
        if info is None:
            self.me = self.racer = None
            self.rings = []
            return
        phase = info['phase']
        if phase in ('countdown', 'racing') and info['round'] != self.round:
            self.load_round(info, atmosphere)
        self.me = next((entry for entry in info['standings'] if entry['id'] == network.player_id), None)
        current = self.round == info['round']
        # Someone who left this round (menu and back) is a spectator until the next one.
        self.racer = self.me if self.me and current and self.me['status'] != 'dnf' else None
        if self.racer:
            self.sync(self.racer, dt, atmosphere)
        self.clock = network.server_time() - info['start']
        if self.racer and phase == 'countdown' and not self.started:
            self.hold(atmosphere)
        elif (self.racer and self.started and self.racer['status'] == 'racing'
              and self.finish_time is None and self.passed < len(self.course)):
            if not self.placed:
                self.place(atmosphere)
            self.track_gate(atmosphere)
        self.previous_position = plane_point(atmosphere)
        self.rings = self.course[self.passed:] if phase in ('countdown', 'racing') and current else []

    def sync(self, me, dt, atmosphere):
        """The server is authoritative: adopt its count, and undo a local pass it never accepted."""
        before = self.passed
        if me['gates'] > self.passed:
            self.passed = me['gates']
        if me['finish'] is not None:
            self.finish_time = me['finish']
        if me['gates'] < self.passed and me['finish'] is None:
            self.unconfirmed += dt
            if self.unconfirmed > self.UNCONFIRMED:
                self.passed, self.finish_time, self.unconfirmed = me['gates'], None, 0.0
                self.game.flash('GATE NOT CONFIRMED', ui.ALERT)
        else:
            self.unconfirmed = 0.0
        if self.passed != before:
            self.aim(atmosphere)

    def put(self, atmosphere, x, y, z, heading):
        atmosphere.position = np.array([x, z])
        atmosphere.altitude, atmosphere.heading = y, heading
        atmosphere.speed = atmosphere.CRUISE_SPEED * atmosphere.speed_scale
        atmosphere.vertical_speed = atmosphere.bank = atmosphere.flight_pitch = 0.0
        atmosphere.crash_timer = 0.0
        self.aim(atmosphere)

    def hold(self, atmosphere):
        """Park the plane on its starting-grid slot until the countdown ends."""
        self.put(atmosphere, *race.grid_slot(self.racer['slot']))
        atmosphere.fuel = 100.0
        self.placed = True

    def place(self, atmosphere):
        """(Re)starting mid-race: the grid if no gate counts yet, else just past the last gate, facing the next."""
        if self.passed == 0:
            self.put(atmosphere, *race.grid_slot(self.racer['slot']))
        else:
            x, y, z, nx, nz = self.course[self.passed - 1]
            x, z = x + nx * 40, z + nz * 40
            target = self.course[self.passed]
            self.put(atmosphere, x, y, z, math.atan2(target[0] - x, target[2] - z))
        self.placed = True

    def track_gate(self, atmosphere):
        ring = self.course[self.passed]
        side = self.ring_side(atmosphere, ring)
        if self.side < 0 <= side:
            if self.through_gate(atmosphere, ring, side):
                self.passed += 1
                if self.passed == len(self.course):
                    self.finish_time = round(max(0.0, self.clock), 3)
                    self.game.flash(f'FINISHED  {race_clock(self.finish_time)}', ui.GOOD)
                    self.game.sound('record')
                else:
                    self.game.flash(f'GATE {self.passed}/{len(self.course)}', ui.ACCENT)
                    self.game.sound('ring')
                    side = self.ring_side(atmosphere, self.course[self.passed])
            else:
                self.game.flash('MISSED - TURN BACK', ui.ALERT)
                self.game.sound('miss')
        self.side = side

    def progress(self):
        return {'round': self.round or 0, 'gates': self.passed, 'finish': self.finish_time}

    def target(self):
        if (self.racer and self.phase in ('countdown', 'racing') and self.finish_time is None
                and self.passed < len(self.course)):
            x, y, z, _, _ = self.course[self.passed]
            return x, y, z, 'GATE'
        return None

    def on_crash(self, atmosphere):
        pass

    def finish(self):
        pass  # rounds end on the server

    def best_text(self):
        return 'Online only: join a server with --connect'

    # ------------------------------------------------------------------ HUD

    def banner(self, surface, fonts, message, detail=''):
        ui.text(surface, message, fonts.h2, ui.TEXT, (640, 112), 'midtop', tracking=1, shadow=True)
        if detail:
            ui.text(surface, detail[:90], fonts.small, ui.MUTED, (640, 146), 'midtop', shadow=True)

    def draw_hud(self, surface, atmosphere, fonts):
        problem = self.connection_problem()
        if problem:
            self.banner(surface, fonts, *problem)
            return
        info, phase = self.info, self.phase
        if info is None:
            self.banner(surface, fonts, 'Connecting to the race server…')
            return
        total = info['gates']
        if phase == 'waiting':
            self.banner(surface, fonts, 'Waiting for the next round…')
        elif phase == 'countdown' and not self.started:
            if self.racer:
                count = max(1, math.ceil(-self.clock))
                pulse = 1 - (-self.clock) % 1
                ui.text(surface, str(count), fonts.display, ui.ACCENT, (640, 236), 'center', shadow=True,
                        alpha=255 * min(1, 0.6 + pulse))
                ui.label(surface, f'Round {info["round"]}  ·  {total} gates  ·  get ready', fonts.tiny, (640, 296),
                         ui.TEXT, 'midtop', shadow=True)
                self.draw_board(surface, fonts, info)
            else:
                self.banner(surface, fonts, f'Joining round {info["round"]}…')
        elif phase in ('countdown', 'racing'):
            if self.racer:
                if self.clock < 1.2:
                    ui.text(surface, 'GO!', fonts.display, ui.GOOD, (640, 236), 'center', shadow=True,
                            alpha=255 * max(0, 1 - max(0, self.clock) / 1.2))
                self.draw_progress(surface, fonts, info, self.racer)
            elif self.me and self.me['status'] == 'dnf':
                self.banner(surface, fonts, 'You left this round', "You'll join the next one.")
            else:
                self.banner(surface, fonts, 'Race in progress', 'You join the next round. Watch the leaders or fly the course.')
            self.draw_board(surface, fonts, info)
        elif phase == 'results':
            self.draw_results(surface, fonts, info)

    def draw_progress(self, surface, fonts, info, me):
        ui.panel(surface, (500, 100, 280, 62))
        ui.label(surface, 'Position', fonts.tiny, (520, 110))
        ui.text(surface, f'{race.ordinal(me["place"])}/{len(info["standings"])}', fonts.mono, ui.ACCENT, (520, 126))
        ui.label(surface, 'Gates', fonts.tiny, (608, 110))
        ui.text(surface, f'{self.passed}/{info["gates"]}', fonts.mono, ui.TEXT, (608, 126))
        ui.label(surface, 'Time', fonts.tiny, (686, 110))
        shown = self.finish_time if self.finish_time is not None else self.clock
        ui.text(surface, race_clock(shown), fonts.mono, ui.GOOD if self.finish_time is not None else ui.TEXT, (686, 126))
        if self.finish_time is not None:
            # Below the FINISHED flash (y 176-206) so the two never overlap.
            ui.text(surface, 'Finished  ·  waiting for the others', fonts.small, ui.GOOD, (640, 214), 'midtop', shadow=True)

    def place_text(self, entry, info):
        """Ordinals only once the race is under way, and never for pilots who left."""
        if entry['status'] == 'dnf' or (info['phase'] == 'countdown' and not self.started):
            return '–'
        return race.ordinal(entry['place'])

    def standing_value(self, entry, total):
        if entry['status'] == 'finished' and entry['finish'] is not None:
            return race_clock(entry['finish'])
        if entry['status'] == 'dnf':
            return 'DNF'
        return f'{entry["gates"]}/{total}'

    def visible_rows(self, standings, count):
        """The top rows, with my own row swapped in last when I am further down."""
        my_id = self.game.network.player_id if self.game.network else None
        rows = list(standings[:count])
        mine = next((entry for entry in standings[count:] if entry['id'] == my_id), None)
        if mine:
            rows[-1] = mine
        return rows, my_id

    def draw_board(self, surface, fonts, info):
        standings, my_id = self.visible_rows(info['standings'], 8)
        if not standings:
            return
        box = pygame.Rect(1256 - 280, 124, 280, 40 + 26 * len(standings))
        ui.panel(surface, box)
        ui.label(surface, f'Race  ·  round {info["round"]}', fonts.tiny, (box.left + 16, box.top + 12), ui.ACCENT)
        y = box.top + 34
        for entry in standings:
            color = ui.ACCENT if entry['id'] == my_id else ui.TEXT
            ui.text(surface, self.place_text(entry, info), fonts.mono_small, color, (box.left + 16, y))
            ui.text(surface, entry['name'][:12], fonts.small, color, (box.left + 62, y))
            gap = f'+{entry["gap"]:.1f}s' if entry['gap'] else ''
            ui.text(surface, gap, fonts.mono_small, ui.MUTED, (box.right - 82, y), 'topright')
            ui.text(surface, self.standing_value(entry, info['gates']), fonts.mono_small, color, (box.right - 16, y), 'topright')
            y += 26

    def draw_results(self, surface, fonts, info):
        standings, my_id = self.visible_rows(info['standings'], 10)
        box = pygame.Rect(640 - 270, 150, 540, 140 + 34 * max(1, len(standings)))
        ui.panel(surface, box, (9, 18, 27, 232))
        ui.label(surface, f'Round {info["round"]} results', fonts.tiny, (box.left + 36, box.top + 28), ui.ACCENT)
        winner = standings[0]['name'] if standings and standings[0]['status'] == 'finished' else 'No finishers'
        ui.text(surface, winner, fonts.h1, ui.TEXT, (box.left + 34, box.top + 48))
        y = box.top + 108
        for entry in standings:
            color = ui.ACCENT if entry['id'] == my_id else ui.TEXT
            ui.text(surface, self.place_text(entry, info), fonts.mono, color, (box.left + 36, y))
            ui.text(surface, entry['name'], fonts.body, color, (box.left + 100, y))
            if entry['gap'] and entry['status'] == 'finished':
                ui.text(surface, f'+{entry["gap"]:.2f}s', fonts.mono_small, ui.MUTED, (box.right - 150, y + 3), 'topright')
            ui.text(surface, self.standing_value(entry, info['gates']), fonts.mono, color, (box.right - 36, y), 'topright')
            y += 34
        left = max(0, math.ceil(info['ends'] - self.game.network.server_time())) if self.game.network else 0
        ui.text(surface, f'Next round in {left}s', fonts.small, ui.MUTED, (640, box.bottom - 22), 'midbottom')
