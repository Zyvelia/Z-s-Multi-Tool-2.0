import importlib
import os
import sys


class PluginManager:

    def __init__(self):
        self.tools = []

    # =====================================================
    # TOOL REGISTRATION
    # =====================================================

    def register(self, tool: dict):
        """
        Tool format:
        {
            "name": str,
            "category": str,
            "desc": str,
            "open": callable
        }
        """
        self.tools.append(tool)

    def get_tools(self):
        return self.tools

    def clear(self):
        self.tools.clear()

    # =====================================================
    # PLUGIN LOADER
    # =====================================================

    def load_plugins(self, module_folder="modules"):
        """
        Auto-import modules and let them self-register
        via `register(manager)` function.
        """

        self.clear()

        print("[PluginManager] Loading plugins...")

        # When frozen (PyInstaller), --add-data files are extracted to
        # sys._MEIPASS at runtime, NOT to the exe's working directory.
        # sys._MEIPASS is already on sys.path (bootloader adds it), so the
        # dotted import name "modules.xxx" still resolves fine — we just
        # need to point the directory SCAN at the right place.
        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = os.getcwd()

        scan_path = os.path.join(base_path, module_folder)

        if not os.path.exists(scan_path):
            print(f"[PluginManager] No modules folder found at {scan_path}")
            return

        self._scan_and_load(scan_path, module_folder)

        print(f"[PluginManager] Loaded plugins: {len(self.tools)}")

    def _scan_and_load(self, scan_path, dotted_prefix, depth=0, max_depth=None):
        """
        Scans `scan_path` and imports/registers whatever it finds.

        - A directory containing __init__.py is a tool package: import it
          and call its register(manager) if present. Recursion stops here
          — a tool package's own internal subfolders are never mistaken
          for more category folders.
        - A directory WITHOUT __init__.py is treated as a plain category
          folder (e.g. modules/Files/, modules/Security/Network/) used
          only to group tool folders in the filesystem — it has no
          registration of its own, so we recurse into it looking for
          tool packages instead of importing it directly. Category
          nesting can now go arbitrarily deep (modules/Cat/Subcat/Tool/,
          etc). Set `max_depth` to cap how many category levels deep the
          scan will go; leave it as None for unlimited recursion.
        - A loose .py file (not __init__.py) is a single-file module.
        """

        for item in sorted(os.listdir(scan_path)):

            if item == "__pycache__" or item.startswith("."):
                continue

            path = os.path.join(scan_path, item)

            try:
                if os.path.isdir(path):
                    if os.path.exists(os.path.join(path, "__init__.py")):
                        # ---------------- PACKAGE MODULE ----------------
                        module_name = f"{dotted_prefix}.{item}"
                        print("[PluginManager] Import package:", module_name)

                        module = importlib.import_module(module_name)

                        # call register(manager)
                        if hasattr(module, "register"):
                            module.register(self)

                    elif max_depth is None or depth < max_depth:
                        # ---------------- CATEGORY FOLDER ----------------
                        print("[PluginManager] Scanning category folder:", item)
                        self._scan_and_load(
                            path,
                            f"{dotted_prefix}.{item}",
                            depth=depth + 1,
                            max_depth=max_depth,
                        )

                    else:
                        print(f"[PluginManager] Skipping (no __init__.py, too deep): {item}")

                # ---------------- SINGLE FILE MODULE ----------------
                elif item.endswith(".py") and item != "__init__.py":
                    module_name = f"{dotted_prefix}.{item[:-3]}"
                    print("[PluginManager] Import file:", module_name)

                    module = importlib.import_module(module_name)

                    if hasattr(module, "register"):
                        module.register(self)

            except Exception as e:
                print(f"[PluginManager] Failed loading {item}: {e}")