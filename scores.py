"""Best scores and progress, kept in a small JSON file in the user's home folder."""

import json
import os
from pathlib import Path


def save_path():
    folder = os.environ.get('PLANEPLANE_HOME')
    return Path(folder) / 'scores.json' if folder else Path.home() / '.planeplane' / 'scores.json'


class Scores:
    def __init__(self, path=None):
        self.path = Path(path) if path else save_path()
        self.data = {}
        try:
            loaded = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            pass  # first run or a damaged file: start fresh

    def get(self, key, default=0):
        value = self.data.get(key, default)
        return value if isinstance(value, type(default)) else default

    def best(self, key, value):
        """Record value if it beats the stored best; returns True for a new record."""
        if value > self.get(key):
            self.data[key] = value
            self.save()
            return True
        return False

    def add_to_set(self, key, item):
        items = self.get(key, [])
        if item not in items:
            self.data[key] = items + [item]
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
            temporary.replace(self.path)
        except OSError as error:
            print(f'Could not save scores: {error}')
