"""Silent audio compatibility interface. Gameplay audio is currently disabled."""


class Audio:
    def __init__(self, pygame, enabled=False):
        self.enabled = False
        self.muted = True

    def play(self, name, delay=0.0):
        pass

    def toggle_mute(self):
        return True

    def update(self, dt, atmosphere, flying):
        pass

    def close(self):
        pass
