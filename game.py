"""The game director: menus, flight modes, HUD, scores and sound in one state machine.

States: title -> flying <-> paused -> results -> title
"""

import numpy as np
import pygame
import math

from hud import Hud
from menu import Menu
from modes import FreeFlight, RingRun
from scores import Scores
from plane import PLANE_MODELS

START = {'position': (0.0, -900.0), 'altitude': 700.0, 'heading': 0.0}
MENU_STATES = ('title',)


class Game:
    def __init__(self, atmosphere, fonts, audio, mode='menu', seed=None, scores=None):
        self.atmosphere = atmosphere
        self.fonts = fonts
        self.audio = audio
        self.scores = scores if scores is not None else Scores()
        saved_tuning = self.scores.get('flight_tuning',{})
        for key,value in saved_tuning.items():
            if key in atmosphere.flight_tuning and isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
                atmosphere.flight_tuning[key] = round(min(100,max(0,value)))
        saved_plane = self.scores.get('plane_model', 'classic')
        atmosphere.plane_id = saved_plane if saved_plane in PLANE_MODELS else 'classic'
        self.hud = Hud(fonts)
        self.modes = {'free': FreeFlight(self), 'rings': RingRun(self, seed)}
        self.mode = None
        self.hud_transform = (1.0, 0, 0)
        self.menu = Menu(self, fonts)
        self.state = 'title'
        self.quit_requested = False
        self.refueling = False
        self.frame_limit = 60
        self.network = None
        if mode in self.modes:
            self.start(mode)
        else:
            atmosphere.autopilot = True

    # ------------------------------------------------------------------ helpers

    @property
    def flying(self):
        return self.state == 'flying'

    @property
    def paused(self):
        return self.state == 'paused'

    def sound(self, name):
        if self.audio:
            self.audio.play(name)

    def flash(self, message, color):
        self.hud.flash_text(message, color)

    # ------------------------------------------------------------------ flow

    def reset_flight(self):
        atmosphere = self.atmosphere
        atmosphere.position = np.array(START['position'])
        atmosphere.altitude = START['altitude']
        atmosphere.heading = START['heading']
        atmosphere.speed = atmosphere.CRUISE_SPEED * atmosphere.speed_scale
        atmosphere.vertical_speed = atmosphere.bank = atmosphere.flight_pitch = 0.0
        atmosphere.crash_timer = atmosphere.impact = 0.0
        atmosphere.fuel = 100.0
        atmosphere.reset_view()

    def start(self, key):
        self.mode = self.modes[key]
        self.atmosphere.autopilot = False
        self.reset_flight()
        self.state = 'flying'
        self.mode.start(self.atmosphere)
        self.sound('start')

    def to_title(self):
        self.state = 'title'
        self.mode = None
        self.atmosphere.autopilot = True
        self.menu.age = 0.0

    def act(self, action):
        if action is None:
            return
        if action in self.modes:
            self.start(action)
        elif action == 'title':
            self.to_title()
        elif action == 'resume':
            self.state = 'flying'
        elif action == 'restart':
            self.start(self.mode.key if self.mode else 'free')
        elif action == 'quit':
            self.quit_requested = True
        elif action in ('frame_limit', 'fps_up', 'fps_down'):
            self.cycle_frame_limit(-1 if action == 'fps_down' else 1)
        elif action == 'aircraft':
            self.cycle_aircraft()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F8:
            self.cycle_aircraft()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F7:
            self.cycle_frame_limit()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F5:
            self.atmosphere.wireframe = not self.atmosphere.wireframe
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
            if self.audio:
                self.audio.toggle_mute()
            return
        if self.state == 'flying':
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.state = 'paused'
                self.menu.pause_index = 0
            return
        self.act(self.menu.handle_event(event, self.state))

    def cycle_frame_limit(self, direction=1):
        limits = (60, 120, 0)
        index = limits.index(self.frame_limit) if self.frame_limit in limits else 0
        self.frame_limit = limits[(index + direction) % len(limits)]
        self.sound('tick')

    def cycle_aircraft(self):
        models = list(PLANE_MODELS)
        self.atmosphere.plane_id = models[(models.index(self.atmosphere.plane_id)+1) % len(models)]
        self.scores.data['plane_model'] = self.atmosphere.plane_id
        self.scores.save()

    def set_tuning(self, key, value):
        if key not in self.atmosphere.flight_tuning:
            return
        self.atmosphere.flight_tuning[key] = round(min(100,max(0,value)))
        self.scores.data['flight_tuning'] = dict(self.atmosphere.flight_tuning)
        self.scores.save()

    def update(self, dt, sim_dt):
        atmosphere = self.atmosphere
        self.menu.update(dt)
        self.hud.update(sim_dt)
        if self.audio:
            self.audio.update(dt, atmosphere, self.flying)
        if self.state in MENU_STATES:
            atmosphere.fuel = 100.0  # the title-screen autopilot never runs dry
        if self.state != 'flying' or not self.mode:
            self.refueling = False
            return
        for name, _ in atmosphere.events:
            if name == 'crash':
                self.mode.on_crash(atmosphere)
        self.mode.update(sim_dt, atmosphere)
        if self.mode.finished:
            self.state = 'results'
            self.sound('record' if self.mode.summary and self.mode.summary['record'] else 'deliver')

    # ------------------------------------------------------------------ drawing

    def scene_shade(self):
        """(top, bottom, left) darkening of the 3D scene behind the HUD or menus."""
        if self.state in MENU_STATES:
            return 0.25, 0.35, 0.68
        return 0.62, 0.5, 0.0

    def draw_world(self, surface):
        if self.mode and self.state in ('flying', 'paused'):
            self.mode.draw_world(surface, self.atmosphere)

    def draw_hud(self, surface, fps, renderer):
        if self.state in MENU_STATES:
            self.menu.draw(surface, self.state)
            return
        self.hud.draw(surface, self.atmosphere, self, fps, renderer)
        if self.mode:
            self.mode.draw_hud(surface, self.atmosphere, self.fonts)
        if self.state in ('paused', 'results'):
            self.menu.draw(surface, self.state)
