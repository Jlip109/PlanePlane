import math
import os
import subprocess
import sys

import numpy as np
import pygame
import pytest

import main
import weather
from camera import project, terrain_height, view_angles
from conftest import ROOT, Keys


def run_cli(*args, gpu=False):
    env = dict(os.environ)
    if gpu:
        env.pop('SDL_VIDEODRIVER', None)
    return subprocess.run([sys.executable, 'main.py', *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


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
    [],
    ['--preset', 'storm', '--game'],
    ['--hour', '23.5', '--preset', 'clear'],
    ['--altitude', '99999', '--cover', '5', '--day-length', '0', '--hour', '-7'],
])
def test_cpu_app_runs(extra, tmp_path):
    shot = tmp_path / 'shot.png'
    result = run_cli('--headless', '--renderer', 'cpu', '--frames', '8', '--fps', '0', '--seed', '1',
                     '--screenshot', str(shot), *extra)
    assert result.returncode == 0, result.stderr
    assert shot.exists()
    assert 'disabled' not in result.stdout


def test_gpu_app_runs(tmp_path):
    shot = tmp_path / 'gpu.png'
    result = run_cli('--headless', '--renderer', 'gpu', '--frames', '8', '--fps', '0', '--seed', '1',
                     '--preset', 'storm', '--game', '--screenshot', str(shot), gpu=True)
    if result.returncode != 0 and 'GPU initialization failed' in result.stderr:
        pytest.skip('no OpenGL 3.3 context available')
    assert result.returncode == 0, result.stderr
    assert 'disabled' not in result.stdout
    pixels = pygame.surfarray.array3d(pygame.image.load(shot))
    assert pixels.mean() > 5 and pixels.std() > 5  # Catch a colour mask left off by the aircraft depth pass.


def test_sanitize_restores_bad_values(atmosphere):
    atmosphere.altitude, atmosphere.cover, atmosphere.storm = math.nan, math.inf, -math.inf
    atmosphere.position = np.array([math.nan, 3.0])
    atmosphere.sanitize()
    assert (atmosphere.altitude, atmosphere.cover, atmosphere.storm) == (1250.0, 0.58, 0.0)
    assert np.all(atmosphere.position == 0)


def test_update_survives_bad_dt_and_every_key(atmosphere, pg):
    keys = Keys({key: 1 for key in (pg.K_w, pg.K_d, pg.K_UP, pg.K_RIGHT, pg.K_PERIOD)})
    for dt in (math.nan, math.inf, -1.0, 1e9, 0.016):
        atmosphere.update(dt, keys)
    for name, value in vars(atmosphere).items():
        if isinstance(value, float):
            assert math.isfinite(value), name
    assert atmosphere.altitude <= 5500


def test_plane_cannot_fly_into_hills(atmosphere, pg):
    keys = Keys({pg.K_s: 1, pg.K_a: 1})
    for _ in range(800):
        atmosphere.update(0.05, keys)
        assert atmosphere.altitude >= terrain_height(*atmosphere.position) + 39


@pytest.mark.parametrize('hour, preset, pitch', [
    (9, 'broken', 0.03), (23.5, 'clear', 0.6), (18.2, 'storm', -1.5), (6, 'overcast', 1.5),
])
def test_cpu_render_is_valid(atmosphere, hour, preset, pitch):
    atmosphere.hour, atmosphere.pitch = hour, pitch
    main.apply_preset(atmosphere, preset)
    atmosphere.update_lighting()
    image = atmosphere.render_array()
    assert image.shape == (main.Atmosphere.HEIGHT, main.Atmosphere.WIDTH, 3)
    assert np.all(np.isfinite(image)) and image.min() >= 0 and image.max() <= 255


def test_night_sky_has_stars(atmosphere):
    atmosphere.hour, atmosphere.pitch = 0.0, 0.5
    main.apply_preset(atmosphere, 'clear')
    atmosphere.update_lighting()
    assert (atmosphere.render_array().max(axis=2) > 150).sum() > 5


def test_project_matches_cpu_renderer_rays(atmosphere):
    atmosphere.heading, atmosphere.look_yaw, atmosphere.pitch = 0.7, 0.2, -0.3
    atmosphere.position = np.array([1500.0, -800.0])
    width, height = 1280, 720
    atmosphere.aspect = width / height
    heading, pitch = view_angles(atmosphere)
    for i, j in [(160, 90), (20, 10), (300, 170)]:
        # Same ray maths as Atmosphere.render_array for CPU pixel (i, j).
        sx = atmosphere.sx[j, i] * atmosphere.aspect / (16 / 9)
        sy = atmosphere.sy[j, i]
        dy = sy * math.cos(pitch) + math.sin(pitch)
        forward = math.cos(pitch) - sy * math.sin(pitch)
        dx = sx * math.cos(heading) + forward * math.sin(heading)
        dz = forward * math.cos(heading) - sx * math.sin(heading)
        point = (atmosphere.position[0] + dx * 500, atmosphere.altitude + dy * 500, atmosphere.position[1] + dz * 500)
        x, y, _ = project(atmosphere, point, (width, height))
        assert x == pytest.approx(width / 2 + (i - 160) * width / 320, abs=1e-3)
        assert y == pytest.approx(height / 2 + (j - 90) * height / 180, abs=1e-3)


def test_project_ignores_points_behind_camera(atmosphere):
    behind = (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1] - 100)
    assert project(atmosphere, behind, (1280, 720)) is None


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


def test_running_app_handles_keys_resize_and_offline_weather(monkeypatch, capsys):
    def offline(url, params):
        raise OSError('no network')

    monkeypatch.setattr(weather, 'fetch_json', offline)
    plan = {1: [pygame.K_n], 3: [pygame.K_4], 5: [pygame.K_l], 7: [pygame.K_g, pygame.K_p, pygame.K_RIGHTBRACKET],
            9: [pygame.K_1, pygame.K_n], 11: [pygame.K_n, pygame.K_l, pygame.K_r]}

    class Script:
        frame = 0

        def update(self, dt, atmosphere):
            for key in plan.get(self.frame, []):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0))
            if self.frame == 6:
                pygame.display.set_mode((3, 2), pygame.RESIZABLE)
            self.frame += 1

    real_build = main.build_systems
    monkeypatch.setattr(main, 'build_systems', lambda args: real_build(args) + [Script()])
    main.main(['--headless', '--renderer', 'cpu', '--frames', '16', '--fps', '0', '--seed', '2'])
    assert 'disabled' not in capsys.readouterr().out
