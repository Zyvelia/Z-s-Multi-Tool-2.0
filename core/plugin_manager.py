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

        for item in os.listdir(scan_path):

            path = os.path.join(scan_path, item)

            try:
                # ---------------- PACKAGE MODULE ----------------
                if os.path.isdir(path) and os.path.exists(os.path.join(path, "__init__.py")):
                    module_name = f"{module_folder}.{item}"
                    print("[PluginManager] Import package:", module_name)

                    module = importlib.import_module(module_name)

                    # call register(manager)
                    if hasattr(module, "register"):
                        module.register(self)

                # ---------------- SINGLE FILE MODULE ----------------
                elif item.endswith(".py") and item != "__init__.py":
                    module_name = f"{module_folder}.{item[:-3]}"
                    print("[PluginManager] Import file:", module_name)

                    module = importlib.import_module(module_name)

                    if hasattr(module, "register"):
                        module.register(self)

            except Exception as e:
                print(f"[PluginManager] Failed loading {item}: {e}")

        print(f"[PluginManager] Loaded plugins: {len(self.tools)}")