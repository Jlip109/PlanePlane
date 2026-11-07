"""The game director: menus, the active mode, radio, HUD, scores and sound in one state machine.

States: title -> (pilots | controls) -> flying <-> paused -> results -> title
"""

import math

import numpy as np
import pygame

import characters
import world
from characters import Radio
from hud import Hud
from menu import Menu
from modes import FreeFlight, RingRun, SkyCourier
from scores import Scores

START = {'position': (0.0, -900.0), 'altitude': 700.0, 'heading': 0.0}
MENU_STATES = ('title', 'pilots', 'controls')
REFUEL_HEIGHT = 450.0  # fly this low (meters above the city) inside a city to refuel
REFUEL_RATE = 14.0     # percent of the tank per second


class Game:
    def __init__(self, atmosphere, fonts, audio, mode='menu', pilot=None, seed=None, scores=None):
        self.atmosphere = atmosphere
        self.fonts = fonts
        self.audio = audio
        self.scores = scores if scores is not None else Scores()
        self.radio = Radio()
        self.hud = Hud(fonts)
        self.modes = {'free': FreeFlight(self), 'rings': RingRun(self, seed), 'courier': SkyCourier(self, seed)}
        self.mode = None
        self.pilot_index = self.pick_pilot(pilot)
        self.apply_pilot()
        self.hud_transform = (1.0, 0, 0)
        self.menu = Menu(self, fonts)
        self.state = 'title'
        self.quit_requested = False
        self.city = None
        self.refueling = False
        if mode in self.modes:
            self.start(mode)
        else:
            atmosphere.autopilot = True

    # ------------------------------------------------------------------ helpers

    def pick_pilot(self, wanted):
        if wanted is not None:
            for index, pilot in enumerate(characters.PILOTS):
                if str(wanted).lower() in (str(index), pilot.role.lower(), pilot.name.split()[0].lower()):
                    return index
        saved = self.scores.get('pilot', 0)
        return saved if 0 <= saved < len(characters.PILOTS) else 0

    def apply_pilot(self):
        pilot = characters.PILOTS[self.pilot_index]
        self.atmosphere.speed_scale = pilot.speed
        self.atmosphere.handling = pilot.handling
        self.atmosphere.boost_scale = pilot.boost

    @property
    def pilot(self):
        return characters.PILOTS[self.pilot_index]

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
        self.radio.clear()
        self.hud.show_help = False
        self.city = None
        self.state = 'flying'
        self.mode.start(self.atmosphere)
        self.sound('start')

    def to_title(self):
        self.state = 'title'
        self.mode = None
        self.radio.clear()
        self.atmosphere.autopilot = True
        self.menu.age = 0.0

    def act(self, action):
        if action is None:
            return
        if action in self.modes:
            self.start(action)
        elif action == 'pilot':
            self.menu.pilot_choice = self.pilot_index
            self.state = 'pilots'
        elif action == 'pilot_chosen':
            self.pilot_index = self.menu.pilot_choice
            self.scores.data['pilot'] = self.pilot_index
            self.scores.save()
            self.apply_pilot()
            self.state = 'title'
        elif action == 'controls':
            self.state = 'controls'
        elif action == 'title':
            self.to_title()
        elif action == 'resume':
            self.state = 'flying'
        elif action == 'restart':
            self.start(self.mode.key if self.mode else 'free')
        elif action == 'quit':
            self.quit_requested = True

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
            if self.audio:
                self.audio.toggle_mute()
            return
        if self.state == 'flying':
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.hud.show_help:
                        self.hud.show_help = False
                    else:
                        self.state = 'paused'
                        self.menu.pause_index = 0
                elif event.key == pygame.K_h:
                    self.hud.show_help = not self.hud.show_help
            return
        self.act(self.menu.handle_event(event, self.state))

    def update(self, dt, sim_dt):
        atmosphere = self.atmosphere
        self.menu.update(dt)
        self.hud.update(sim_dt)
        self.radio.update(sim_dt)
        if self.audio:
            self.audio.update(dt, atmosphere, self.flying)
        if self.state in MENU_STATES:
            atmosphere.fuel = 100.0  # the title-screen autopilot never runs dry
        if self.state != 'flying' or not self.mode:
            self.refueling = False
            return
        self.refuel(sim_dt)
        for name, _ in atmosphere.events:
            if name == 'crash':
                self.mode.on_crash(atmosphere)
        city = world.city_at(atmosphere.position[0], atmosphere.position[1])
        if city is not None and city != self.city:
            self.hud.city_banner(city)
        self.city = city
        self.mode.update(sim_dt, atmosphere)
        if self.mode.finished:
            self.state = 'results'
            self.radio.clear()
            self.sound('record' if self.mode.summary and self.mode.summary['record'] else 'deliver')

    def refuel(self, dt):
        """Every city has an airfield: fly low over it and the tank fills up."""
        atmosphere = self.atmosphere
        city = world.city_at(atmosphere.position[0], atmosphere.position[1])
        low = city is not None and atmosphere.altitude < world.CITY_LEVELS[city] + REFUEL_HEIGHT
        near = city is not None and math.hypot(atmosphere.position[0] - world.CITIES[city][1],
                                               atmosphere.position[1] - world.CITIES[city][2]) < world.CITIES[city][3] * 0.75
        self.refueling = bool(low and near and not atmosphere.crashed and atmosphere.fuel < 100)
        if self.refueling:
            atmosphere.fuel = min(100.0, atmosphere.fuel + REFUEL_RATE * dt)

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
        self.radio.draw(surface, self.fonts)
        if self.state in ('paused', 'results'):
            self.menu.draw(surface, self.state)
