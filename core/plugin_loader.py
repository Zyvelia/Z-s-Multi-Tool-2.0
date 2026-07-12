# core/plugin_loader.py

import os
import importlib
from core.tool_registry import clear_tools, get_tools


def load_plugins():
    clear_tools()

    module_path = "modules"

    for item in os.listdir(module_path):
        full = os.path.join(module_path, item)

        try:
            if os.path.isdir(full) and "__init__.py" in os.listdir(full):
                importlib.import_module(f"{module_path}.{item}")

            elif item.endswith(".py") and item != "__init__.py":
                importlib.import_module(f"{module_path}.{item[:-3]}")

        except Exception as e:
            print(f"[PluginLoader] Failed {item}: {e}")

    print("[PluginLoader] Loaded:", len(get_tools()))