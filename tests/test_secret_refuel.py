from types import SimpleNamespace

import pygame
import pytest

from test_features import make_game,press


@pytest.mark.parametrize('mode',['free','rings','practice'])
@pytest.mark.parametrize('paused',[False,True])
def test_f6_refills_offline_tank(atmosphere,fonts,tmp_path,mode,paused):
    game=make_game(atmosphere,fonts,tmp_path,mode)
    if paused:game.state='paused'
    atmosphere.fuel=0
    press(game,pygame.K_F6)
    assert atmosphere.fuel==100 and atmosphere.gallons==20


@pytest.mark.parametrize('mode',['free','ffa'])
def test_f6_cannot_refuel_network_games_even_solo_practice(atmosphere,fonts,tmp_path,mode):
    game=make_game(atmosphere,fonts,tmp_path,mode)
    game.network=SimpleNamespace(status='Connected',race={'practice':True})
    atmosphere.fuel=7
    press(game,pygame.K_F6)
    assert atmosphere.fuel==7
