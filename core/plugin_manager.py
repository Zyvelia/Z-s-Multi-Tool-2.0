import importlib
import os
import sys


def _resolve_page(spec):
    if not isinstance(spec, str):
        return spec
    mod_name, cls_name = spec.rsplit(":", 1)
    return getattr(importlib.import_module(mod_name), cls_name)


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
            "open": callable,          # legacy
            "page_class": type,        # preferred — auto-wrapped with settings + themes
        }
        """
        tool = dict(tool)
        name = tool.get("name", "")

        qt_page = tool.pop("qt_page", None)
        tool.pop("page_class", None)
        tool.pop("widget", None)
        if qt_page is not None:
            def _open_qt(manager, pc=qt_page, mid=name):
                from core.qt.module_shell import open_qt_module

                return open_qt_module(manager, mid, _resolve_page(pc))

            tool["open_qt"] = _open_qt

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

        self._enable_marketplace_overlay()
        if os.path.exists(scan_path):
            self._scan_and_load(scan_path, module_folder)
            self._tag_untagged("bundled")
        else:
            print(f"[PluginManager] No bundled modules folder at {scan_path}")

        overlay_path = self._overlay_path()
        if overlay_path and os.path.isdir(overlay_path) and os.listdir(overlay_path):
            self._forget_overlay_imports()
            self._patch_overlay_package_paths()
            print("[PluginManager] Scanning marketplace overlay:", overlay_path)
            self._scan_and_load(overlay_path, module_folder)
            self._tag_untagged("marketplace")

        self._dedupe_tools()
        self._apply_installed_meta()

        print(f"[PluginManager] Loaded plugins: {len(self.tools)}")

    def reload(self):
        importlib.invalidate_caches()
        self.load_plugins()

    def _overlay_path(self):
        try:
            from core.marketplace import dirs

            return str(dirs.overlay_modules())
        except Exception:
            return ""

    def _enable_marketplace_overlay(self):
        overlay = self._overlay_path()
        if not overlay:
            return
        try:
            modules = importlib.import_module("modules")
        except Exception as e:
            print(f"[PluginManager] Could not import modules namespace: {e}")
            return
        paths = list(getattr(modules, "__path__", []))
        if overlay in paths:
            paths.remove(overlay)
        modules.__path__ = [overlay] + paths

    def _patch_overlay_package_paths(self):
        overlay = self._overlay_path()
        if not overlay or not os.path.isdir(overlay):
            return
        for dirpath, dirnames, _filenames in os.walk(overlay):
            dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
            rel = os.path.relpath(dirpath, overlay)
            if rel == ".":
                continue
            dotted = "modules." + rel.replace(os.sep, ".")
            try:
                pkg = importlib.import_module(dotted)
            except Exception:
                continue
            if not hasattr(pkg, "__path__"):
                continue
            paths = list(pkg.__path__)
            if dirpath in paths:
                paths.remove(dirpath)
            pkg.__path__ = [dirpath] + paths

    def _forget_overlay_imports(self):
        try:
            from core.marketplace.client import load_installed
            from core.marketplace.reload_app import forget_module_imports
        except Exception:
            return
        for rec in load_installed().values():
            forget_module_imports(rec.get("relpath"))

    def _tag_untagged(self, origin: str):
        from core.marketplace import dirs

        for tool in self.tools:
            if tool.get("_origin"):
                continue
            tool["_origin"] = origin
            tool["_module_id"] = dirs.slug(tool.get("name") or "")
            tool["_build"] = 0 if origin == "bundled" else tool.get("_build") or 0

    def _dedupe_tools(self):
        by_name = {}
        for tool in self.tools:
            name = tool.get("name")
            prev = by_name.get(name)
            if prev is None or tool.get("_origin") == "marketplace":
                by_name[name] = tool
        self.tools = list(by_name.values())

    def _apply_installed_meta(self):
        try:
            from core.marketplace import dirs
            from core.marketplace.client import load_installed
        except Exception:
            return
        records = load_installed()
        for tool in self.tools:
            mid = tool.get("_module_id") or dirs.slug(tool.get("name") or "")
            rec = records.get(mid)
            if not rec:
                continue
            tool["_module_id"] = mid
            tool["_build"] = int(rec.get("build") or 0)
            tool["_origin"] = rec.get("origin") or tool.get("_origin")
            tool["_label"] = rec.get("label")

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
                    try:
                        with open(path, encoding="utf-8") as fh:
                            src = fh.read()
                    except Exception:
                        src = ""
                    if "def register" not in src:
                        continue
                    module_name = f"{dotted_prefix}.{item[:-3]}"
                    print("[PluginManager] Import file:", module_name)

                    module = importlib.import_module(module_name)

                    if hasattr(module, "register"):
                        module.register(self)

            except Exception as e:
                print(f"[PluginManager] Failed loading {item}: {e}")