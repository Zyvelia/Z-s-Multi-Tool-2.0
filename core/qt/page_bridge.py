"""PageManager stand-in for the Qt shell."""

from __future__ import annotations


class PageBridge:
    def __init__(self, container, window, plugin_manager, settings):
        self.container = container
        self.window = window
        self.plugin_manager = plugin_manager
        self.settings = settings
        self.pages = {}
        self.current = None
        self.current_name = None

    def after(self, ms, callback):
        return self.container.after(ms, callback)

    def add_page(self, name, page):
        self.pages[name] = page

    def show_page(self, name):
        prev = self.current
        if name in ("catalog", "settings", "now", "marketplace"):
            if prev is not None and hasattr(prev, "on_hide") and prev is not self.pages.get(name):
                try:
                    prev.on_hide()
                except Exception:
                    pass
            self.window.show_qt_page(name)
            self.current = self.pages.get(name)
            self.current_name = name
            self._discord(name)
            self._restore_default_theme()
            page = self.pages.get(name)
            if page is not None and hasattr(page, "on_show"):
                try:
                    page.on_show()
                except Exception as e:
                    print(f"[PageBridge] on_show failed for {name}: {e}")
            return

        tool = self._tool_by_name(name)
        page = self.pages.get(name)
        if page is None:
            if tool is None or not tool.get("open_qt"):
                print(f"[PageBridge] Missing Qt page: {name}")
                return
            try:
                page = tool["open_qt"](self)
            except Exception as e:
                print(f"[PageBridge] open_qt failed for {name}: {e}")
                return
            if page is None:
                print(f"[PageBridge] open_qt() returned None for {name}")
                return
            self.pages[name] = page

        if prev is not None and hasattr(prev, "on_hide") and prev is not page:
            try:
                prev.on_hide()
            except Exception:
                pass

        self.window.show_qt_tool(page)
        self.current = page
        self.current_name = name
        self._discord(name)
        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception as e:
                print(f"[PageBridge] on_show failed for {name}: {e}")

    def _tool_by_name(self, name):
        for tool in self.plugin_manager.get_tools():
            if tool.get("name") == name:
                return tool
        return None

    def _discord(self, name):
        try:
            self.container.discord_service.update(name, "Using Z's Multi Tool")
        except Exception:
            pass

    def _restore_default_theme(self):
        try:
            from core.theme import restore_default_theme

            restore_default_theme()
        except Exception:
            pass
