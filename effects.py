"""Rain, lightning and storm gloom, drawn as a screen overlay so both renderers get them."""

import math

import numpy as np
import pygame

DROPS = 260


class WeatherEffects:
    def __init__(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.drops = self.rng.random((DROPS, 2))
        self.lengths = 0.6 + self.rng.random(DROPS) * 0.8
        self.rain = 0.0
        self.slant = 0.0
        self.next_strike = 2.0
        self.echo = 0.0

    def update(self, dt, atmosphere):
        # Rain falls from the lowest cloud deck, so it fades out as you climb above ~900 m.
        self.rain = atmosphere.precipitation * float(np.clip((1700 - atmosphere.altitude) / 800, 0, 1))
        self.slant = math.sin(atmosphere.wind_angle - atmosphere.heading - atmosphere.look_yaw) * atmosphere.wind / 45
        self.drops[:, 1] += dt * (1.6 + atmosphere.wind / 30) * self.lengths
        self.drops[:, 0] += dt * self.slant * 0.6 * self.lengths
        fallen = self.drops[:, 1] > 1
        self.drops[fallen, 1] -= 1
        self.drops[fallen, 0] = self.rng.random(int(fallen.sum()))
        self.drops[:, 0] %= 1

        atmosphere.flash = max(0.0, atmosphere.flash - dt * 4)
        if self.echo > 0:
            self.echo -= dt
            if self.echo <= 0:
                atmosphere.flash = max(atmosphere.flash, 0.6)
        if atmosphere.storm > 0.05:
            self.next_strike -= dt * atmosphere.storm
            if self.next_strike <= 0:
                atmosphere.flash = 1.0
                atmosphere.emit('lightning')
                self.echo = 0.12  # real strikes often flicker twice
                self.next_strike = 2.5 + self.rng.random() * 6

    def draw_world(self, surface, atmosphere):
        width, height = surface.get_size()
        gloom = max(atmosphere.storm, atmosphere.precipitation * 0.5)
        if atmosphere.flash > 0.01:
            surface.fill((235, 240, 255, int(170 * atmosphere.flash)))
        elif gloom > 0.01:
            surface.fill((12, 16, 24, int(80 * gloom)))
        if self.rain < 0.02:
            return
        count = int(DROPS * self.rain)
        color = (190, 205, 220, int(90 + 90 * self.rain))
        length = height * 0.035
        for (x, y), scale in zip(self.drops[:count], self.lengths[:count]):
            start = (x * width, y * height)
            end = (start[0] - self.slant * length * scale, start[1] - length * scale)
            pygame.draw.line(surface, color, start, end, 1)
