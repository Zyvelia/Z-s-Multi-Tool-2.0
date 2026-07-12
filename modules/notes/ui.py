# modules/notes/ui.py
#
# General-purpose note-taking: free-form title + body text, with zero or
# more attached links per note. Not a checklist/shopping-list layout —
# just information you want to keep, with the option to attach reference
# links to it.

import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from core import theme
from . import storage


class NotesPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager

        self.current_note_id = None   # None = new/unsaved note
        self.link_rows = []           # [{"frame", "label_var", "url_var"}]

        self._build_ui()
        self.refresh_list()
        self._new_note()

    # =====================================================
    # LAYOUT
    # =====================================================

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        ctk.CTkLabel(
            header,
            text="📝  Notes",
            font=theme.font(22, "bold"),
            text_color=theme.TEXT
        ).pack(side="left", padx=theme.PAD_LG, pady=14)

        self.search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            header,
            placeholder_text="Search notes...",
            textvariable=self.search_var,
            width=240,
            height=34,
            fg_color=theme.PANEL_2,
            border_width=0,
            corner_radius=theme.RADIUS_SM,
            text_color=theme.TEXT
        )
        search_entry.pack(side="right", padx=(0, theme.PAD_LG), pady=14)
        self.search_var.trace_add("write", lambda *_: self.refresh_list())

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        body.grid_columnconfigure(0, weight=0, minsize=280)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ── Left: note list ─────────────────────────────
        list_panel = ctk.CTkFrame(body, **theme.panel_style())
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, theme.PAD))
        list_panel.grid_rowconfigure(1, weight=1)
        list_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            list_panel,
            text="+ New Note",
            height=36,
            command=self._new_note,
            **theme.primary_button_style()
        ).grid(row=0, column=0, sticky="ew", padx=theme.PAD, pady=theme.PAD)

        self.list_frame = ctk.CTkScrollableFrame(
            list_panel,
            fg_color="transparent"
        )
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=(6, 6), pady=(0, 6))
        self.list_frame.grid_columnconfigure(0, weight=1)

        # ── Right: editor ────────────────────────────────
        editor_panel = ctk.CTkFrame(body, **theme.panel_style())
        editor_panel.grid(row=0, column=1, sticky="nsew")
        editor_panel.grid_rowconfigure(2, weight=1)
        editor_panel.grid_columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(editor_panel, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG, 8))
        top_row.grid_columnconfigure(0, weight=1)

        self.title_entry = ctk.CTkEntry(
            top_row,
            placeholder_text="Note title...",
            font=theme.font(18, "bold"),
            fg_color=theme.PANEL_2,
            border_width=0,
            corner_radius=theme.RADIUS_SM,
            text_color=theme.TEXT,
            height=42
        )
        self.title_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.pin_btn = ctk.CTkButton(
            top_row, text="☆", width=42, height=42,
            command=self._toggle_pin,
            **theme.secondary_button_style()
        )
        self.pin_btn.grid(row=0, column=1, padx=(0, 8))

        ctk.CTkButton(
            top_row, text="🗑", width=42, height=42,
            command=self._delete_note,
            **theme.danger_button_style()
        ).grid(row=0, column=2)

        # links section
        links_section = ctk.CTkFrame(editor_panel, fg_color="transparent")
        links_section.grid(row=1, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, 8))
        links_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            links_section, text="LINKS", font=theme.font(10, "bold"),
            text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.links_frame = ctk.CTkFrame(links_section, fg_color="transparent")
        self.links_frame.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        self.links_frame.grid_columnconfigure(0, weight=1)

        add_link_row = ctk.CTkFrame(links_section, fg_color="transparent")
        add_link_row.grid(row=2, column=0, sticky="ew")
        add_link_row.grid_columnconfigure(1, weight=1)

        self.new_link_label = ctk.CTkEntry(
            add_link_row, placeholder_text="Label (optional)",
            width=140, height=30, fg_color=theme.PANEL_2, border_width=0,
            corner_radius=theme.RADIUS_SM, text_color=theme.TEXT
        )
        self.new_link_label.grid(row=0, column=0, padx=(0, 6))

        self.new_link_url = ctk.CTkEntry(
            add_link_row, placeholder_text="https://...",
            height=30, fg_color=theme.PANEL_2, border_width=0,
            corner_radius=theme.RADIUS_SM, text_color=theme.TEXT
        )
        self.new_link_url.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.new_link_url.bind("<Return>", lambda _e: self._add_link_row())

        ctk.CTkButton(
            add_link_row, text="Add Link", width=90, height=30,
            command=self._add_link_row,
            **theme.secondary_button_style()
        ).grid(row=0, column=2)

        # body text
        self.body_text = ctk.CTkTextbox(
            editor_panel,
            fg_color=theme.PANEL_2,
            corner_radius=theme.RADIUS_SM,
            text_color=theme.TEXT,
            border_width=0,
            font=theme.font(13),
            wrap="word"
        )
        self.body_text.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_LG, pady=(0, 8))

        ctk.CTkButton(
            editor_panel,
            text="Save Note",
            height=38,
            command=self._save_note,
            **theme.primary_button_style()
        ).grid(row=3, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))

    # =====================================================
    # NOTE LIST
    # =====================================================

    def refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        notes = storage.search_notes(self.search_var.get())

        if not notes:
            ctk.CTkLabel(
                self.list_frame,
                text="No notes yet." if not self.search_var.get() else "No matches.",
                font=theme.font(12),
                text_color=theme.MUTED
            ).grid(row=0, column=0, sticky="w", padx=6, pady=10)
            return

        for i, note in enumerate(notes):
            self._build_list_item(note, i)

    def _build_list_item(self, note, row):
        selected = note["id"] == self.current_note_id

        item = ctk.CTkFrame(
            self.list_frame,
            fg_color=theme.PANEL_HOVER if selected else theme.PANEL_2,
            corner_radius=theme.RADIUS_SM,
            border_width=1,
            border_color=theme.ACCENT if selected else theme.BORDER
        )
        item.grid(row=row, column=0, sticky="ew", pady=4)
        item.grid_columnconfigure(0, weight=1)

        title = note.get("title", "Untitled")
        if note.get("pinned"):
            title = "📌 " + title

        ctk.CTkLabel(
            item, text=title, font=theme.font(13, "bold"),
            text_color=theme.TEXT, anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))

        snippet = (note.get("body", "") or "").strip().replace("\n", " ")
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."
        link_count = len(note.get("links", []))
        meta = snippet or "(empty note)"
        if link_count:
            meta += f"   🔗 {link_count}"

        ctk.CTkLabel(
            item, text=meta, font=theme.font(11),
            text_color=theme.MUTED, anchor="w"
        ).grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))

        for widget in (item,) + tuple(item.winfo_children()):
            widget.bind("<Button-1>", lambda _e, n=note: self._load_note(n))

    # =====================================================
    # EDITOR
    # =====================================================

    def _clear_links_ui(self):
        for row in self.link_rows:
            row["frame"].destroy()
        self.link_rows = []

    def _add_link_row(self, label="", url=""):
        # called both by the "Add Link" button (reads the new-link entries)
        # and internally when loading an existing note's saved links
        if label == "" and url == "":
            label = self.new_link_label.get().strip()
            url = self.new_link_url.get().strip()
            if not url:
                return
            self.new_link_label.delete(0, "end")
            self.new_link_url.delete(0, "end")

        row_frame = ctk.CTkFrame(self.links_frame, fg_color=theme.PANEL_2, corner_radius=6)
        row_frame.grid(row=len(self.link_rows), column=0, sticky="ew", pady=2)
        row_frame.grid_columnconfigure(0, weight=1)

        display = label if label else url
        link_label = ctk.CTkLabel(
            row_frame, text=f"🔗 {display}", font=theme.font(12),
            text_color=theme.ACCENT, anchor="w", cursor="hand2"
        )
        link_label.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        link_label.bind("<Button-1>", lambda _e, u=url: self._open_link(u))

        entry = {"frame": row_frame, "label": label, "url": url}

        ctk.CTkButton(
            row_frame, text="✕", width=24, height=24, corner_radius=12,
            fg_color=theme.PANEL, hover_color=theme.DANGER_HOVER,
            text_color=theme.MUTED, font=theme.font(10, "bold"),
            command=lambda: self._remove_link_row(entry)
        ).grid(row=0, column=1, padx=6)

        self.link_rows.append(entry)

    def _remove_link_row(self, entry):
        entry["frame"].destroy()
        self.link_rows.remove(entry)
        # re-pack remaining rows so there's no gap
        for i, row in enumerate(self.link_rows):
            row["frame"].grid(row=i, column=0, sticky="ew", pady=2)

    def _open_link(self, url):
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Couldn't Open Link", str(e))

    def _new_note(self):
        self.current_note_id = None
        self.title_entry.delete(0, "end")
        self.body_text.delete("1.0", "end")
        self._clear_links_ui()
        self.pin_btn.configure(text="☆")
        self.title_entry.focus_set()
        self.refresh_list()

    def _load_note(self, note):
        self.current_note_id = note["id"]
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, note.get("title", ""))
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", note.get("body", ""))
        self._clear_links_ui()
        for link in note.get("links", []):
            self._add_link_row(label=link.get("label", ""), url=link.get("url", ""))
        self.pin_btn.configure(text="📌" if note.get("pinned") else "☆")
        self.refresh_list()

    def _save_note(self):
        title = self.title_entry.get().strip()
        body = self.body_text.get("1.0", "end-1c")
        links = [{"label": r["label"], "url": r["url"]} for r in self.link_rows]

        if self.current_note_id is None:
            note = storage.create_note(title=title, body=body, links=links)
            self.current_note_id = note["id"]
        else:
            storage.update_note(self.current_note_id, title=title, body=body, links=links)

        self.refresh_list()

    def _delete_note(self):
        if self.current_note_id is None:
            self._new_note()
            return

        if messagebox.askyesno("Delete Note", "Delete this note? This can't be undone."):
            storage.delete_note(self.current_note_id)
            self._new_note()

    def _toggle_pin(self):
        if self.current_note_id is None:
            messagebox.showinfo("Save First", "Save the note before pinning it.")
            return
        note = storage.toggle_pin(self.current_note_id)
        if note:
            self.pin_btn.configure(text="📌" if note.get("pinned") else "☆")
            self.refresh_list()

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def on_show(self):
        # Picks up notes changed elsewhere (there's nowhere else that
        # edits notes right now, but this keeps behavior consistent with
        # other pages if that ever changes) and re-highlights selection.
        self.refresh_list()
