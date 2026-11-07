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
| Right mouse (hold), UP / DOWN, R | Look around, reset view |
| N | Start or stop a ring run: fly through the gold ring before the clock runs out (+12 s per ring) |
| L | Live weather on/off (real cloud cover, wind, rain, storms and local time) |
| 1 2 3 4 | Clear, broken cloud, overcast (rain), storm (lightning) |
| LEFT / RIGHT, P, [ ] | Change time, pause the day cycle, cycle speed |
| , / . | Less / more wind |
| G, F11, ESC | Ground color, fullscreen, release mouse or quit |

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```
