import asyncio
import json
import math
import socket
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

import race
from network import VERSION, NetworkClient, RoomServer, clean_race, clean_state, encode


def state(**changes):
    base = dict(x=0., y=700., z=-900., heading=0., bank=0., flight_pitch=0., speed=75., fuel=100., model='classic')
    base.update(changes)
    return base


# ------------------------------------------------------------------ course


def test_course_is_deterministic_per_seed_and_matches_ring_mode(fake_game):
    import modes
    first, again, other = race.course(1234), race.course(1234), race.course(1235)
    assert first == again and first != other and len(first) == race.GATES
    for x, y, z, nx, nz in first:
        assert y >= 300 and math.isclose(nx * nx + nz * nz, 1)
    # The single-player ring generator shares the same code path.
    run = modes.RingRun(fake_game, seed=1234)
    run.cursor = race.START
    run.rings = []
    run.add_ring(first=True)
    for _ in range(race.GATES - 1):
        run.add_ring()
    assert run.rings == first
    # First gate straight ahead of the start line, gates evenly spaced.
    assert first[0][0] == pytest.approx(0) and first[0][2] == pytest.approx(race.START[2] + race.SPACING)
    for a, b in zip(first, first[1:]):
        assert math.dist((a[0], a[2]), (b[0], b[2])) == pytest.approx(race.SPACING)


def test_minimum_times_and_grid_slots():
    rings = race.course(9)
    times = race.minimum_times(rings)
    assert all(b > a for a, b in zip(times, times[1:]))
    assert times[0] == pytest.approx(math.dist(race.START[:3], rings[0][:3]) / race.MAX_FLIGHT_SPEED_MPS)
    slots = {race.grid_slot(i)[::2] for i in range(12)}
    assert len(slots) == 12 and all(race.grid_slot(i)[2] < race.START[2] for i in range(12))
    assert [race.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == [
        '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st']


# ------------------------------------------------------------------ protocol


def test_state_race_fields_default_for_version_one_clients():
    clean = clean_state(state())
    assert clean['racing'] is False and clean['gates'] == 0 and clean['round'] == 0 and clean['finish'] is None
    clean = clean_state(state(racing=True, round=3, gates=4, finish=None))
    assert clean['racing'] and clean['round'] == 3 and clean['gates'] == 4
    assert clean_state(state(racing=True, round=3, gates=12, finish=61))['finish'] == 61.0


@pytest.mark.parametrize('field,value', [
    ('racing', 1), ('racing', 'yes'), ('gates', -1), ('gates', race.GATES + 1), ('gates', 2.0), ('gates', True),
    ('round', -1), ('round', 'x'), ('finish', math.nan), ('finish', math.inf), ('finish', -1.0), ('finish', True),
    ('finish', '12'), ('finish', 1e6)])
def test_invalid_race_fields_are_rejected(field, value):
    with pytest.raises(ValueError):
        clean_state(state(**{field: value}))


def test_race_snapshot_validation():
    director = race.RaceDirector(seed=3, countdown=1)
    director.tick(10.0, {'a': ('Ann', True)})
    info = json.loads(json.dumps(director.snapshot(10.0)))
    clean = clean_race(info)
    assert clean['phase'] == 'countdown' and clean['standings'][0]['name'] == 'Ann'
    for broken in ({'phase': 'party'}, dict(info, seed='x'), dict(info, start=math.inf),
                   dict(info, gates=99), dict(info, standings='no'),
                   dict(info, standings=[dict(info['standings'][0], status='winning')]),
                   dict(info, standings=[dict(info['standings'][0], place=-1)]),
                   dict(info, standings=[dict(info['standings'][0], gap=math.nan)])):
        with pytest.raises(ValueError):
            clean_race(broken)


# ------------------------------------------------------------------ race director


def through(director, player_id, gate, now, **extra):
    """A legitimate report of passing gate number `gate` (1-based), from just past its centre."""
    x, y, z, nx, nz = director.rings[gate - 1]
    claim = state(x=x + nx * 20, y=y, z=z + nz * 20, racing=True, round=director.round, gates=gate)
    claim.update(extra)
    return director.report(player_id, claim, now)


def fly(director, player_id, gates, start, pace, peers):
    now = start
    for gate in range(1, gates + 1):
        now += pace
        director.tick(now, peers)
        assert through(director, player_id, gate, now)
    return now


def test_round_cycle_lobby_race_results_and_new_seed():
    director = race.RaceDirector(seed=1, countdown=5, results=10, gates=4)
    peers = {'a': ('Ann', True), 'b': ('Bo', True), 'x': ('Watcher', False)}
    director.tick(0.0, peers)
    assert director.phase == 'countdown' and director.round == 1 and set(director.racers) == {'a', 'b'}
    first_seed = director.seed
    assert director.rings == race.course(first_seed, 4)
    # No progress counts before the start.
    assert through(director, 'a', 1, 2.0) and director.racers['a']['times'] == []
    director.tick(5.0, peers)
    assert director.phase == 'racing'
    fly(director, 'a', 4, 5.0, 2.0, peers)
    fly(director, 'b', 4, 5.0, 3.0, peers)
    director.tick(18.0, peers)
    assert director.phase == 'results'
    standings = director.standings()
    assert [(e['id'], e['place'], e['status']) for e in standings] == [('a', 1, 'finished'), ('b', 2, 'finished')]
    assert standings[0]['finish'] == pytest.approx(8.0) and standings[1]['finish'] == pytest.approx(12.0)
    assert standings[1]['gap'] == pytest.approx(4.0) and standings[0]['gap'] is None
    director.tick(27.0, peers)
    assert director.phase == 'results'
    director.tick(28.5, peers)
    assert director.phase == 'countdown' and director.round == 2 and director.seed != first_seed
    assert all(not racer['times'] for racer in director.racers.values())


def test_live_order_by_gates_then_time_and_gap():
    director = race.RaceDirector(seed=2, countdown=0, gates=6)
    peers = {'a': ('Ann', True), 'b': ('Bo', True), 'c': ('Cy', True)}
    director.tick(0.0, peers)
    director.tick(0.1, peers)
    assert through(director, 'b', 1, 2.0) and through(director, 'a', 1, 2.5)
    assert through(director, 'b', 2, 4.0)
    order = director.standings()
    assert [e['id'] for e in order] == ['b', 'a', 'c']
    assert [e['place'] for e in order] == [1, 2, 3]
    assert order[1]['gap'] == pytest.approx(0.5) and order[2]['gap'] is None


def test_ties_share_a_place():
    director = race.RaceDirector(seed=4, countdown=0, gates=3)
    peers = {'a': ('Ann', True), 'b': ('Bo', True)}
    director.tick(0.0, peers)
    director.tick(0.0, peers)
    for gate in (1, 2, 3):
        assert through(director, 'a', gate, gate * 2.0)
        assert through(director, 'b', gate, gate * 2.0)
    places = [e['place'] for e in director.standings()]
    assert places == [1, 1]
    assert [e['place'] for e in race.RaceDirector().standings()] == []
    # Before anyone moves, everyone is level on the grid.
    fresh = race.RaceDirector(seed=4, countdown=0)
    fresh.tick(0.0, peers)
    assert [e['place'] for e in fresh.standings()] == [1, 1]


def test_cheating_reports_are_rejected():
    director = race.RaceDirector(seed=5, countdown=0, gates=4)
    peers = {'a': ('Ann', True)}
    director.tick(0.0, peers)
    director.tick(0.0, peers)
    assert director.phase == 'racing'
    assert not through(director, 'a', 2, 5.0)  # skipping a gate
    assert not through(director, 'a', 1, 0.01)  # faster than Mach 5 from the start line
    far = state(x=5000., y=900., z=5000., racing=True, round=1, gates=1)
    assert not director.report('a', far, 5.0)  # nowhere near the gate
    assert through(director, 'a', 1, 5.0, round=99)  # stale round: ignored, not counted
    assert director.racers['a']['times'] == [] and director.rejected == 3
    assert through(director, 'a', 1, 5.0) and not through(director, 'a', 1 + 2, 6.0)
    assert not director.report('a', state(racing=True, round=1, gates=0), 7.0)  # going backwards
    assert through(director, 'a', 2, 8.0) and through(director, 'a', 3, 9.0)
    # Finish claims must be physically possible and not much earlier than the server heard them.
    assert through(director, 'a', 4, 10.0, finish=0.2)
    assert director.racers['a']['finish'] == pytest.approx(10.0)
    # A strayed client that is not in the race cannot add itself.
    assert through(director, 'zz', 1, 10.0) and 'zz' not in director.racers


def test_honest_finish_claim_within_latency_is_kept():
    director = race.RaceDirector(seed=6, countdown=0, gates=2)
    peers = {'a': ('Ann', True)}
    director.tick(0.0, peers)
    director.tick(0.0, peers)
    assert through(director, 'a', 1, 3.0) and through(director, 'a', 2, 6.0, finish=5.7)
    assert director.racers['a']['finish'] == pytest.approx(5.7)


def test_joins_and_leaves_at_any_moment():
    director = race.RaceDirector(seed=7, countdown=5, results=4, gates=3)
    director.tick(0.0, {'a': ('Ann', True)})
    director.tick(1.0, {'a': ('Ann', True), 'b': ('Bo', True)})  # joins the countdown
    assert set(director.racers) == {'a', 'b'}
    assert director.racers['b']['slot'] == 1
    director.tick(2.0, {'b': ('Bo', True)})  # a leaves before the start
    assert set(director.racers) == {'b'}
    director.tick(3.0, {'a': ('Ann', True), 'b': ('Bo', True)})  # a returns and reuses the free slot
    assert director.racers['a']['slot'] == 0
    peers = {'a': ('Ann', True), 'b': ('Bo', True), 'c': ('Cy', True)}
    director.tick(5.0, peers)
    assert director.phase == 'racing' and 'c' in director.racers  # joined in the last tick before GO
    director.tick(5.5, dict(peers, d=('Late', True)))
    assert 'd' not in director.racers  # late joiners spectate
    assert through(director, 'a', 1, 6.0)
    director.remove('a')  # disconnects mid-race: DNF but kept in the results
    del peers['a']
    director.tick(6.5, peers)
    assert director.phase == 'racing'
    entry = {e['id']: e for e in director.standings()}
    assert entry['a']['status'] == 'dnf' and entry['a']['gates'] == 1
    assert director.standings()[-1]['id'] == 'a'
    director.tick(7.0, {'c': ('Cy', False), 'd': ('Late', True)})  # b leaves, c switches to free flight
    assert director.phase == 'results'
    director.tick(11.5, {'d': ('Late', True)})
    assert director.phase == 'countdown' and set(director.racers) == {'d'} and director.round == 2


def test_everyone_leaving_ends_the_round_and_the_room_idles():
    director = race.RaceDirector(seed=8, countdown=2, results=3)
    director.tick(0.0, {'a': ('Ann', True)})
    director.tick(1.0, {})
    assert director.phase == 'waiting' and not director.racers
    director.tick(2.0, {'a': ('Ann', True)})
    director.tick(4.5, {'a': ('Ann', True)})
    assert director.phase == 'racing'
    director.tick(5.0, {})
    assert director.phase == 'results'
    director.tick(9.0, {})
    assert director.phase == 'waiting'
    assert director.snapshot(9.0)['standings'] == []


def test_time_limit_and_finish_grace_end_the_race():
    director = race.RaceDirector(seed=9, countdown=0, limit=100, grace=10, gates=2)
    peers = {'a': ('Ann', True), 'b': ('Bo', True)}
    director.tick(0.0, peers)
    director.tick(0.0, peers)
    assert through(director, 'a', 1, 2.0) and through(director, 'a', 2, 4.0)
    director.tick(13.9, peers)
    assert director.phase == 'racing'
    director.tick(14.1, peers)
    assert director.phase == 'results'
    assert [e['status'] for e in director.standings()] == ['finished', 'racing']
    slow = race.RaceDirector(seed=9, countdown=0, limit=100)
    slow.tick(0.0, peers)
    slow.tick(99.0, peers)
    assert slow.phase == 'racing'
    slow.tick(100.0, peers)
    assert slow.phase == 'results'


# ------------------------------------------------------------------ server details


def test_new_pilots_spawn_beside_the_room_and_version_one_still_joins():
    async def scenario():
        room = RoomServer(seed=3)
        port = await room.start(port=0)
        clients = []
        try:
            first = await asyncio.to_thread(NetworkClient, f'127.0.0.1:{port}', 'One')
            clients.append(first)
            first.publish(SimpleNamespace(position=np.array([4000., 2500.]), altitude=1500., heading=1.2, bank=0.,
                                          flight_pitch=0., speed=90., fuel=80., plane_id='classic'))
            for _ in range(40):
                await asyncio.sleep(.05)
                if room.peers[first.player_id]['state']['x'] == 4000.:
                    break
            second = await asyncio.to_thread(NetworkClient, f'127.0.0.1:{port}', 'Two')
            clients.append(second)
            spawn = second.welcome['spawn']
            assert math.dist((spawn['x'], spawn['z']), (4000., 2500.)) < 300
            assert spawn['heading'] == pytest.approx(1.2) and spawn['y'] >= 1500
            # The newcomer is behind the first pilot, so the first pilot is in front of their camera.
            ahead = (4000. - spawn['x']) * math.sin(1.2) + (2500. - spawn['z']) * math.cos(1.2)
            assert ahead > 100
            assert second.clock_offset is not None and abs(second.server_time() - time.monotonic()) < 5

            def old_client():
                with socket.create_connection(('127.0.0.1', port), timeout=5) as raw:
                    raw.sendall(encode({'type': 'join', 'version': 1, 'name': 'Old'}))
                    return json.loads(raw.makefile().readline())
            welcome = await asyncio.to_thread(old_client)
            assert welcome['type'] == 'welcome' and welcome['version'] == 1 and VERSION == 2
        finally:
            for client in clients:
                await asyncio.to_thread(client.close)
            await room.close()
    asyncio.run(scenario())


# ------------------------------------------------------------------ end to end


class Pilot:
    """A headless race client: the real RaceMode and NetworkClient, flown straight through gate centres."""

    def __init__(self, client, pace, quit_after=None):
        import modes
        self.client = client
        self.pace = pace
        self.quit_after = quit_after
        self.flashes = []
        game = SimpleNamespace(network=client, flash=lambda text, color: self.flashes.append(text),
                               sound=lambda name: None)
        self.atmosphere = SimpleNamespace(position=np.array([0., -900.]), altitude=700., heading=0., bank=0.,
                                          flight_pitch=0., speed=75., fuel=100., plane_id='classic',
                                          vertical_speed=0., crash_timer=0., CRUISE_SPEED=75., speed_scale=1.)
        self.mode = modes.RaceMode(game)
        self.mode.start(self.atmosphere)
        self.last_pass = None
        self.gone = False

    def step(self, dt):
        if self.gone:
            return
        mode, atmosphere = self.mode, self.atmosphere
        mode.update(dt, atmosphere)
        if mode.phase == 'racing' and mode.me and mode.passed < len(mode.course) and mode.finish_time is None:
            self.last_pass = self.last_pass or time.monotonic()
            if time.monotonic() - self.last_pass >= self.pace:
                x, y, z, nx, nz = mode.course[mode.passed]
                for offset in (-25, 25):
                    atmosphere.position = np.array([x + nx * offset, z + nz * offset])
                    atmosphere.altitude = y
                    mode.update(0.0, atmosphere)
                self.last_pass = time.monotonic()
        self.client.publish(atmosphere, mode.progress())
        if self.quit_after is not None and mode.me and mode.me['gates'] >= self.quit_after:
            self.client.close()
            self.gone = True


@pytest.mark.parametrize('transport', ['tcp', 'websocket'])
def test_three_clients_race_to_a_correct_leaderboard(transport):
    async def scenario():
        room = RoomServer(seed=11, countdown=0.6, results=30, gates=4)
        if transport == 'tcp':
            port = await room.start(port=0)
            address = f'127.0.0.1:{port}'
        else:
            port = await room.start_websocket('127.0.0.1', 0)
            address = f'ws://127.0.0.1:{port}'
        clients = []
        try:
            for name in ('Ann', 'Bo', 'Cy'):
                clients.append(await asyncio.to_thread(NetworkClient, address, name))
            pilots = [Pilot(clients[0], 0.55), Pilot(clients[1], 0.9), Pilot(clients[2], 0.6, quit_after=2)]

            def fly():
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    for pilot in pilots:
                        pilot.step(0.02)
                    info = clients[0].race_state()
                    if info and info['phase'] == 'results':
                        return info
                    time.sleep(0.02)
                return clients[0].race_state()
            info = await asyncio.to_thread(fly)
            assert info['phase'] == 'results' and info['round'] == 1
            order = [(e['name'], e['place'], e['status'], e['gates']) for e in info['standings']]
            assert order == [('Ann', 1, 'finished', 4), ('Bo', 2, 'finished', 4), ('Cy', 3, 'dnf', 2)]
            ann, bo = info['standings'][0], info['standings'][1]
            assert 4 * 0.55 - 0.3 < ann['finish'] < bo['finish'] < 4 * 0.9 + 1.5
            assert bo['gap'] == pytest.approx(bo['finish'] - ann['finish'], abs=0.01)
            assert room.race.rejected == 0
            # Every client flew the same course from the round seed.
            assert pilots[0].mode.course == pilots[1].mode.course == race.course(room.race.seed, 4)
            assert pilots[0].mode.finish_time == pytest.approx(ann['finish'])
            assert 'FINISHED' in pilots[0].flashes[-1]
            # Remote pilots carry names for the floating tags.
            assert {p['name'] for p in clients[0].players()} == {'Bo'}
        finally:
            for client in clients:
                await asyncio.to_thread(client.close)
            await room.close()
    asyncio.run(scenario())


# ------------------------------------------------------------------ client UI


class FakeNetwork:
    player_id = 'me'
    status = 'Connected'

    def __init__(self, info=None, now=100.0):
        self.info, self.now = info, now

    def race_state(self):
        return self.info

    def server_time(self):
        return self.now


def race_info(phase, standings=(), start=100.0, gates=race.GATES):
    return {'phase': phase, 'round': 2, 'seed': 77, 'gates': gates, 'start': start, 'ends': start + 20,
            'standings': [dict(dict(id='', name='', place=1, gates=0, finish=None, gap=None, slot=0, status='racing'), **e)
                          for e in standings]}


def test_race_mode_only_offered_while_connected(atmosphere, fonts, tmp_path):
    import menu
    from game import Game
    from scores import Scores
    offline = Game(atmosphere, fonts, None, scores=Scores(tmp_path / 's.json'))
    assert 'race' not in offline.modes and offline.menu.title_items() == menu.TITLE_ITEMS
    online = Game(atmosphere, fonts, None, 'race', scores=Scores(tmp_path / 's.json'), network=FakeNetwork())
    assert online.flying and online.mode.key == 'race'
    assert [key for key, _ in online.menu.title_items()] == ['free', 'rings', 'race', 'aircraft', 'quit']
    assert online.mode.progress() == {'round': 0, 'gates': 0, 'finish': None}
    assert offline.modes['free'].progress() is None
    with pytest.raises(SystemExit):
        import main
        main.parse_args(['--mode', 'race'])


def test_race_mode_holds_grid_counts_gates_and_draws_every_phase(atmosphere, fonts, tmp_path, pg):
    from game import Game
    from scores import Scores
    network = FakeNetwork(race_info('countdown', [dict(id='me', name='Me', slot=5), dict(id='o', name='Other')]),
                          now=97.4)
    game = Game(atmosphere, fonts, None, 'race', scores=Scores(tmp_path / 's.json'), network=network)
    mode = game.mode
    surface = pg.Surface((1280, 720), pg.SRCALPHA)
    game.update(0.016, 0.016)
    x, y, z, heading = race.grid_slot(5)
    assert tuple(atmosphere.position) == (x, z) and atmosphere.altitude == y
    assert mode.course == race.course(77) and mode.target()[:3] == mode.course[0][:3]
    game.draw_hud(surface, 60, 'GPU')
    # GO: fly through the first gate, miss the second.
    network.info = race_info('racing', [dict(id='me', name='Me', slot=5)])
    network.now = 100.5
    gx, gy, gz, nx, nz = mode.course[0]
    for offset in (-30, 30):
        atmosphere.position = np.array([gx + nx * offset, gz + nz * offset])
        atmosphere.altitude = gy
        game.update(0.016, 0.016)
    assert mode.passed == 1 and mode.progress()['gates'] == 1
    gx, gy, gz, nx, nz = mode.course[1]
    for offset in (-30, 30):
        atmosphere.position = np.array([gx + nx * offset + 200, gz + nz * offset])
        atmosphere.altitude = gy
        game.update(0.016, 0.016)
    assert mode.passed == 1 and mode.target()[:3] == mode.course[1][:3]
    game.draw_hud(surface, 60, 'GPU')
    # The server never confirms the pass: roll back to its count.
    for _ in range(200):
        game.update(0.016, 0.016)
    assert mode.passed == 0
    # The server's count wins when it is ahead (for example after Restart).
    network.info = race_info('racing', [dict(id='me', name='Me', gates=3), dict(id='o', name='O', place=2, gap=1.5)])
    game.update(0.016, 0.016)
    assert mode.passed == 3
    game.draw_hud(surface, 60, 'GPU')
    network.info = race_info('results', [dict(id='me', name='Me', status='finished', finish=71.25, gates=12),
                                         dict(id='o', name='O', place=2, status='finished', finish=73.0, gap=1.75, gates=12),
                                         dict(id='z', name='Z', place=3, status='dnf', gates=4)])
    game.update(0.016, 0.016)
    assert mode.finish_time == 71.25 and mode.rings == [] and mode.target() is None
    game.draw_hud(surface, 60, 'GPU')
    network.info = race_info('racing', [dict(id='o', name='O')])  # spectating a round we are not in
    network.info['round'] = 3
    game.update(0.016, 0.016)
    assert mode.me is None and mode.passed == 0 and len(mode.rings) == race.GATES and mode.target() is None
    game.draw_hud(surface, 60, 'GPU')
    for info in (None, race_info('waiting')):
        network.info = info
        game.update(0.016, 0.016)
        game.draw_hud(surface, 60, 'GPU')


def test_pilot_markers_tag_on_screen_and_arrow_off_screen(atmosphere, fonts, tmp_path, pg):
    from game import Game
    from hud import PilotMarkers, marker
    from scores import Scores
    atmosphere.position = np.array([0., 0.])
    atmosphere.altitude, atmosphere.heading = 1000., 0.
    atmosphere.third_person = False
    size = (1280, 720)
    kind, x, y = marker(atmosphere, (0., 1000., 2000.), size)
    assert kind == 'tag' and abs(x - 640) < 2
    kind, x, y, angle = marker(atmosphere, (3000., 1000., 500.), size)  # far to the right
    assert kind == 'edge' and x == pytest.approx(1280 - 40) and abs(angle) < 0.3
    kind, x, y, angle = marker(atmosphere, (-300., 1000., -2000.), size)  # behind, to the left
    assert kind == 'edge' and x < 640
    kind, x, y, angle = marker(atmosphere, (0., 1000., -2000.), size)  # dead astern: arrow somewhere on the edge
    assert kind == 'edge' and (x in (40, 1240) or y in (pytest.approx(40), pytest.approx(680)))
    network = FakeNetwork(race_info('racing', [dict(id='p', name='Pal', place=2)]))
    game = Game(atmosphere, fonts, None, 'free', scores=Scores(tmp_path / 's.json'), network=network)
    atmosphere.remote_players = [dict(id='p', name='Pal', x=0., y=1000., z=900., model='classic'),
                                 dict(id='q', name='Far', x=0., y=1000., z=-9000., model='f15')]
    overlay = pg.Surface(size, pg.SRCALPHA)
    PilotMarkers(game).draw_world(overlay, atmosphere)
    assert overlay.get_bounding_rect().width > 0
    assert PilotMarkers(game).places() == {'p': 2}
