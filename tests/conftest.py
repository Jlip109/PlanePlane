import os
import sys
from pathlib import Path

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402
import pytest  # noqa: E402

import main  # noqa: E402
from characters import Radio  # noqa: E402
from scores import Scores  # noqa: E402


class Keys(dict):
    """Stand-in for pygame.key.get_pressed(): unknown keys read as not pressed."""

    def __getitem__(self, key):
        return self.get(key, 0)


class FakeGame:
    """The bits of game.Game that modes use."""

    def __init__(self, folder):
        self.scores = Scores(Path(folder) / 'scores.json')
        self.radio = Radio()
        self.flashes = []
        self.sounds = []

    def flash(self, message, color):
        self.flashes.append(message)

    def sound(self, name):
        self.sounds.append(name)


@pytest.fixture(autouse=True)
def isolated_saves(tmp_path, monkeypatch):
    monkeypatch.setenv('PLANEPLANE_HOME', str(tmp_path / 'home'))


@pytest.fixture
def pg():
    pygame.init()
    pygame.display.set_mode((64, 36))
    yield pygame
    pygame.quit()


@pytest.fixture
def atmosphere(pg):
    return main.Atmosphere(pg)


@pytest.fixture
def fonts(pg):
    from ui import Fonts
    return Fonts()


@pytest.fixture
def fake_game(tmp_path):
    return FakeGame(tmp_path)
