"""Pilot emotes: dances and gestures the pilot performs in the cockpit (keys 1-6 in flight)."""

from collections import namedtuple

Emote = namedtuple('Emote', 'key label clip duration')

# clip is the animation name in assets/people/clips_*.npz; duration in seconds before returning to idle.
EMOTES = [
    Emote('groove', 'Groove', 'dance_cool', 6.0),
    Emote('goofy', 'Goofy', 'dance_silly', 6.0),
    Emote('hype', 'Hype', 'dance_hype', 6.0),
    Emote('cheer', 'Cheer', 'cheer', 3.5),
    Emote('wave', 'Wave', 'wave', 3.0),
    Emote('clap', 'Clap', 'clap', 3.0),
]
BY_KEY = {emote.key: emote for emote in EMOTES}
IDLE_CLIP = 'sit_idle'       # seated, hands near the controls
LOBBY_IDLE_CLIP = 'stand_idle'
