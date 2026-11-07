"""Plane² atmospheric flight study. Run with Python 3.10+ and requirements.txt."""

import argparse
import math
import os
from pathlib import Path
import time
import traceback

import numpy as np

import world
from camera import compute_camera, view_angles

DEFAULT_PITCH = 0.03
PRESETS = {  # cover, wind, precipitation, storm
    'clear': (0.18, 5, 0.0, 0.0),
    'broken': (0.58, 12, 0.0, 0.0),
    'overcast': (0.92, 29, 0.45, 0.0),
    'storm': (0.97, 38, 1.0, 1.0),
}


def smoothstep(low, high, value):
    value = np.clip((value - low) / (high - low), 0, 1)
    return value * value * (3 - 2 * value)


def load_image(pygame, path):
    try:
        return pygame.image.load(path)
    except (FileNotFoundError, pygame.error) as error:
        raise SystemExit(f'Could not load {path.name} from {path.parent} ({error}). '
                         'Make sure the assets folder is next to main.py.') from error


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
    cell_x, cell_y = np.floor(azimuth * 180), np.floor(elevation * 180)
    hashed = np.mod(np.sin(cell_x * 12.9898 + cell_y * 78.233) * 43758.5453, 1)
    twinkle = 0.75 + 0.25 * np.sin(t * 3 + hashed * 400)
    return (hashed > 0.996) * smoothstep(0.0, 0.12, dy / ray_length) * twinkle * night * (1 - cover * 0.9)


CLOUD_LAYERS = [(850, 0.52, 0.85, 24), (1450, 0.43, 1.0, 97), (2150, 0.32, 1.23, 161), (3000, 0.20, 1.5, 233)]
BASE_SPEED = 75.0
MAX_ALTITUDE = 5500.0


class NoKeys:
    """Key state with nothing pressed (menus, autopilot, crashes)."""

    def __getitem__(self, key):
        return 0


class Atmosphere:
    WIDTH = 320
    HEIGHT = 180
    FOCAL = WIDTH * 0.52

    def __init__(self, pygame):
        self.pg = pygame
        assets = Path(__file__).parent / "assets"
        texture = pygame.surfarray.array3d(load_image(pygame, assets / "Cloud.png"))
        self.texture = texture.mean(axis=2).astype(np.float32) / 255
        self.palette = pygame.surfarray.array3d(load_image(pygame, assets / "skycolors.png")).astype(np.float32)
        x, y = np.meshgrid(np.arange(self.WIDTH), np.arange(self.HEIGHT))
        self.sx = ((x - self.WIDTH / 2) / self.FOCAL).astype(np.float32)
        self.sy = ((self.HEIGHT / 2 - y) / self.FOCAL).astype(np.float32)
        self.aspect = 16 / 9
        self.altitude = 1250.0
        self.heading = 0.0
        self.pitch = DEFAULT_PITCH
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
        self.speed = BASE_SPEED
        self.vertical_speed = 0.0
        self.turn_rate = 0.0
        self.bank = 0.0
        self.flight_pitch = 0.0
        self.boost = 1.0
        self.impact = 0.0
        self.crash_timer = 0.0
        self.risk = 0.0
        self.drift = np.zeros(2)
        self.precipitation = 0.0
        self.storm = 0.0
        self.flash = 0.0
        self.speed_scale = 1.0
        self.handling = 1.0
        self.boost_scale = 1.0
        self.defaults = {name: value for name, value in vars(self).items() if isinstance(value, float)}
        self.weather_label = 'SIMULATED WEATHER'
        self.boosting = False
        self.boost_empty = False
        self.autopilot = False
        self.crashes = 0
        self.events = []
        self.camera = compute_camera(self)

    def emit(self, name, **data):
        self.events.append((name, data))

    def sanitize(self):
        # Never let NaN/inf reach the renderers; a bad value resets to its starting default.
        for name, default in self.defaults.items():
            if not math.isfinite(getattr(self, name)):
                setattr(self, name, default)
        for name in ('position', 'drift'):
            if not np.all(np.isfinite(getattr(self, name))):
                setattr(self, name, np.zeros(2))
        self.altitude = min(self.altitude, MAX_ALTITUDE)

    @property
    def moon_direction(self):
        return -self.sun_direction

    @property
    def sun_direction(self):
        angle = (self.hour - 6) / 24 * math.tau
        return np.array([math.cos(angle) * 0.6, math.sin(angle), math.cos(angle) * 0.8], dtype=np.float32)

    @property
    def crashed(self):
        return self.crash_timer > 0

    def update_lighting(self):
        self.hour %= 24
        self.phase = float(1 - smoothstep(-0.20, 0.20, self.sun_direction[1]))

    def mouse_look(self, relative):
        self.look_yaw = (self.look_yaw + relative[0] * 0.0025 + math.pi) % math.tau - math.pi
        self.pitch = float(np.clip(self.pitch - relative[1] * 0.0025, -1.5, 1.5))

    def reset_view(self):
        self.look_yaw, self.pitch = 0.0, DEFAULT_PITCH

    def cloud_layers(self):
        """(elevation, opacity, wind scale, seed) for each cloud deck, farthest from the camera first."""
        layers = []
        for base, opacity, wind_scale, seed in CLOUD_LAYERS:
            elevation = base + math.sin(self.elapsed * 0.065 + seed) * (35 + self.cover * 65)
            layers.append((elevation, opacity, wind_scale, seed))
        return sorted(layers, key=lambda layer: abs(layer[0] - self.camera[1]), reverse=True)

    def cloud_cover_between(self, point):
        """How much cloud (0..1) hides a world point from the camera; used to tuck overlays behind clouds."""
        cx, cy, cz = self.camera
        hidden = 0.0
        for elevation, opacity, wind_scale, seed in CLOUD_LAYERS:
            elevation = elevation + math.sin(self.elapsed * 0.065 + seed) * (35 + self.cover * 65)
            if (cy - elevation) * (point[1] - elevation) >= 0:
                continue
            t = (elevation - cy) / (point[1] - cy)
            x = cx + (point[0] - cx) * t - self.drift[0] * wind_scale
            z = cz + (point[2] - cz) * t - self.drift[1] * wind_scale
            density = float(self.sample_cloud(np.array([x / 11 + seed]), np.array([z / 11 + seed * 2]))[0])
            threshold = 0.83 - self.cover * 0.53 + (elevation / 3000) * 0.09
            alpha = float(smoothstep(threshold - 0.06, threshold + 0.20, density)) * opacity
            hidden = 1 - (1 - hidden) * (1 - alpha)
        return hidden

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

    def autopilot_keys(self):
        """Gentle sightseeing circuit for the title screen."""
        pg = self.pg
        target = 700 + 250 * math.sin(self.elapsed * 0.05)
        keys = {pg.K_d: 1 if math.sin(self.elapsed * 0.03) > 0.2 else 0,
                pg.K_w: 1 if self.altitude < target - 40 else 0,
                pg.K_s: 1 if self.altitude > target + 40 else 0}
        return lambda key: keys.get(key, 0)

    def update(self, dt, keys):
        pg = self.pg
        dt = min(max(dt, 0.0), 0.15) if math.isfinite(dt) else 0.0
        self.elapsed += dt
        press = self.autopilot_keys() if self.autopilot else keys.__getitem__
        if self.crashed:
            press = NoKeys().__getitem__
            self.crash_timer -= dt
            if self.crash_timer <= 0:
                self.respawn()
        self.fly(dt, press)
        self.pitch = float(np.clip(self.pitch + (press(pg.K_UP) - press(pg.K_DOWN)) * dt * 0.35, -1.5, 1.5))
        if not self.cycle_paused:
            self.hour += dt * 24 / self.day_length
        self.hour += (press(pg.K_RIGHT) - press(pg.K_LEFT)) * dt * 2
        self.update_lighting()
        self.wind = float(np.clip(self.wind + (press(pg.K_PERIOD) - press(pg.K_COMMA)) * dt * 9, 0, 45))
        self.drift += np.array([math.sin(self.wind_angle), math.cos(self.wind_angle)]) * self.wind * dt
        self.impact = max(0.0, self.impact - dt * 1.5)
        # An intentionally game-like exposure metric, not an aviation model.
        self.risk = float(np.clip(max(0, self.altitude - 1800) / 3700 * 68 + self.wind / 45 * 32, 0, 100))
        self.sanitize()
        self.camera = compute_camera(self)

    def fly(self, dt, press):
        pg = self.pg
        if self.crashed:
            self.speed = 0.0
            self.vertical_speed = 0.0
            return
        follow = min(1.0, dt * 3 * self.handling)
        self.turn_rate += ((press(pg.K_d) - press(pg.K_a)) * 0.62 * self.handling - self.turn_rate) * follow
        self.heading = (self.heading + self.turn_rate * dt + math.pi) % math.tau - math.pi
        self.bank = self.turn_rate * 1.15
        self.vertical_speed += ((press(pg.K_w) - press(pg.K_s)) * 190 - self.vertical_speed) * min(1.0, dt * 2.5)
        # An empty tank has to refill a little before boost works again, so it doesn't stutter.
        if self.boost <= 0.02:
            self.boost_empty = True
        elif self.boost >= 0.25:
            self.boost_empty = False
        self.boosting = bool(press(pg.K_SPACE)) and not self.boost_empty
        if self.boosting:
            self.boost = max(0.0, self.boost - dt * 0.22 / self.boost_scale)
        else:
            self.boost = min(1.0, self.boost + dt * 0.09)
        target_speed = BASE_SPEED * self.speed_scale * (2.0 if self.boosting else 1.0)
        self.speed += (target_speed - self.speed) * min(1.0, dt * 1.5)
        self.flight_pitch = math.atan2(self.vertical_speed, max(self.speed, 1.0))
        self.altitude += self.vertical_speed * dt
        if self.altitude > MAX_ALTITUDE:
            self.altitude, self.vertical_speed = MAX_ALTITUDE, min(self.vertical_speed, 0.0)
        self.position += np.array([math.sin(self.heading), math.cos(self.heading)]) * self.speed * dt
        floor = world.obstacle_height(self.position[0], self.position[1])
        if self.altitude < floor + 1.5:
            self.altitude = floor + 1.5
            self.crash()

    def crash(self):
        if self.crashed:
            return
        self.crash_timer = 2.5
        self.crashes += 1
        self.impact = 1.0
        self.emit('crash', position=(self.position[0], self.altitude, self.position[1]))

    def respawn(self):
        self.crash_timer = 0.0
        floor = world.obstacle_height(self.position[0], self.position[1])
        self.altitude = min(MAX_ALTITUDE, max(self.altitude, floor) + 300)
        self.vertical_speed = self.turn_rate = self.bank = self.flight_pitch = 0.0
        self.speed = BASE_SPEED * self.speed_scale
        self.emit('respawn')

    def render(self):
        return self.pg.surfarray.make_surface(np.transpose(self.render_array().astype(np.uint8), (1, 0, 2)))

    def render_array(self):
        t = self.elapsed
        heading, pitch = view_angles(self)
        dy = self.sy * math.cos(pitch) + math.sin(pitch)
        forward = math.cos(pitch) - self.sy * math.sin(pitch)
        sx = self.sx * self.aspect / (16 / 9)
        dx = sx * math.cos(heading) + forward * math.sin(heading)
        dz = forward * math.cos(heading) - sx * math.sin(heading)
        camera_x, camera_y, camera_z = self.camera

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
        scene, ground_distance = self.draw_ground(sky, dx, dy, dz, night)

        night_dim = 1 - night * 0.79
        sunset = math.exp(-((self.phase - 0.48) / 0.17) ** 2)
        cloud_color = np.array([220, 228, 234], dtype=np.float32) * night_dim
        cloud_color = cloud_color * (1 - sunset * 0.30) + np.array([242, 167, 134], dtype=np.float32) * sunset * 0.30
        for elevation, opacity, wind_scale, seed in self.cloud_layers():
            delta = elevation - camera_y
            distance = delta / np.where(np.abs(dy) > 0.008, dy, 0.008)
            valid = (distance > 0) & (np.abs(dy) > 0.008) & (distance < ground_distance)
            distance = np.clip(distance, 0, 20000)
            world_x = (camera_x + dx * distance - self.drift[0] * wind_scale).astype(np.float32)
            world_z = (camera_z + dz * distance - self.drift[1] * wind_scale).astype(np.float32)
            density = self.sample_cloud(world_x / 11 + seed, world_z / 11 + seed * 2)
            base = elevation - math.sin(t * 0.065 + seed) * (35 + self.cover * 65)
            threshold = 0.83 - self.cover * 0.53 + (base / 3000) * 0.09
            alpha = smoothstep(threshold - 0.06, threshold + 0.20, density)
            alpha *= opacity * valid * (1 - smoothstep(6000, 18000, distance))
            shade = (0.70 + density * 0.30)[..., None]
            scene = scene * (1 - alpha[..., None]) + cloud_color * shade * alpha[..., None]
            # Thin volume around each plane prevents a hard cut while crossing it.
            fog = math.exp(-(delta / 95) ** 2) * self.cover * opacity * 0.75
            scene = scene * (1 - fog) + cloud_color * fog
        return np.clip(np.nan_to_num(scene), 0, 255)

    def draw_ground(self, sky, dx, dy, dz, night):
        """Flat-shaded countryside and rooftops (the GPU path adds 3D buildings)."""
        camera_x, camera_y, camera_z = self.camera
        below = dy < -0.008
        safe_dy = np.minimum(dy[below], -0.008)
        rx, rz = dx[below], dz[below]
        distance = np.maximum(0, (world.raw_terrain_np(camera_x, camera_z) - camera_y) / safe_dy)
        x, z = camera_x + rx * distance, camera_z + rz * distance
        # Which town each pixel lands in barely changes between iterations, so look it up once.
        places = world.settlements_np(x, z)
        for _ in range(3):
            distance = np.maximum(0, (world.ground_height_np(x, z, places) - camera_y) / safe_dy)
            x, z = camera_x + rx * distance, camera_z + rz * distance
        color, lamps = world.land_color_np(x, z, distance, self.ground_mode, night, places)
        daylight = float(smoothstep(-0.12, 0.35, self.sun_direction[1]))
        light = 0.09 + daylight * 0.85
        ground = color * light * 255 + np.array([255, 184, 97]) * (lamps * 0.9)[..., None]
        haze = smoothstep(2500, 18000, distance)[..., None]
        scene = sky.copy()
        scene[below] = ground * (1 - haze) + sky[below] * haze
        ground_distance = np.full(dy.shape, np.inf)
        ground_distance[below] = distance
        return scene, ground_distance


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
    from life import SkyLife
    from weather import LiveWeather
    return [LiveWeather(args.city), WeatherEffects(args.seed), SkyLife(args.seed)]


def apply_preset(atmosphere, name):
    atmosphere.cover, atmosphere.wind, atmosphere.precipitation, atmosphere.storm = PRESETS[name]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Plane\u00b2: a flight through a living sky.')
    parser.add_argument('--mode', choices=['menu', 'free', 'rings', 'courier'], default='menu',
                        help='Skip the title screen and start a mode')
    parser.add_argument('--pilot', help='Pilot by name or callsign, e.g. "mei" or "tailwind"')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--renderer', choices=['auto', 'gpu', 'cpu'], default='auto')
    parser.add_argument('--fps', type=int, default=60, help='Frame cap. Use 0 for uncapped benchmarking.')
    parser.add_argument('--frames', type=int, default=0)
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--mute', action='store_true')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--altitude', type=finite, default=None)
    parser.add_argument('--time', type=finite, default=None, help='Legacy palette position, 0 day to 1 night')
    parser.add_argument('--hour', type=finite, default=9.0, help='Starting hour in the 24-hour cycle')
    parser.add_argument('--day-length', type=finite, default=240.0, help='Real seconds per simulated 24 hours')
    parser.add_argument('--ground', choices=['green', 'yellow', 'white', 'summer', 'autumn', 'winter'],
                        default='summer', help='Season (green/yellow/white are the old names)')
    parser.add_argument('--cover', type=finite, default=0.58)
    parser.add_argument('--preset', choices=list(PRESETS), help='Starting weather (overrides --cover)')
    parser.add_argument('--city', help='Start with live weather for a city, e.g. "Troy, NY"')
    parser.add_argument('--game', action='store_true', help='Same as --mode rings')
    parser.add_argument('--seed', type=int, default=None, help='Seed for rings, jobs, birds and lightning')
    args = parser.parse_args(argv)
    if args.game:
        args.mode = 'rings'
    return args


SEASON_NAMES = {'green': 0, 'yellow': 1, 'white': 2, 'summer': 0, 'autumn': 1, 'winter': 2}


def open_window(pygame, args):
    use_gpu = args.renderer == 'gpu' or (args.renderer == 'auto' and not args.headless)
    gpu = None
    if use_gpu:
        try:
            from gpu_renderer import GPURenderer
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
            flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
            if args.headless:
                flags |= pygame.HIDDEN
            pygame.display.set_mode((1280, 720), flags, vsync=0)
            gpu = GPURenderer(pygame, offscreen=args.headless)
            print(f'OpenGL renderer: {gpu.name}')
        except Exception as error:
            if args.renderer == 'gpu':
                pygame.quit()
                raise RuntimeError(f'GPU initialization failed: {error}. Try --renderer cpu.') from error
            print(f'GPU unavailable, using CPU renderer: {error}')
    if gpu is None:
        pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    pygame.display.set_caption('Plane\u00b2')
    return gpu


def main(argv=None):
    args = parse_args(argv)
    use_gpu = args.renderer == 'gpu' or (args.renderer == 'auto' and not args.headless)
    if args.headless and not use_gpu:
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
    if args.headless:
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
    import pygame
    from audio import Audio
    from game import Game
    import ui
    from ui import Fonts
    pygame.init()
    gpu = open_window(pygame, args)
    window = pygame.display.get_surface()
    fonts = Fonts()
    atmosphere = Atmosphere(pygame)
    atmosphere.hour = args.hour % 24
    if args.time is not None:
        atmosphere.hour = (12 + float(np.clip(args.time, 0, 1)) * 12) % 24
    atmosphere.day_length = float(np.clip(args.day_length, 1.0, 86400))
    atmosphere.ground_mode = SEASON_NAMES[args.ground]
    atmosphere.update_lighting()
    atmosphere.cover = float(np.clip(args.cover, 0, 1))
    if args.preset:
        apply_preset(atmosphere, args.preset)
    audio = Audio(pygame, enabled=not args.headless and not args.mute)
    game = Game(atmosphere, fonts, audio, args.mode, args.pilot, args.seed)
    if args.altitude is not None:
        atmosphere.altitude = float(np.clip(args.altitude, 180, MAX_ALTITUDE))
    systems = build_systems(args)
    clock = pygame.time.Clock()
    running, frames = True, 0
    start = time.perf_counter()
    display_controls = DisplayControls(pygame)
    if args.fullscreen:
        display_controls.toggle_fullscreen()
    hud = pygame.Surface((1280, 720), pygame.SRCALPHA)
    overlay = pygame.Surface(pygame.display.get_window_size(), pygame.SRCALPHA)
    captured = None
    shade_cache = [None, None]
    presets = {pygame.K_1: 'clear', pygame.K_2: 'broken', pygame.K_3: 'overcast', pygame.K_4: 'storm'}
    while running:
        dt = min(clock.tick(max(0, args.fps)) / 1000, 0.15)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and (
                    event.key == pygame.K_F11 or (event.key == pygame.K_RETURN and event.mod & pygame.KMOD_ALT)):
                display_controls.toggle_fullscreen()
                continue
            if game.flying:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        atmosphere.reset_view()
                    elif event.key == pygame.K_g:
                        atmosphere.ground_mode = (atmosphere.ground_mode + 1) % 3
                    elif event.key == pygame.K_p:
                        atmosphere.cycle_paused = not atmosphere.cycle_paused
                    elif event.key == pygame.K_LEFTBRACKET:
                        atmosphere.day_length = min(86400, atmosphere.day_length * 2)
                    elif event.key == pygame.K_RIGHTBRACKET:
                        atmosphere.day_length = max(10, atmosphere.day_length / 2)
                    elif event.key in presets:
                        apply_preset(atmosphere, presets[event.key])
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    display_controls.grab_mouse(True)
                if event.type == pygame.MOUSEMOTION and display_controls.mouse_looking:
                    atmosphere.mouse_look(event.rel)
                call_systems(systems, 'handle_event', event, atmosphere)
            if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                display_controls.grab_mouse(False)
            if event.type == pygame.WINDOWFOCUSLOST:
                display_controls.grab_mouse(False)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and display_controls.mouse_looking:
                display_controls.grab_mouse(False)
                continue
            game.handle_event(event)
        if game.quit_requested:
            running = False
        if not game.flying and display_controls.mouse_looking:
            display_controls.grab_mouse(False)
        sim_dt = 0.0 if game.paused else dt
        keys = pygame.key.get_pressed() if game.flying else NoKeys()
        atmosphere.update(sim_dt, keys)
        call_systems(systems, 'update', sim_dt, atmosphere)
        game.update(dt, sim_dt)
        atmosphere.sanitize()
        width, height = pygame.display.get_window_size()
        # A minimized window can report 0x0; skip drawing rather than scaling to nothing.
        if width > 0 and height > 0:
            atmosphere.aspect = width / height
            shade = game.scene_shade()
            if gpu:
                if not args.headless and args.fps > 0:
                    gpu.adapt(clock.get_fps(), dt)
                gpu.render(atmosphere, (width, height))
                gpu.draw_shade(*shade)
            else:
                window = pygame.display.get_surface()
                view = atmosphere.render()
                pygame.transform.smoothscale(view, (width, height), window)
                key = ((width, height), shade)
                if shade_cache[0] != key:
                    shade_cache[:] = [key, ui.scene_shade((width, height), *shade)]
                window.blit(shade_cache[1], (0, 0))
            hud.fill((0, 0, 0, 0))
            renderer = f'GPU {gpu.scale:.0%}' if gpu and gpu.scale < 1 else ('GPU' if gpu else 'CPU')
            game.draw_hud(hud, clock.get_fps(), renderer)
            scale = min(width / 1280, height / 720)
            hud_size = (max(1, round(1280 * scale)), max(1, round(720 * scale)))
            offset = ((width - hud_size[0]) // 2, (height - hud_size[1]) // 2)
            game.hud_transform = (scale, *offset)
            if overlay.get_size() != (width, height):
                overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 0))
            call_systems(systems, 'draw_world', overlay, atmosphere)
            game.draw_world(overlay)
            # Composite in premultiplied alpha so scaled text keeps clean edges at any window size.
            composite = overlay.premul_alpha()
            scaled_hud = hud.premul_alpha()
            if hud_size != (1280, 720):
                scaled_hud = pygame.transform.smoothscale(scaled_hud, hud_size)
            composite.blit(scaled_hud, offset, special_flags=pygame.BLEND_PREMULTIPLIED)
            if gpu:
                gpu.draw_hud(composite)
            else:
                window.blit(composite, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
            if args.screenshot and ((args.frames and frames + 1 >= args.frames) or not running):
                captured = gpu.screenshot((width, height)) if gpu else window.copy()
        atmosphere.events.clear()
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
    audio.close()
    display_controls.grab_mouse(False)
    if gpu:
        gpu.close()
    pygame.quit()


if __name__ == '__main__':
    main()
