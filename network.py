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
import race
from units import MAX_FLIGHT_SPEED_MPS

VERSION = 2
SUPPORTED_VERSIONS = (1, 2)  # version 1 clients still fly together; they just never race
TICK_RATE = 20
INTERPOLATION_DELAY = .1
LEAD = .15  # extrapolate remote planes this far ahead so formation partners appear where they really are
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
    # Optional flags (protocol 2). Absent fields mean "flying, not racing".
    for name in ('racing','idle'):
        flag = message.get(name,False)
        if not isinstance(flag,bool):
            raise ValueError(f'Invalid {name} flag')
        result[name] = flag
    for name,limit in (('round',2**31),('gates',race.GATES)):
        value = message.get(name,0)
        if isinstance(value,bool) or not isinstance(value,int) or not 0 <= value <= limit:
            raise ValueError(f'Invalid {name}')
        result[name] = value
    finish = message.get('finish')
    if finish is not None and (isinstance(finish,bool) or not isinstance(finish,(float,int))
                               or not math.isfinite(finish) or not 0 <= finish <= 3600):
        raise ValueError('Invalid finish time')
    result['finish'] = None if finish is None else float(finish)
    return result


def spawn_near(anchor, count=1):
    """A spawn just behind and beside a pilot's state, matching their heading, altitude and speed."""
    side = (40.0+(count//2 % 4)*30.0)*(1 if count % 2 else -1)
    sh,ch = math.sin(anchor['heading']),math.cos(anchor['heading'])
    x = anchor['x']-sh*140+ch*side
    z = anchor['z']-ch*140-sh*side
    y = min(5400.0,max(anchor['y'],race.world.obstacle_height(x,z)+250))
    speed = min(MAX_FLIGHT_SPEED_MPS,max(45.0,anchor.get('speed',75.0)))
    return {'x':x,'y':y,'z':z,'heading':anchor['heading'],'speed':speed}


def clean_race(info):
    """Validate the race block a server sends with each snapshot."""
    if not isinstance(info,dict) or info.get('phase') not in race.PHASES:
        raise ValueError('Invalid race state')
    result = {'phase': info['phase']}
    for name in ('round','seed','gates'):
        value = info.get(name)
        if isinstance(value,bool) or not isinstance(value,int) or not 0 <= value <= 2**31:
            raise ValueError(f'Invalid race {name}')
        result[name] = value
    if result['gates'] > race.GATES:
        raise ValueError('Invalid race gates')
    for name in ('start','ends'):
        value = info.get(name)
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
            raise ValueError(f'Invalid race {name}')
        result[name] = float(value)
    standings = info.get('standings',[])
    if not isinstance(standings,list) or len(standings) > 100:
        raise ValueError('Invalid standings')
    result['standings'] = []
    for entry in standings:
        if not isinstance(entry,dict) or entry.get('status') not in ('racing','finished','dnf'):
            raise ValueError('Invalid standing')
        clean = {'id': str(entry.get('id',''))[:24], 'name': str(entry.get('name',''))[:24], 'status': entry['status']}
        for name,limit in (('place',100),('gates',race.GATES),('slot',100)):
            value = entry.get(name)
            if isinstance(value,bool) or not isinstance(value,int) or not 0 <= value <= limit:
                raise ValueError(f'Invalid standing {name}')
            clean[name] = value
        for name in ('finish','gap'):
            value = entry.get(name)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value)):
                raise ValueError(f'Invalid standing {name}')
            clean[name] = None if value is None else float(value)
        result['standings'].append(clean)
    return result


class RoomServer:
    def __init__(self, seed=1, max_players=100, hour=10.0, day_length=3600.0, **race_options):
        self.seed = seed
        self.hour = hour % 24
        self.day_length = min(86400.0,max(10.0,day_length))
        self.max_players = min(100,max(1,max_players))
        self.peers = {}
        self.race = race.RaceDirector(seed,**race_options)
        self.server = None
        self.broadcast_task = None
        self.started = time.monotonic()

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
            if not isinstance(hello,dict) or hello.get('version') not in SUPPORTED_VERSIONS or hello.get('type') != 'join':
                raise ValueError('Protocol version mismatch')
            if len(self.peers) >= self.max_players:
                raise ValueError('Room is full')
            player_id = uuid.uuid4().hex[:12]
            name = ''.join(c for c in str(hello.get('name','Pilot')) if c.isprintable())[:24] or 'Pilot'
            model = hello.get('model','classic')
            if not isinstance(model,str) or model not in PLANE_MODELS:
                raise ValueError('Unknown aircraft')
            spawn = self.spawn_point()
            state = clean_state(dict(spawn,bank=0.,flight_pitch=0.,fuel=100.,model=model))
            self.peers[player_id] = {'writer':writer,'name':name,'state':state}
            # A slow shared clock (default: one day per hour, starting mid-morning) keeps demos in daylight.
            hour = (self.hour+(time.monotonic()-self.started)*24/self.day_length) % 24
            writer.write(encode({'type':'welcome','version':hello['version'],'id':player_id,'seed':self.seed,
                                 'spawn':spawn,'hour':hour,'day_length':self.day_length,'time':time.monotonic()}))
            await writer.drain()
            while raw := await asyncio.wait_for(reader.readline(),30):
                message = json.loads(raw)
                if not isinstance(message,dict) or message.get('type') != 'state':
                    raise ValueError('Expected state update')
                state = clean_state(message)
                self.peers[player_id]['state'] = state
                self.race.report(player_id,state,time.monotonic())
        except (ValueError, OSError, asyncio.TimeoutError, ConnectionError) as error:
            if not writer.is_closing():
                try:
                    writer.write(encode({'type':'error','message':str(error)}))
                except OSError:
                    pass
        finally:
            if player_id:
                self.peers.pop(player_id,None)
                self.race.remove(player_id)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def spawn_point(self):
        """Join just behind and beside the room's longest-flying pilot, facing the same way, so you see them."""
        flying = [peer['state'] for peer in self.peers.values() if not peer['state'].get('idle')]
        if not flying:
            return {'x':0.0,'y':700.0,'z':-900.0,'heading':0.0,'speed':75.0}
        return spawn_near(flying[0],len(self.peers))

    def tick_race(self):
        now = time.monotonic()
        self.race.tick(now,{player_id:(peer['name'],peer['state'].get('racing',False))
                            for player_id,peer in self.peers.items()})
        return now

    async def broadcast(self):
        while True:
            now = self.tick_race()
            players = [dict(peer['state'],id=player_id,name=peer['name']) for player_id,peer in self.peers.items()]
            packet = encode({'type':'snapshot','players':players,'time':now,'race':self.race.snapshot(now)})
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
    def __init__(self, address, name='Pilot', model='classic'):
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
        self.race = None
        self.clock_offset = None
        self.sync_clock(self.welcome.get('time'))
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
            self.websocket.send(encode({'type':'join','version':VERSION,'name':name,'model':model}).decode().strip())
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
        self.race = None
        self.clock_offset = None
        self.sync_clock(self.welcome.get('time'))
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
            race_info = clean_race(message['race']) if 'race' in message else None
            with self.lock:
                self.snapshots.append((time.monotonic(),players))
                if race_info is not None:
                    self.race = race_info
            self.sync_clock(message.get('time'))
        elif message.get('type') == 'error':
            raise ValueError(message.get('message','Server error'))

    def sync_clock(self, server_time):
        """Track server clock - local clock. Delivery delay only ever makes a sample smaller, so keep the largest."""
        if isinstance(server_time,bool) or not isinstance(server_time,(float,int)) or not math.isfinite(server_time):
            return
        sample = server_time-time.monotonic()
        if self.clock_offset is None or sample > self.clock_offset:
            self.clock_offset = sample

    def server_time(self):
        return time.monotonic()+(self.clock_offset or 0.0)

    def race_state(self):
        with self.lock:
            return self.race

    def publish(self, atmosphere, progress=None, idle=False):
        state = {'type':'state','x':float(atmosphere.position[0]),'y':atmosphere.altitude,
                 'z':float(atmosphere.position[1]),'heading':atmosphere.heading,'bank':atmosphere.bank,
                 'flight_pitch':atmosphere.flight_pitch,'speed':atmosphere.speed,'fuel':atmosphere.fuel,
                 'model':atmosphere.plane_id}
        if idle:
            state['idle'] = True
        if progress:
            state.update(racing=True,round=int(progress['round']),gates=int(progress['gates']),
                         finish=progress['finish'])
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
                    self.handle(json.loads(line))
        except Exception as error:
            if not self.stop.is_set():
                self.status = f'Disconnected: {error}'
        finally:
            self.socket.close()

    def players(self, lead=0.0):
        """Remote pilots interpolated INTERPOLATION_DELAY in the past, then led `lead` seconds along their path."""
        with self.lock:
            frames = list(self.snapshots)
        if not frames or not self.status.startswith('Connected'):
            return []
        target = time.monotonic()-INTERPOLATION_DELAY
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
            if player_id == self.player_id or current.get('idle'):
                continue
            a = before[1].get(player_id,current)
            b = after[1].get(player_id,current)
            state = dict(current)
            for field in STATE_FIELDS:
                delta = b[field]-a[field]
                if field == 'heading':
                    delta = (delta+math.pi)%math.tau-math.pi
                state[field] = a[field]+delta*blend
            if lead:
                ahead = state['speed']*lead
                state['x'] += math.sin(state['heading'])*math.cos(state['flight_pitch'])*ahead
                state['z'] += math.cos(state['heading'])*math.cos(state['flight_pitch'])*ahead
                state['y'] += math.sin(state['flight_pitch'])*ahead
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
