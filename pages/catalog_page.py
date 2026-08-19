import customtkinter as ctk

from pages.catalog_theme import resolve_catalog_theme


class CatalogPage(ctk.CTkFrame):

    def __init__(self, parent, manager, plugin_manager):
        self.manager = manager
        self.plugin_manager = plugin_manager
        self.settings = parent.settings
        self._load_theme()

        super().__init__(parent, fg_color=self._t.BG)

        self.category = "All"
        self.category_buttons = {}

        # cache tool instances (IMPORTANT for music player state)
        self.tool_instances = {}

        # Persistent card widgets, keyed by tool name. render() reuses these
        # instead of destroying/rebuilding the whole grid every time (e.g.
        # every keystroke in search) — that used to reset any live widgets
        # embedded in a card (CPU/RAM bars, music progress) back to zero
        # and cause a visible flash, even for cards that stayed on screen.
        self.cards = {}
        self.empty_frame = None
        self.empty_label = None

        # ---- drag-to-reorder state ----
        # Names of the tools in the exact order they were last drawn in
        # the grid (post filter/search) — this is what dragging swaps
        # positions within. self._drag_name is set while a drag is in
        # progress (from ButtonPress-1 on a card until ButtonRelease-1).
        self._last_rendered_names = []
        self._drag_name = None
        self._drag_card = None

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_filters()
        self._build_grid()
        self._enable_smooth_scroll()
        self._style_scroll_area()

        self.render()

    def _load_theme(self, theme_id=None):
        bundle = resolve_catalog_theme(
            theme_id if theme_id is not None else self.settings.get("catalog_theme")
        )
        self._theme_id = bundle.id
        self._t = bundle.t
        self._on_accent = bundle.on_accent
        self._scroll_track = bundle.scroll_track
        self._scroll_thumb = bundle.scroll_thumb
        self._scroll_thumb_hover = bundle.scroll_thumb_hover
        self._card_hues = list(bundle.t.ACCENT_HUES)

    def _stable_color(self, name: str) -> str:
        total = sum(ord(c) for c in name)
        return self._card_hues[total % len(self._card_hues)]

    def apply_theme(self, theme_id=None):
        """Hot-swap catalog colors (called from Settings)."""
        search_text = ""
        if hasattr(self, "search"):
            try:
                search_text = self.search.get()
            except Exception:
                pass

        self._load_theme(theme_id)
        self.configure(fg_color=self._t.BG)

        if getattr(self, "_header", None) is not None:
            try:
                self._header.destroy()
            except Exception:
                pass
        if getattr(self, "_filter_outer", None) is not None:
            try:
                self._filter_outer.destroy()
            except Exception:
                pass

        for card in list(self.cards.values()):
            try:
                card.destroy()
            except Exception:
                pass
        self.cards.clear()
        self.category_buttons.clear()

        self._build_header()
        if search_text:
            self.search.insert(0, search_text)
        self._build_filters()

        if hasattr(self, "grid_frame"):
            self.grid_frame.configure(fg_color=self._t.BG)
        if hasattr(self, "empty_label"):
            self.empty_label.configure(
                font=self._t.font(15, "bold"),
                text_color=self._t.MUTED,
            )
        self._style_scroll_area()
        if hasattr(self, "_scroll_canvas"):
            try:
                self._scroll_canvas.configure(bg=self._t.BG)
            except Exception:
                pass

        self.render()
        try:
            self.winfo_toplevel().configure(fg_color=self._t.BG)
        except Exception:
            pass

    def on_show(self):
        """Sync theme from settings and match the root window background."""
        saved = self.settings.get("catalog_theme")
        if saved and saved != self._theme_id:
            self.apply_theme(saved)
            return
        try:
            self.winfo_toplevel().configure(fg_color=self._t.BG)
        except Exception:
            pass

    def _style_scroll_area(self):
        """Keep the scrollable region and scrollbar on-palette (no default gray)."""
        gf = self.grid_frame
        try:
            inner = getattr(gf, "_parent_frame", None)
            if inner is not None:
                inner.configure(fg_color=self._t.BG)
        except Exception:
            pass
        try:
            sb = getattr(gf, "_scrollbar", None)
            if sb is not None:
                sb.configure(
                    fg_color=self._scroll_track,
                    button_color=self._scroll_thumb,
                    button_hover_color=self._scroll_thumb_hover,
                )
        except Exception:
            pass

    # =====================================================
    # HEADER
    # =====================================================

    def _build_header(self):

        header = ctk.CTkFrame(
            self,
            fg_color=self._t.PANEL,
            corner_radius=self._t.RADIUS,
            border_width=1,
            border_color=self._t.BORDER,
        )
        header.grid(row=0, column=0, sticky="ew", padx=self._t.PAD_LG, pady=(self._t.PAD_LG, self._t.PAD))

        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=2)
        header.grid_columnconfigure(2, weight=0)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w", padx=self._t.PAD_LG, pady=self._t.PAD)

        ctk.CTkLabel(
            title_box,
            text="⚡ Z's Multi Tool",
            font=self._t.font(26, "bold"),
            text_color=self._t.ACCENT,
        ).pack(anchor="w")

        status_row = ctk.CTkFrame(title_box, fg_color="transparent")
        status_row.pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            status_row,
            text="●",
            font=self._t.font(10, "bold"),
            text_color=self._t.ACCENT,
        ).pack(side="left")
        ctk.CTkLabel(
            status_row,
            text="SYSTEM ONLINE",
            font=self._t.mono(10, "bold"),
            text_color=self._t.FAINT,
        ).pack(side="left", padx=(4, 0))

        self.subtitle = ctk.CTkLabel(
            title_box,
            text="Loading tools…",
            font=self._t.font(12),
            text_color=self._t.MUTED,
        )
        self.subtitle.pack(anchor="w", pady=(4, 0))

        self.search = ctk.CTkEntry(
            header,
            placeholder_text="Search tools…",
            fg_color=self._t.PANEL_2,
            border_color=self._t.BORDER,
            text_color=self._t.TEXT,
            placeholder_text_color=self._t.FAINT,
            corner_radius=self._t.RADIUS_SM,
            height=38,
            border_width=1,
        )
        self.search.grid(row=0, column=1, sticky="ew", padx=self._t.PAD)
        self.search.bind("<KeyRelease>", lambda e: self.render())

        ctk.CTkButton(
            header,
            text="Settings",
            width=120,
            height=38,
            command=lambda: self.manager.show_page("settings"),
            fg_color=self._t.PANEL_2,
            hover_color=self._t.PANEL_HOVER,
            text_color=self._t.TEXT,
            border_width=1,
            border_color=self._t.BORDER,
            corner_radius=self._t.RADIUS_SM,
            font=self._t.font(13),
        ).grid(row=0, column=2, padx=self._t.PAD_LG)

        self._header = header

    # =====================================================
    # FILTERS
    # =====================================================

    def _build_filters(self):
        outer = ctk.CTkFrame(
            self,
            fg_color=self._t.PANEL,
            corner_radius=self._t.RADIUS,
            border_width=1,
            border_color=self._t.BORDER,
        )
        outer.grid(row=1, column=0, sticky="ew", padx=self._t.PAD_LG, pady=(0, self._t.PAD))
        outer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            outer,
            text="CATEGORY",
            font=self._t.mono(10, "bold"),
            text_color=self._t.ACCENT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=self._t.PAD_LG, pady=(self._t.PAD, 2))

        # A plain ctk.CTkFrame doesn't grow to fit children placed with
        # .place() (only pack/grid do that), so _reflow_filters() sets its
        # height explicitly once it knows how many rows the pills wrapped
        # into — that's what lets this wrap to a second row instead of
        # ever running off the edge of the window.
        self.filter_frame = ctk.CTkFrame(outer, fg_color="transparent")
        self.filter_frame.grid(
            row=1, column=0, sticky="ew", padx=self._t.PAD, pady=(0, self._t.PAD)
        )

        # Counts (and the category list itself) are computed once here,
        # same as before — matches the existing tradeoff elsewhere in this
        # page of keeping widgets persistent rather than rebuilding on
        # every render() (e.g. every search keystroke). Hiding a tool
        # won't live-update its category's count until the page is
        # rebuilt, which was already true of the category list itself.
        hidden = set(self.settings.get("hidden_tools") or [])
        visible = [
            tool for tool in self.plugin_manager.get_tools()
            if tool.get("name") not in hidden
        ]

        counts = {}
        for tool in visible:
            cat = tool.get("category", "Other")
            counts[cat] = counts.get(cat, 0) + 1

        ordered = ["All"] + sorted(set(counts) - {"All"})

        self._category_widths = {}
        for cat in ordered:
            count = len(visible) if cat == "All" else counts.get(cat, 0)
            label = f"{cat}  ·  {count}"
            # Sized to the label instead of a fixed width — a short name
            # like "All" no longer sits in an oversized pill, and a long
            # category name no longer gets clipped. +30px covers going
            # bold on selection without the text touching the edges.
            width = max(92, min(220, 30 + 8 * len(label)))
            self._category_widths[cat] = width

            btn = ctk.CTkButton(
                self.filter_frame,
                text=label,
                width=width,
                height=32,
                corner_radius=16,
                font=self._t.font(12),
                command=lambda c=cat: self.set_category(c),
            )
            self.category_buttons[cat] = btn

        self._refresh_filter_styles()
        self.filter_frame.bind("<Configure>", lambda e: self._reflow_filters())
        self._reflow_filters()
        self._filter_outer = outer

    def _reflow_filters(self):
        """Lay the category pills out left-to-right, wrapping to a new row
        whenever the next pill wouldn't fit — so the filter bar adapts to
        the window width instead of overflowing it."""
        frame = self.filter_frame
        available = frame.winfo_width()
        if available <= 1:
            available = self.winfo_width() or 900

        gap = 8
        row_height = 32 + gap
        x = y = 0

        for cat, btn in self.category_buttons.items():
            width = self._category_widths[cat]
            if x > 0 and x + width > available:
                x = 0
                y += row_height
            btn.place(x=x, y=y)
            x += width + gap

        frame.configure(height=y + 32)

    def _refresh_filter_styles(self):
        for cat, btn in self.category_buttons.items():
            active = cat == self.category
            btn.configure(
                fg_color=self._t.ACCENT if active else self._t.PANEL_2,
                hover_color=self._t.ACCENT_HOVER if active else self._t.PANEL_HOVER,
                text_color=self._on_accent if active else self._t.TEXT,
                border_width=1,
                border_color=self._t.ACCENT if active else self._t.BORDER,
                font=self._t.font(12, "bold" if active else "normal"),
            )

    def set_category(self, category):
        self.category = category
        self._refresh_filter_styles()
        self.render()

    # =====================================================
    # GRID
    # =====================================================

    def _build_grid(self):

        self.grid_frame = ctk.CTkScrollableFrame(self, fg_color=self._t.BG)
        self.grid_frame.grid(row=2, column=0, sticky="nsew", padx=self._t.PAD_LG, pady=(0, self._t.PAD_LG))

        for c in range(3):
            self.grid_frame.grid_columnconfigure(c, weight=1, uniform="cards")

        # Empty-state placeholder is built once and just shown/hidden —
        # same reasoning as the cards below.
        self.empty_frame = ctk.CTkFrame(self.grid_frame, fg_color="transparent")

        ctk.CTkLabel(
            self.empty_frame,
            text="🗂️",
            font=self._t.font(40)
        ).pack()

        self.empty_label = ctk.CTkLabel(
            self.empty_frame,
            text="",
            font=self._t.font(15, "bold"),
            text_color=self._t.MUTED
        )
        self.empty_label.pack(pady=(8, 0))

    # =====================================================
    # SMOOTH SCROLLING
    # =====================================================
    # CTkScrollableFrame's default wheel handling jumps a fixed number
    # of rows per notch — feels jerky, and on top of that the jump can
    # leave the canvas without a clean chance to redraw, which is what
    # causes stale ghost widgets (e.g. a leftover "Open" button) to
    # sometimes stick around in the wrong spot after a scroll.
    #
    # This replaces it with an eased/inertial scroll: each wheel notch
    # adds to a velocity instead of jumping straight there, and a ~60fps
    # loop drains that velocity in small steps (with friction), forcing
    # a redraw after every step so nothing is ever left stale on screen.

    _SCROLL_IMPULSE = 32       # pixels of velocity added per wheel notch
    _SCROLL_FRICTION = 0.80    # velocity multiplier applied every frame
    _SCROLL_MIN_VELOCITY = 0.6
    _SCROLL_MAX_VELOCITY = 140  # caps how much a burst of fast notches can build up
    _SCROLL_MAX_STEP = 26       # hard cap on pixels moved in a single frame — this
                                 # is what actually stops fast scrolling from
                                 # jumping the canvas far enough in one go to
                                 # break the embedded cards' redraw and ghost

    def _enable_smooth_scroll(self):
        canvas = getattr(self.grid_frame, "_parent_canvas", None)
        if canvas is None:
            # Different CTk version / internals changed — fall back to
            # default scrolling rather than breaking the page.
            return

        # 1 "unit" == 1 pixel, so yview_scroll(n, "units") gives us
        # fine-grained control instead of CTk's default chunky steps.
        try:
            canvas.configure(yscrollincrement=1)
        except Exception:
            return

        self._scroll_canvas = canvas
        self._scroll_velocity = 0.0
        self._scroll_job = None

        try:
            canvas.configure(bg=self._t.BG, highlightthickness=0)
        except Exception:
            pass

        self._bind_wheel_recursive(self.grid_frame)

    def _bind_wheel_recursive(self, widget):
        """Binds the smooth-scroll wheel handler onto `widget` and every
        descendants. Needed because Tk delivers <MouseWheel> to whatever
        widget is directly under the cursor — a label or button deep
        inside a card, not the canvas — so every card (and anything it
        contains, including third-party tool widgets) has to carry the
        binding too. add="+" so it never clobbers a widget's own
        bindings (e.g. a button's click handler is a different event)."""
        widget.bind("<MouseWheel>", self._on_mouse_wheel, add="+")
        widget.bind("<Button-4>", self._on_mouse_wheel, add="+")  # Linux scroll up
        widget.bind("<Button-5>", self._on_mouse_wheel, add="+")  # Linux scroll down
        for child in widget.winfo_children():
            self._bind_wheel_recursive(child)

    def _on_mouse_wheel(self, event):
        if not hasattr(self, "_scroll_canvas"):
            return

        num = getattr(event, "num", None)
        if num == 4:
            impulse = self._SCROLL_IMPULSE
        elif num == 5:
            impulse = -self._SCROLL_IMPULSE
        else:
            # Windows delivers delta in multiples of 120 per notch.
            impulse = (event.delta / 120) * self._SCROLL_IMPULSE

        self._scroll_velocity -= impulse
        self._scroll_velocity = max(
            -self._SCROLL_MAX_VELOCITY,
            min(self._SCROLL_MAX_VELOCITY, self._scroll_velocity)
        )

        if self._scroll_job is None:
            self._scroll_job = self.after(12, self._scroll_step)

        # Stop this event from also reaching CTk's own default handler
        # (which would otherwise add its own instant jump on top).
        return "break"

    def _scroll_step(self):
        if abs(self._scroll_velocity) < self._SCROLL_MIN_VELOCITY:
            self._scroll_velocity = 0.0
            self._scroll_job = None
            return

        # Move by at most _SCROLL_MAX_STEP this frame — any velocity
        # beyond that just carries over and gets drained next frame
        # instead of covered in one big jump, so fast scrolling glides
        # at a capped top speed instead of teleporting.
        step = max(-self._SCROLL_MAX_STEP, min(self._SCROLL_MAX_STEP, self._scroll_velocity))

        self._scroll_canvas.yview_scroll(int(round(step)), "units")
        # Force the canvas to actually repaint now rather than waiting
        # for Tk's idle queue to get around to it — this is what closes
        # the window where a widget could otherwise be left stale.
        self._scroll_canvas.update_idletasks()

        self._scroll_velocity *= self._SCROLL_FRICTION
        self._scroll_job = self.after(12, self._scroll_step)

    # =====================================================
    # RENDER
    # =====================================================

    def render(self):

        search = self.search.get().lower().strip()

        # Apply the saved drag order to the FULL tool list first (before
        # hidden/category/search whittle it down), so the relative order
        # of whatever ends up visible always matches what the user
        # arranged, regardless of which filter is active.
        tools_by_name = {
            tool.get("name"): tool for tool in self.plugin_manager.get_tools()
        }
        tools = [tools_by_name[n] for n in self._ordered_tool_names() if n in tools_by_name]

        hidden = set(self.settings.get("hidden_tools") or [])
        tools = [tool for tool in tools if tool.get("name") not in hidden]

        total = len(tools)

        # ---------------- CATEGORY FILTER ----------------
        if self.category != "All":
            tools = [tool for tool in tools if tool.get("category") == self.category]

        # ---------------- SEARCH FILTER ----------------
        if search:
            tools = [
                tool for tool in tools
                if search in tool.get("name", "").lower()
                or search in tool.get("desc", "").lower()
            ]

        self.subtitle.configure(
            text=f"{len(tools)} of {total} tool{'s' if total != 1 else ''} available"
        )

        # ---------------- EMPTY STATE ----------------
        if not tools:
            self.empty_label.configure(
                text="No tools match your search" if (search or self.category != "All") else "No tools installed yet"
            )
            self.empty_frame.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=60)
            for card in self.cards.values():
                card.grid_remove()
            self._last_rendered_names = []
            return

        self.empty_frame.grid_remove()

        # ---------------- GRID ----------------
        # Cards are built once per tool and cached in self.cards forever
        # after that — render() (called on every keystroke in search, on
        # category change, on hide, on drop, ...) only ever repositions
        # or grid_remove()s existing widgets instead of destroying and
        # rebuilding the whole grid. That's what keeps any embedded live
        # widgets (CPU/RAM bars, music progress) ticking smoothly instead
        # of resetting/flashing on every render, and avoids the
        # destroy-storm that could leave labels drawn blank/black for a
        # frame while everything gets rebuilt from scratch.
        cols = 3
        row = 0
        col = 0

        self._last_rendered_names = [tool.get("name") for tool in tools]
        visible_names = set(self._last_rendered_names)

        for tool in tools:

            name = tool.get("name")
            card = self.cards.get(name)
            if card is None:
                card = self._build_card(tool)
                self.cards[name] = card

            if card is not self._drag_card:
                card.configure(border_color=self._t.BORDER)

            card.grid(
                row=row,
                column=col,
                padx=8,
                pady=8,
                sticky="nsew"
            )

            col += 1
            if col >= cols:
                col = 0
                row += 1

        # Hide any cached cards that shouldn't currently be on screen
        # (hidden tool, filtered out by category/search) without
        # destroying them — they're still there, ready to reappear.
        for name, card in self.cards.items():
            if name not in visible_names:
                card.grid_remove()

        # Force a clean repaint after any grid()/grid_remove() shuffle —
        # same reasoning as the smooth-scroll redraw above, so a card
        # that just moved or disappeared can't leave a stale ghost.
        self.grid_frame.update_idletasks()

    def _build_card(self, tool):

        name = tool.get("name", "")
        accent = self._stable_color(name)
        icon = tool.get("icon", "🧩")

        card = ctk.CTkFrame(
            self.grid_frame,
            fg_color=self._t.PANEL,
            corner_radius=self._t.RADIUS,
            border_width=1,
            border_color=self._t.BORDER,
            cursor="fleur",
        )
        card.grid_columnconfigure(0, weight=1)

        hide_btn = ctk.CTkButton(
            card,
            text="✕",
            width=22,
            height=22,
            corner_radius=11,
            fg_color=self._t.PANEL_2,
            hover_color=self._t.DANGER_BG,
            text_color=self._t.MUTED,
            border_width=1,
            border_color=self._t.BORDER,
            font=self._t.font(11, "bold"),
            command=lambda t=tool: self.hide_tool(t["name"]),
        )
        hide_btn.place(relx=1.0, x=-10, y=14, anchor="ne")

        # Small grip handle (top-left, mirrors the ✕ hide button on the
        # top-right) — the obvious "grab here to drag" affordance. Drag
        # also works from the title/description/category text below,
        # but not from the hide/open buttons or an embedded tool widget.
        grip = ctk.CTkLabel(
            card,
            text="⠿",
            font=self._t.font(14, "bold"),
            text_color=self._t.ACCENT_DIM,
            cursor="fleur",
        )
        grip.place(x=12, y=13)

        title_label = ctk.CTkLabel(
            card,
            text=f"{icon}  {tool['name']}",
            font=self._t.font(16, "bold"),
            text_color=self._t.TEXT,
            anchor="w",
            cursor="fleur"
        )
        title_label.grid(row=0, column=0, sticky="ew", padx=(34, 16), pady=(16, 4))

        desc_label = ctk.CTkLabel(
            card,
            text=tool.get("desc", "No description"),
            font=self._t.font(12),
            text_color=self._t.MUTED,
            justify="left",
            anchor="w",
            wraplength=240,
            cursor="fleur"
        )
        desc_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

        for draggable in (card, grip, title_label, desc_label):
            self._bind_drag(draggable, name, card)

        next_row = 2

        widget_builder = tool.get("widget")
        if widget_builder:
            try:
                card_widget = widget_builder(card, self.manager)
                card_widget.grid(row=next_row, column=0, sticky="ew", padx=16, pady=(0, 10))
                next_row += 1
            except Exception as e:
                print(f"[CatalogPage] Card widget failed for {tool.get('name')}: {e}")

        category_label = ctk.CTkLabel(
            card,
            text=tool.get("category", "Other").upper(),
            font=self._t.mono(10, "bold"),
            text_color=self._t.ACCENT,
            anchor="w",
            cursor="fleur",
        )
        category_label.grid(row=next_row, column=0, sticky="ew", padx=16, pady=(0, 12))
        next_row += 1
        self._bind_drag(category_label, name, card)

        # Neon accent Open button — stands out on every card regardless of
        # that card's hover border tint.
        ctk.CTkButton(
            card,
            text="Open",
            height=34,
            command=lambda t=tool: self.open_tool(t),
            fg_color=self._t.ACCENT,
            hover_color=self._t.ACCENT_HOVER,
            text_color=self._on_accent,
            corner_radius=self._t.RADIUS_SM,
            font=self._t.font(13, "bold"),
        ).grid(row=next_row, column=0, sticky="ew", padx=16, pady=(0, 16))

        # subtle hover highlight, tinted with this card's own accent
        # color instead of the fixed app accent — the only place that
        # color still shows up on the card now
        def on_enter(_e):
            card.configure(border_color=accent)

        def on_leave(_e):
            card.configure(border_color=self._t.BORDER)

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)

        # New cards (and any custom widget a tool embeds inside one)
        # need the smooth-scroll wheel binding too — see
        # _bind_wheel_recursive for why this has to be recursive.
        if hasattr(self, "_scroll_canvas"):
            self._bind_wheel_recursive(card)

        return card

    # =====================================================
    # HIDE TOOL
    # =====================================================

    def hide_tool(self, name):
        hidden = list(self.settings.get("hidden_tools") or [])
        if name not in hidden:
            hidden.append(name)
            self.settings.set("hidden_tools", hidden)
        self.render()

    # =====================================================
    # OPEN TOOL (FIXED: persistent instances)
    # =====================================================

    def open_tool(self, tool):

        name = tool["name"]

        # -----------------------------------------------------
        # reuse existing instance (IMPORTANT FIX)
        # -----------------------------------------------------
        if name in self.tool_instances:
            page = self.tool_instances[name]
        else:
            page = tool["open"](self.manager)

            if page:
                self.tool_instances[name] = page
                self.manager.add_page(name, page)

        # switch page
        if page:
            self.manager.show_page(name)

    # =====================================================
    # DRAG TO REORDER
    # =====================================================
    # Cards can be dragged (from the grip, title, description, or
    # category text — anywhere that isn't a button or embedded tool
    # widget) and dropped onto another card to swap positions. The
    # resulting order is merged into the FULL tool order (including
    # currently hidden/filtered-out tools) and saved to settings.json
    # immediately, so it's restored exactly on the next launch.

    def _ordered_tool_names(self):
        """Full name order for every installed tool: the saved order,
        with any tool not yet in it (new plugins) appended at the end in
        registration order, and any stale saved names (uninstalled
        plugins) dropped."""
        all_names = [tool.get("name") for tool in self.plugin_manager.get_tools()]
        known = set(all_names)
        saved = [n for n in (self.settings.get("tool_order") or []) if n in known]
        saved += [n for n in all_names if n not in saved]
        return saved

    def _bind_drag(self, widget, name, card):
        widget.bind("<ButtonPress-1>", lambda e, n=name, c=card: self._drag_start(n, c))
        widget.bind("<B1-Motion>", self._drag_motion)
        widget.bind("<ButtonRelease-1>", self._drag_end)

    def _drag_start(self, name, card):
        self._drag_name = name
        self._drag_card = card
        card.configure(border_color=self._t.ACCENT)

    def _widget_to_tool_name(self, widget):
        """Climbs from whatever widget is directly under the pointer
        (which might be a label or an embedded tool widget several
        levels deep) up to the enclosing card, and returns its tool
        name — or None if the pointer isn't over a card at all."""
        depth = 0
        while widget is not None and depth < 8:
            for name, card in self.cards.items():
                if widget is card:
                    return name
            widget = getattr(widget, "master", None)
            depth += 1
        return None

    def _drag_motion(self, event):
        if not self._drag_name:
            return
        target = self._widget_to_tool_name(
            self.winfo_containing(event.x_root, event.y_root)
        )
        for name in self._last_rendered_names:
            card = self.cards[name]
            if name == self._drag_name:
                card.configure(border_color=self._t.ACCENT)
            elif name == target:
                card.configure(border_color=self._t.ACCENT_HOVER)
            else:
                card.configure(border_color=self._t.BORDER)

    def _drag_end(self, event):
        if not self._drag_name:
            return

        dragged = self._drag_name
        target = self._widget_to_tool_name(
            self.winfo_containing(event.x_root, event.y_root)
        )
        self._drag_name = None
        self._drag_card = None

        if target and target != dragged:
            self._reorder_tool(dragged, target)

        # Re-render either way — this also resets every border back to
        # normal (drop or cancel) since it rebuilds all cards fresh.
        self.render()

    def _reorder_tool(self, dragged, target):
        """Moves `dragged` to sit where `target` currently is, within
        the order the grid was last drawn in, then saves it."""
        visible = list(self._last_rendered_names)
        if dragged not in visible or target not in visible:
            return
        visible.remove(dragged)
        visible.insert(visible.index(target), dragged)

        # Merge the reordered VISIBLE names back into the full order,
        # leaving hidden/other-category tools exactly where they were —
        # only the relative order of the tools that were actually on
        # screen during the drag changes.
        full_order = self._ordered_tool_names()
        visible_set = set(visible)
        it = iter(visible)
        merged = [next(it) if n in visible_set else n for n in full_order]

        self.settings.set("tool_order", merged)
