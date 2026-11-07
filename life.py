"""Things that share the sky: hot-air balloons around each city and flocks of geese."""

import math

import numpy as np
import pygame

import world
from camera import SCREEN_SCALE, project

BALLOON_COLORS = [((232, 92, 64), (248, 206, 92)), ((52, 120, 196), (238, 240, 236)),
                  ((88, 168, 112), (246, 228, 150)), ((180, 76, 140), (250, 180, 90)),
                  ((240, 150, 60), (70, 60, 120)), ((40, 150, 160), (240, 120, 100))]


def fade_for(atmosphere, point, depth, far):
    visible = 1.0 - min(1.0, max(0.0, (depth - far * 0.45) / (far * 0.55)))
    if visible <= 0:
        return 0.0
    return visible * (1.0 - atmosphere.cloud_cover_between(point))


class Balloon:
    def __init__(self, x, z, altitude, colors, phase):
        self.anchor = (x, z)
        self.altitude = altitude
        self.colors = colors
        self.phase = phase

    def position(self, t):
        x, z = self.anchor
        drift = 260
        return (x + math.sin(t * 0.011 + self.phase) * drift,
                self.altitude + math.sin(t * 0.07 + self.phase * 2) * 18,
                z + math.cos(t * 0.009 + self.phase) * drift)


class SkyLife:
    def __init__(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.balloons = []
        for index, (_, cx, cz, radius, _, _) in enumerate(world.CITIES):
            level = world.CITY_LEVELS[index]
            for k in range(2):
                angle = self.rng.uniform(0, math.tau)
                distance = radius * self.rng.uniform(0.9, 1.6)
                self.balloons.append(Balloon(cx + math.cos(angle) * distance, cz + math.sin(angle) * distance,
                                             level + self.rng.uniform(260, 720),
                                             BALLOON_COLORS[(index * 2 + k) % len(BALLOON_COLORS)],
                                             self.rng.uniform(0, 100)))
        self.flocks = []
        self.time = 0.0

    def update(self, dt, atmosphere):
        self.time += dt
        camera = atmosphere.camera
        # Geese live below ~1400 m; keep one or two flocks near the camera.
        self.flocks = [flock for flock in self.flocks
                       if math.hypot(flock['x'] - camera[0], flock['z'] - camera[2]) < 2500]
        if camera[1] < 1400 and len(self.flocks) < 2 and self.rng.random() < dt * 0.4:
            angle = atmosphere.heading + self.rng.uniform(-0.7, 0.7)
            distance = self.rng.uniform(250, 700)
            self.flocks.append({
                'x': camera[0] + math.sin(angle) * distance, 'z': camera[2] + math.cos(angle) * distance,
                'y': max(camera[1] + self.rng.uniform(-60, 40), world.ground_height(camera[0], camera[2]) + 60),
                'heading': self.rng.uniform(0, math.tau), 'count': int(self.rng.integers(5, 10)),
                'phase': self.rng.uniform(0, 10)})
        for flock in self.flocks:
            flock['x'] += math.sin(flock['heading']) * 14 * dt
            flock['z'] += math.cos(flock['heading']) * 14 * dt

    def draw_world(self, surface, atmosphere):
        size = surface.get_size()
        k = size[1] * SCREEN_SCALE
        items = []
        for balloon in self.balloons:
            point = balloon.position(self.time)
            screen = project(atmosphere, point, size)
            if screen and -200 < screen[0] < size[0] + 200 and -200 < screen[1] < size[1] + 200 and screen[2] < 9000:
                items.append((screen[2], 'balloon', balloon, point, screen))
        for flock in self.flocks:
            for n in range(flock['count']):
                row = (n + 1) // 2
                side = 1 if n % 2 else -1
                back = row * 3.2
                lateral = side * row * 2.6
                h = flock['heading']
                point = (flock['x'] - math.sin(h) * back + math.cos(h) * lateral, flock['y'] + row * 0.4,
                         flock['z'] - math.cos(h) * back - math.sin(h) * lateral)
                screen = project(atmosphere, point, size)
                if screen and 0 <= screen[0] < size[0] and 0 <= screen[1] < size[1]:
                    items.append((screen[2], 'goose', flock, n, screen))
        for item in sorted(items, key=lambda item: -item[0]):
            if item[1] == 'balloon':
                self.draw_balloon(surface, atmosphere, item[2], item[3], item[4], k)
            else:
                self.draw_goose(surface, atmosphere, item[2], item[3], item[4], k)

    def draw_balloon(self, surface, atmosphere, balloon, point, screen, k):
        x, y, depth = screen
        alpha = fade_for(atmosphere, point, depth, 9000)
        if alpha <= 0.02:
            return
        radius = 9.5 * k / depth
        night = atmosphere.phase
        light = 0.35 + 0.65 * (1 - night * 0.8)
        main, stripe = balloon.colors
        if radius < 2.5:
            color = tuple(int(c * light) for c in main)
            pygame.draw.circle(surface, (*color, int(255 * alpha)), (int(x), int(y)), max(1, int(radius)))
            return
        layer_size = int(radius * 2.6) + 8
        layer = pygame.Surface((layer_size, int(radius * 3.6) + 8), pygame.SRCALPHA)
        cx, cy = layer_size / 2, radius + 4
        sun = atmosphere.sun_direction
        heading = atmosphere.heading + atmosphere.look_yaw
        # sun direction projected onto the screen's horizontal axis, for the lit side of the envelope
        sun_side = sun[0] * math.cos(heading) - sun[2] * math.sin(heading)

        def half_width(v):
            # v from -1 (crown) to 1.45 (mouth): round top, tapering skirt
            return radius * (math.sqrt(max(0.0, 1 - v * v)) if v < 0.35 else
                             math.sqrt(1 - 0.35 ** 2) * (1 - (v - 0.35) / 1.1 * 0.72))

        rows = [(-1 + i * 2.45 / 18) for i in range(19)]
        gores = 8
        for g in range(gores):
            a0 = -math.pi / 2 + g * math.pi / gores
            a1 = a0 + math.pi / gores
            left = [(cx + half_width(v) * math.sin(a0), cy + v * radius) for v in rows]
            right = [(cx + half_width(v) * math.sin(a1), cy + v * radius) for v in reversed(rows)]
            mid = math.sin((a0 + a1) / 2)
            lit = 0.72 + 0.28 * max(-1.0, min(1.0, mid * sun_side * 2 + 0.3))
            base = main if g % 2 else stripe
            color = tuple(int(c * light * lit) for c in base)
            pygame.draw.polygon(layer, color, left + right)
        mouth_y = cy + 1.45 * radius
        basket = pygame.Rect(0, 0, max(2, int(radius * 0.36)), max(2, int(radius * 0.3)))
        basket.center = (int(cx), int(mouth_y + radius * 0.42))
        rope = tuple(int(c * light) for c in (70, 60, 50))
        for side in (-1, 1):
            pygame.draw.line(layer, rope, (cx + side * radius * 0.26, mouth_y), (basket.centerx + side * basket.width / 2, basket.top), 1)
        pygame.draw.rect(layer, tuple(int(c * light) for c in (122, 86, 52)), basket)
        if night > 0.6 and int(self.time * 3 + balloon.phase) % 7 == 0:
            pygame.draw.circle(layer, (255, 190, 100), (int(cx), int(mouth_y)), max(1, int(radius * 0.18)))
        layer.set_alpha(int(255 * alpha))
        surface.blit(layer, (x - cx, y - cy))

    def draw_goose(self, surface, atmosphere, flock, n, screen, k):
        x, y, depth = screen
        alpha = fade_for(atmosphere, (flock['x'], flock['y'], flock['z']), depth, 1500)
        if alpha <= 0.05:
            return
        span = max(1.5, 0.9 * k / depth)
        flap = math.sin(self.time * 7 + flock['phase'] + n * 0.7)
        tip = span * (0.2 + 0.5 * flap)
        color = (28, 32, 36, int(230 * alpha)) if atmosphere.phase < 0.6 else (10, 12, 16, int(160 * alpha))
        width = 2 if span > 4 else 1
        pygame.draw.line(surface, color, (x - span, y - tip), (x, y), width)
        pygame.draw.line(surface, color, (x, y), (x + span, y - tip), width)
