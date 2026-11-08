# Plane² — In the Clouds

A Python flight game with two modes, a third-person aircraft, flat-coloured terrain, and a living sky.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

Choose **Free Roam** to explore or **Ring Mode** to fly through ten-sided 3D gates.
Clear gates before the timer runs out to gain time and build a score multiplier.
Gates rotate around their flight axis. Their pass-through boundary rotates with them,
and the GPU uses shared depth testing for aircraft and gates.

## Controls

| Control | Action |
| --- | --- |
| Up / Down or W / S | Emergency climb / descent; uses extra fuel |
| Left / Right or A / D | Emergency banking and turning; uses extra fuel |
| Hold Space | Accelerate toward Mach 5, using extra fuel |
| Hold left mouse and drag | Smoothly aim and steer the aircraft; the camera follows its motion |
| Hold right mouse and drag | Look around without steering |
| R | Center the camera |
| V | Switch chase / cockpit camera |
| F5 | Toggle terrain, aircraft, and gate wireframe |
| F7 | Cycle 60 FPS, 120 FPS, and Uncapped |
| Esc | Release captured mouse, then pause / resume |
| F11 or Alt+Enter | Fullscreen |
| F8 | Switch between Original and F-15 aircraft |
| F1 / F2 / F3 / F4 | Clear, broken clouds, overcast, storm |
| L | Toggle live weather |
| G | Summer / autumn / winter colours |
| P | Pause the day cycle |
| [ / ] | Slow / accelerate the day cycle |
| Comma / Period | Decrease / increase wind |

Choose an aircraft from the title menu or press F8 during flight. The choice is saved.
The aircraft casts a sun-projected silhouette shadow, sharp near the ground and softer and fainter at altitude.
All gameplay audio is disabled.

Press Esc to open the pause menu's three flight-tuning sliders: W/S climb response,
acceleration, and A/D steering. Each runs from 0 to 100; higher values respond faster.
Changes apply when you resume and save automatically. Defaults are **V60 A50 S50**;
use the displayed V/A/S values when reporting how the controls feel.
W/S response controls both vertical motion and nose smoothing: 0 eases in slowly
(about six seconds to 95% climb rate), while 100 responds almost immediately
(about 0.15 seconds). It also changes how quickly the plane levels off after release.
The maximum W/S climb and descent speed scales from the original speed at 0
to triple that speed at 100, with intermediate settings scaling proportionally.
These sliders also apply while holding left click: climb response and movement
use the W/S setting, turns use the A/D setting, and Space acceleration uses the
acceleration setting while mouse steering is active.
Mouse and keyboard commands add independently on both axes. Full mouse input plus
a matching key gives 200% of one input's steering force; opposing commands cancel.
Keyboard steering costs an extra 0.18% of the tank per second per active axis,
including when counteracting the mouse. Arrow keys follow the same rules as WASD.
Releasing the keys removes the extra fuel cost and returns to mouse-only steering.
The pause menu also has a frame-cap selector. The map shows heading, the aircraft, and gate targets.
The HUD uses feet, mph, and US gallons. The tank starts at 20 gallons. Boost trades fuel and
control authority for speed, with twice the original acceleration. Both planes currently
max out at Mach 5 (about 3,806 mph), using a fixed sea-level speed-of-sound reference of about 761 mph.
Releasing boost eases back to cruise.

## Launch options

```powershell
python main.py --mode rings --fps 120
python main.py --mode free --fps 0 --wireframe
python main.py --fullscreen --city "Troy, NY"
```

`--city` chooses a live-weather source. `--renderer cpu` enables the CPU fallback.
`--altitude` accepts feet. `--day-length` sets real seconds per simulated 24-hour day.

Three small city clusters use 36 buildings derived from the supplied Blender models,
with flat material colours and distance culling. The CPU fallback uses simple building
proxies beyond 700 metres; the GPU renderer keeps the exported meshes.

## Multiplayer baseline

Start a server on the host computer:

```powershell
python server.py --host 0.0.0.0 --port 8765
```

Join from the same computer:

```powershell
python main.py --connect 127.0.0.1:8765 --name PilotOne --plane classic
```

On another computer on the LAN, replace `HOST_IP` with the server computer's IPv4 address:

```powershell
python main.py --connect HOST_IP:8765 --name PilotTwo --plane f15
```

The server assigns player IDs, distributes a world seed and starting clock, and relays validated
movement and aircraft selections at 20 Hz. Clients interpolate remote aircraft, share GPU depth
with the local plane, and show other pilots on the map. The room limit is configurable up to
100 players. Verification uses two simultaneous game clients.

### Online play (over the internet)

The same server also speaks WebSocket, which is what cloud hosts route. Run it in the cloud with the
included `render.yaml` (Render → New → Blueprint → this repo, free plan; it installs only
`requirements-server.txt` and starts `python server.py`, which picks up Render's `$PORT`). Then everyone joins with:

```powershell
python main.py --connect wss://YOUR-SERVICE.onrender.com --name PilotOne
```

To test online mode locally: `python server.py --websocket 8080` and `python main.py --connect ws://127.0.0.1:8080`.
`/health` reports how many pilots are online. A free Render service sleeps after 15 idle minutes and takes about
a minute to wake, so open `https://YOUR-SERVICE.onrender.com/health` a few minutes before a demo
(the game also waits up to 75 s when connecting).

Use `127.0.0.1` rather than `localhost` on Windows (it avoids a slow IPv6 attempt first).

Finding each other: every other pilot has a floating name tag with their distance, an arrow on the
screen edge when they are off screen or behind you, and a blue dot on the map. New pilots join just
behind and beside someone already flying (same heading, height and speed), and Restart online
puts you next to another pilot. The server keeps a slow shared clock (`--hour 10 --day-length 3600`
by default) so a demo stays in daylight.

### Multiplayer Ring Race

Everyone in the room who picks race mode races the same gold gates:

```powershell
python server.py --host 0.0.0.0 --port 8765          # or: python server.py --websocket 8080
python main.py --connect 127.0.0.1:8765 --name Ann --mode race
python main.py --connect 127.0.0.1:8765 --name Bo --mode race
```

Online it is the same with `--connect wss://YOUR-SERVICE.onrender.com`. While connected, the main
menu (ESC, Main Menu) also offers **Ring Race**.

- The server runs the rounds: a 5 s countdown on every screen (everyone is parked on a starting
  grid), the race through 12 gates, a results board for 12 s, then a new round on a new course.
  Every client builds the course from the round seed the server sends, so all courses are identical.
- Miss a gate and you have to turn back through it. The panel shows your position, gates and time;
  the board on the right shows the live order with gaps to the leader.
- Join mid-race and you spectate (the course is shown) until the next round. Leaving mid-race is a DNF.
  A round ends when every racer has finished or left, 45 s after the winner, or after 5 minutes.
- The server is authoritative: it only accepts one more gate at a time, from near that gate, no
  sooner than a straight Mach 5 line allows, and it times finishes itself (a client's own finish
  time is used only if it is within a second of when the server heard it).
- `python server.py --countdown 3 --results 8` shortens the cycle for demos (the countdown is at least 2 s).
- Restart during a race puts you back on the grid or just past your last counted gate, facing the next one.
  If you go to the menu mid-round you spectate until the next round. If the server goes away, the race
  HUD says so and you fly on freely.
- A new game client joining an older server still flies together with everyone (no races) and prints
  that the server needs updating (LAN: pull and restart `server.py`; Render: redeploy).

Protocol version 2 adds optional `racing`, `round`, `gates`, `finish` and `idle` fields to state
messages and a `race` block plus server `time` to snapshots. Version 1 clients can still join and fly
together; they just never race.

Flight stays client-simulated, so this is a friendly-competition setup rather than a cheat-proof
one: authentication, matchmaking and cross-player collisions are future work.

Both selectable models use the same flight physics. The original `.blend` / `.blend1` files
and runtime `.npz` exports are under `assets/`; Blender is only needed when exporting a new model.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
