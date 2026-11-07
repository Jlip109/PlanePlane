# Plane² — HackRPI 2026 "In the Clouds"

A flight through a living sky. Drifting cloud decks, a full day and night cycle, live real-world weather, and a countryside of farms, forests, lakes, villages and six cities to explore.

## Run it

```
pip install -r requirements.txt
python main.py
```

Python 3.10 or newer. On Python 3.14 the requirements install `pygame-ce` (regular pygame has no 3.14 build yet); everything else is identical. If your graphics driver can't do OpenGL 3.3, run `python main.py --renderer cpu`.

Useful options: `--mode free|rings|courier` skips the title screen, `--city "Troy, NY"` starts with live weather, `--preset storm` starts in a thunderstorm, `--camera first` starts in the cockpit, `--altitude 5000` (feet), `--fullscreen`, `--mute`.

## Play

| Mode | What you do |
| --- | --- |
| **Free Flight** | Fly anywhere. Each city's tower greets you the first time you arrive; discover all six. |
| **Ring Run** | Thread the gold gate before the clock runs out. Every gate adds time; clean runs build a ×5 combo. |
| **Sky Courier** | Five passengers, five deliveries. Fly low over a city to pick up, then race to the destination for a tip. |

Pick one of four pilots on the title screen — each flies a little differently (cruise speed, handling, boost).

## Controls

| Key | Action |
| --- | --- |
| W / S | Climb / descend |
| A / D | Turn |
| Space (hold) | Boost from about 168 mph toward Mach 1 (about 761 mph), burning extra fuel and reducing turning/climbing authority. Release to ease back to cruise. |
| V | Chase camera / cockpit view |
| Right mouse (hold), ↑ / ↓, R | Look around (orbits the plane in chase view), center view |
| 1 2 3 4 | Clear, broken cloud, overcast with rain, thunderstorm |
| L | Live weather for your city (Open-Meteo, no API key) |
| ← / →, P, [ ] | Move the clock, pause the day cycle, cycle speed |
| , / . | Less / more wind |
| G | Season (summer, autumn, winter) |
| H | All controls |
| Esc | Pause menu |
| M | Mute |
| F11 | Fullscreen |

## The aircraft

The chase camera shows the team's Blender aircraft (`assets/PlaneModel-PlaneGame.blend`, exported to `assets/plane_mesh.npz`). The HUD uses feet for altitude, mph for airspeed and wind, and US gallons for fuel. You start with a 20-gallon tank; an empty tank disables boost and climbing and the plane slows into a glide. Fly low over any city's center to refuel. Mach 1 uses the standard sea-level speed of sound at 59°F; at the cap the HUD shows `MACH 1 - SPEED OF SOUND`.

## The world

| City | Character |
| --- | --- |
| Troy | Brick river town and home base |
| Skyport | Glass towers above the haze |
| Nimbus Heights | Spires that pierce the clouds |
| Albany | The capital, dense and busy |
| Lake George | Lakeside resort town |
| Saratoga | Gardens, porches and racetracks |

Buildings are real 3D geometry on the GPU renderer, ray-marched through each city's lot grid; windows and streets light up at night. The same integer hashes generate the world in Python and GLSL, so what you see is exactly what you can crash into.

## Code map

`main.py` flight sim, CPU renderer and main loop · `gpu_renderer.py` OpenGL sky, terrain, cities and aircraft · `plane.py` aircraft mesh · `world.py` terrain, cities, villages · `game.py` game states · `modes.py` Free Flight, Ring Run, Sky Courier · `menu.py`, `hud.py`, `ui.py` interface · `characters.py` pilots, towers, passengers, radio · `life.py` balloons and geese · `effects.py` rain and lightning · `weather.py` live weather · `audio.py` synthesized sound · `scores.py` saved bests (`~/.planeplane/scores.json`)

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```
