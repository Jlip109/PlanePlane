import pygame
import pytest

from conftest import Keys


def test_acceleration_is_doubled_and_release_slows_normally(atmosphere):
    initial = atmosphere.speed
    atmosphere.update(0.1, Keys({pygame.K_SPACE: 1}))
    assert atmosphere.speed - initial == pytest.approx(7)
    initial = atmosphere.speed
    atmosphere.update(0.1, Keys())
    assert initial - atmosphere.speed == pytest.approx(2.5)
