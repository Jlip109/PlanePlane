# Plane² — HackRPI 2026 "In the Clouds"

A flight through a living sky: drifting cloud layers, a day/night cycle, live real-world weather and a ring-run game.

## Run it

```
pip install -r requirements.txt
python main.py
```

Add `--city "Troy, NY"` to start with live weather (Open-Meteo, no API key), `--game` to start a ring run, or `--preset storm` for a thunderstorm. If the GPU renderer fails, use `--renderer cpu`.

## Controls

| Key | Action |
| --- | --- |
| W / S, A / D | Climb / descend, turn |
| Space (hold) | Boost from about 168 mph toward Mach 1 (about 761 mph), consuming extra fuel and reducing turning/climbing authority. Releasing eases back to cruise speed. |
| V | Toggle third-person chase camera and first-person view |
| Right mouse (hold), UP / DOWN, R | Look around, reset view |
| N | Start or stop a ring run: fly through the gold ring before the clock runs out (+12 s per ring) |
| L | Live weather on/off (real cloud cover, wind, rain, storms and local time) |
| 1 2 3 4 | Clear, broken cloud, overcast (rain), storm (lightning) |
| LEFT / RIGHT, P, [ ] | Change time, pause the day cycle, cycle speed |
| , / . | Less / more wind |
| G, F11, ESC | Ground color, fullscreen, release mouse or quit |

The default chase camera shows the supplied Blender aircraft. Hold right mouse to orbit it.
The HUD uses feet for altitude and ring distances, mph for airspeed and wind, and US gallons for fuel.
The prototype starts with a 20-US-gallon tank. An empty tank disables boost and climbing, and the plane slows into a glide.
Mach 1 uses a fixed standard sea-level speed of sound at 59°F. At the cap, the HUD displays
`MACH 1 - SPEED OF SOUND`. The `--altitude` argument accepts feet, e.g. `--altitude 5000`.
Use `--camera first` to start in first-person view. The original model is in
`assets/PlaneModel-PlaneGame.blend`, and the game loads its exported mesh from `assets/plane_mesh.npz`.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```
