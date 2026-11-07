"""In-flight HUD: heading tape, flight readouts, location, radar, banners and the controls page."""

import math

import pygame

import ui
import world

CONTROLS = [
    ('Flying', [('W  S', 'Climb / descend'), ('A  D', 'Turn'), ('SPACE', 'Boost'),
                ('RIGHT MOUSE', 'Hold to look around'), ('↑  ↓', 'Look up / down'), ('R', 'Center view')]),
    ('World', [('1  2  3  4', 'Clear / broken / overcast / storm'), ('L', 'Live weather for your city'),
               ('←  →', 'Move the clock'), ('P', 'Pause the day cycle'), ('[  ]', 'Day cycle speed'),
               (',  .', 'Less / more wind'), ('G', 'Season')]),
    ('Game', [('H', 'This page'), ('ESC', 'Pause menu'), ('M', 'Mute sound'), ('F11', 'Fullscreen')]),
]
SEASONS = ['Summer', 'Autumn', 'Winter']


class Hud:
    def __init__(self, fonts):
        self.fonts = fonts
        self.show_help = False
        self.banner = None
        self.flash = None
        self.radar_range = 14000.0

    def city_banner(self, index):
        self.banner = (index, 0.0)

    def flash_text(self, message, color):
        self.flash = (message, color, 0.0)

    def update(self, dt):
        if self.banner:
            self.banner = (self.banner[0], self.banner[1] + dt)
            if self.banner[1] > 5:
                self.banner = None
        if self.flash:
            self.flash = (self.flash[0], self.flash[1], self.flash[2] + dt)
            if self.flash[2] > 1.4:
                self.flash = None

    def draw(self, surface, atmosphere, game, fps, renderer):
        fonts = self.fonts
        target = game.mode.target() if game.mode else None
        self.draw_reticle(surface)
        self.draw_heading_tape(surface, atmosphere, target)
        self.draw_location(surface, atmosphere)
        self.draw_readouts(surface, atmosphere)
        self.draw_radar(surface, atmosphere, target)
        if self.banner:
            self.draw_banner(surface)
        if self.flash:
            message, color, age = self.flash
            alpha = 255 * ui.fade_in_out(age, 1.4, 0.25)
            ui.text(surface, message, fonts.h2, color, (640, 176), 'midtop', tracking=2, alpha=alpha, shadow=True)
        if atmosphere.crashed:
            self.draw_crash(surface, atmosphere)
        ui.hint_row(surface, [('H', 'Controls'), ('ESC', 'Pause')], fonts, (1256, 704), 'bottomright')
        ui.text(surface, f'{renderer}  {fps:.0f} FPS', fonts.tiny, ui.MUTED, (1256, 670), 'bottomright', shadow=True)
        if self.show_help:
            self.draw_controls(surface)

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

    def draw_location(self, surface, atmosphere):
        fonts = self.fonts
        x, z = atmosphere.position
        city = world.city_at(x, z)
        if city is not None:
            ui.label(surface, 'Over', fonts.tiny, (24, 22), shadow=True)
            ui.text(surface, world.CITIES[city][0].title(), fonts.h2, ui.TEXT, (24, 38), shadow=True)
        else:
            nearest, distance = world.nearest_city(x, z)
            ui.label(surface, 'Countryside', fonts.tiny, (24, 22), shadow=True)
            ui.text(surface, f'{world.CITIES[nearest][0].title()}  {ui.format_distance(distance)}',
                    fonts.h2, ui.TEXT, (24, 38), shadow=True)
        minutes = int(atmosphere.hour * 60) % 1440
        clock = f'{minutes // 60:02d}:{minutes % 60:02d}'
        if atmosphere.cycle_paused:
            clock += '  (paused)'
        weather = atmosphere.weather_label.title().replace('  ', ' · ')
        ui.text(surface, f'{weather}  ·  {clock}  ·  {SEASONS[atmosphere.ground_mode]}',
                fonts.small, ui.TEXT, (24, 72), shadow=True)

    def draw_readouts(self, surface, atmosphere):
        fonts = self.fonts
        columns = [('Alt', f'{atmosphere.altitude:,.0f}', 'm'), ('Speed', f'{atmosphere.speed * 3.6:.0f}', 'km/h'),
                   ('Climb', f'{atmosphere.vertical_speed:+.0f}', 'm/s')]
        x = 1256
        for name, value, unit in reversed(columns):
            unit_rect = ui.text(surface, unit, fonts.small, ui.MUTED, (x, 52), 'bottomright', shadow=True)
            value_rect = ui.text(surface, value, fonts.mono, ui.TEXT, (unit_rect.left - 6, 54), 'bottomright', shadow=True)
            ui.label(surface, name, fonts.tiny, (value_rect.left, 22), shadow=True)
            x = value_rect.left - 28
        ui.label(surface, 'Boost', fonts.tiny, (1256 - 150, 66), shadow=True)
        ui.bar(surface, (1256 - 150, 84, 150, 4), atmosphere.boost,
               ui.ACCENT if atmosphere.boost > 0.25 or int(atmosphere.elapsed * 4) % 2 else ui.ALERT)

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
        for index, (name, cx, cz, city_radius, _, _) in enumerate(world.CITIES):
            pos, inside = to_radar(cx, cz)
            size = max(3, int(city_radius * scale)) if inside else 3
            pygame.draw.circle(surface, (238, 241, 236, 150 if inside else 90), pos, size, 0 if not inside else 1)
            if inside:
                ui.text(surface, name.title(), fonts.tiny, ui.MUTED, (pos[0], pos[1] + size + 2), 'midtop')
        if target:
            pos, inside = to_radar(target[0], target[2])
            pygame.draw.circle(surface, ui.ACCENT, pos, 6, 2)
        pygame.draw.polygon(surface, ui.TEXT, [(center[0], center[1] - 7), (center[0] - 5, center[1] + 5),
                                               (center[0], center[1] + 2), (center[0] + 5, center[1] + 5)])
        ui.label(surface, f'{self.radar_range / 1000:.0f} km', fonts.tiny, (center[0], center[1] + radius + 6),
                 ui.DIM, 'midtop')

    def draw_banner(self, surface):
        index, age = self.banner
        alpha = 255 * ui.fade_in_out(age, 5.0, 0.8)
        name, *_, description = world.CITIES[index]
        fonts = self.fonts
        ui.label(surface, 'Now arriving', fonts.tiny, (640, 214), ui.ACCENT, 'midtop', alpha, shadow=True)
        ui.text(surface, name, fonts.h1, ui.TEXT, (640, 232), 'midtop', tracking=8, alpha=alpha, shadow=True)
        ui.text(surface, description, fonts.body, ui.TEXT, (640, 284), 'midtop', alpha=alpha, shadow=True)

    def draw_crash(self, surface, atmosphere):
        fonts = self.fonts
        tint = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        tint.fill((120, 20, 10, int(110 * atmosphere.impact)))
        surface.blit(tint, (0, 0))
        ui.text(surface, 'CRASHED', fonts.h1, ui.TEXT, (640, 300), 'midtop', tracking=10, shadow=True)
        ui.text(surface, 'Recovering altitude…', fonts.body, ui.TEXT, (640, 352), 'midtop', shadow=True)

    def draw_controls(self, surface):
        fonts = self.fonts
        box = pygame.Rect(240, 104, 800, 508)
        ui.panel(surface, box, (9, 18, 27, 236))
        ui.label(surface, 'Controls', fonts.tiny, (box.left + 40, box.top + 30), ui.ACCENT)
        columns = [(box.left + 40, CONTROLS[0:1] + CONTROLS[2:3]), (box.left + 420, CONTROLS[1:2])]
        for x, groups in columns:
            y = box.top + 62
            for title, rows in groups:
                ui.text(surface, title, fonts.h2, ui.TEXT, (x, y))
                y += 38
                for key, action in rows:
                    cap = ui.key_cap(surface, key, fonts, (x, y))
                    ui.text(surface, action, fonts.small, ui.MUTED, (x + 132, cap.centery), 'midleft')
                    y += 31
                y += 14
        ui.text(surface, 'Press H to close', fonts.small, ui.DIM, (box.right - 40, box.bottom - 24), 'bottomright')
