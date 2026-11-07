"""Synthesized sound: engine, wind, rain, thunder and interface chimes. No audio files needed.

If the computer has no usable audio device, every method quietly does nothing.
"""

import math

import numpy as np

RATE = 44100


def tone(frequency, seconds, decay=6.0, harmonics=(1.0, 0.35, 0.12)):
    t = np.arange(int(RATE * seconds)) / RATE
    wave = sum(weight * np.sin(2 * math.pi * frequency * (n + 1) * t) for n, weight in enumerate(harmonics))
    attack = np.minimum(1.0, t / 0.006)
    return wave * attack * np.exp(-t * decay)


def noise(seconds, rng, smooth=1):
    signal = rng.standard_normal(int(RATE * seconds))
    if smooth > 1:
        kernel = np.ones(smooth) / smooth
        signal = np.convolve(signal, kernel, mode='same')
    return signal / (np.abs(signal).max() + 1e-9)


def loopable(signal, fade=0.25):
    """Crossfade the tail into the head so the loop has no click."""
    n = int(RATE * fade)
    ramp = np.linspace(0, 1, n)
    head, tail = signal[:n].copy(), signal[-n:]
    signal = signal[:-n].copy()
    signal[:n] = head * ramp + tail * (1 - ramp)
    return signal


def sequence(notes, gap=0.07, decay=7.0):
    total = int(RATE * (gap * len(notes) + 0.6))
    out = np.zeros(total)
    for index, frequency in enumerate(notes):
        part = tone(frequency, 0.6, decay)
        start = int(RATE * gap * index)
        out[start:start + len(part)] += part[:total - start]
    return out


class Audio:
    def __init__(self, pygame, enabled=True, seed=3):
        self.pg = pygame
        self.enabled = False
        self.muted = False
        self.pending = []
        self.rng = np.random.default_rng(seed)
        if not enabled:
            return
        try:
            pygame.mixer.pre_init(RATE, -16, 2, 512)
            pygame.mixer.init(RATE, -16, 2, 512)
            pygame.mixer.set_num_channels(16)
            self.build(np.random.default_rng(seed))
            self.loops = {name: pygame.mixer.Channel(index) for index, name in enumerate(('engine', 'boost', 'wind', 'rain'))}
            for name, channel in self.loops.items():
                channel.play(self.sounds[name], loops=-1)
                channel.set_volume(0.0)
            pygame.mixer.set_reserved(len(self.loops))
            self.enabled = True
        except Exception as error:  # no device, no driver, or no numpy support in the mixer
            print(f'Sound disabled: {error}')

    def make(self, signal, volume):
        signal = np.clip(signal / (np.abs(signal).max() + 1e-9) * volume, -1, 1)
        stereo = np.repeat((signal * 32767).astype(np.int16)[:, None], 2, axis=1)
        return self.pg.sndarray.make_sound(np.ascontiguousarray(stereo))

    def build(self, rng):
        t = np.arange(RATE * 2) / RATE
        hum = (np.sin(2 * math.pi * 70 * t) + 0.5 * np.sin(2 * math.pi * 140 * t) + 0.25 * np.sin(2 * math.pi * 210 * t)
               + 0.15 * np.sin(2 * math.pi * 35 * t))
        hum *= 0.85 + 0.15 * np.sin(2 * math.pi * 4 * t)
        whine = (np.sin(2 * math.pi * 105 * t) + 0.6 * np.sin(2 * math.pi * 210 * t) + 0.3 * np.sin(2 * math.pi * 420 * t))
        whine *= 0.8 + 0.2 * np.sin(2 * math.pi * 7 * t)
        wind = loopable(noise(3.25, rng, smooth=60) * (0.7 + 0.3 * np.sin(np.linspace(0, 6 * math.pi, int(RATE * 3.25)))))
        rain_raw = noise(2.25, rng)
        rain = loopable(rain_raw - np.convolve(rain_raw, np.ones(8) / 8, mode='same'))
        thunder_t = np.arange(int(RATE * 3.5)) / RATE
        thunder = noise(3.5, rng, smooth=120) * np.exp(-thunder_t * 1.2) * (1 - np.exp(-thunder_t * 30))
        crash_t = np.arange(int(RATE * 1.4)) / RATE
        crash = (noise(1.4, rng, smooth=20) * np.exp(-crash_t * 3) + np.sin(2 * math.pi * 48 * crash_t) * np.exp(-crash_t * 5))
        self.sounds = {
            'engine': self.make(hum, 0.5), 'boost': self.make(whine, 0.45), 'wind': self.make(wind, 0.6),
            'rain': self.make(rain, 0.5), 'thunder': self.make(thunder, 0.9), 'crash': self.make(crash, 0.8),
            'tick': self.make(tone(1800, 0.05, 60, (1.0,)), 0.25),
            'select': self.make(sequence([880, 1320], 0.06, 12), 0.35),
            'ring': self.make(sequence([1047, 1319, 1568], 0.05, 9), 0.4),
            'miss': self.make(tone(160, 0.3, 9, (1.0, 0.6, 0.4)), 0.35),
            'pickup': self.make(sequence([660, 990], 0.08, 8), 0.4),
            'deliver': self.make(sequence([784, 988, 1175, 1568], 0.07, 7), 0.45),
            'record': self.make(sequence([523, 659, 784, 1047, 1319], 0.09, 5), 0.45),
            'start': self.make(noise(0.6, rng, smooth=30) * np.linspace(0, 1, int(RATE * 0.6)) ** 2, 0.3),
        }

    def play(self, name, delay=0.0):
        if not self.enabled or self.muted or name not in self.sounds:
            return
        if delay > 0:
            self.pending.append([delay, name])
            return
        self.sounds[name].play()

    def toggle_mute(self):
        self.muted = not self.muted
        if self.enabled and self.muted:
            for channel in self.loops.values():
                channel.set_volume(0.0)
        return self.muted

    def update(self, dt, atmosphere, flying):
        if not self.enabled:
            return
        for item in self.pending:
            item[0] -= dt
        for _, name in [item for item in self.pending if item[0] <= 0]:
            self.play(name)
        self.pending = [item for item in self.pending if item[0] > 0]
        for name, _ in atmosphere.events:
            if name == 'lightning':
                self.play('thunder', delay=0.4 + 1.6 * (1 - atmosphere.storm) + self.rng.uniform(0, 1))
            elif name == 'crash':
                self.play('crash')
        if self.muted:
            return
        speed = atmosphere.speed / 150
        alive = 0.0 if atmosphere.crashed else 1.0
        volumes = {
            'engine': (0.16 + 0.12 * min(speed, 1.0)) * alive * (1.0 if flying else 0.5),
            'boost': (0.22 if atmosphere.boosting else 0.0) * alive,
            'wind': min(0.35, 0.08 + speed * 0.12 + atmosphere.wind / 45 * 0.18),
            'rain': atmosphere.precipitation * 0.35 * min(1.0, max(0.0, (1700 - atmosphere.altitude) / 800)),
        }
        for name, target in volumes.items():
            channel = self.loops[name]
            current = channel.get_volume()
            channel.set_volume(current + (target - current) * min(1.0, dt * 4))

    def close(self):
        if self.enabled:
            try:
                self.pg.mixer.stop()
                self.pg.mixer.quit()
            except Exception:
                pass
            self.enabled = False
