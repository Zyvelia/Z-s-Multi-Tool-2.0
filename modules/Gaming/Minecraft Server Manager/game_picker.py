"""Scrollable game-type picker — CTk shell + native Tk list (fast, no flash)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from core import theme as t

GAME_PICKER_HEIGHT = 220
_LINE_HEIGHT = 22


class GamePicker(ctk.CTkFrame):
    """Fixed-height scrollable game list with search (icon + name)."""

    def __init__(
        self,
        master,
        choices: list[tuple[str, str, str]],
        on_select: Callable[[str, str], None],
        *,
        height: int = GAME_PICKER_HEIGHT,
        defer_build: bool = False,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_select = on_select
        self._all_choices = list(choices)
        self._game_map: dict[str, str] = {}
        self._rev: dict[str, str] = {}
        self._selected_gt: str | None = None
        self._build_done = not defer_build
        self._on_build_complete: Callable[[], None] | None = None
        self._list_height = max(6, height // _LINE_HEIGHT)

        for gt, name, icon in choices:
            label = f"{icon}  {name}"
            self._game_map[label] = gt
            self._rev[gt] = label

        self._search_var = ctk.StringVar(value="")
        self._search = ctk.CTkEntry(
            self,
            textvariable=self._search_var,
            placeholder_text="Search games…",
            height=28,
            fg_color=t.PANEL_2,
            border_color=t.BORDER,
            text_color=t.TEXT,
        )
        self._search.pack(fill="x", pady=(0, 6))
        self._search.bind("<KeyRelease>", self._on_search_changed)

        list_px = self._list_height * _LINE_HEIGHT + 2
        self._list_border = tk.Frame(
            self,
            bg=t.BORDER,
            highlightthickness=0,
            bd=0,
            height=list_px,
        )
        self._list_border.pack(fill="x", expand=False)
        self._list_border.pack_propagate(False)

        inner = tk.Frame(self._list_border, bg=t.PANEL_2, bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        self._scrollbar = tk.Scrollbar(inner, orient="vertical", bg=t.PANEL_2)
        self._scrollbar.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            inner,
            height=self._list_height,
            bg=t.PANEL_2,
            fg=t.TEXT,
            selectbackground=t.ACCENT,
            selectforeground="#ffffff",
            activestyle="none",
            highlightthickness=0,
            borderwidth=0,
            font=("Segoe UI", 11),
            yscrollcommand=self._scrollbar.set,
        )
        self._listbox.pack(side="left", fill="both", expand=True)
        self._scrollbar.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self._listbox.bind("<Double-Button-1>", self._on_list_activate)
        self._listbox.bind("<Return>", self._on_list_activate)
        for widget in (self._listbox, inner, self._list_border):
            widget.bind("<MouseWheel>", self._on_mousewheel)
            widget.bind("<Button-4>", self._on_mousewheel)
            widget.bind("<Button-5>", self._on_mousewheel)

        if not defer_build:
            self._populate_list()
            if choices:
                self._select_game_type(choices[0][0], notify=False)

    def start_build(
        self,
        on_complete: Callable[[], None] | None = None,
        *,
        chunk_size: int | None = None,
    ) -> None:
        del chunk_size  # native list loads in one shot
        self._on_build_complete = on_complete
        if not self._build_done:
            self._populate_list()
            if self._all_choices and self._selected_gt is None:
                self._select_game_type(self._all_choices[0][0], notify=False)
            self._build_done = True
        if self._on_build_complete:
            cb = self._on_build_complete
            self._on_build_complete = None
            cb()

    def cancel_build(self) -> None:
        self._on_build_complete = None

    def focus_search(self) -> None:
        try:
            self._search.focus_set()
        except Exception:
            pass

    def _filtered_choices(self) -> list[tuple[str, str, str]]:
        query = self._search_var.get().strip().lower()
        if not query:
            return self._all_choices
        out: list[tuple[str, str, str]] = []
        for gt, name, icon in self._all_choices:
            if query in name.lower() or query in gt.replace("_", " "):
                out.append((gt, name, icon))
        return out

    def _populate_list(self) -> None:
        self._listbox.delete(0, tk.END)
        for gt, name, icon in self._filtered_choices():
            self._listbox.insert(tk.END, f"{icon}  {name}")

    def _on_mousewheel(self, event) -> str:
        """Scroll one game row at a time; stop propagation to parent scroll areas."""
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", 0)
        if num == 4 or delta > 0:
            self._listbox.yview_scroll(-1, "units")
        elif num == 5 or delta < 0:
            self._listbox.yview_scroll(1, "units")
        return "break"

    def _on_search_changed(self, _event=None) -> None:
        if not self._build_done:
            return
        keep = self._selected_gt
        self._populate_list()
        if keep and keep in self._rev:
            label = self._rev[keep]
            if label in self._listbox.get(0, tk.END):
                self._select_label(label, notify=False)
            elif self._listbox.size() > 0:
                self._select_index(0, notify=False)
        elif self._listbox.size() > 0:
            self._select_index(0, notify=False)

    def _on_list_select(self, _event=None) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        label = self._listbox.get(sel[0])
        gt = self._game_map.get(label)
        if not gt:
            return
        if gt != self._selected_gt:
            self._selected_gt = gt
            self._on_select(label, gt)

    def _on_list_activate(self, _event=None) -> str:
        """Enter / double-click — ensure selection applies even when re-picking the same row."""
        sel = self._listbox.curselection()
        if not sel:
            return "break"
        label = self._listbox.get(sel[0])
        gt = self._game_map.get(label)
        if not gt:
            return "break"
        self._selected_gt = gt
        self._on_select(label, gt)
        return "break"

    def _select_index(self, index: int, *, notify: bool) -> None:
        if index < 0 or index >= self._listbox.size():
            return
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(index)
        self._listbox.activate(index)
        label = self._listbox.get(index)
        gt = self._game_map.get(label)
        if not gt:
            return
        self._selected_gt = gt
        if notify:
            self._on_select(label, gt)

    def _select_label(self, label: str, *, notify: bool) -> None:
        items = self._listbox.get(0, tk.END)
        if label not in items:
            return
        self._select_index(items.index(label), notify=notify)

    def _select_game_type(self, game_type: str, *, notify: bool) -> None:
        label = self._rev.get(game_type)
        if not label:
            return
        if not self._build_done:
            self._selected_gt = game_type
            return
        if label in self._listbox.get(0, tk.END):
            self._select_label(label, notify=notify)
        else:
            self._selected_gt = game_type

    def set_game_type(self, game_type: str) -> None:
        if game_type not in self._rev:
            return
        if not self._build_done:
            self._selected_gt = game_type
            return
        label = self._rev[game_type]
        if label not in self._listbox.get(0, tk.END):
            self._search_var.set("")
            self._populate_list()
        self._select_label(label, notify=False)

    def set_by_label(self, label: str) -> None:
        gt = self._game_map.get(label)
        if gt:
            self.set_game_type(gt)

    def selected_game_type(self) -> str | None:
        return self._selected_gt

    def label_for(self, game_type: str) -> str | None:
        return self._rev.get(game_type)
