"""Game modes. Each one gets the shared scores and sound context and the atmosphere."""

import math

import numpy as np
import pygame

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
        x, y, z, heading = self.cursor
        if not first:
            heading += self.rng.uniform(-0.4, 0.4)
            y += self.rng.uniform(-130, 130)
        x += math.sin(heading) * self.SPACING
        z += math.cos(heading) * self.SPACING
        # Keep every gate above the highest terrain under its opening.
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
            x, y, z, nx, nz = ring
            fraction = -self.side / (side - self.side)
            current = np.array(plane_point(atmosphere))
            crossing = np.array(self.previous_position) + fraction * (current - self.previous_position)
            horizontal = (crossing[0] - x) * nz - (crossing[2] - z) * nx
            vertical = crossing[1] - y
            apothem = (self.RADIUS - 3) * math.cos(math.pi / 10)
            inside = all(horizontal * math.cos((i + 0.5) * math.tau / 10 + self.gate_rotation(ring))
                         + vertical * math.sin((i + 0.5) * math.tau / 10 + self.gate_rotation(ring)) <= apothem for i in range(10))
            if inside:
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
