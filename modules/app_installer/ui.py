"""
App Installer — UI.

Lets the user search for and install desktop apps (Discord, Chrome, Steam,
etc.) via Windows Package Manager (winget), plus define their own custom
install commands. Follows the shared ZsMultiTool module convention:
exposes a CTkFrame subclass that the plugin manager instantiates and
packs into `manager.container`.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from .backend import (
    AppResult,
    CommandWorker,
    CustomApp,
    InstallWorker,
    ProgressEvent,
    QUICK_APPS_BY_CATEGORY,
    SearchWorker,
    load_custom_apps,
    save_custom_apps,
    winget_available,
)

BG = "#0f1115"
PANEL = "#151922"
PANEL_2 = "#1b2030"
PANEL_BORDER = "#262c3d"
ACCENT = "#4ea1ff"
ACCENT_HOVER = "#3d8ae0"
DANGER = "#ff5c5c"
OK_COLOR = "#3ddc84"
MUTED = "#7d8494"

POLL_MS = 60
CATEGORIES = list(QUICK_APPS_BY_CATEGORY.keys())


class AppInstallerModule(ctk.CTkFrame):
    """App search/install module. `manager` is the plugin manager / root
    App instance (manager.container is the root, per the shared convention)."""

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.manager = manager

        self._search_worker: SearchWorker | None = None
        self._install_worker: InstallWorker | CommandWorker | None = None
        self._results: list[AppResult] = []
        self.custom_apps: list[CustomApp] = load_custom_apps()
        self.category_tabs: dict[str, ctk.CTkFrame] = {}

        self._build_layout()
        if not winget_available():
            self.status_label.configure(
                text="winget not found — install 'App Installer' from the Microsoft Store to search/install."
            )
            self.search_btn.configure(state="disabled")

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)  # results panel fills leftover space

        # ---- header ----
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        top_row.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            top_row, text="App Installer",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white",
        )
        header.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            top_row, text="+ Custom App", width=120, height=28, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=lambda: self._open_custom_dialog(),
        ).grid(row=0, column=1, sticky="e")

        # ---- search bar (top) ----
        search_bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        search_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        search_bar.grid_columnconfigure(0, weight=1)

        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(
            search_bar, textvariable=self.search_var,
            placeholder_text="Search for an app, e.g. 'Discord'",
            fg_color=PANEL_2, height=36, corner_radius=8,
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=10)
        self.search_entry.bind("<Return>", lambda _e: self._start_search())

        self.search_btn = ctk.CTkButton(
            search_bar, text="Search", width=90, height=36, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._start_search,
        )
        self.search_btn.grid(row=0, column=1, padx=(0, 10), pady=10)

        # ---- category tabs (curated apps + custom apps filed into them) ----
        self.quick_tabs = ctk.CTkTabview(
            self, fg_color=PANEL, segmented_button_fg_color=PANEL_2,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT,
            height=130,
        )
        self.quick_tabs.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        for category in CATEGORIES:
            tab = self.quick_tabs.add(category)
            self.category_tabs[category] = tab
            self._build_category_grid(category)

        # ---- search results panel ----
        results_panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        results_panel.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 12))
        results_panel.grid_columnconfigure(0, weight=1)
        results_panel.grid_rowconfigure(0, weight=1)

        self.results_frame = ctk.CTkScrollableFrame(results_panel, fg_color="transparent")
        self.results_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.results_frame.grid_columnconfigure(0, weight=1)
        self._show_placeholder("Search results will appear here.")

        # ---- status / progress ----
        status_row = ctk.CTkFrame(self, fg_color="transparent")
        status_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        status_row.grid_columnconfigure(1, weight=1)

        self.progress = ctk.CTkProgressBar(status_row, progress_color=ACCENT, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.progress.grid_remove()

        self.status_label = ctk.CTkLabel(status_row, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="w")

    # ------------------------------------------------------------ category grids

    def _build_category_grid(self, category: str) -> None:
        """(Re)builds one category tab: curated apps first, then any custom
        apps the user filed under this category."""
        parent = self.category_tabs[category]
        for w in parent.winfo_children():
            w.destroy()

        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.pack(fill="x", padx=4, pady=4)
        cols_per_row = 4
        for c in range(cols_per_row):
            row_frame.grid_columnconfigure(c, weight=1)

        entries = list(QUICK_APPS_BY_CATEGORY.get(category, []))
        custom_entries = [
            (i, app) for i, app in enumerate(self.custom_apps) if app.category == category
        ]

        i = 0
        for name, pkg_id in entries:
            r, c = divmod(i, cols_per_row)
            btn = ctk.CTkButton(
                row_frame, text=name, height=28, corner_radius=8,
                fg_color=PANEL_2, hover_color=ACCENT,
                border_width=1, border_color=PANEL_BORDER,
                text_color="#e4e7ee",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda pid=pkg_id, n=name: self._quick_install(pid, n),
            )
            btn.grid(row=r, column=c, padx=4, pady=3, sticky="ew")
            i += 1

        for idx, app in custom_entries:
            r, c = divmod(i, cols_per_row)
            btn = ctk.CTkButton(
                row_frame, text=app.name, height=28, corner_radius=8,
                fg_color=PANEL_2, hover_color=ACCENT,
                border_width=1, border_color=PANEL_BORDER,
                text_color="#e4e7ee",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda a=app: self._start_custom_install(a),
            )
            btn.grid(row=r, column=c, padx=4, pady=3, sticky="ew")
            btn.bind("<Button-3>", lambda _e, i=idx: self._show_custom_app_menu(i))
            i += 1

        if not entries and not custom_entries:
            ctk.CTkLabel(row_frame, text="Nothing here yet.", text_color=MUTED).grid(
                row=0, column=0, sticky="w", padx=4, pady=8
            )

    def _refresh_category(self, category: str) -> None:
        if category in self.category_tabs:
            self._build_category_grid(category)

    def _show_custom_app_menu(self, index: int) -> None:
        """Right-click context menu on a custom app button: edit or remove."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Edit", command=lambda: self._open_custom_dialog(edit_index=index))
        menu.add_command(label="Remove", command=lambda: self._remove_custom_app(index))
        try:
            x, y = self.winfo_pointerxy()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _show_placeholder(self, text: str) -> None:
        for w in self.results_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.results_frame, text=text, text_color=MUTED).grid(
            row=0, column=0, sticky="w", padx=8, pady=8
        )

    # ---------------------------------------------------------- custom apps

    def _open_custom_dialog(self, edit_index: int | None = None) -> None:
        _CustomAppDialog(self, edit_index=edit_index)

    def _remove_custom_app(self, index: int) -> None:
        if 0 <= index < len(self.custom_apps):
            removed = self.custom_apps.pop(index)
            save_custom_apps(self.custom_apps)
            self._refresh_category(removed.category)
            self.status_label.configure(text=f"Removed {removed.name}.")

    def _start_custom_install(self, app: CustomApp) -> None:
        if self._install_worker is not None and self._install_worker.is_alive():
            self.status_label.configure(text="An install is already running — wait for it to finish.")
            return
        if self._search_worker is not None and self._search_worker.is_alive():
            self.status_label.configure(text="Wait for the search to finish first.")
            return

        self.progress.grid()
        self.progress.start()
        self.status_label.configure(text=f"Installing {app.name}…")

        self._install_worker = CommandWorker(app.command)
        self._install_worker.start()
        self.after(POLL_MS, self._poll_install)

    # ------------------------------------------------------------- search

    def _start_search(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            self.status_label.configure(text="Enter something to search for.")
            return
        if self._search_worker is not None and self._search_worker.is_alive():
            return
        if self._install_worker is not None and self._install_worker.is_alive():
            self.status_label.configure(text="An install is already running — wait for it to finish.")
            return

        self.search_btn.configure(state="disabled")
        self._show_placeholder("Searching…")
        self.status_label.configure(text=f"Searching for '{query}'…")

        self._search_worker = SearchWorker(query)
        self._search_worker.start()
        self.after(POLL_MS, self._poll_search)

    def _poll_search(self) -> None:
        if self._search_worker is None:
            return
        try:
            while True:
                event: ProgressEvent = self._search_worker.events.get_nowait()
                self._handle_search_event(event)
        except Exception:
            pass  # queue.Empty — nothing more this tick

        if self._search_worker is not None and self._search_worker.is_alive():
            self.after(POLL_MS, self._poll_search)

    def _handle_search_event(self, event: ProgressEvent) -> None:
        self.search_btn.configure(state="normal")
        if event.kind == "search_done":
            self._results = event.results
            self._render_results()
            self.status_label.configure(text=f"{len(event.results)} result(s).")
            self._search_worker = None
        elif event.kind == "fatal_error":
            self._show_placeholder("Search failed.")
            self.status_label.configure(text=f"Search failed: {event.message}")
            self._search_worker = None

    def _render_results(self) -> None:
        for w in self.results_frame.winfo_children():
            w.destroy()
        if not self._results:
            self._show_placeholder("No results.")
            return
        for i, app in enumerate(self._results[:25]):
            row = ctk.CTkFrame(self.results_frame, fg_color=PANEL_2, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=3)
            row.grid_columnconfigure(0, weight=1)

            label_text = f"{app.name}   ·   {app.id}"
            if app.version:
                label_text += f"   ·   v{app.version}"
            ctk.CTkLabel(
                row, text=label_text, text_color="white", anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=8)

            ctk.CTkButton(
                row, text="Install", width=80, height=26, corner_radius=8,
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                command=lambda a=app: self._start_install(a.id, a.name),
            ).grid(row=0, column=1, padx=10, pady=8)

    # ------------------------------------------------------------ install

    def _quick_install(self, package_id: str, name: str) -> None:
        self._start_install(package_id, name)

    def _start_install(self, package_id: str, name: str) -> None:
        if self._install_worker is not None and self._install_worker.is_alive():
            self.status_label.configure(text="An install is already running — wait for it to finish.")
            return
        if self._search_worker is not None and self._search_worker.is_alive():
            self.status_label.configure(text="Wait for the search to finish first.")
            return

        self.progress.grid()
        self.progress.start()
        self.status_label.configure(text=f"Installing {name}…")

        self._install_worker = InstallWorker(package_id)
        self._install_worker.start()
        self.after(POLL_MS, self._poll_install)

    def _poll_install(self) -> None:
        if self._install_worker is None:
            return
        try:
            while True:
                event: ProgressEvent = self._install_worker.events.get_nowait()
                self._handle_install_event(event)
        except Exception:
            pass  # queue.Empty — nothing more this tick

        if self._install_worker is not None and self._install_worker.is_alive():
            self.after(POLL_MS, self._poll_install)

    def _handle_install_event(self, event: ProgressEvent) -> None:
        if event.kind == "log":
            self.status_label.configure(text=event.message)
        elif event.kind == "overall_done":
            self.progress.stop()
            self.progress.grid_remove()
            self.status_label.configure(text=event.message)
            self._install_worker = None
        elif event.kind == "fatal_error":
            self.progress.stop()
            self.progress.grid_remove()
            self.status_label.configure(text=f"Install failed: {event.message}")
            self._install_worker = None


class _CustomAppDialog(ctk.CTkToplevel):
    """Modal for adding or editing a custom install command. Lets the user
    pick which category tab it should be filed under."""

    def __init__(self, parent: AppInstallerModule, edit_index: int | None = None):
        super().__init__(parent)
        self.parent = parent
        self.edit_index = edit_index
        is_edit = edit_index is not None

        self.title("Edit Custom App" if is_edit else "Add Custom App")
        self.geometry("420x320")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        existing = parent.custom_apps[edit_index] if is_edit else None

        ctk.CTkLabel(
            self, text="Edit Custom App" if is_edit else "Add Custom App",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="white",
        ).pack(anchor="w", padx=20, pady=(20, 10))

        ctk.CTkLabel(self, text="Name", text_color=MUTED, anchor="w").pack(fill="x", padx=20)
        self.name_var = tk.StringVar(value=existing.name if existing else "")
        ctk.CTkEntry(self, textvariable=self.name_var, fg_color=PANEL_2).pack(
            fill="x", padx=20, pady=(2, 10)
        )

        ctk.CTkLabel(self, text="Category", text_color=MUTED, anchor="w").pack(fill="x", padx=20)
        self.category_var = tk.StringVar(value=existing.category if existing else CATEGORIES[0])
        ctk.CTkOptionMenu(
            self, variable=self.category_var, values=CATEGORIES,
            fg_color=PANEL_2, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
        ).pack(fill="x", padx=20, pady=(2, 10))

        ctk.CTkLabel(self, text="Install command", text_color=MUTED, anchor="w").pack(fill="x", padx=20)
        default_cmd = existing.command if existing else (
            "winget install --id  -e --accept-package-agreements "
            "--accept-source-agreements --silent"
        )
        self.command_var = tk.StringVar(value=default_cmd)
        ctk.CTkEntry(self, textvariable=self.command_var, fg_color=PANEL_2).pack(
            fill="x", padx=20, pady=(2, 4)
        )
        ctk.CTkLabel(
            self, text="Runs exactly as typed — any CLI install command works, not just winget.",
            text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w", justify="left",
        ).pack(fill="x", padx=20)

        self.error_label = ctk.CTkLabel(self, text="", text_color=DANGER, anchor="w")
        self.error_label.pack(fill="x", padx=20, pady=(4, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(10, 20))
        ctk.CTkButton(
            btn_row, text="Cancel", fg_color=PANEL_2, hover_color=DANGER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row, text="Save", fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._save,
        ).pack(side="right")

    def _save(self) -> None:
        name = self.name_var.get().strip()
        command = self.command_var.get().strip()
        category = self.category_var.get()
        if not name:
            self.error_label.configure(text="Name can't be empty.")
            return
        if not command:
            self.error_label.configure(text="Install command can't be empty.")
            return

        old_category = None
        if self.edit_index is not None:
            old_category = self.parent.custom_apps[self.edit_index].category

        app = CustomApp(name=name, command=command, category=category)
        if self.edit_index is not None:
            self.parent.custom_apps[self.edit_index] = app
        else:
            self.parent.custom_apps.append(app)
        save_custom_apps(self.parent.custom_apps)

        self.parent._refresh_category(category)
        if old_category is not None and old_category != category:
            self.parent._refresh_category(old_category)

        self.parent.status_label.configure(text=f"Saved {name} ({category}).")
        self.parent.quick_tabs.set(category)
        self.destroy()
