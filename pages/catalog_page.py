import customtkinter as ctk

from core import theme

# Muted neon hues for per-tool accent colors, same spirit as Gaming Hub's
# game cards. A small extra magenta/teal pair are mixed in here so a
# grid full of tools doesn't repeat colors as quickly as a shorter game
# list would.
CARD_HUES = [
    "#4ea1ff",  # blue (matches theme.ACCENT)
    "#a78bfa",  # violet
    "#34d399",  # green
    "#fb923c",  # orange
    "#f472b6",  # pink
    "#2dd4bf",  # teal
    "#facc15",  # yellow
]


def _stable_color(name: str) -> str:
    """
    Maps a name to one of CARD_HUES via a hash that's stable across
    restarts. Deliberately NOT using Python's built-in hash() for
    strings — that's randomized per-process (PYTHONHASHSEED) by default,
    so the same tool would get a different color every time the app
    launches. This sums character codes instead, which is slower but
    always gives the same result for the same name, every run.
    """
    total = sum(ord(c) for c in name)
    return CARD_HUES[total % len(CARD_HUES)]


class CatalogPage(ctk.CTkFrame):

    def __init__(self, parent, manager, plugin_manager):
        super().__init__(parent, fg_color=theme.BG)

        self.manager = manager
        self.plugin_manager = plugin_manager
        self.settings = parent.settings

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

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_filters()
        self._build_grid()

        self.render()

    # =====================================================
    # HEADER
    # =====================================================

    def _build_header(self):

        header = ctk.CTkFrame(self, **theme.panel_style())
        header.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=2)
        header.grid_columnconfigure(2, weight=0)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w", padx=theme.PAD_LG, pady=theme.PAD)

        ctk.CTkLabel(
            title_box,
            text="⚡ Z's Multi Tool",
            font=theme.font(26, "bold"),
            text_color=theme.TEXT
        ).pack(anchor="w")

        self.subtitle = ctk.CTkLabel(
            title_box,
            text="Loading tools…",
            font=theme.font(12),
            text_color=theme.MUTED
        )
        self.subtitle.pack(anchor="w")

        self.search = ctk.CTkEntry(
            header,
            placeholder_text="🔍  Search tools…",
            fg_color=theme.PANEL_2,
            border_color=theme.BORDER,
            text_color=theme.TEXT,
            corner_radius=theme.RADIUS_SM,
            height=38
        )
        self.search.grid(row=0, column=1, sticky="ew", padx=theme.PAD)
        self.search.bind("<KeyRelease>", lambda e: self.render())

        ctk.CTkButton(
            header,
            text="⚙  Settings",
            width=120,
            height=38,
            command=lambda: self.manager.show_page("settings"),
            **theme.secondary_button_style()
        ).grid(row=0, column=2, padx=theme.PAD_LG)

    # =====================================================
    # FILTERS
    # =====================================================

    def _build_filters(self):
        outer = ctk.CTkFrame(self, **theme.panel_style())
        outer.grid(row=1, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD))
        outer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            outer,
            text="CATEGORY",
            font=theme.font(10, "bold"),
            text_color=theme.FAINT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=theme.PAD_LG, pady=(theme.PAD, 2))

        # A plain ctk.CTkFrame doesn't grow to fit children placed with
        # .place() (only pack/grid do that), so _reflow_filters() sets its
        # height explicitly once it knows how many rows the pills wrapped
        # into — that's what lets this wrap to a second row instead of
        # ever running off the edge of the window.
        self.filter_frame = ctk.CTkFrame(outer, fg_color="transparent")
        self.filter_frame.grid(
            row=1, column=0, sticky="ew", padx=theme.PAD, pady=(0, theme.PAD)
        )

        # Counts (and the category list itself) are computed once here,
        # same as before — matches the existing tradeoff elsewhere in this
        # page of keeping widgets persistent rather than rebuilding on
        # every render() (e.g. every search keystroke). Hiding a tool
        # won't live-update its category's count until the page is
        # rebuilt, which was already true of the category list itself.
        hidden = set(self.settings.get("hidden_tools") or [])
        visible = [
            t for t in self.plugin_manager.get_tools() if t.get("name") not in hidden
        ]

        counts = {}
        for t in visible:
            counts[t.get("category", "Other")] = counts.get(t.get("category", "Other"), 0) + 1

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
                font=theme.font(12),
                command=lambda c=cat: self.set_category(c),
            )
            self.category_buttons[cat] = btn

        self._refresh_filter_styles()
        self.filter_frame.bind("<Configure>", lambda e: self._reflow_filters())
        self._reflow_filters()

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
                fg_color=theme.ACCENT if active else theme.PANEL_2,
                hover_color=theme.ACCENT_HOVER if active else theme.PANEL_HOVER,
                text_color="#0b0d10" if active else theme.TEXT,
                font=theme.font(12, "bold" if active else "normal"),
            )

    def set_category(self, category):
        self.category = category
        self._refresh_filter_styles()
        self.render()

    # =====================================================
    # GRID
    # =====================================================

    def _build_grid(self):

        self.grid_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.grid_frame.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))

        for c in range(3):
            self.grid_frame.grid_columnconfigure(c, weight=1, uniform="cards")

    # =====================================================
    # RENDER
    # =====================================================

    def render(self):

        # clear UI
        for w in self.grid_frame.winfo_children():
            w.destroy()

        search = self.search.get().lower().strip()

        tools = self.plugin_manager.get_tools()

        hidden = set(self.settings.get("hidden_tools") or [])
        tools = [t for t in tools if t.get("name") not in hidden]

        total = len(tools)

        # ---------------- CATEGORY FILTER ----------------
        if self.category != "All":
            tools = [t for t in tools if t.get("category") == self.category]

        # ---------------- SEARCH FILTER ----------------
        if search:
            tools = [
                t for t in tools
                if search in t.get("name", "").lower()
                or search in t.get("desc", "").lower()
            ]

        self.subtitle.configure(
            text=f"{len(tools)} of {total} tool{'s' if total != 1 else ''} available"
        )

        # ---------------- EMPTY STATE ----------------
        if not tools:
            empty = ctk.CTkFrame(self.grid_frame, fg_color="transparent")
            empty.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=60)

            ctk.CTkLabel(
                empty,
                text="🗂️",
                font=theme.font(40)
            ).pack()

            ctk.CTkLabel(
                empty,
                text="No tools match your search" if (search or self.category != "All") else "No tools installed yet",
                font=theme.font(15, "bold"),
                text_color=theme.MUTED
            ).pack(pady=(8, 0))

            return

        # ---------------- GRID ----------------
        cols = 3
        row = 0
        col = 0

        for tool in tools:

            card = self._build_card(tool)

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

    def _build_card(self, tool):

        accent = _stable_color(tool.get("name", ""))
        icon = tool.get("icon", "🧩")

        card = ctk.CTkFrame(
            self.grid_frame,
            fg_color=theme.PANEL,
            corner_radius=theme.RADIUS,
            border_width=1,
            border_color=theme.BORDER
        )
        card.grid_columnconfigure(0, weight=1)

        hide_btn = ctk.CTkButton(
            card,
            text="✕",
            width=22,
            height=22,
            corner_radius=11,
            fg_color=theme.PANEL_2,
            hover_color=theme.DANGER_HOVER,
            text_color=theme.MUTED,
            font=theme.font(11, "bold"),
            command=lambda t=tool: self.hide_tool(t["name"])
        )
        hide_btn.place(relx=1.0, x=-10, y=14, anchor="ne")

        ctk.CTkLabel(
            card,
            text=f"{icon}  {tool['name']}",
            font=theme.font(16, "bold"),
            text_color=theme.TEXT,
            anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))

        ctk.CTkLabel(
            card,
            text=tool.get("desc", "No description"),
            font=theme.font(12),
            text_color=theme.MUTED,
            justify="left",
            anchor="w",
            wraplength=240
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

        next_row = 2

        widget_builder = tool.get("widget")
        if widget_builder:
            try:
                card_widget = widget_builder(card, self.manager)
                card_widget.grid(row=next_row, column=0, sticky="ew", padx=16, pady=(0, 10))
                next_row += 1
            except Exception as e:
                print(f"[CatalogPage] Card widget failed for {tool.get('name')}: {e}")

        ctk.CTkLabel(
            card,
            text=tool.get("category", "Other").upper(),
            font=theme.font(10, "bold"),
            text_color=theme.FAINT,
            anchor="w"
        ).grid(row=next_row, column=0, sticky="ew", padx=16, pady=(0, 12))
        next_row += 1

        # Open button gets its own fixed color (a calm sky blue) instead
        # of theme.primary_button_style()'s ACCENT purple, so it reads
        # as "the button" on every card regardless of that card's own
        # accent-tinted hover border.
        ctk.CTkButton(
            card,
            text="Open",
            height=34,
            command=lambda t=tool: self.open_tool(t),
            fg_color="#4ea1ff",
            hover_color="#7dbaff",
            text_color="#0b0d10",
            corner_radius=theme.RADIUS_SM,
            font=theme.font(13, "bold"),
        ).grid(row=next_row, column=0, sticky="ew", padx=16, pady=(0, 16))

        # subtle hover highlight, tinted with this card's own accent
        # color instead of the fixed app accent — the only place that
        # color still shows up on the card now
        def on_enter(_e):
            card.configure(border_color=accent)

        def on_leave(_e):
            card.configure(border_color=theme.BORDER)

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)

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
