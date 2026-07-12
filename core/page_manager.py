# core/page_manager.py

class PageManager:

    def __init__(self, container):
        self.container = container
        self.pages = {}
        self.current = None

        # Pressing Escape jumps back to the catalog (home) page.
        # Bound directly on the root window, so it only ever fires
        # while this app's window actually has focus — pressing Esc
        # in some other app won't trigger it. Works automatically for
        # every module, current and future, since it's global rather
        # than per-module.
        self.container.bind("<Escape>", self._on_escape)

    def add_page(self, name, page):
        if name not in self.pages:
            self.pages[name] = page
            page.grid(row=0, column=0, sticky="nsew")

    def _on_escape(self, event=None):
        if self.current is not self.pages.get("catalog"):
            self.show_page("catalog")

    def show_page(self, name):
        page = self.pages.get(name)

        if not page:
            print(f"[PageManager] Missing page: {name}")
            return

        try:
            # Update Discord presence when a new page is shown
            self.container.discord_service.update(
                name, # Using 'name' for page_name as requested
                "Using Z's Multi Tool"
            )
        except Exception:
            # Silently catch exceptions if Discord service is not available or fails
            pass

        self.current = page
        page.tkraise()

        # Optional lifecycle hook: pages can define on_show() to refresh
        # themselves whenever they're navigated to (e.g. picking up state
        # that changed while another page was visible).
        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception as e:
                print(f"[PageManager] on_show failed for {name}: {e}")
