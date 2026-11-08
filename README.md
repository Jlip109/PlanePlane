# Plane² — In the Clouds

A Python flight game with two modes, a third-person aircraft, flat-coloured terrain, and a living sky.

## Run

For the standalone Windows x64 build, double-click `PlanePlane.exe`. Python and
Blender are not required, and the runtime assets are bundled inside the executable.
The launcher opens first for username, plane, RGB colour and online/offline selection.
Online play connects to the same Render service as the Python version.
If startup fails, a dialog gives the error and log path (`%LOCALAPPDATA%\PlanePlane\game.log`).

To rebuild the executable on Windows:

```powershell
.\build_exe.ps1
```

The result is `dist\PlanePlane.exe`. Build dependencies are separate from the server
requirements. Source Blender files and build output are excluded from the executable.

```powershell
python -m pip install -r requirements.txt
python main.py
```

The launcher asks for a username, RGB plane colour, aircraft and server address before
connecting. **CREATE LOBBY** and **JOIN LOBBY** connect to `wss://planeplane.onrender.com`.
Offline Free Roam and Ring Mode remain available. Framerate defaults to uncapped.

## Online Free for All

The server and every player must run this update. Push the changes and redeploy the
Render service before joining; an older server cannot run the new lobby protocol.
No terminal commands are needed after the launcher opens.

There are exactly three lobby slots, **Lobby 1**, **Lobby 2** and **Lobby 3**, with a
maximum of 24 connected racers each. CREATE opens an empty slot; JOIN selects an
existing lobby. Each lobby has its own players, course, weather, readiness and clock.
Empty lobbies close and free their slot. The directory updates live. A full or occupied
slot reports an error without disconnecting the player.

Everyone clicks **READY** (or presses Enter). A solo pilot can click **START PRACTICE**;
the run shows timing and points but does not save competitive records. The player list
locks when loading starts; late arrivals wait for the next round. The server displays “Waiting for the match
to finalize” while it loads a shared course and weather, then places pilots on the
starting runway for a five-second countdown. Hold Space to accelerate, then W or
left-mouse upward steering to take off. The username is reserved while connected;
duplicate names are rejected, and disconnecting frees the name.

Each route has 48 required rings along about 22 miles of twists, turns and climbs above
12,000 feet. It targets roughly two minutes at 670 mph, rather than imposing a fixed
two-minute race cutoff. The route always descends toward the finish runway. Blue rings
award 100 points, smaller red rings award 200. Missing a ring does not advance the course;
return and clear it before continuing. Green fuel rings remain optional detours.

Clearing the course and touching the finish runway immediately shows **FINISHED** with
the pilot's elapsed time. Finish order determines placing. The first finisher starts a
30-second countdown for everyone else; remaining racers are disqualified at the cutoff.
If everyone finishes or is disqualified sooner, the results start immediately. There is
a ten-minute no-finisher failsafe. Competitive finish times and scores update local best
records; solo practice never writes them. Server session records last for the room lifetime.

A controlled landing adds 500 bonus points when speed is at most 123 mph and the wings
and nose are nearly level. A faster runway arrival still finishes, without that bonus.
After finishing, the aircraft automatically brakes to zero, stays inside the runway,
and ignores throttle/steering inputs while the finish time and placing remain fixed.
Hold **E** to brake, even while holding Space. Brakes can stop the plane on the runway;
in the air they reduce speed toward 78 mph. Runway contact cannot cause a crash.

Crashing, leaving the match, disconnecting, or straying more than 5,906 feet from the
3D course disqualifies the pilot from winning. The first valid finisher wins a competitive
race. Results show for 15 seconds before everyone returns to the READY lobby.
Late arrivals wait for the next round. The offline Ring Mode Range slider does not
change this shared competitive boundary. Pausing does not stop the online race clock.

The server randomly chooses a real location and requests its current Open-Meteo weather.
The location and course are withheld from clients throughout loading and the countdown,
then revealed together at GO. The runway staging area uses neutral weather until then.
Everyone shares that weather and the location's current local time, frozen for the round.
Weather failure is labelled explicitly; local time still comes from the city's timezone.
Terrain and cities remain procedural rather than geographic reconstructions.
The location pool is Karachi, Saratoga Springs, Los Angeles, Nuuk, Tokyo, Stockholm,
Cairo, Darwin and Honolulu. To pin one while testing, start the server with, for example:

```powershell
python server.py --websocket 8080 --location "Darwin, Australia"
```

`temperature.py` applies a standard tropospheric lapse rate of about 3.57°F per
1,000 feet above the race runway's weather reference elevation. The HUD shows air
temperature; the ground palette and tree species use the observed surface temperature.
This is an atmosphere approximation, not a prediction of local inversions. The model
is based on the [NASA Glenn atmosphere reference](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/earth-atmosphere-equation-metric/).
Warmer air increases fuel use modestly (about +6% at 100°F versus 59°F); this fuel
modifier is a game rule. Green fuel rings sit off the scoring route, refill 5 US gallons
(capped at a full tank), and award zero points. Each pilot can collect each fuel ring
once per round, independently of other pilots. Fuel collection is scored by the server.

The supplied 32-column grass palette selects column 0 at 100°F or hotter, moving right
one column per 3.125°F drop, capped at column 31 at 0°F or colder. Grass polygons keep
single colours sampled from that column. Trees 1 and 2 grow only on green dry grass;
below 32°F, Tree3 replaces them on dry land. Trees avoid water, runways and buildings,
and city building footprints are moved off water. Trees are distance-culled sprites.

Original, F-15 and Plane Odd are selectable and share Mach 5 flight physics for now.
W/S response at 100 now has twice the previous top vertical speed (six times the base
rate); mouse and emergency keyboard inputs still add and use the same tuning.

To bypass the launcher for a local server test:

```powershell
python main.py --mode ffa --connect ws://127.0.0.1:8080 --name PilotOne --plane odd --color "255,0,0"
python main.py --mode ffa --connect ws://127.0.0.1:8080 --name PilotTwo --lobby-action join --lobby 1
```

`--lobby-action create --lobby 2` creates Lobby 2 directly. `--lobby-action browse`
opens the directory. The default command-line action joins or creates Lobby 1.
Protocol version 2 requires updated clients and server; rebuild the `.exe` as well
as redeploying Render when moving from the previous single-lobby release.

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
| Hold E | Brake; overrides Space |
| Hold left mouse and drag | Smoothly aim and steer the aircraft; the camera follows its motion |
| Hold right mouse and drag | Look around without steering |
| Hold middle mouse and drag | Orbit freely around the plane without mouse steering; temporarily uses chase view |
| R | Center the camera |
| V | Switch chase / cockpit camera |
| F5 | Toggle terrain, aircraft, and gate wireframe |
| F7 | Cycle 60 FPS, 120 FPS, and Uncapped |
| Esc | Release captured mouse, then pause / resume |
| F11 or Alt+Enter | Fullscreen |
| F8 | Cycle Original, F-15 and Plane Odd |
| F1 / F2 / F3 / F4 | Clear, broken clouds, overcast, storm |
| L | Toggle live weather |
| G | Summer / autumn / winter colours |
| P | Pause the day cycle |
| [ / ] | Slow / accelerate the day cycle |
| Comma / Period | Decrease / increase wind |

Choose an aircraft from the title menu or press F8 during flight. The choice is saved.
The aircraft casts a sun-projected silhouette shadow, sharp near the ground and softer and fainter at altitude.
All gameplay audio is disabled.
Middle-mouse freecam takes priority over left-mouse steering when both are held.
Releasing middle mouse restores the previous cockpit/chase view; R centres the camera.

Press Esc to open the pause menu's three flight-tuning sliders: W/S climb response,
acceleration, and A/D steering. Each runs from 0 to 100; higher values respond faster.
Changes apply when you resume and save automatically. Defaults are **V60 A50 S50**;
use the displayed V/A/S values when reporting how the controls feel.
W/S response controls both vertical motion and nose smoothing: 0 eases in slowly
(about 3.4 seconds to 95% climb rate), while 100 responds almost immediately
(about 0.086 seconds). It also changes how quickly the plane levels off after release.
The maximum W/S climb and descent speed scales from the original speed at 0
to six times that speed at 100, with intermediate settings scaling proportionally.
These sliders also apply while holding left click: climb response and movement
use the W/S setting, turns use the A/D setting, and Space acceleration uses the
acceleration setting while mouse steering is active.
Mouse and keyboard commands add independently on both axes. Full mouse input plus
a matching key gives 200% of one input's steering force; opposing commands cancel.
Steering acceleration responds 1.75 times faster than the previous release, and all
flight fuel consumption is four times higher. At standard temperature, cruise consumes
0.32% of the tank per second and continuous boost consumes 2.24% per second before
climbing and steering costs. Empty tanks disable Space acceleration.
With no fuel, forward drag slows the plane all the way to zero, and lost lift produces
an accelerating fall under gravity (downward speed capped at about 403 mph). W/S and
Space cannot arrest the fall. E still brakes forward speed. Collecting a fuel ring
restores powered flight. Safe post-finish rollout takes priority, even with an empty tank.
Keyboard steering costs an extra 0.72% of the tank per second per active axis,
including when counteracting the mouse. Arrow keys follow the same rules as WASD.
Releasing the keys removes the extra fuel cost and returns to mouse-only steering.
The pause menu also has a frame-cap selector. The map shows heading, the aircraft, and gate targets.
The HUD uses feet, mph, and US gallons. The tank starts at 20 gallons. Boost trades fuel and
control authority for speed, with twice the original acceleration. All planes currently
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

Free for All lobby, scoring, readiness, timer, disqualification and winners are server-owned.
Flight positions are still simulated by clients; this is not a cheat-resistant authoritative
flight server. Authentication, multiple simultaneous rooms and cross-player collisions are
future work. Offline Ring Mode scores remain local.

All selectable models use the same flight physics. The original `.blend` / `.blend1` files
and runtime `.npz` exports are under `assets/`; Blender is only needed when exporting a new model.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
