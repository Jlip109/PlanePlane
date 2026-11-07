"""Ring run: fly through as many rings as you can before the clock runs out."""

import math

import numpy as np
import pygame

from camera import SCREEN_SCALE, project, view_angles
from units import FEET_PER_METRE

RADIUS = 120.0
SPACING = 800.0
START_TIME = 25.0
BONUS = 12.0
AHEAD = 3


class RingRun:
    help = 'N start/stop ring run'

    def __init__(self, seed=None, start_now=False):
        self.rng = np.random.default_rng(seed)
        self.start_now = start_now
        self.active = False
        self.rings = []
        self.cursor = None
        self.score = 0
        self.best = 0
        self.time_left = 0.0
        self.message = ''
        self.message_time = 0.0

    def start(self, atmosphere):
        self.active = True
        self.score = 0
        self.time_left = START_TIME
        self.rings = []
        self.cursor = (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1], atmosphere.heading)
        for _ in range(AHEAD):
            self.add_ring()
        self.show('FLY THROUGH THE RINGS', 2.5)

    def add_ring(self):
        x, y, z, heading = self.cursor
        heading += self.rng.uniform(-0.45, 0.45)
        x += math.sin(heading) * SPACING
        z += math.cos(heading) * SPACING
        y = float(np.clip(y + self.rng.uniform(-220, 220), 450, 3800))
        self.cursor = (x, y, z, heading)
        self.rings.append((x, y, z, math.sin(heading), math.cos(heading)))

    def next_ring(self):
        self.rings.pop(0)
        self.add_ring()

    def show(self, text, seconds):
        self.message, self.message_time = text, seconds

    def handle_event(self, event, atmosphere):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
            if self.active:
                self.active = False
                self.show('RUN STOPPED', 2)
            else:
                self.start(atmosphere)

    def update(self, dt, atmosphere):
        if self.start_now:
            self.start_now = False
            self.start(atmosphere)
        self.message_time = max(0.0, self.message_time - dt)
        if not self.active:
            return
        self.time_left -= dt
        x, y, z, nx, nz = self.rings[0]
        rx, ry, rz = atmosphere.position[0] - x, atmosphere.altitude - y, atmosphere.position[1] - z
        if rx * rx + ry * ry + rz * rz < RADIUS * RADIUS:
            self.score += 1
            self.time_left += BONUS
            self.next_ring()
            self.show(f'+{BONUS:.0f}s', 1)
        elif rx * nx + rz * nz > 150:
            self.next_ring()
            self.show('MISSED', 1)
        if self.time_left <= 0:
            self.active = False
            self.best = max(self.best, self.score)
            self.show(f'RUN OVER  /  {self.score} RINGS  /  N TO RETRY', 6)

    def draw_world(self, surface, atmosphere):
        if not self.active:
            return
        size = surface.get_size()
        k = size[1] * SCREEN_SCALE
        visible = False
        for index in reversed(range(len(self.rings))):
            x, y, z, nx, nz = self.rings[index]
            point = project(atmosphere, (x, y, z), size)
            if point is None:
                continue
            sx, sy, depth = point
            radius = RADIUS * k / depth
            if radius < 2 or radius > 4 * size[0]:
                continue
            # Rings face their flight direction, so they look narrower when seen from the side.
            rx, ry, rz = x - atmosphere.position[0], y - atmosphere.altitude, z - atmosphere.position[1]
            facing = abs(rx * nx + rz * nz) / max(1.0, math.sqrt(rx * rx + ry * ry + rz * rz))
            half_width = radius * max(facing, 0.15)
            rect = pygame.Rect(0, 0, max(2, int(2 * half_width)), max(2, int(2 * radius)))
            rect.center = (int(sx), int(sy))
            color = (255, 196, 92, 235) if index == 0 else (255, 255, 255, 110)
            pygame.draw.ellipse(surface, color, rect, max(2, int(radius * 0.08)))
            if index == 0 and 0 <= sx <= size[0] and 0 <= sy <= size[1]:
                visible = True
        if not visible:
            self.draw_pointer(surface, atmosphere)

    def draw_pointer(self, surface, atmosphere):
        x, _, z, _, _ = self.rings[0]
        heading, _ = view_angles(atmosphere)
        bearing = math.atan2(x - atmosphere.position[0], z - atmosphere.position[1]) - heading
        side = 1 if math.sin(bearing) > 0 else -1
        width, height = surface.get_size()
        tip_x = width - 30 if side > 0 else 30
        points = [(tip_x, height // 2), (tip_x - side * 26, height // 2 - 18), (tip_x - side * 26, height // 2 + 18)]
        pygame.draw.polygon(surface, (255, 196, 92, 235), points)

    def draw_hud(self, surface, atmosphere, fonts):
        font, _, title = fonts
        if self.active:
            x, y, z, _, _ = self.rings[0]
            distance = math.dist((x, y, z), (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1]))
            text = f'RINGS {self.score}   TIME {max(0.0, self.time_left):04.1f}S   NEXT {distance * FEET_PER_METRE:4.0f} FT   BEST {self.best}'
            label = font.render(text, True, (255, 214, 140))
            surface.blit(label, (640 - label.get_width() // 2, 112))
        if self.message_time > 0:
            label = title.render(self.message, True, (255, 236, 200))
            surface.blit(label, (640 - label.get_width() // 2, 150))
