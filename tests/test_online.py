import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pytest

from network import NetworkClient, RoomServer, clean_state


def aircraft(model='classic'):
    return SimpleNamespace(position=np.array([25.,-800.]),altitude=900.,heading=.3,bank=.1,
                           flight_pitch=.05,speed=100.,fuel=90.,plane_id=model)


def test_network_accepts_mach_five_and_rejects_faster():
    from units import MAX_FLIGHT_SPEED_MPS
    state = dict(x=0., y=700., z=0., heading=0., bank=0., flight_pitch=0.,
                 speed=MAX_FLIGHT_SPEED_MPS, fuel=100., model='classic')
    assert clean_state(state)['speed'] == MAX_FLIGHT_SPEED_MPS
    state['speed'] += .01
    with pytest.raises(ValueError, match='flight limits'):
        clean_state(state)


def test_two_clients_share_movement_models_and_disconnects():
    async def scenario():
        room = RoomServer(seed=42)
        port = await room.start(port=0)
        clients = []
        try:
            first = await asyncio.to_thread(NetworkClient,f'127.0.0.1:{port}','One','classic')
            clients.append(first)
            second = await asyncio.to_thread(NetworkClient,f'127.0.0.1:{port}','Two','f15')
            clients.append(second)
            assert first.player_id != second.player_id and first.welcome['seed'] == 42
            first.publish(aircraft('f15'))
            second.publish(aircraft())
            for _ in range(40):
                await asyncio.sleep(.05)
                peers = second.players()
                if peers and peers[0]['model'] == 'f15' and abs(peers[0]['x']-25) < .01:
                    break
            assert peers[0]['id'] == first.player_id
            assert peers[0]['model'] == 'f15' and peers[0]['y'] == pytest.approx(900)
            await asyncio.to_thread(first.close)
            for _ in range(20):
                await asyncio.sleep(.05)
                if not second.players():
                    break
            assert not second.players()
        finally:
            for client in clients:
                await asyncio.to_thread(client.close)
            await room.close()
    asyncio.run(scenario())


def test_full_room_rejects_extra_connections():
    async def scenario():
        room = RoomServer(max_players=1)
        port = await room.start(port=0)
        client = None
        try:
            client = await asyncio.to_thread(NetworkClient,f'127.0.0.1:{port}')
            with pytest.raises(ValueError,match='full'):
                await asyncio.to_thread(NetworkClient,f'127.0.0.1:{port}')
        finally:
            if client:
                await asyncio.to_thread(client.close)
            await room.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('value',[math.nan,math.inf,True,'bad'])
def test_invalid_network_state_is_rejected(value):
    state = dict(x=0.,y=700.,z=0.,heading=0.,bank=0.,flight_pitch=0.,speed=75.,fuel=100.,model='classic')
    state['x'] = value
    with pytest.raises(ValueError):
        clean_state(state)
