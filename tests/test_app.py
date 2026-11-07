import math
import os
import subprocess
import sys

import numpy as np
import pygame
import pytest

import camera
import main
import weather
import world
from camera import project, view_angles
from conftest import ROOT, Keys


def run_cli(*args, gpu=False):
    env = dict(os.environ)
    if gpu:
        env.pop('SDL_VIDEODRIVER', None)
    return subprocess.run([sys.executable, 'main.py', *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize('flag', ['--altitude', '--hour', '--cover', '--day-length', '--time'])
@pytest.mark.parametrize('value', ['nan', 'inf', '-inf', 'abc'])
def test_bad_numbers_are_rejected(flag, value):
    with pytest.raises(SystemExit) as error:
        main.parse_args([flag, value])
    assert error.value.code == 2


def test_cli_rejects_nan_without_traceback():
    result = run_cli('--headless', '--renderer', 'cpu', '--frames', '1', '--altitude', 'nan')
    assert result.returncode == 2
    assert 'finite' in result.stderr and 'Traceback' not in result.stderr


@pytest.mark.parametrize('extra', [
    ['--mode', 'menu'],
    ['--mode', 'free', '--preset', 'storm'],
    ['--mode', 'rings', '--hour', '23.5', '--preset', 'clear', '--ground', 'winter'],
    ['--mode', 'courier', '--pilot', 'tailwind', '--ground', 'yellow'],
    ['--game', '--altitude', '99999', '--cover', '5', '--day-length', '0', '--hour', '-7'],
])
def test_cpu_app_runs(extra, tmp_path):
    shot = tmp_path / 'shot.png'
    result = run_cli('--headless', '--renderer', 'cpu', '--frames', '8', '--fps', '0', '--seed', '1',
                     '--screenshot', str(shot), *extra)
    assert result.returncode == 0, result.stderr
    assert shot.exists()
    assert 'disabled' not in result.stdout


@pytest.mark.parametrize('mode', ['menu', 'courier'])
def test_gpu_app_runs(mode, tmp_path):
    shot = tmp_path / 'gpu.png'
    result = run_cli('--headless', '--renderer', 'gpu', '--frames', '8', '--fps', '0', '--seed', '1',
                     '--mode', mode, '--preset', 'storm', '--screenshot', str(shot), gpu=True)
    if result.returncode != 0 and 'GPU initialization failed' in result.stderr:
        pytest.skip('no OpenGL 3.3 context available')
    assert result.returncode == 0, result.stderr
    assert 'disabled' not in result.stdout
    image = pygame.image.load(str(shot))
    assert pygame.transform.average_color(image)[:3] != (0, 0, 0)


def test_sanitize_restores_bad_values(atmosphere):
    atmosphere.altitude, atmosphere.cover, atmosphere.storm = math.nan, math.inf, -math.inf
    atmosphere.position = np.array([math.nan, 3.0])
    atmosphere.sanitize()
    assert (atmosphere.altitude, atmosphere.cover, atmosphere.storm) == (1250.0, 0.58, 0.0)
    assert np.all(atmosphere.position == 0)


def test_update_survives_bad_dt_and_every_key(atmosphere, pg):
    keys = Keys({key: 1 for key in (pg.K_w, pg.K_d, pg.K_UP, pg.K_RIGHT, pg.K_PERIOD, pg.K_SPACE)})
    for dt in (math.nan, math.inf, -1.0, 1e9, 0.016):
        atmosphere.update(dt, keys)
    for name, value in vars(atmosphere).items():
        if isinstance(value, float):
            assert math.isfinite(value), name
    assert atmosphere.altitude <= main.MAX_ALTITUDE


def test_diving_into_the_ground_crashes_and_respawns(atmosphere, pg):
    keys = Keys({pg.K_s: 1})
    atmosphere.altitude = 400.0
    crashed = False
    for _ in range(400):
        atmosphere.update(0.05, keys)
        floor = world.obstacle_height(*atmosphere.position)
        assert atmosphere.altitude >= floor + 1.0
        crashed |= any(name == 'crash' for name, _ in atmosphere.events)
        atmosphere.events.clear()
        if crashed and not atmosphere.crashed:
            break
    assert crashed and atmosphere.crashes >= 1 and not atmosphere.crashed
    assert atmosphere.altitude > world.obstacle_height(*atmosphere.position) + 200


def test_flying_into_a_skyscraper_crashes(atmosphere):
    name, cx, cz, radius, style, _ = world.CITIES[1]
    place = (1, cx, cz, radius, world.CITY_LEVELS[1], style)
    i0, j0 = int(cx // world.CELL), int(cz // world.CELL)
    tower = max(((i, j) for i in range(i0 - 8, i0 + 8) for j in range(j0 - 8, j0 + 8)),
                key=lambda cell: world.lot_height(*cell, place))
    x, z = (tower[0] + 0.5) * world.CELL, (tower[1] + 0.5) * world.CELL
    roof = world.obstacle_height(x, z)
    assert roof > world.CITY_LEVELS[1] + 100
    atmosphere.position = np.array([x, z - 40.0])
    atmosphere.altitude = roof - 30
    atmosphere.heading = 0.0
    for _ in range(40):
        atmosphere.update(0.05, Keys())
        if atmosphere.crashed:
            break
    assert atmosphere.crashed


def test_boost_drains_and_recharges(atmosphere, pg):
    for _ in range(30):
        atmosphere.update(0.1, Keys({pg.K_SPACE: 1}))
    assert atmosphere.boost < 0.6 and atmosphere.speed > main.BASE_SPEED * 1.5
    for _ in range(40):
        atmosphere.update(0.1, Keys({pg.K_SPACE: 1}))
    assert atmosphere.boost_empty and not atmosphere.boosting
    atmosphere.update(0.5, Keys({pg.K_SPACE: 1}))
    assert not atmosphere.boosting  # no stutter while the tank refills
    for _ in range(200):
        atmosphere.update(0.1, Keys())
    assert atmosphere.boost == pytest.approx(1.0) and atmosphere.speed < main.BASE_SPEED * 1.05


@pytest.mark.parametrize('hour, preset, pitch, season', [
    (9, 'broken', 0.03, 0), (23.5, 'clear', 0.6, 0), (18.2, 'storm', -1.5, 1), (6, 'overcast', 1.5, 2),
])
def test_cpu_render_is_valid(atmosphere, hour, preset, pitch, season):
    atmosphere.hour, atmosphere.pitch, atmosphere.ground_mode = hour, pitch, season
    main.apply_preset(atmosphere, preset)
    atmosphere.update_lighting()
    atmosphere.camera = camera.compute_camera(atmosphere)
    image = atmosphere.render_array()
    assert image.shape == (main.Atmosphere.HEIGHT, main.Atmosphere.WIDTH, 3)
    assert np.all(np.isfinite(image)) and image.min() >= 0 and image.max() <= 255


def test_cpu_render_shows_a_city(atmosphere):
    atmosphere.position = np.array([0.0, 2400.0])
    atmosphere.altitude = 600.0
    atmosphere.pitch = -0.6
    atmosphere.camera = camera.compute_camera(atmosphere)
    image = atmosphere.render_array()
    roofs = (image[..., 0] > image[..., 1] * 1.25) & (image[..., 0] > 90)  # Troy's brick-red roofs
    assert roofs.sum() > 50


def test_night_sky_has_stars(atmosphere):
    atmosphere.hour, atmosphere.pitch = 0.0, 0.5
    main.apply_preset(atmosphere, 'clear')
    atmosphere.update_lighting()
    assert (atmosphere.render_array().max(axis=2) > 150).sum() > 5


def test_project_matches_cpu_renderer_rays(atmosphere):
    atmosphere.heading, atmosphere.look_yaw, atmosphere.pitch = 0.7, 0.2, -0.3
    atmosphere.position = np.array([1500.0, -800.0])
    atmosphere.camera = camera.compute_camera(atmosphere)
    width, height = 1280, 720
    atmosphere.aspect = width / height
    heading, pitch = view_angles(atmosphere)
    cx, cy, cz = atmosphere.camera
    for i, j in [(160, 90), (20, 10), (300, 170)]:
        sx = atmosphere.sx[j, i] * atmosphere.aspect / (16 / 9)
        sy = atmosphere.sy[j, i]
        dy = sy * math.cos(pitch) + math.sin(pitch)
        forward = math.cos(pitch) - sy * math.sin(pitch)
        dx = sx * math.cos(heading) + forward * math.sin(heading)
        dz = forward * math.cos(heading) - sx * math.sin(heading)
        x, y, _ = project(atmosphere, (cx + dx * 500, cy + dy * 500, cz + dz * 500), (width, height))
        assert x == pytest.approx(width / 2 + (i - 160) * width / 320, abs=1e-3)
        assert y == pytest.approx(height / 2 + (j - 90) * height / 180, abs=1e-3)


def test_project_ignores_points_behind_camera(atmosphere):
    behind = (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1] - 100)
    assert project(atmosphere, behind, (1280, 720)) is None


def test_camera_never_goes_underground(atmosphere):
    atmosphere.position = np.array([0.0, 3400.0])
    atmosphere.altitude = -500.0
    assert camera.compute_camera(atmosphere)[1] >= world.obstacle_height(0.0, 3400.0) + 3


def test_broken_system_is_disabled_not_fatal(capsys):
    class Broken:
        calls = 0

        def update(self, dt, atmosphere):
            Broken.calls += 1
            raise RuntimeError('boom')

    systems = [Broken()]
    for _ in range(3):
        main.call_systems(systems, 'update', 0.1, None)
    assert Broken.calls == 1
    assert 'disabled' in capsys.readouterr().out


def run_scripted(monkeypatch, plan, frames, extra=()):
    """Run the real game loop in-process, posting key events at given frames."""
    events = []

    class Script:
        frame = 0

        def update(self, dt, atmosphere):
            for item in plan.get(self.frame, []):
                if item == 'tiny':
                    pygame.display.set_mode((3, 2), pygame.RESIZABLE)
                elif isinstance(item, tuple):
                    pygame.event.post(pygame.event.Event(item[0], **item[1]))
                else:
                    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=item, mod=0, unicode=''))
            self.frame += 1

    real_build = main.build_systems
    monkeypatch.setattr(main, 'build_systems', lambda args: real_build(args) + [Script()])
    monkeypatch.setattr(weather, 'fetch_json', lambda url, params: (_ for _ in ()).throw(OSError('offline')))
    import game
    original = game.Game.update

    def spy(self, dt, sim_dt):
        original(self, dt, sim_dt)
        events.append(self.state)

    monkeypatch.setattr(game.Game, 'update', spy)
    main.main(['--headless', '--renderer', 'cpu', '--frames', str(frames), '--fps', '0', '--seed', '2', *extra])
    return events


def test_full_menu_flow_in_the_running_game(monkeypatch, capsys):
    k = pygame
    plan = {
        2: [k.K_DOWN, k.K_DOWN, k.K_DOWN, k.K_RETURN],    # Choose Pilot
        4: [k.K_RIGHT, k.K_RETURN],                        # pick the next pilot
        6: [k.K_UP, k.K_UP, k.K_RETURN],                   # Ring Run
        9: [k.K_4, k.K_l, k.K_g, k.K_p, k.K_RIGHTBRACKET, k.K_h],
        11: [k.K_h, k.K_ESCAPE],                           # pause
        13: [k.K_DOWN, k.K_RETURN],                        # restart
        15: ['tiny', k.K_ESCAPE],
        17: [k.K_DOWN, k.K_DOWN, k.K_RETURN],              # main menu
        19: [k.K_UP, k.K_UP, k.K_RETURN],                  # Sky Courier from the title (wraps to item 4? no: index math below)
        22: [(pygame.MOUSEMOTION, {'pos': (10, 10), 'rel': (1, 1), 'buttons': (0, 0, 0)}),
             (pygame.MOUSEBUTTONDOWN, {'pos': (10, 10), 'button': 1})],
    }
    states = run_scripted(monkeypatch, plan, 26)
    assert 'flying' in states and 'paused' in states and states.count('title') > 3
    assert 'disabled' not in capsys.readouterr().out


def test_quit_from_the_title_screen(monkeypatch):
    states = run_scripted(monkeypatch, {2: [pygame.K_ESCAPE]}, 50)
    assert len(states) < 10
