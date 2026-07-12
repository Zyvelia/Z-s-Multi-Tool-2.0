# core/settings.py

import json
import os

from core import paths

SETTINGS_FILE = paths.migrate_legacy_file(
    paths.data_path("settings.json"),
    "settings.json"
)

DEFAULT = {
    "theme": "dark",
    "auto_update_check": True,
    "hidden_tools": []
}


class SettingsManager:

    def __init__(self):
        self.data = DEFAULT.copy()
        self.load()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    self.data.update(json.load(f))
            except:
                self.data = DEFAULT.copy()

    def save(self):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self.data, f, indent=4)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def reset(self):
        self.data = DEFAULT.copy()
        self.save()