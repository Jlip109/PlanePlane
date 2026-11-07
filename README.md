# Plane² — In the Clouds

A Python flight game with two modes, a third-person aircraft, flat-coloured terrain, and a living sky.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

Choose **Free Roam** to explore or **Ring Mode** to fly through ten-sided 3D gates.
Clear gates before the timer runs out to gain time and build a score multiplier.
Blue gates have larger openings (105-metre radius); red gates are smaller
(45-metre radius). They alternate along a route with gradual turns and elevation changes.
Use **Esc → Ring path range** to set the allowed distance from the 3D route,
from 250 to 5,000 feet. The setting saves automatically. Leaving the route shows
a five-second return countdown; returning resets it, while staying out ends the run.
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

This is a LAN multiplayer foundation with client-simulated flight. Competitive authority,
authentication, matchmaking, shared scoring and cross-player collisions are future work.
Ring scoring currently runs locally on each client.

Both selectable models use the same flight physics. The original `.blend` / `.blend1` files
and runtime `.npz` exports are under `assets/`; Blender is only needed when exporting a new model.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
