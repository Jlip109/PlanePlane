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
        ui.text(surface, f'{weather}  ·  {clock}  ·  {SEASONS[atmosphere.ground_mode]}',
                fonts.small, ui.TEXT, (24, 28), shadow=True)

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
        if atmosphere.speed >= atmosphere.MAX_SPEED:
            state, color = 'MACH 5 - SPEED LIMIT', ui.ACCENT
        elif refueling:
            state, color = 'Refueling', ui.GOOD
        elif atmosphere.boosting:
            state, color = 'Boost', ui.ACCENT
        elif atmosphere.fuel <= 0:
            state, color = 'Gliding', ui.ALERT
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
        pygame.draw.polygon(surface, ui.TEXT, [(center[0], center[1] - 7), (center[0] - 5, center[1] + 5),
                                               (center[0], center[1] + 2), (center[0] + 5, center[1] + 5)])
        for player in atmosphere.remote_players:
            # Drawn over your own arrow and pushed clear of it, so a wingman right beside you still shows.
            pos, inside = to_radar(player['x'],player['z'])
            dx, dy = pos[0] - center[0], pos[1] - center[1]
            length = math.hypot(dx, dy)
            if length < 11:
                dx, dy = (dx / length * 11, dy / length * 11) if length > 1e-6 else (0, -11)
                pos = (center[0] + dx, center[1] + dy)
            pygame.draw.circle(surface, ui.INK, pos, 6)
            pygame.draw.circle(surface, PILOT_COLOR, pos, 4)
        ui.label(surface, f'{self.radar_range / 1609.344:.0f} mi', fonts.tiny, (center[0], center[1] + radius + 6),
                 ui.DIM, 'midtop')

    def draw_crash(self, surface, atmosphere):
        fonts = self.fonts
        tint = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        tint.fill((120, 20, 10, int(110 * atmosphere.impact)))
        surface.blit(tint, (0, 0))
        ui.text(surface, 'CRASHED', fonts.h1, ui.TEXT, (640, 300), 'midtop', tracking=10, shadow=True)
        ui.text(surface, 'Recovering altitude…', fonts.body, ui.TEXT, (640, 352), 'midtop', shadow=True)


PILOT_COLOR = (90, 210, 245)


def marker(atmosphere, point, size, margin=40):
    """Where to mark a world point on a window of this size, using the shared camera:
    ('tag', x, y) when it is on screen, else ('edge', x, y, angle) for an arrow on the screen edge."""
    from camera import SCREEN_SCALE, basis, view_angles, view_origin
    right, up, forward = basis(*view_angles(atmosphere))
    relative = [p - o for p, o in zip(point, view_origin(atmosphere))]
    side, rise, depth = (sum(a * b for a, b in zip(relative, axis)) for axis in (right, up, forward))
    width, height = size
    if depth > 1:
        focal = height * SCREEN_SCALE
        x, y = width / 2 + side / depth * focal, height / 2 - rise / depth * focal
        if margin <= x <= width - margin and margin <= y <= height - margin:
            return 'tag', x, y
        dx, dy = x - width / 2, y - height / 2
    else:
        # Behind the camera: point the way you would turn to face it (mostly sideways, mid-height).
        dx, dy = side, -rise * 0.25
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            dx, dy = 0.0, 1.0
    stretch = min((width / 2 - margin) / max(abs(dx), 1e-9), (height / 2 - margin) / max(abs(dy), 1e-9))
    return 'edge', width / 2 + dx * stretch, height / 2 + dy * stretch, math.atan2(dy, dx)


# HUD areas (1280x720 HUD coordinates) that pilot labels must not cover: gauges, heading tape, race board,
# map and key hints. The countdown adds its number and caption.
HUD_ZONES = [(990, 0, 290, 114), (420, 8, 440, 92), (966, 118, 300, 262), (0, 440, 244, 280),
             (0, 18, 430, 34), (880, 640, 400, 80), (490, 96, 300, 72)]
COUNTDOWN_ZONE = (400, 186, 480, 130)


class PilotMarkers:
    """Name tags over other pilots and edge-of-screen arrows toward the ones out of view.

    A main-loop system: draw_world() paints the window-sized overlay that both renderers composite.
    Labels avoid the HUD panels and each other; nearer pilots get the first pick of space."""

    def __init__(self, game):
        self.game = game

    def race_mode(self):
        mode = self.game.mode
        return mode if mode is not None and mode.key == 'race' else None

    def places(self):
        """Race places to show in tags: only once a race is running or finished, never for pilots who left."""
        network = self.game.network
        info = network.race_state() if network else None
        mode = self.race_mode()
        if not info or info['phase'] not in ('racing', 'results', 'countdown'):
            return {}
        if info['phase'] == 'countdown' and not (mode and mode.started):
            return {}
        return {entry['id']: entry['place'] for entry in info['standings'] if entry['status'] != 'dnf'}

    def zones(self, size):
        scale, ox, oy = self.game.hud_transform
        boxes = list(HUD_ZONES)
        mode = self.race_mode()
        if mode and mode.phase == 'countdown' and not mode.started:
            boxes.append(COUNTDOWN_ZONE)
        return [pygame.Rect(round(x * scale + ox), round(y * scale + oy), round(w * scale), round(h * scale))
                for x, y, w, h in boxes]

    @staticmethod
    def free(rect, taken, bounds, step, horizontal=False, tries=8):
        """Slide rect along one axis (inside bounds) to the nearest spot clear of everything taken."""
        for index in range(tries * 2 + 1):
            shift = (index + 1) // 2 * step * (1 if index % 2 else -1)
            moved = rect.move((shift, 0) if horizontal else (0, shift)).clamp(bounds)
            if moved.collidelist(taken) < 0:
                return moved
        return None

    def draw_world(self, surface, atmosphere):
        if self.game.state not in ('flying', 'paused', 'results') or not atmosphere.remote_players:
            return
        from race import ordinal
        fonts = self.game.fonts
        places = self.places()
        size = surface.get_size()
        bounds = surface.get_rect().inflate(-8, -8)
        taken = self.zones(size)
        eye = atmosphere.camera
        pilots = sorted(atmosphere.remote_players, key=lambda p: math.dist(eye, (p['x'], p['y'], p['z'])))
        for player in pilots:
            point = (player['x'], player['y'] + 3, player['z'])
            name = player['name']
            if player['id'] in places:
                name = f'{ordinal(places[player["id"]])}  {name}'
            where = marker(atmosphere, point, size)
            reach = ui.format_distance(math.dist(eye, point))
            name_image = ui.render(name, fonts.small if where[0] == 'tag' else fonts.tiny, ui.TEXT)
            reach_image = ui.render(reach, fonts.tiny, PILOT_COLOR)
            label = pygame.Rect(0, 0, max(name_image.get_width(), reach_image.get_width()) + 6,
                                name_image.get_height() + reach_image.get_height())
            if where[0] == 'tag':
                _, x, y = where
                pygame.draw.polygon(surface, PILOT_COLOR, [(x, y - 4), (x - 7, y - 14), (x + 7, y - 14)])
                label.midbottom = (x, y - 16)
                spot = self.free(label, taken, bounds, -label.height // 2 or -8, tries=3)
            else:
                _, x, y, angle = where
                c, s = math.cos(angle), math.sin(angle)
                along_x = abs(c) < abs(s)  # arrow on the top or bottom edge slides sideways
                arrow = pygame.Rect(0, 0, 34, 34)
                arrow.center = (x, y)
                moved = self.free(arrow, taken, bounds, 18, along_x, tries=30)
                if moved:
                    x, y = moved.center
                    arrow = moved
                tip = (x + c * 16, y + s * 16)
                pygame.draw.polygon(surface, PILOT_COLOR, [tip, (x - s * 10, y + c * 10), (x + s * 10, y - c * 10)])
                label.center = (x - c * (22 + label.width / 2), y - s * (16 + label.height / 2))
                taken.append(arrow)
                spot = self.free(label, taken, bounds, label.height // 2 or 8, along_x)
            if spot is None:
                continue  # no clear room: the marker alone still shows the way
            taken.append(spot)
            ui.text(surface, name, fonts.small if where[0] == 'tag' else fonts.tiny, ui.TEXT,
                    (spot.centerx, spot.top), 'midtop', shadow=True)
            ui.text(surface, reach, fonts.tiny, PILOT_COLOR, (spot.centerx, spot.bottom), 'midbottom', shadow=True)
