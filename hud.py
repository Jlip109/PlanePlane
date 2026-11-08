"""In-flight HUD with flight readouts, weather, heading and a navigation map."""

import math

import pygame

import ui
import world
from units import FEET_PER_METRE, MPH_PER_MPS

SEASONS = ['Summer', 'Autumn', 'Winter']


class Hud:
    def __init__(self, fonts):
        self.fonts = fonts
        self.flash = None
        self.radar_range = 8 * 1609.344

    def flash_text(self, message, color):
        self.flash = (message, color, 0.0)

    def update(self, dt):
        if self.flash:
            self.flash = (self.flash[0], self.flash[1], self.flash[2] + dt)
            if self.flash[2] > 1.4:
                self.flash = None

    def draw(self, surface, atmosphere, game, fps, renderer):
        fonts = self.fonts
        target = game.mode.target() if game.mode else None
        if not atmosphere.third_person or atmosphere.mouse_steering:
            self.draw_reticle(surface)
        self.draw_heading_tape(surface, atmosphere, target)
        self.draw_weather(surface, atmosphere)
        self.draw_readouts(surface, atmosphere, game.refueling)
        self.draw_radar(surface, atmosphere, target)
        if game.network:
            status = game.network.status
            text = f'ONLINE  {len(atmosphere.remote_players)+1} PILOTS' if status == 'Connected' else 'DISCONNECTED'
            ui.text(surface,text,fonts.tiny,ui.MUTED,(24,478),shadow=True)
        if self.flash:
            message, color, age = self.flash
            alpha = 255 * ui.fade_in_out(age, 1.4, 0.25)
            ui.text(surface, message, fonts.h2, color, (640, 176), 'midtop', tracking=2, alpha=alpha, shadow=True)
        if atmosphere.crashed:
            self.draw_crash(surface, atmosphere)
        limit = f'{game.frame_limit} FPS' if game.frame_limit else 'Uncapped'
        ui.hint_row(surface, [('F5', 'Wireframe'), ('F7', limit), ('ESC', 'Pause')], fonts, (1256, 704), 'bottomright')
        ui.text(surface, f'{renderer}  {fps:.0f} FPS', fonts.tiny, ui.MUTED, (1256, 670), 'bottomright', shadow=True)
        from plane import PLANE_MODELS
        ui.text(surface,PLANE_MODELS[atmosphere.plane_id][0]+'  ·  F8',fonts.tiny,ui.MUTED,(24,454),shadow=True)
    def draw_reticle(self, surface):
        color = (238, 241, 236, 200)
        pygame.draw.line(surface, color, (612, 360), (630, 360), 2)
        pygame.draw.line(surface, color, (650, 360), (668, 360), 2)
        pygame.draw.circle(surface, color, (640, 360), 4, 2)

    def draw_heading_tape(self, surface, atmosphere, target):
        fonts = self.fonts
        width, scale = 420, 420 / 110
        box = pygame.Rect(640 - width // 2, 18, width, 40)
        ui.panel(surface, box, ui.PANEL_SOFT, radius=8)
        heading = math.degrees(atmosphere.heading + atmosphere.look_yaw) % 360
        clip = surface.get_clip()
        surface.set_clip(box.inflate(-8, 0))
        start = int(heading - 55) // 5 * 5
        for degrees in range(start, start + 115, 5):
            x = 640 + (degrees - heading) * scale
            major = degrees % 30 == 0
            pygame.draw.line(surface, (238, 241, 236, 170 if major else 80), (x, box.bottom - 4),
                             (x, box.bottom - (14 if major else 8)), 2 if major else 1)
            if major:
                name = ui.compass_label(degrees)
                ui.text(surface, name, fonts.tiny, ui.TEXT if name in 'NESW' else ui.MUTED, (x, box.top + 6), 'midtop')
        if target:
            relative = (math.degrees(ui.bearing(atmosphere.position[0], atmosphere.position[1], target[0], target[2]))
                        - heading + 180) % 360 - 180
            x = 640 + max(-200, min(200, relative * scale))
            pygame.draw.polygon(surface, ui.ACCENT, [(x, box.bottom - 2), (x - 6, box.bottom - 10), (x, box.bottom - 18),
                                                     (x + 6, box.bottom - 10)])
        surface.set_clip(clip)
        pygame.draw.polygon(surface, ui.ACCENT, [(640, box.bottom + 1), (634, box.bottom + 9), (646, box.bottom + 9)])
        ui.text(surface, f'{heading:03.0f}°', fonts.mono_small, ui.TEXT, (640, box.bottom + 12), 'midtop', shadow=True)

    def draw_weather(self, surface, atmosphere):
        fonts = self.fonts
        minutes = int(atmosphere.hour * 60) % 1440
        clock = f'{minutes // 60:02d}:{minutes % 60:02d}'
        if atmosphere.cycle_paused:
            clock += '  (paused)'
        weather = 'Live weather' if atmosphere.weather_label.startswith('LIVE') else 'Simulated weather'
        if atmosphere.weather_label=='MAP REVEALS AT GO':
            weather='Unknown location · Reveals at GO'
        if atmosphere.weather_label.startswith('WEATHER UNAVAILABLE'):
            weather = 'Weather unavailable'
        if atmosphere.temperature_f is not None:
            weather += f' · {atmosphere.air_temperature_f:.0f}°F air'
        season=f'  ·  {SEASONS[atmosphere.ground_mode]}' if atmosphere.temperature_f is None else ''
        ui.text(surface, f'{weather}  ·  {clock}{season}',
                fonts.small, ui.TEXT, (24, 28), shadow=True)
        if atmosphere.weather_label.startswith(('LIVE WEATHER','WEATHER UNAVAILABLE')):
            location=atmosphere.weather_label.removeprefix('LIVE WEATHER ').removeprefix('WEATHER UNAVAILABLE ')
            condition=getattr(atmosphere,'weather_condition','')
            if condition:
                location+=f' · {condition} · Wind {atmosphere.wind*MPH_PER_MPS:.0f} mph'
            ui.text(surface,location,fonts.tiny,ui.MUTED,(24,54),shadow=True)

    def draw_readouts(self, surface, atmosphere, refueling=False):
        fonts = self.fonts
        # Truncate so rounding can never announce Mach 1 early.
        mach = math.floor(atmosphere.mach * 100) / 100
        columns = [('Alt', f'{atmosphere.altitude * FEET_PER_METRE:,.0f}', 'ft'),
                   ('Speed', f'{atmosphere.speed * MPH_PER_MPS:.0f}', 'mph'), ('Mach', f'{mach:.2f}', '')]
        x = 1256
        for name, value, unit in reversed(columns):
            if unit:
                unit_rect = ui.text(surface, unit, fonts.small, ui.MUTED, (x, 52), 'bottomright', shadow=True)
                right = unit_rect.left - 6
            else:
                right = x
            value_rect = ui.text(surface, value, fonts.mono, ui.TEXT, (right, 54), 'bottomright', shadow=True)
            ui.label(surface, name, fonts.tiny, (value_rect.left, 22), shadow=True)
            x = value_rect.left - 28
        if getattr(atmosphere,'finish_rollout',False):
            state,color=('Parked' if atmosphere.speed<=.1 else 'Braking'),ui.ACCENT
        elif atmosphere.fuel<=0:
            grounded=world.on_runway(*atmosphere.position) and atmosphere.altitude<=world.RUNWAY_HEIGHT+4
            state,color=('Fuel empty' if grounded else 'Falling - no fuel'),ui.ALERT
        elif getattr(atmosphere,'braking',False):
            state,color='Braking',ui.ACCENT
        elif atmosphere.speed >= atmosphere.MAX_SPEED:
            state, color = 'MACH 5 - SPEED LIMIT', ui.ACCENT
        elif refueling:
            state, color = 'Refueling', ui.GOOD
        elif atmosphere.boosting:
            state, color = 'Boost', ui.ACCENT
        else:
            state, color = 'Cruise', ui.MUTED
        low = atmosphere.fuel < 15
        ui.label(surface, 'Fuel', fonts.tiny, (1256 - 190, 66), shadow=True)
        ui.label(surface, state, fonts.tiny, (1256, 66), color, 'topright', shadow=True)
        ui.bar(surface, (1256 - 190, 84, 190, 4), atmosphere.fuel / 100,
               ui.ALERT if low and int(atmosphere.elapsed * 4) % 2 else (ui.GOOD if refueling else ui.ACCENT))
        ui.text(surface, f'{atmosphere.gallons:.1f} US gal', fonts.small, ui.MUTED, (1256, 92), 'topright', shadow=True)

    def draw_radar(self, surface, atmosphere, target):
        fonts = self.fonts
        center, radius = (118, 594), 92
        disc = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(disc, ui.PANEL, (radius + 1, radius + 1), radius)
        pygame.draw.circle(disc, (255, 255, 255, 40), (radius + 1, radius + 1), radius, 1)
        pygame.draw.circle(disc, (255, 255, 255, 22), (radius + 1, radius + 1), radius // 2, 1)
        surface.blit(disc, (center[0] - radius - 1, center[1] - radius - 1))
        heading = atmosphere.heading + atmosphere.look_yaw
        px, pz = atmosphere.position
        scale = radius / self.radar_range

        def to_radar(x, z, clamp=True):
            dx, dz = x - px, z - pz
            # rotate so the nose points up the radar
            rx = dx * math.cos(heading) - dz * math.sin(heading)
            ry = dx * math.sin(heading) + dz * math.cos(heading)
            length = math.hypot(rx, ry) * scale
            inside = length <= radius - 6
            if not inside and clamp:
                rx, ry = rx / max(length, 1e-6) * (radius - 6) / scale, ry / max(length, 1e-6) * (radius - 6) / scale
            return (center[0] + rx * scale, center[1] - ry * scale), inside

        north, _ = to_radar(px, pz + self.radar_range * 0.86, clamp=False)
        ui.text(surface, 'N', fonts.tiny, ui.MUTED, north, 'center')
        if target:
            pos, inside = to_radar(target[0], target[2])
            pygame.draw.circle(surface, ui.ACCENT, pos, 6, 2)
        for player in atmosphere.remote_players:
            pos, inside = to_radar(player['x'],player['z'])
            pygame.draw.circle(surface,(90,210,245),pos,3)
        pygame.draw.polygon(surface, ui.TEXT, [(center[0], center[1] - 7), (center[0] - 5, center[1] + 5),
                                               (center[0], center[1] + 2), (center[0] + 5, center[1] + 5)])
        ui.label(surface, f'{self.radar_range / 1609.344:.0f} mi', fonts.tiny, (center[0], center[1] + radius + 6),
                 ui.DIM, 'midtop')

    def draw_crash(self, surface, atmosphere):
        fonts = self.fonts
        tint = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        tint.fill((120, 20, 10, int(110 * atmosphere.impact)))
        surface.blit(tint, (0, 0))
        ui.text(surface, 'CRASHED', fonts.h1, ui.TEXT, (640, 300), 'midtop', tracking=10, shadow=True)
        ui.text(surface, 'Recovering altitude…', fonts.body, ui.TEXT, (640, 352), 'midtop', shadow=True)
