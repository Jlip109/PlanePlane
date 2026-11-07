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


class Keys(dict):
    """Stand-in for pygame.key.get_pressed(): unknown keys read as not pressed."""

    def __getitem__(self, key):
        return self.get(key, 0)


@pytest.fixture
def pg():
    pygame.init()
    pygame.display.set_mode((64, 36))
    yield pygame
    pygame.quit()


@pytest.fixture
def atmosphere(pg):
    return main.Atmosphere(pg)
