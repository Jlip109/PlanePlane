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
import secrets

from plane import PLANE_MODELS
from units import MAX_FLIGHT_SPEED_MPS
from race import RaceRoom, spawn_for
from flight_settings import ONLINE_FLIGHT_TUNING

VERSION = 3
TICK_RATE = 20
MAX_LINE = 262144
STATE_FIELDS = ('x','y','z','heading','bank','flight_pitch','speed','fuel')


def encode(message):
    return (json.dumps(message, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def clean_state(message):
    if not isinstance(message, dict) or not isinstance(message.get('model'),str) or message['model'] not in PLANE_MODELS:
        raise ValueError('Invalid aircraft state')
    result = {'model': message['model']}
    color = message.get('color',[220,220,220])
    if not isinstance(color,(list,tuple)) or len(color)!=3 or any(type(c) is not int or not 0<=c<=255 for c in color):
        raise ValueError('RGB must contain three integers from 0 to 255')
    result['color'] = list(color)
    result['crashed'] = bool(message.get('crashed',False))
    result['left_match'] = bool(message.get('left_match',False))
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
    def __init__(self, seed=1, max_players=100, location=None):
        self.seed = seed
        self.max_players = min(100,max(1,max_players))
        self.peers = {}
        self.server = None
        self.broadcast_task = None
        self.started = time.monotonic()
        self.rooms = {}
        self.preparations = {}
        self.location = location

    @property
    def race(self):
        return self.rooms.get(1)

    def directory(self):
        return [dict(id=i,name=f'Lobby {i}',exists=i in self.rooms,capacity=24,
                     count=sum(p.get('lobby')==i for p in self.peers.values()),
                     phase=self.rooms[i].phase if i in self.rooms else 'empty') for i in (1,2,3)]

    def leave_lobby(self, player_id):
        peer=self.peers.get(player_id)
        if not peer:return
        lobby=peer.get('lobby')
        peer['lobby']=None
        if lobby in self.rooms:
            self.rooms[lobby].leave(player_id)
            if not any(p.get('lobby')==lobby for p in self.peers.values()):
                self.rooms.pop(lobby)
                task=self.preparations.pop(lobby,None)
                if task:task.cancel()

    def join_lobby(self, player_id, action, lobby):
        if type(lobby) is not int or lobby not in (1,2,3):
            raise ValueError('Choose Lobby 1, 2 or 3')
        if action not in ('create','join','auto'):
            raise ValueError('Choose CREATE LOBBY or JOIN LOBBY')
        if action=='create' and lobby in self.rooms:
            raise ValueError(f'Lobby {lobby} already exists')
        if action=='join' and lobby not in self.rooms:
            raise ValueError(f'Lobby {lobby} does not exist yet')
        peer=self.peers[player_id]
        if peer.get('lobby')==lobby:
            return
        if sum(p.get('lobby')==lobby for p in self.peers.values())>=24:
            raise ValueError(f'Lobby {lobby} is full (24 racers)')
        self.leave_lobby(player_id)
        if lobby not in self.rooms:self.rooms[lobby]=RaceRoom(self.seed+lobby*1000+secrets.randbits(31))
        peer['lobby']=lobby
        room=self.rooms[lobby]
        room.join(player_id,peer['name'])
        spawn=spawn_for(sum(p.get('lobby')==lobby for p in self.peers.values())-1)
        peer['state'].update(spawn,speed=0)

    async def start(self, host='127.0.0.1', port=8765):
        self.server = await asyncio.start_server(self.accept,host,port,limit=4096)
        self.broadcast_task = asyncio.create_task(self.broadcast())
        return self.server.sockets[0].getsockname()[1]

    async def start_websocket(self, host='0.0.0.0', port=8080):
        """Serve the same protocol over WebSocket (cloud hosts only route HTTP/WebSocket traffic)."""
        from websockets.asyncio.server import serve
        self.ws_server = await serve(self.accept_websocket,host,port,process_request=self.health,
                                     max_size=MAX_LINE,ping_interval=20,ping_timeout=20)
        if self.broadcast_task is None:
            self.broadcast_task = asyncio.create_task(self.broadcast())
        return list(self.ws_server.sockets)[0].getsockname()[1]

    def health(self, connection, request):
        if request.path in ('/','/health'):
            return connection.respond(200,f'PlanePlane server ok - {len(self.peers)} pilots online\n')
        return None

    async def accept_websocket(self, websocket):
        writer = WebSocketWriter(websocket)
        sender = asyncio.create_task(writer.pump())
        try:
            await self.accept(WebSocketReader(websocket),writer)
        finally:
            sender.cancel()
            await asyncio.gather(sender,return_exceptions=True)

    async def accept(self, reader, writer):
        player_id = None
        try:
            raw = await asyncio.wait_for(reader.readline(),5)
            hello = json.loads(raw)
            if not isinstance(hello,dict) or hello.get('version') != VERSION or hello.get('type') != 'join':
                raise ValueError('Protocol version mismatch; update the game and server to the same version')
            if len(self.peers) >= self.max_players:
                raise ValueError('Room is full')
            player_id = uuid.uuid4().hex[:12]
            name = ''.join(c for c in str(hello.get('name','Pilot')) if c.isprintable()).strip()[:24] or 'Pilot'
            if any(peer['name'].casefold()==name.casefold() for peer in self.peers.values()):
                raise ValueError('Username is already online; choose another name')
            model = hello.get('model','classic')
            if not isinstance(model,str) or model not in PLANE_MODELS:
                raise ValueError('Unknown aircraft')
            spawn = {'x': (len(self.peers)%10)*24.0, 'y': 700.0, 'z': -900.0+(len(self.peers)//10)*40}
            state = dict(spawn,heading=0.,bank=0.,flight_pitch=0.,speed=75.,fuel=100.,model=model)
            state.update(color=hello.get('color',[220,220,220]))
            state = clean_state(state)
            mode = hello.get('mode','free')
            self.peers[player_id] = {'writer':writer,'name':name,'state':state,'mode':mode,'lobby':None}
            if mode=='ffa':
                action=hello.get('lobby_action','auto')
                if action!='browse':
                    self.join_lobby(player_id,action,hello.get('lobby',1))
                    spawn={key:state[key] for key in ('x','y','z')}
            room=self.rooms.get(self.peers[player_id]['lobby'])
            hour = (9+(time.monotonic()-self.started)*.1) % 24
            writer.write(encode({'type':'welcome','version':VERSION,'id':player_id,'seed':self.seed,'spawn':spawn,'hour':hour,
                                 'race':room.snapshot() if room else None,'lobbies':self.directory(),'lobby_protocol':2,
                                 'flight_tuning':ONLINE_FLIGHT_TUNING}))
            await writer.drain()
            while raw := await asyncio.wait_for(reader.readline(),30):
                message = json.loads(raw)
                room=self.rooms.get(self.peers[player_id].get('lobby'))
                if isinstance(message,dict) and message.get('type')=='lobby':
                    try:
                        if self.peers[player_id]['mode']!='ffa':raise ValueError('Lobby selection requires Free for All')
                        if message.get('action')=='leave':self.leave_lobby(player_id)
                        else:self.join_lobby(player_id,message.get('action'),message.get('lobby'))
                    except ValueError as error:
                        writer.write(encode(dict(type='lobby_error',message=str(error))))
                    continue
                if isinstance(message,dict) and message.get('type')=='ready':
                    if room:room.ready(player_id,message.get('ready') is True)
                    continue
                if not isinstance(message,dict) or message.get('type') != 'state':
                    raise ValueError('Expected state update')
                self.peers[player_id]['state'] = clean_state(message)
                if room:room.receive(player_id,self.peers[player_id]['state'])
        except (ValueError, OSError, asyncio.TimeoutError, ConnectionError) as error:
            if not writer.is_closing():
                try:
                    writer.write(encode({'type':'error','message':str(error)}))
                except OSError:
                    pass
        finally:
            if player_id:
                self.leave_lobby(player_id)
                self.peers.pop(player_id,None)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def broadcast(self):
        while True:
            for lobby,room in list(self.rooms.items()):
                room.tick()
                task=self.preparations.get(lobby)
                if room.phase=='loading' and (task is None or task.done()):
                    self.preparations[lobby] = asyncio.create_task(self.prepare_race(lobby,room))
            directory=self.directory()
            packets={}
            for peer in list(self.peers.values()):
                lobby=peer.get('lobby')
                key=(lobby,peer['mode'])
                if key not in packets:
                    players=[dict(p['state'],id=player_id,name=p['name']) for player_id,p in self.peers.items()
                             if p.get('lobby')==lobby and p['mode']==peer['mode']]
                    room=self.rooms.get(lobby)
                    packets[key]=encode(dict(type='snapshot',players=players,race=room.snapshot() if room else None,
                                             lobbies=directory,lobby=lobby))
                packet=packets[key]
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

    async def prepare_race(self, lobby, room):
        from climate import race_environment
        seed=self.seed+room.round+lobby+int(time.time())
        environment = await asyncio.to_thread(race_environment,seed,self.location) if self.location else await asyncio.to_thread(race_environment,seed)
        if self.rooms.get(lobby) is room:room.prepared(environment)

    async def close(self):
        for task in self.preparations.values():task.cancel()
        await asyncio.gather(*self.preparations.values(),return_exceptions=True)
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
        ws_server = getattr(self,'ws_server',None)
        if ws_server:
            ws_server.close()
            await ws_server.wait_closed()


class WebSocketReader:
    """Looks like asyncio.StreamReader.readline() to RoomServer.accept: one message per line."""
    def __init__(self, websocket):
        self.websocket = websocket

    async def readline(self):
        try:
            message = await self.websocket.recv()
        except Exception:
            return b''
        if isinstance(message,str):
            message = message.encode('utf-8')
        if len(message) > MAX_LINE:
            raise ValueError('Message too large')
        return message.rstrip(b'\n')+b'\n'


class WebSocketWriter:
    """Looks like asyncio.StreamWriter to RoomServer: buffered writes sent by pump()."""
    def __init__(self, websocket):
        self.websocket = websocket
        self.queue = deque()
        self.buffered = 0
        self.ready = asyncio.Event()
        self.closing = False
        self.transport = self

    def get_write_buffer_size(self):
        return self.buffered

    def write(self, data):
        if self.closing:
            return
        self.queue.append(data)
        self.buffered += len(data)
        self.ready.set()

    async def drain(self):
        while self.queue and not self.closing:
            await asyncio.sleep(0.005)

    async def pump(self):
        while not self.closing:
            await self.ready.wait()
            self.ready.clear()
            while self.queue:
                data = self.queue.popleft()
                self.buffered -= len(data)
                try:
                    await self.websocket.send(data.decode('utf-8').rstrip('\n'))
                except Exception:
                    self.close()
                    return

    def is_closing(self):
        return self.closing

    def close(self):
        self.closing = True
        self.ready.set()
        asyncio.ensure_future(self.websocket.close())

    async def wait_closed(self):
        try:
            await self.websocket.wait_closed()
        except Exception:
            pass


class NetworkClient:
    def __init__(self, address, name='Pilot', model='classic', mode='free', color=(220,220,220), lobby=1, lobby_action='auto'):
        self.join_info = dict(type='join',version=VERSION,name=name,model=model,mode=mode,color=list(color),lobby=lobby,lobby_action=lobby_action)
        self.race = None
        self.lobbies = []
        self.lobby_id = None
        self.lobby_error = ''
        self.online = []
        self.commands = deque()
        self.websocket = None
        if address.startswith(('ws://','wss://','http://','https://')):
            self.connect_websocket(address,name,model)
            return
        host,separator,port = address.rpartition(':')
        if not separator or not host or not port.isdigit():
            raise ValueError('Use --connect HOST:PORT')
        if not 1 <= int(port) <= 65535:
            raise ValueError('Server port must be between 1 and 65535')
        self.socket = socket.create_connection((host,int(port)),timeout=5)
        self.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.socket.sendall(encode(self.join_info))
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

    def connect_websocket(self, address, name, model):
        from websockets.sync.client import connect
        url = 'ws://'+address[7:] if address.startswith('http://') else address
        url = 'wss://'+url[8:] if url.startswith('https://') else url
        url = url.rstrip('/')
        if url.count('/') < 3:
            url += '/play'
        # Entered as a context manager (newer websockets warn otherwise); closed explicitly in close().
        self.websocket = connect(url,open_timeout=75,close_timeout=1,max_size=MAX_LINE).__enter__()
        try:
            self.websocket.send(encode(self.join_info).decode().strip())
            self.welcome = json.loads(self.websocket.recv(timeout=15))
            if self.welcome.get('type') != 'welcome' or self.welcome.get('version') != VERSION:
                raise ValueError(self.welcome.get('message','Invalid welcome message'))
        except TimeoutError as error:
            self.websocket.close()
            raise ValueError('Server did not answer') from error
        except Exception:
            self.websocket.close()
            raise
        self.player_id = self.welcome['id']
        self.pending = bytearray()
        self.lock = threading.Lock()
        self.state = None
        self.snapshots = deque(maxlen=8)
        self.status = 'Connected'
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run_websocket,name='PlanePlane network',daemon=True)
        self.thread.start()

    def run_websocket(self):
        next_send = 0.0
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if now >= next_send:
                    with self.lock:
                        state = self.state
                        commands = list(self.commands)
                        self.commands.clear()
                    for command in commands:
                        self.websocket.send(encode(command).decode().strip())
                    if state:
                        self.websocket.send(encode(state).decode().strip())
                    next_send = now+1/TICK_RATE
                try:
                    message = self.websocket.recv(timeout=.01)
                except TimeoutError:
                    continue
                if isinstance(message,bytes):
                    message = message.decode('utf-8')
                self.handle(json.loads(message))
        except Exception as error:
            if not self.stop.is_set():
                self.status = f'Disconnected: {error}'
        finally:
            self.websocket.close()

    def handle(self, message):
        if message.get('type') == 'snapshot':
            players = {}
            for item in message['players']:
                state = clean_state(item)
                players[str(item['id'])] = dict(state,id=str(item['id']),name=str(item['name'])[:24])
            with self.lock:
                self.snapshots.append((time.monotonic(),players))
                self.race = message.get('race')
                self.lobbies = message.get('lobbies',[])
                self.lobby_id = message.get('lobby')
                self.online = [{'id':p['id'],'name':p['name']} for p in message['players']]
        elif message.get('type')=='lobby_error':
            self.lobby_error=str(message.get('message','Could not join lobby'))
        elif message.get('type') == 'error':
            raise ValueError(message.get('message','Server error'))

    def publish(self, atmosphere):
        state = {'type':'state','x':float(atmosphere.position[0]),'y':atmosphere.altitude,
                 'z':float(atmosphere.position[1]),'heading':atmosphere.heading,'bank':atmosphere.bank,
                 'flight_pitch':atmosphere.flight_pitch,'speed':atmosphere.speed,'fuel':atmosphere.fuel,
                 'model':atmosphere.plane_id}
        state.update(color=list(getattr(atmosphere,'plane_color',(220,220,220))),
                     crashed=getattr(atmosphere,'crashed',False),left_match=getattr(atmosphere,'left_match',False))
        with self.lock:
            self.state = state

    def set_ready(self, ready):
        with self.lock:
            self.commands.append(dict(type='ready',ready=bool(ready)))

    def select_lobby(self, action, lobby=None):
        self.lobby_error=''
        with self.lock:
            self.commands.append(dict(type='lobby',action=action,lobby=lobby))

    def run(self):
        next_send = 0.0
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if now >= next_send:
                    with self.lock:
                        state = self.state
                        commands = list(self.commands)
                        self.commands.clear()
                    for command in commands:
                        self.socket.sendall(encode(command))
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
                    self.handle(json.loads(line))
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
        if self.websocket is not None:
            self.thread.join(timeout=1)
            self.websocket.close()
            return
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.thread.join(timeout=1)
        self.socket.close()
