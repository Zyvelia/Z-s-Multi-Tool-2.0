# modules/AI/prompt_library/ui.py
#
# Save/organize/reuse prompts. Deliberately decoupled from AI Chat and
# Local Model Runner — "reuse" here means "Copy" puts the (optionally
# variable-filled) prompt text on the clipboard, which pastes into
# either of those, or anywhere else. No cross-module wiring needed, so
# this keeps working even if those modules are removed/renamed.

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import pyperclip

from core import theme
from . import storage

ALL_CATEGORY = "All"
FAVORITES_CATEGORY = "★ Favorites"


class PromptLibraryUI(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager

        self.prompts = storage.load_all()
        self.active_filter = ALL_CATEGORY
        self.search_text = ""

        self._build_ui()
        self._refresh()

    # =====================================================
    # LAYOUT
    # =====================================================

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        ctk.CTkLabel(
            header, text="📚  Prompt Library", font=theme.font(22, "bold"),
            text_color=theme.TEXT
        ).pack(side="left", padx=theme.PAD_LG, pady=14)

        ctk.CTkButton(
            header, text="+ New Prompt", width=130, height=32,
            command=lambda: self._open_editor(None), **theme.primary_button_style()
        ).pack(side="right", padx=(0, theme.PAD_LG), pady=14)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_list(body)

    def _build_sidebar(self, parent):
        panel = ctk.CTkFrame(parent, width=200, **theme.panel_style())
        panel.grid(row=0, column=0, sticky="ns", padx=(0, theme.PAD))
        panel.grid_propagate(False)

        ctk.CTkLabel(
            panel, text="SEARCH", font=theme.font(10, "bold"), text_color=theme.FAINT, anchor="w"
        ).pack(anchor="w", padx=theme.PAD, pady=(theme.PAD, 4))

        self.search_entry = ctk.CTkEntry(
            panel, placeholder_text="Search title, tag, body...",
            fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
        )
        self.search_entry.pack(fill="x", padx=theme.PAD, pady=(0, theme.PAD))
        self.search_entry.bind("<KeyRelease>", self._on_search_changed)

        ctk.CTkLabel(
            panel, text="CATEGORIES", font=theme.font(10, "bold"), text_color=theme.FAINT, anchor="w"
        ).pack(anchor="w", padx=theme.PAD, pady=(4, 4))

        self.category_list = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.category_list.pack(fill="both", expand=True, padx=(4, 4), pady=(0, theme.PAD))

    def _build_list(self, parent):
        panel = ctk.CTkFrame(parent, **theme.panel_style())
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD, 4))

        self.list_title_label = ctk.CTkLabel(
            head, text="All Prompts", font=theme.font(13, "bold"), text_color=theme.TEXT, anchor="w"
        )
        self.list_title_label.pack(side="left")

        self.list_count_label = ctk.CTkLabel(
            head, text="", font=theme.font(10), text_color=theme.FAINT
        )
        self.list_count_label.pack(side="right")

        self.card_frame = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.card_frame.grid(row=1, column=0, sticky="nsew", padx=(6, 6), pady=(0, theme.PAD))
        self.card_frame.grid_columnconfigure(0, weight=1)

    # =====================================================
    # FILTER SIDEBAR
    # =====================================================

    def _rebuild_category_buttons(self):
        for w in self.category_list.winfo_children():
            w.destroy()

        entries = [ALL_CATEGORY, FAVORITES_CATEGORY] + storage.get_categories(self.prompts)
        # de-dupe while keeping order (get_categories already includes
        # DEFAULT_CATEGORY, ALL/FAVORITES are prepended separately)
        seen = set()
        ordered = []
        for e in entries:
            if e not in seen:
                seen.add(e)
                ordered.append(e)

        for cat in ordered:
            is_active = cat == self.active_filter
            btn = ctk.CTkButton(
                self.category_list, text=cat, anchor="w", height=30,
                fg_color=theme.ACCENT_MUTED if is_active else "transparent",
                hover_color=theme.PANEL_HOVER,
                text_color=theme.ACCENT if is_active else theme.MUTED,
                font=theme.font(12, "bold" if is_active else "normal"),
                command=lambda c=cat: self._set_filter(c)
            )
            btn.pack(fill="x", pady=1)

    def _set_filter(self, category):
        self.active_filter = category
        self._refresh()

    def _on_search_changed(self, _event=None):
        self.search_text = self.search_entry.get().strip().lower()
        self._refresh()

    # =====================================================
    # LIST RENDERING
    # =====================================================

    def _filtered_prompts(self):
        result = self.prompts

        if self.active_filter == FAVORITES_CATEGORY:
            result = [p for p in result if p.get("favorite")]
        elif self.active_filter != ALL_CATEGORY:
            result = [p for p in result if (p.get("category") or storage.DEFAULT_CATEGORY) == self.active_filter]

        if self.search_text:
            q = self.search_text
            result = [
                p for p in result
                if q in p.get("title", "").lower()
                or q in p.get("body", "").lower()
                or any(q in t.lower() for t in p.get("tags", []))
            ]

        return result

    def _refresh(self):
        self.prompts = storage.load_all()
        self._rebuild_category_buttons()
        self._render_cards()

    def _render_cards(self):
        for w in self.card_frame.winfo_children():
            w.destroy()

        prompts = self._filtered_prompts()
        self.list_title_label.configure(text=self.active_filter)
        self.list_count_label.configure(
            text=f"{len(prompts)} prompt{'s' if len(prompts) != 1 else ''}"
        )

        if not prompts:
            ctk.CTkLabel(
                self.card_frame,
                text="No prompts here yet. Click + New Prompt to save one.",
                font=theme.font(12), text_color=theme.FAINT
            ).pack(pady=40)
            return

        for p in prompts:
            self._render_card(p)

    def _render_card(self, p):
        card = ctk.CTkFrame(self.card_frame, **theme.panel_style())
        card.pack(fill="x", padx=4, pady=5)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=theme.PAD, pady=(theme.PAD, 2))

        star = "★" if p.get("favorite") else "☆"
        ctk.CTkButton(
            top, text=star, width=28, height=28,
            fg_color="transparent", hover_color=theme.PANEL_HOVER,
            text_color=theme.ACCENT if p.get("favorite") else theme.FAINT,
            font=theme.font(15),
            command=lambda pid=p["id"]: self._toggle_favorite(pid)
        ).pack(side="left")

        ctk.CTkLabel(
            top, text=p.get("title", "Untitled"), font=theme.font(14, "bold"),
            text_color=theme.TEXT, anchor="w"
        ).pack(side="left", padx=(4, 8))

        ctk.CTkLabel(
            top, text=p.get("category", storage.DEFAULT_CATEGORY), font=theme.font(10, "bold"),
            text_color=theme.MUTED, fg_color=theme.PANEL_2, corner_radius=6
        ).pack(side="left", padx=(0, 4), ipadx=6, ipady=2)

        tags = p.get("tags", [])
        if tags:
            ctk.CTkLabel(
                top, text="  ".join(f"#{t}" for t in tags), font=theme.font(10),
                text_color=theme.FAINT
            ).pack(side="left", padx=(4, 0))

        use_count = p.get("use_count", 0)
        if use_count:
            ctk.CTkLabel(
                top, text=f"used {use_count}×", font=theme.font(10), text_color=theme.FAINT
            ).pack(side="right")

        snippet = p.get("body", "").strip().replace("\n", "  ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "…"
        ctk.CTkLabel(
            card, text=snippet or "(empty)", font=theme.font(12), text_color=theme.MUTED,
            anchor="w", justify="left", wraplength=560
        ).pack(fill="x", padx=theme.PAD, pady=(0, theme.PAD))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=theme.PAD, pady=(0, theme.PAD))

        var_count = len(storage.extract_variables(p.get("body", "")))
        use_label = f"Use ({var_count} var{'s' if var_count != 1 else ''})" if var_count else "Copy"

        ctk.CTkButton(
            actions, text=use_label, width=130, height=28,
            command=lambda pp=p: self._use_prompt(pp), **theme.primary_button_style()
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            actions, text="Edit", width=70, height=28,
            command=lambda pp=p: self._open_editor(pp), **theme.secondary_button_style()
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            actions, text="Delete", width=70, height=28,
            command=lambda pid=p["id"], title=p.get("title", ""): self._delete_prompt(pid, title),
            **theme.danger_button_style()
        ).pack(side="left")

    # =====================================================
    # ACTIONS
    # =====================================================

    def _toggle_favorite(self, prompt_id):
        storage.toggle_favorite(prompt_id)
        self._refresh()

    def _delete_prompt(self, prompt_id, title):
        if not messagebox.askyesno("Delete Prompt", f"Delete \"{title}\"? This can't be undone."):
            return
        storage.delete_prompt(prompt_id)
        self._refresh()

    def _use_prompt(self, prompt):
        variables = storage.extract_variables(prompt.get("body", ""))
        if variables:
            VariableFillDialog(self, prompt, variables, on_done=self._finish_use)
        else:
            self._finish_use(prompt, prompt.get("body", ""))

    def _finish_use(self, prompt, filled_text):
        pyperclip.copy(filled_text)
        storage.mark_used(prompt["id"])
        self._refresh()
        self._flash_status(f"Copied \"{prompt.get('title', 'prompt')}\" to clipboard.")

    def _flash_status(self, text):
        # Lightweight, non-blocking confirmation — a toast-style label
        # that fades itself out rather than an interrupting messagebox,
        # since "copied to clipboard" doesn't need acknowledgement.
        toast = ctk.CTkLabel(
            self, text=text, font=theme.font(12, "bold"),
            fg_color=theme.PANEL_2, text_color=theme.ACCENT, corner_radius=8
        )
        toast.place(relx=0.5, rely=0.97, anchor="s")
        self.after(2200, toast.destroy)

    def _open_editor(self, prompt):
        PromptEditorDialog(self, prompt, on_save=self._on_editor_saved)

    def _on_editor_saved(self, record):
        self._refresh()
        self._flash_status(f"Saved \"{record.get('title', 'prompt')}\".")


# =====================================================
# VARIABLE FILL DIALOG
# =====================================================

class VariableFillDialog(ctk.CTkToplevel):
    """Small modal: one entry per {{variable}} in the prompt, then
    copies the filled-in text to the clipboard."""

    def __init__(self, parent, prompt, variables, on_done):
        super().__init__(parent)
        self.prompt = prompt
        self.variables = variables
        self.on_done = on_done
        self.entries = {}

        self.title(f"Fill Variables — {prompt.get('title', 'Prompt')}")
        self.geometry("420x" + str(120 + 46 * len(variables)))
        self.configure(fg_color=theme.BG)
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Fill in the placeholders, then Copy.", font=theme.font(12),
            text_color=theme.MUTED
        ).pack(padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        for var in variables:
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=theme.PAD_LG, pady=4)
            ctk.CTkLabel(
                row, text=var, width=110, anchor="w", font=theme.font(12, "bold"),
                text_color=theme.TEXT
            ).pack(side="left")
            entry = ctk.CTkEntry(
                row, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
            )
            entry.pack(side="left", fill="x", expand=True)
            self.entries[var] = entry

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=theme.PAD_LG, pady=theme.PAD_LG)

        ctk.CTkButton(
            btn_row, text="Copy", command=self._on_copy, **theme.primary_button_style()
        ).pack(side="right")
        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy, **theme.secondary_button_style()
        ).pack(side="right", padx=(0, 6))

    def _on_copy(self):
        values = {k: e.get() for k, e in self.entries.items()}
        filled = storage.fill_variables(self.prompt.get("body", ""), values)
        self.destroy()
        self.on_done(self.prompt, filled)


# =====================================================
# EDITOR DIALOG
# =====================================================

class PromptEditorDialog(ctk.CTkToplevel):
    """Add/edit modal. Use {{variable_name}} anywhere in the body to
    create a fill-in-the-blank prompt."""

    def __init__(self, parent, prompt, on_save):
        super().__init__(parent)
        self.prompt = prompt  # None -> new prompt
        self.on_save = on_save

        self.title("Edit Prompt" if prompt else "New Prompt")
        self.geometry("520x560")
        self.configure(fg_color=theme.BG)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._field_label("Title")
        self.title_entry = ctk.CTkEntry(
            self, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
        )
        self.title_entry.grid(row=1, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD))

        meta_row = ctk.CTkFrame(self, fg_color="transparent")
        meta_row.grid(row=2, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD))
        meta_row.grid_columnconfigure(0, weight=1)
        meta_row.grid_columnconfigure(1, weight=1)

        cat_wrap = ctk.CTkFrame(meta_row, fg_color="transparent")
        cat_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(
            cat_wrap, text="Category", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.category_entry = ctk.CTkEntry(
            cat_wrap, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT,
            placeholder_text=storage.DEFAULT_CATEGORY
        )
        self.category_entry.pack(fill="x")

        tags_wrap = ctk.CTkFrame(meta_row, fg_color="transparent")
        tags_wrap.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(
            tags_wrap, text="Tags (comma separated)", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.tags_entry = ctk.CTkEntry(
            tags_wrap, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT,
            placeholder_text="coding, review"
        )
        self.tags_entry.pack(fill="x")

        self._field_label("Body — use {{variable}} for fill-in-the-blank placeholders", row=3)
        self.body_text = ctk.CTkTextbox(
            self, fg_color=theme.PANEL_2, text_color=theme.TEXT, wrap="word",
            font=theme.font(13)
        )
        self.body_text.grid(row=4, column=0, sticky="nsew", padx=theme.PAD_LG, pady=(0, theme.PAD))
        self.grid_rowconfigure(4, weight=1)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))

        ctk.CTkButton(
            btn_row, text="Save", command=self._on_save, **theme.primary_button_style()
        ).pack(side="right")
        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy, **theme.secondary_button_style()
        ).pack(side="right", padx=(0, 6))

        if prompt:
            self.title_entry.insert(0, prompt.get("title", ""))
            self.category_entry.insert(0, prompt.get("category", ""))
            self.tags_entry.insert(0, ", ".join(prompt.get("tags", [])))
            self.body_text.insert("1.0", prompt.get("body", ""))

    def _field_label(self, text, row=0):
        ctk.CTkLabel(
            self, text=text, font=theme.font(10, "bold"), text_color=theme.FAINT, anchor="w"
        ).grid(row=row, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG if row == 0 else 8, 4))

    def _on_save(self):
        title = self.title_entry.get().strip()
        body = self.body_text.get("1.0", "end").strip()

        if not title:
            messagebox.showwarning("Missing Title", "Give this prompt a title before saving.")
            return
        if not body:
            messagebox.showwarning("Missing Body", "The prompt body can't be empty.")
            return

        tags = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]

        record = storage.save_prompt({
            "id": self.prompt.get("id") if self.prompt else None,
            "title": title,
            "category": self.category_entry.get().strip(),
            "tags": tags,
            "body": body,
            "favorite": self.prompt.get("favorite", False) if self.prompt else False,
        })

        self.destroy()
        self.on_save(record)
