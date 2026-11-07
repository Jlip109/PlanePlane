"""Versioned TCP movement replication for local and LAN multiplayer sessions."""

import asyncio
from collections import deque
import json
import math
import select
import socket
import threading
import time
import uuid

from plane import PLANE_MODELS
from units import MAX_FLIGHT_SPEED_MPS

VERSION = 1
TICK_RATE = 20
MAX_LINE = 262144
STATE_FIELDS = ('x','y','z','heading','bank','flight_pitch','speed','fuel')


def encode(message):
    return (json.dumps(message, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def clean_state(message):
    if not isinstance(message, dict) or not isinstance(message.get('model'),str) or message['model'] not in PLANE_MODELS:
        raise ValueError('Invalid aircraft state')
    result = {'model': message['model']}
    for name in STATE_FIELDS:
        value = message.get(name)
        if isinstance(value, bool) or not isinstance(value, (float,int)) or not math.isfinite(value):
            raise ValueError(f'Invalid {name}')
        result[name] = float(value)
    if abs(result['x']) > 1e7 or abs(result['z']) > 1e7 or not 0 <= result['y'] <= 5500:
        raise ValueError('Position outside supported world')
    if not 0 <= result['speed'] <= MAX_FLIGHT_SPEED_MPS or not 0 <= result['fuel'] <= 100:
        raise ValueError('Invalid flight limits')
    result['heading'] = (result['heading']+math.pi) % math.tau-math.pi
    result['bank'] = min(math.pi,max(-math.pi,result['bank']))
    result['flight_pitch'] = min(1.5,max(-1.5,result['flight_pitch']))
    return result


class RoomServer:
    def __init__(self, seed=1, max_players=100):
        self.seed = seed
        self.max_players = min(100,max(1,max_players))
        self.peers = {}
        self.server = None
        self.broadcast_task = None
        self.started = time.monotonic()

    async def start(self, host='127.0.0.1', port=8765):
        self.server = await asyncio.start_server(self.accept,host,port,limit=4096)
        self.broadcast_task = asyncio.create_task(self.broadcast())
        return self.server.sockets[0].getsockname()[1]

    async def accept(self, reader, writer):
        player_id = None
        try:
            raw = await asyncio.wait_for(reader.readline(),5)
            hello = json.loads(raw)
            if not isinstance(hello,dict) or hello.get('version') != VERSION or hello.get('type') != 'join':
                raise ValueError('Protocol version mismatch')
            if len(self.peers) >= self.max_players:
                raise ValueError('Room is full')
            player_id = uuid.uuid4().hex[:12]
            name = ''.join(c for c in str(hello.get('name','Pilot')) if c.isprintable())[:24] or 'Pilot'
            model = hello.get('model','classic')
            if not isinstance(model,str) or model not in PLANE_MODELS:
                raise ValueError('Unknown aircraft')
            spawn = {'x': (len(self.peers)%10)*24.0, 'y': 700.0, 'z': -900.0+(len(self.peers)//10)*40}
            state = dict(spawn,heading=0.,bank=0.,flight_pitch=0.,speed=75.,fuel=100.,model=model)
            self.peers[player_id] = {'writer':writer,'name':name,'state':state}
            hour = (9+(time.monotonic()-self.started)*.1) % 24
            writer.write(encode({'type':'welcome','version':VERSION,'id':player_id,'seed':self.seed,'spawn':spawn,'hour':hour}))
            await writer.drain()
            while raw := await asyncio.wait_for(reader.readline(),30):
                message = json.loads(raw)
                if not isinstance(message,dict) or message.get('type') != 'state':
                    raise ValueError('Expected state update')
                self.peers[player_id]['state'] = clean_state(message)
        except (ValueError, OSError, asyncio.TimeoutError, ConnectionError) as error:
            if not writer.is_closing():
                try:
                    writer.write(encode({'type':'error','message':str(error)}))
                except OSError:
                    pass
        finally:
            if player_id:
                self.peers.pop(player_id,None)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def broadcast(self):
        while True:
            players = [dict(peer['state'],id=player_id,name=peer['name']) for player_id,peer in self.peers.items()]
            packet = encode({'type':'snapshot','players':players})
            for peer in list(self.peers.values()):
                writer = peer['writer']
                if writer.is_closing():
                    continue
                if writer.transport.get_write_buffer_size() > MAX_LINE:
                    writer.close()
                else:
                    try:
                        writer.write(packet)
                    except OSError:
                        writer.close()
            await asyncio.sleep(1/TICK_RATE)

    async def close(self):
        if self.broadcast_task:
            self.broadcast_task.cancel()
            await asyncio.gather(self.broadcast_task,return_exceptions=True)
        writers = [peer['writer'] for peer in self.peers.values()]
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(*(writer.wait_closed() for writer in writers),return_exceptions=True)
        if self.server:
            self.server.close()
            await self.server.wait_closed()


class NetworkClient:
    def __init__(self, address, name='Pilot', model='classic'):
        host,separator,port = address.rpartition(':')
        if not separator or not host or not port.isdigit():
            raise ValueError('Use --connect HOST:PORT')
        if not 1 <= int(port) <= 65535:
            raise ValueError('Server port must be between 1 and 65535')
        self.socket = socket.create_connection((host,int(port)),timeout=5)
        self.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.socket.sendall(encode({'type':'join','version':VERSION,'name':name,'model':model}))
        self.pending = bytearray()
        try:
            while b'\n' not in self.pending:
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise ConnectionError('Server closed the connection')
                self.pending.extend(chunk)
                if len(self.pending) > MAX_LINE:
                    raise ValueError('Server response too large')
            line,_,rest = self.pending.partition(b'\n')
            self.welcome = json.loads(line)
            if self.welcome.get('type') != 'welcome' or self.welcome.get('version') != VERSION:
                raise ValueError(self.welcome.get('message','Invalid welcome message'))
            self.pending = bytearray(rest)
        except Exception:
            self.socket.close()
            raise
        self.player_id = self.welcome['id']
        self.lock = threading.Lock()
        self.state = None
        self.snapshots = deque(maxlen=8)
        self.status = 'Connected'
        self.stop = threading.Event()
        self.socket.settimeout(.25)
        self.thread = threading.Thread(target=self.run,name='PlanePlane network',daemon=True)
        self.thread.start()

    def publish(self, atmosphere):
        state = {'type':'state','x':float(atmosphere.position[0]),'y':atmosphere.altitude,
                 'z':float(atmosphere.position[1]),'heading':atmosphere.heading,'bank':atmosphere.bank,
                 'flight_pitch':atmosphere.flight_pitch,'speed':atmosphere.speed,'fuel':atmosphere.fuel,
                 'model':atmosphere.plane_id}
        with self.lock:
            self.state = state

    def run(self):
        next_send = 0.0
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if now >= next_send:
                    with self.lock:
                        state = self.state
                    if state:
                        self.socket.sendall(encode(state))
                    next_send = now+1/TICK_RATE
                if select.select([self.socket],[],[],.01)[0]:
                    chunk = self.socket.recv(65536)
                    if not chunk:
                        raise ConnectionError('Disconnected')
                    self.pending.extend(chunk)
                if len(self.pending) > MAX_LINE:
                    raise ValueError('Server response too large')
                while b'\n' in self.pending:
                    line,_,rest = self.pending.partition(b'\n')
                    self.pending = bytearray(rest)
                    message = json.loads(line)
                    if message.get('type') == 'snapshot':
                        players = {}
                        for item in message['players']:
                            state = clean_state(item)
                            players[str(item['id'])] = dict(state,id=str(item['id']),name=str(item['name'])[:24])
                        with self.lock:
                            self.snapshots.append((time.monotonic(),players))
                    elif message.get('type') == 'error':
                        raise ValueError(message.get('message','Server error'))
        except (OSError, ValueError, KeyError, TypeError) as error:
            if not self.stop.is_set():
                self.status = f'Disconnected: {error}'
        finally:
            self.socket.close()

    def players(self):
        with self.lock:
            frames = list(self.snapshots)
        if not frames or not self.status.startswith('Connected'):
            return []
        target = time.monotonic()-.1
        before = frames[0]
        after = frames[-1]
        for frame in frames:
            if frame[0] <= target:
                before = frame
            if frame[0] >= target:
                after = frame
                break
        span = after[0]-before[0]
        blend = min(1,max(0,(target-before[0])/span)) if span > 0 else 1
        result = []
        for player_id,current in frames[-1][1].items():
            if player_id == self.player_id:
                continue
            a = before[1].get(player_id,current)
            b = after[1].get(player_id,current)
            state = dict(current)
            for field in STATE_FIELDS:
                delta = b[field]-a[field]
                if field == 'heading':
                    delta = (delta+math.pi)%math.tau-math.pi
                state[field] = a[field]+delta*blend
            result.append(state)
        return result

    def close(self):
        self.stop.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.thread.join(timeout=1)
        self.socket.close()
