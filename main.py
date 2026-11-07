"""Plane² atmospheric flight study. Run with Python 3.10+ and requirements.txt."""

import argparse
import math
import os
from pathlib import Path
import time
import traceback

import numpy as np

from camera import terrain_height, view_angles, view_origin
from units import FEET_PER_METRE, MPH_PER_MPS

PRESETS = {  # cover, wind, precipitation, storm
    'clear': (0.18, 5, 0.0, 0.0),
    'broken': (0.58, 12, 0.0, 0.0),
    'overcast': (0.92, 29, 0.45, 0.0),
    'storm': (0.97, 38, 1.0, 1.0),
}


def smoothstep(low, high, value):
    value = np.clip((value - low) / (high - low), 0, 1)
    return value * value * (3 - 2 * value)


def finite(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not a number') from None
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f'{text!r} is not a finite number')
    return value


def star_field(dx, dy, dz, ray_length, night, cover, t):
    # Hash the ray direction into small angular cells; a few cells become stars.
    azimuth = np.arctan2(dz, dx)
    elevation = np.arcsin(np.clip(dy / ray_length, -1, 1))
    angular = np.stack((azimuth, elevation), axis=-1) * 180
    cell_x, cell_y = np.floor(angular[..., 0]), np.floor(angular[..., 1])
    hashed = np.mod(np.sin(cell_x * 12.9898 + cell_y * 78.233) * 43758.5453, 1)
    twinkle = 0.75 + 0.25 * np.sin(t * 3 + hashed * 400)
    offset = np.mod(angular, 1) - 0.5
    spot = 1 - smoothstep(0.14, 0.27, np.linalg.norm(offset, axis=-1))
    return (hashed > 0.996) * spot * smoothstep(0.0, 0.12, dy / ray_length) * twinkle * night * (1 - cover * 0.9)


class Atmosphere:
    WIDTH = 320
    HEIGHT = 180
    FOCAL = WIDTH * 0.52
    CRUISE_SPEED = 75.0
    MAX_SPEED = 340.294  # Standard sea-level speed of sound at 59 degrees Fahrenheit, in m/s.
    FUEL_CAPACITY_GALLONS = 20.0

    def __init__(self, pygame):
        self.pg = pygame
        assets = Path(__file__).parent / "assets"
        texture = pygame.surfarray.array3d(pygame.image.load(assets / "Cloud.png"))
        self.texture = texture.mean(axis=2).astype(np.float32) / 255
        self.palette = pygame.surfarray.array3d(pygame.image.load(assets / "skycolors.png")).astype(np.float32)
        x, y = np.meshgrid(np.arange(self.WIDTH), np.arange(self.HEIGHT))
        self.sx = ((x - self.WIDTH / 2) / self.FOCAL).astype(np.float32)
        self.sy = ((self.HEIGHT / 2 - y) / self.FOCAL).astype(np.float32)
        self.aspect = 16 / 9
        self.altitude = 1250.0
        self.heading = 0.0
        self.pitch = 0.03
        self.look_yaw = 0.0
        self.hour = 9.0
        self.day_length = 240.0
        self.cycle_paused = False
        self.ground_mode = 0
        self.position = np.array([0.0, 0.0])
        self.elapsed = 0.0
        self.phase = 0.0
        self.cover = 0.58
        self.wind = 12.0
        self.wind_angle = 0.6
        self.speed = self.CRUISE_SPEED
        self.fuel = 100.0
        self.boosting = False
        self.third_person = False
        self.bank = 0.0
        self.flight_pitch = 0.0
        self.risk = 0.0
        self.drift = np.zeros(2)
        self.precipitation = 0.0
        self.storm = 0.0
        self.flash = 0.0
        self.weather_label = 'SIMULATED WEATHER'
        self.defaults = {name: value for name, value in vars(self).items() if isinstance(value, float)}

    def sanitize(self):
        # Never let NaN/inf reach the renderers; a bad value resets to its starting default.
        for name, default in self.defaults.items():
            if not math.isfinite(getattr(self, name)):
                setattr(self, name, default)
        for name in ('position', 'drift'):
            if not np.all(np.isfinite(getattr(self, name))):
                setattr(self, name, np.zeros(2))

    @property
    def mach(self):
        return self.speed / self.MAX_SPEED

    @property
    def moon_direction(self):
        return -self.sun_direction

    @property
    def sun_direction(self):
        angle = (self.hour - 6) / 24 * math.tau
        return np.array([math.cos(angle) * 0.6, math.sin(angle), math.cos(angle) * 0.8], dtype=np.float32)

    @property
    def ground_color(self):
        return [(0.07, 0.19, 0.09), (0.65, 0.53, 0.16), (0.86, 0.89, 0.91)][self.ground_mode]

    def update_lighting(self):
        self.hour %= 24
        self.phase = float(1 - smoothstep(-0.20, 0.20, self.sun_direction[1]))

    def mouse_look(self, relative):
        self.look_yaw = (self.look_yaw + relative[0] * 0.0025 + math.pi) % math.tau - math.pi
        self.pitch = float(np.clip(self.pitch - relative[1] * 0.0025, -1.5, 1.5))

    def sample_cloud(self, u, v):
        # Mirrored repeats keep the supplied non-periodic texture edges continuous.
        width, height = self.texture.shape
        u = (width - 1) - np.abs(np.mod(u, 2 * (width - 1)) - (width - 1))
        v = (height - 1) - np.abs(np.mod(v, 2 * (height - 1)) - (height - 1))
        x = u.astype(np.int32)
        y = v.astype(np.int32)
        fx, fy = u - x.astype(np.float32), v - y.astype(np.float32)
        x1, y1 = np.minimum(x + 1, width - 1), np.minimum(y + 1, height - 1)
        return ((self.texture[x, y] * (1 - fx) + self.texture[x1, y] * fx) * (1 - fy)
                + (self.texture[x, y1] * (1 - fx) + self.texture[x1, y1] * fx) * fy)

    def update(self, dt, keys):
        pg = self.pg
        dt = min(max(dt, 0.0), 0.15) if math.isfinite(dt) else 0.0
        self.elapsed += dt
        self.boosting = bool(keys[pg.K_SPACE] and self.fuel > 0)
        target_speed = self.MAX_SPEED if self.boosting else (self.CRUISE_SPEED if self.fuel > 0 else 45.0)
        acceleration = 35.0 if self.boosting else 25.0
        self.speed += float(np.clip(target_speed - self.speed, -acceleration * dt, acceleration * dt))
        self.speed = float(np.clip(self.speed, 0, self.MAX_SPEED))
        fast = max(float(self.boosting), float(np.clip(
            (self.speed - self.CRUISE_SPEED) / (self.MAX_SPEED - self.CRUISE_SPEED), 0, 1)))
        control = 1 - fast * 0.55
        turn = keys[pg.K_d] - keys[pg.K_a]
        climb = (keys[pg.K_w] - keys[pg.K_s]) * control if self.fuel > 0 else -0.025
        self.heading += turn * dt * 0.55 * control
        self.bank += (-turn * 0.40 * control - self.bank) * (1 - math.exp(-dt * 5))
        self.flight_pitch += (climb * 0.30 - self.flight_pitch) * (1 - math.exp(-dt * 3))
        burn = 0.08 + 0.48 * self.boosting + max(0, climb) * 0.06
        self.fuel = max(0.0, self.fuel - burn * dt)
        self.pitch = float(np.clip(self.pitch + (keys[pg.K_UP] - keys[pg.K_DOWN]) * dt * 0.35, -1.5, 1.5))
        self.altitude = float(np.clip(self.altitude + climb * dt * 430, 180, 5500))
        if not self.cycle_paused:
            self.hour += dt * 24 / self.day_length
        self.hour += (keys[pg.K_RIGHT] - keys[pg.K_LEFT]) * dt * 2
        self.update_lighting()
        self.wind = float(np.clip(self.wind + (keys[pg.K_PERIOD] - keys[pg.K_COMMA]) * dt * 9, 0, 45))
        self.position += np.array([math.sin(self.heading), math.cos(self.heading)]) * self.speed * dt
        self.drift += np.array([math.sin(self.wind_angle), math.cos(self.wind_angle)]) * self.wind * dt
        # Hills reach 230 m, above the old 180 m floor, so keep the plane clear of the terrain.
        floor = terrain_height(self.position[0], self.position[1]) + 40
        self.altitude = max(self.altitude, floor)
        # An intentionally game-like exposure metric, not an aviation model.
        self.risk = float(np.clip(max(0, self.altitude - 1800) / 3700 * 68 + self.wind / 45 * 32, 0, 100))
        self.sanitize()

    def render(self):
        return self.pg.surfarray.make_surface(np.transpose(self.render_array().astype(np.uint8), (1, 0, 2)))

    def render_array(self):
        t = self.elapsed
        origin = view_origin(self)
        heading, pitch = view_angles(self)
        dy = self.sy * math.cos(pitch) + math.sin(pitch)
        forward = math.cos(pitch) - self.sy * math.sin(pitch)
        sx = self.sx * self.aspect / (16 / 9)
        dx = sx * math.cos(heading) + forward * math.sin(heading)
        dz = forward * math.cos(heading) - sx * math.sin(heading)

        column = self.phase * (self.palette.shape[0] - 1)
        left = int(column)
        right = min(left + 1, self.palette.shape[0] - 1)
        gradient = self.palette[left] * (1 - column + left) + self.palette[right] * (column - left)
        # Palette top is zenith, bottom is horizon. Looking down reveals haze.
        vertical = np.clip(1 - dy / 0.65, 0, 1) * (len(gradient) - 1)
        index = vertical.astype(np.int32)
        next_index = np.minimum(index + 1, len(gradient) - 1)
        fraction = (vertical - index.astype(np.float32))[..., None]
        sky = gradient[index] * (1 - fraction) + gradient[next_index] * fraction
        luminance = sky.mean(axis=2, keepdims=True)
        sky = sky * (1 - self.cover * 0.68) + luminance * self.cover * 0.68
        sky *= 1 - self.cover * 0.21
        sun = self.sun_direction
        ray_length = np.sqrt(dx * dx + dy * dy + dz * dz)
        alignment = (dx * sun[0] + dy * sun[1] + dz * sun[2]) / ray_length
        disk = smoothstep(math.cos(0.025), math.cos(0.019), alignment)
        glow = np.exp((alignment - 1) * 160) * 0.25
        visibility = float(smoothstep(-0.035, 0.02, sun[1]))
        sun_color = np.array([255, 205 + 45 * max(0, sun[1]), 125 + 110 * max(0, sun[1])])
        sky = sky * (1 - disk[..., None] * visibility) + sun_color * (disk + glow)[..., None] * visibility
        night = float(smoothstep(0.55, 1.0, self.phase))
        if night > 0:
            moon = self.moon_direction
            moon_alignment = (dx * moon[0] + dy * moon[1] + dz * moon[2]) / ray_length
            moon_disk = smoothstep(math.cos(0.022), math.cos(0.017), moon_alignment) * night * (1 - self.cover * 0.6)
            sky = sky * (1 - moon_disk[..., None]) + np.array([226, 232, 240]) * moon_disk[..., None]
            sky = sky + star_field(dx, dy, dz, ray_length, night, self.cover, t)[..., None] * 230
        scene = self.draw_ground(sky, dx, dy, dz)

        layers = [(850, 0.52, 0.85, 24), (1450, 0.43, 1.0, 97),
                  (2150, 0.32, 1.23, 161), (3000, 0.20, 1.5, 233)]
        layers = sorted(layers, key=lambda layer: abs(layer[0] - self.altitude), reverse=True)
        for base, opacity, wind_scale, seed in layers:
            elevation = base + math.sin(t * 0.065 + seed) * (35 + self.cover * 65)
            delta = elevation - origin[1]
            distance = delta / np.where(np.abs(dy) > 0.008, dy, 0.008)
            valid = (distance > 0) & (np.abs(dy) > 0.008)
            distance = np.clip(distance, 0, 20000)
            world_x = (origin[0] + dx * distance - self.drift[0] * wind_scale).astype(np.float32)
            world_z = (origin[2] + dz * distance - self.drift[1] * wind_scale).astype(np.float32)
            density = self.sample_cloud(world_x / 11 + seed, world_z / 11 + seed * 2)
            threshold = 0.83 - self.cover * 0.53 + (base / 3000) * 0.09
            alpha = smoothstep(threshold - 0.06, threshold + 0.20, density)
            alpha *= opacity * valid * (1 - smoothstep(6000, 18000, distance))
            night = smoothstep(0.55, 1.0, self.phase)
            light = 1 - night * 0.79
            cloud_color = np.array([220, 228, 234], dtype=np.float32) * light
            sunset = math.exp(-((self.phase - 0.48) / 0.17) ** 2)
            cloud_color = cloud_color * (1 - sunset * 0.30) + np.array([242, 167, 134], dtype=np.float32) * sunset * 0.30
            shade = (0.70 + density * 0.30)[..., None]
            scene = scene * (1 - alpha[..., None]) + cloud_color * shade * alpha[..., None]
            # Thin volume around each plane prevents a hard cut while crossing it.
            fog = math.exp(-(delta / 95) ** 2) * self.cover * opacity * 0.75
            scene = scene * (1 - fog) + cloud_color * fog
        return np.clip(np.nan_to_num(scene), 0, 255)

    def draw_ground(self, sky, dx, dy, dz):
        origin = view_origin(self)
        safe_dy = np.minimum(dy, -0.008)
        distance = np.maximum(0, (100 - origin[1]) / safe_dy)
        for _ in range(4):
            x, z = origin[0] + dx * distance, origin[2] + dz * distance
            height = 100 + 130 * np.sin(x / 1700) * np.cos(z / 1500)
            distance = np.maximum(0, (height - origin[1]) / safe_dy)
        x, z = origin[0] + dx * distance, origin[2] + dz * distance
        edge = np.minimum(np.abs((x + 210) % 420 - 210), np.abs((z + 210) % 420 - 210))
        line = 1 - smoothstep(0, np.clip(distance / self.FOCAL, 2, 70), edge)
        daylight = float(smoothstep(-0.12, 0.35, self.sun_direction[1]))
        ground = np.array(self.ground_color) * (0.09 + daylight * 0.91) * 255
        shaded = ground * (1 - line[..., None] * 0.28)
        haze = smoothstep(2500, 18000, distance)[..., None]
        ground_scene = shaded * (1 - haze) + sky * haze
        return np.where((dy < -0.008)[..., None], ground_scene, sky)


class DisplayControls:
    def __init__(self, pygame):
        self.pg = pygame
        self.fullscreen = False
        self.mouse_looking = False
        self.windowed_size = pygame.display.get_window_size()

    def toggle_fullscreen(self):
        from pygame._sdl2.video import Window
        native_window = Window.from_display_module()
        if self.fullscreen:
            native_window.set_windowed()
            native_window.size = self.windowed_size
        else:
            self.windowed_size = native_window.size
            native_window.set_fullscreen(desktop=True)
        self.fullscreen = not self.fullscreen

    def grab_mouse(self, enabled):
        self.mouse_looking = enabled
        self.pg.event.set_grab(enabled)
        self.pg.mouse.set_visible(not enabled)
        self.pg.mouse.get_rel()


def draw_hud(pg, surface, atmosphere, fonts, renderer, fps):
    font, small, title = fonts
    ink = (221, 245, 240)
    surface.fill((0, 0, 0, 0))
    pg.draw.rect(surface, (8, 20, 29, 190), (0, 0, 1280, 100))
    surface.blit(title.render('PLANE² / ATMOSPHERE STUDY', True, ink), (28, 19))
    minutes = int(atmosphere.hour * 60) % 1440
    clock_text = f'{minutes // 60:02d}:{minutes % 60:02d}'
    cycle_text = 'PAUSED' if atmosphere.cycle_paused else f'{atmosphere.day_length:g}S / DAY'
    if not atmosphere.cycle_paused and atmosphere.day_length >= 86400:
        cycle_text = 'REAL TIME'
    subtitle = f'{atmosphere.weather_label}    /    {clock_text}    /    {cycle_text}'
    surface.blit(small.render(subtitle, True, (143, 184, 187)), (29, 58))
    stats = (f'{atmosphere.altitude * FEET_PER_METRE:05.0f} FT   |   '
             f'WIND {atmosphere.wind * MPH_PER_MPS:02.0f} MPH   |   COVER {atmosphere.cover:.0%}')
    surface.blit(font.render(stats, True, ink), (715, 24))
    risk = f'ALTITUDE EXPOSURE  {atmosphere.risk:02.0f}%'
    surface.blit(small.render(risk, True, (245, 190, 127)), (715, 57))
    surface.blit(small.render(f'{renderer} {fps:.0f} FPS', True, ink), (1130, 57))
    engine = 'BOOST' if atmosphere.boosting else ('CRUISE' if atmosphere.fuel > 0 else 'GLIDING')
    at_limit = atmosphere.speed >= atmosphere.MAX_SPEED
    if at_limit:
        engine = 'MACH 1 - SPEED OF SOUND'
    # Truncate below the limit so rounding cannot announce Mach 1 prematurely.
    displayed_mach = math.floor(atmosphere.mach * 100) / 100
    gallons = atmosphere.fuel / 100 * atmosphere.FUEL_CAPACITY_GALLONS
    flight = (f'{atmosphere.speed * MPH_PER_MPS:05.1f} MPH   MACH {displayed_mach:.2f}   '
              f'FUEL {gallons:04.1f} US GAL   {engine}')
    surface.blit(small.render(flight, True, (255, 214, 140)), (29, 80))
    pg.draw.line(surface, ink, (608, 360), (628, 360), 1)
    pg.draw.line(surface, ink, (652, 360), (672, 360), 1)
    pg.draw.circle(surface, ink, (640, 360), 4, 1)
    pg.draw.rect(surface, (8, 20, 29, 205), (0, 626, 1280, 94))
    ground_name = ['GREEN', 'YELLOW', 'WHITE'][atmosphere.ground_mode]
    lines = [
        'W/S altitude   A/D heading   SPACE boost   Hold RIGHT MOUSE to orbit   R reset   V view   N rings',
        'F11 or ALT+ENTER fullscreen   LEFT/RIGHT time   P pause cycle   [/] cycle speed   L live weather',
        f'1 clear   2 broken   3 overcast   4 storm   ,/. wind   G ground ({ground_name})   ESC release / exit',
    ]
    for row, text in enumerate(lines):
        surface.blit(small.render(text, True, ink), (28, 642 + row * 24))


def call_systems(systems, method, *args):
    for system in systems:
        handler = getattr(system, method, None)
        if handler is None:
            continue
        try:
            handler(*args)
        except Exception:
            # One broken feature shouldn't take the whole flight down; report it and switch it off.
            print(f'{type(system).__name__}.{method} failed and was disabled:')
            traceback.print_exc()
            setattr(system, method, None)


def build_systems(args):
    from effects import WeatherEffects
    from game import RingRun
    from weather import LiveWeather
    return [LiveWeather(args.city), WeatherEffects(args.seed), RingRun(args.seed, args.game)]


def apply_preset(atmosphere, name):
    atmosphere.cover, atmosphere.wind, atmosphere.precipitation, atmosphere.storm = PRESETS[name]


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--renderer', choices=['auto', 'gpu', 'cpu'], default='auto')
    parser.add_argument('--fps', type=int, default=60, help='Frame cap. Use 0 for uncapped benchmarking.')
    parser.add_argument('--frames', type=int, default=0)
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--altitude', type=finite, default=1250 * FEET_PER_METRE,
                        help='Starting altitude in feet')
    parser.add_argument('--time', type=finite, default=None, help='Legacy palette position, 0 day to 1 night')
    parser.add_argument('--hour', type=finite, default=9.0, help='Starting hour in the 24-hour cycle')
    parser.add_argument('--day-length', type=finite, default=240.0, help='Real seconds per simulated 24 hours')
    parser.add_argument('--ground', choices=['green', 'yellow', 'white'], default='green')
    parser.add_argument('--cover', type=finite, default=0.58)
    parser.add_argument('--preset', choices=list(PRESETS), help='Starting weather (overrides --cover)')
    parser.add_argument('--city', help='Start with live weather for a city, e.g. "Troy, NY"')
    parser.add_argument('--game', action='store_true', help='Start a ring run right away')
    parser.add_argument('--seed', type=int, default=None, help='Seed for rings and lightning')
    parser.add_argument('--camera', choices=['third', 'first'], default='third', help='Starting camera view')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    use_gpu = args.renderer == 'gpu' or (args.renderer == 'auto' and not args.headless)
    if args.headless and not use_gpu:
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
    import pygame
    pygame.init()
    gpu = None
    if use_gpu:
        try:
            from gpu_renderer import GPURenderer
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
            pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
            flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
            if args.headless:
                flags |= pygame.HIDDEN
            window = pygame.display.set_mode((1280, 720), flags, vsync=0)
            gpu = GPURenderer(pygame)
            print(f'OpenGL renderer: {gpu.name}')
        except Exception as error:
            if args.renderer == 'gpu':
                pygame.quit()
                raise RuntimeError(f'GPU initialization failed: {error}. Try --renderer cpu.') from error
            print(f'GPU unavailable, using CPU renderer: {error}')
    if gpu is None:
        window = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    pygame.display.set_caption('Plane² | Atmosphere prototype')
    font = pygame.font.SysFont('consolas', 18)
    small = pygame.font.SysFont('consolas', 14)
    title = pygame.font.SysFont('consolas', 27, bold=True)
    fonts = (font, small, title)
    atmosphere = Atmosphere(pygame)
    atmosphere.third_person = args.camera == 'third'
    atmosphere.altitude = float(np.clip(args.altitude / FEET_PER_METRE, 180, 5500))
    atmosphere.hour = args.hour % 24
    if args.time is not None:
        atmosphere.hour = (12 + float(np.clip(args.time, 0, 1)) * 12) % 24
    atmosphere.day_length = float(np.clip(args.day_length, 1.0, 86400))
    atmosphere.ground_mode = ['green', 'yellow', 'white'].index(args.ground)
    atmosphere.update_lighting()
    atmosphere.cover = float(np.clip(args.cover, 0, 1))
    if args.preset:
        apply_preset(atmosphere, args.preset)
    systems = build_systems(args)
    from plane import PlaneModel
    plane = PlaneModel()
    if gpu:
        gpu.set_plane(plane)
    clock = pygame.time.Clock()
    running, frames = True, 0
    start = time.perf_counter()
    display_controls = DisplayControls(pygame)
    if args.fullscreen:
        display_controls.toggle_fullscreen()
    hud = pygame.Surface((1280, 720), pygame.SRCALPHA)
    overlay = pygame.Surface(pygame.display.get_window_size(), pygame.SRCALPHA)
    captured = None
    while running:
        dt = min(clock.tick(max(0, args.fps)) / 1000, 0.15)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if display_controls.mouse_looking:
                        display_controls.grab_mouse(False)
                    else:
                        running = False
                if event.key == pygame.K_F11 or (event.key == pygame.K_RETURN and event.mod & pygame.KMOD_ALT):
                    display_controls.toggle_fullscreen()
                if event.key == pygame.K_r:
                    atmosphere.look_yaw, atmosphere.pitch = 0.0, 0.03
                if event.key == pygame.K_v:
                    atmosphere.third_person = not atmosphere.third_person
                if event.key == pygame.K_g:
                    atmosphere.ground_mode = (atmosphere.ground_mode + 1) % 3
                if event.key == pygame.K_p:
                    atmosphere.cycle_paused = not atmosphere.cycle_paused
                if event.key == pygame.K_LEFTBRACKET:
                    atmosphere.day_length = min(86400, atmosphere.day_length * 2)
                if event.key == pygame.K_RIGHTBRACKET:
                    atmosphere.day_length = max(10, atmosphere.day_length / 2)
                presets = {pygame.K_1: 'clear', pygame.K_2: 'broken', pygame.K_3: 'overcast', pygame.K_4: 'storm'}
                if event.key in presets:
                    apply_preset(atmosphere, presets[event.key])
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                display_controls.grab_mouse(True)
            if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                display_controls.grab_mouse(False)
            if event.type == pygame.MOUSEMOTION and display_controls.mouse_looking:
                atmosphere.mouse_look(event.rel)
            if event.type == pygame.WINDOWFOCUSLOST:
                display_controls.grab_mouse(False)
            call_systems(systems, 'handle_event', event, atmosphere)
        atmosphere.update(dt, pygame.key.get_pressed())
        call_systems(systems, 'update', dt, atmosphere)
        atmosphere.sanitize()
        width, height = pygame.display.get_window_size()
        # A minimized window can report 0x0; skip drawing rather than scaling to nothing.
        if width > 0 and height > 0:
            atmosphere.aspect = width / height
            if gpu:
                gpu.render(atmosphere, (width, height))
            else:
                window = pygame.display.get_surface()
                view = atmosphere.render()
                pygame.transform.smoothscale(view, (width, height), window)
                plane.draw_world(window, atmosphere)
            draw_hud(pygame, hud, atmosphere, fonts, 'GPU' if gpu else 'CPU', clock.get_fps())
            call_systems(systems, 'draw_hud', hud, atmosphere, fonts)
            scale = min(width / 1280, height / 720)
            hud_size = (max(1, round(1280 * scale)), max(1, round(720 * scale)))
            if overlay.get_size() != (width, height):
                overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 0))
            call_systems(systems, 'draw_world', overlay, atmosphere)
            scaled_hud = pygame.transform.smoothscale(hud, hud_size)
            overlay.blit(scaled_hud, ((width - hud_size[0]) // 2, (height - hud_size[1]) // 2))
            if gpu:
                gpu.draw_hud(overlay)
            else:
                window.blit(overlay, (0, 0))
            if args.screenshot and ((args.frames and frames + 1 >= args.frames) or not running):
                captured = gpu.screenshot((width, height)) if gpu else window.copy()
        pygame.display.flip()
        frames += 1
        if args.frames and frames >= args.frames:
            running = False
    if args.screenshot:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(captured if captured is not None else window, args.screenshot)
    if gpu:
        gpu.context.finish()
    duration = max(time.perf_counter() - start, 1e-6)
    print(f'{frames} frames in {duration:.2f}s ({frames / duration:.1f} FPS average)')
    call_systems(systems, 'close')
    display_controls.grab_mouse(False)
    if gpu:
        gpu.close()
    pygame.quit()


if __name__ == '__main__':
    main()
