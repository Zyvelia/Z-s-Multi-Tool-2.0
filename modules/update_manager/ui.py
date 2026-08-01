"""
ui.py
-----
The visual layer for the Update Manager module. Presentational only — all
real work is delegated to backend.py. Long-running work (service control,
Get-HotFix, wusa.exe) runs on background threads so the UI never freezes,
with results marshalled back to the main thread through a thread-safe
queue polled via `after()`, matching the convention used in cleaner/ui.py
and app_installer/ui.py.
"""

from __future__ import annotations

import datetime
import queue
import threading
import webbrowser
from typing import List, Optional

import customtkinter as ctk

from .admin import is_admin, relaunch_as_admin
from .backend import (
    HistoryEntry,
    InstalledUpdate,
    ProgressEvent,
    ServiceStatus,
    block_updates,
    get_full_history,
    get_pause_expiry,
    get_status,
    is_blocked,
    kb_support_url,
    list_installed_updates,
    pause_updates,
    resume_updates_from_pause,
    unblock_updates,
    uninstall_update_async,
)
from core import theme

# ── Colours (matches the app's shared dark theme) ─────────────────────────
BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
DANGER = theme.DANGER
SUCCESS = theme.SUCCESS
TEXT = theme.TEXT
MUTED = theme.MUTED

_BTN = dict(fg_color=PANEL_2, hover_color=ACCENT, text_color=TEXT, height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=theme.ACCENT_DIM, text_color="white", height=34, corner_radius=8)
_BTN_DANGER = dict(fg_color=DANGER, hover_color=DANGER, text_color="white", height=34, corner_radius=8)


def _make_btn(parent, text, cmd, **overrides):
    return ctk.CTkButton(parent, text=text, command=cmd, **{**_BTN, **overrides})


class UpdateManagerPage(ctk.CTkFrame):
    """Main page for the Update Manager module."""

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager

        self._block_queue: "queue.Queue[tuple]" = queue.Queue()
        self._uninstall_queue: Optional["queue.Queue[ProgressEvent]"] = None
        self._updates: List[InstalledUpdate] = []
        self._history: List[HistoryEntry] = []
        self._busy = False

        self._build_ui()
        self._poll_queue()
        self.refresh_status()
        self.refresh_pause_status()

    # ── Build ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()

        self.tabs = ctk.CTkTabview(
            self, fg_color=PANEL, corner_radius=10,
            segmented_button_fg_color=PANEL_2,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_DIM,
        )
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tabs.add("Block Updates")
        self.tabs.add("Pause Updates")
        self.tabs.add("Uninstall Updates")
        self.tabs.add("History")

        self._build_block_tab(self.tabs.tab("Block Updates"))
        self._build_pause_tab(self.tabs.tab("Pause Updates"))
        self._build_uninstall_tab(self.tabs.tab("Uninstall Updates"))
        self._build_history_tab(self.tabs.tab("History"))

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=12)

        ctk.CTkLabel(header, text="🛡 Update Manager", font=("Segoe UI", 18, "bold"), text_color=TEXT
                      ).pack(side="left", padx=12, pady=10)

        admin_text = "🛡 Running as administrator" if is_admin() else "Not elevated"
        admin_color = SUCCESS if is_admin() else MUTED
        ctk.CTkLabel(header, text=admin_text, text_color=admin_color).pack(side="left", padx=8)

        if not is_admin():
            btn_bar = ctk.CTkFrame(header, fg_color="transparent")
            btn_bar.pack(side="right", padx=8, pady=8)
            _make_btn(btn_bar, "Restart as Administrator", self._restart_as_admin, width=190
                       ).pack(side="left", padx=4)

    # ── Block tab ────────────────────────────────────────────────────────

    def _build_block_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)

        warn = ctk.CTkFrame(tab, fg_color=PANEL_2, corner_radius=8)
        warn.pack(fill="x", padx=10, pady=(10, 8))
        ctk.CTkLabel(
            warn, justify="left", anchor="w", text_color=MUTED, wraplength=640,
            text=("Blocking Windows Update stops your PC from receiving ANY updates, "
                  "including security patches, until you unblock it. Use this for "
                  "temporary control (e.g. before a big deadline), not as a permanent "
                  "setting — leaving it blocked for long periods leaves you exposed."),
        ).pack(fill="x", padx=12, pady=10)

        status_panel = ctk.CTkFrame(tab, fg_color=PANEL_2, corner_radius=8)
        status_panel.pack(fill="x", padx=10, pady=(0, 8))

        top = ctk.CTkFrame(status_panel, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))
        self._status_lbl = ctk.CTkLabel(top, text="Checking status…",
                                         font=("Segoe UI", 15, "bold"), text_color=TEXT)
        self._status_lbl.pack(side="left")
        _make_btn(top, "Refresh", self.refresh_status, width=90).pack(side="right")

        self._service_rows_frame = ctk.CTkFrame(status_panel, fg_color="transparent")
        self._service_rows_frame.pack(fill="x", padx=12, pady=(4, 12))

        btn_bar = ctk.CTkFrame(tab, fg_color="transparent")
        btn_bar.pack(fill="x", padx=10, pady=(0, 10))
        self._block_btn = ctk.CTkButton(btn_bar, text="Block Windows Update", width=190,
                                         command=self._confirm_block, **_BTN_DANGER)
        self._block_btn.pack(side="left", padx=(0, 8))
        self._unblock_btn = ctk.CTkButton(btn_bar, text="Unblock Windows Update", width=190,
                                           command=self._do_unblock, **_BTN_ACCENT)
        self._unblock_btn.pack(side="left")

        self._block_log = ctk.CTkTextbox(
            tab, fg_color=PANEL_2, text_color=TEXT, corner_radius=8,
            font=("Consolas", 12), state="disabled", height=100,
        )
        self._block_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def refresh_status(self):
        threading.Thread(target=self._status_worker, daemon=True).start()

    def _status_worker(self):
        statuses = get_status()
        self._block_queue.put(("status", statuses))

    def _on_status(self, statuses: List[ServiceStatus]):
        for child in self._service_rows_frame.winfo_children():
            child.destroy()

        blocked = bool(statuses) and all(s.start_type == "disabled" for s in statuses)
        if blocked:
            self._status_lbl.configure(text="🔴 Windows Update is BLOCKED", text_color=DANGER)
        else:
            self._status_lbl.configure(text="🟢 Windows Update is active", text_color=SUCCESS)

        for s in statuses:
            row = ctk.CTkFrame(self._service_rows_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=s.name, text_color=TEXT, width=100, anchor="w").pack(side="left")
            state_text = f"start type: {s.start_type}"
            if s.running:
                state_text += " · running"
            ctk.CTkLabel(row, text=state_text, text_color=MUTED, anchor="w").pack(side="left", padx=8)

        self._block_btn.configure(state="disabled" if blocked else "normal")
        self._unblock_btn.configure(state="normal" if blocked else "disabled")

    def _confirm_block(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Block Windows Update")
        dialog.geometry("420x200")
        dialog.configure(fg_color=BG)
        dialog.transient(self.winfo_toplevel())
        self.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - 420) // 2
        y = root.winfo_rooty() + (root.winfo_height() - 200) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(10, dialog.focus_force)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, justify="left", anchor="w", wraplength=380, text_color=TEXT,
            text=("This disables the Windows Update and Update Orchestrator services. "
                  "Your PC will stop checking for and installing updates, including "
                  "security fixes, until you come back here and unblock it."),
        ).pack(fill="x", padx=16, pady=(16, 6))

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(side="bottom", pady=16)
        _make_btn(btns, "Cancel", dialog.destroy, width=100).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Block", width=100,
                       command=lambda: (dialog.destroy(), self._do_block()),
                       **_BTN_DANGER).pack(side="left", padx=8)

    def _do_block(self):
        self._append_block_log("Blocking Windows Update…")
        self._set_block_buttons_busy(True)
        threading.Thread(target=self._block_worker, daemon=True).start()

    def _do_unblock(self):
        self._append_block_log("Unblocking Windows Update…")
        self._set_block_buttons_busy(True)
        threading.Thread(target=self._unblock_worker, daemon=True).start()

    def _block_worker(self):
        errors = block_updates()
        self._block_queue.put(("block_done", errors))

    def _unblock_worker(self):
        errors = unblock_updates()
        self._block_queue.put(("unblock_done", errors))

    def _set_block_buttons_busy(self, busy: bool):
        self._block_btn.configure(state="disabled")
        self._unblock_btn.configure(state="disabled")
        if not busy:
            self.refresh_status()

    def _on_block_done(self, kind: str, errors: List[str]):
        if errors:
            self._append_block_log(f"⚠ Done with {len(errors)} error(s):")
            for e in errors:
                self._append_block_log(f"  {e}")
            if not is_admin():
                self._append_block_log("  This usually means the app needs to run as Administrator.")
        else:
            verb = "blocked" if kind == "block_done" else "unblocked"
            self._append_block_log(f"✓ Windows Update {verb}.")
        self.refresh_status()

    def _append_block_log(self, text: str):
        self._block_log.configure(state="normal")
        self._block_log.insert("end", text + "\n")
        self._block_log.see("end")
        self._block_log.configure(state="disabled")

    # ── Pause tab ────────────────────────────────────────────────────────

    def _build_pause_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(tab, fg_color=PANEL_2, corner_radius=8)
        info.pack(fill="x", padx=10, pady=(10, 8))
        ctk.CTkLabel(
            info, justify="left", anchor="w", text_color=MUTED, wraplength=640,
            text=("A gentler alternative to Block: this uses the same registry setting as "
                  "Settings > Windows Update > Pause updates. The update services stay "
                  "running, and Windows automatically resumes updates once the pause "
                  "expires — capped at 35 days, same as the built-in feature."),
        ).pack(fill="x", padx=12, pady=10)

        status_panel = ctk.CTkFrame(tab, fg_color=PANEL_2, corner_radius=8)
        status_panel.pack(fill="x", padx=10, pady=(0, 8))
        top = ctk.CTkFrame(status_panel, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=10)
        self._pause_status_lbl = ctk.CTkLabel(top, text="Checking status…",
                                               font=("Segoe UI", 15, "bold"), text_color=TEXT)
        self._pause_status_lbl.pack(side="left")
        _make_btn(top, "Refresh", self.refresh_pause_status, width=90).pack(side="right")

        btn_bar = ctk.CTkFrame(tab, fg_color="transparent")
        btn_bar.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(btn_bar, text="Pause for:", text_color=TEXT).pack(side="left", padx=(0, 6))
        self._pause_days_var = ctk.StringVar(value="7")
        ctk.CTkOptionMenu(
            btn_bar, variable=self._pause_days_var, values=["3", "7", "14", "21", "30", "35"],
            fg_color=PANEL_2, button_color=PANEL_2, button_hover_color=ACCENT,
            text_color=TEXT, width=80,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(btn_bar, text="days", text_color=MUTED).pack(side="left", padx=(0, 12))
        self._pause_btn = ctk.CTkButton(btn_bar, text="Pause Updates", width=150,
                                         command=self._do_pause, **_BTN_ACCENT)
        self._pause_btn.pack(side="left", padx=(0, 8))
        self._resume_pause_btn = ctk.CTkButton(btn_bar, text="Resume Now", width=130,
                                                command=self._do_resume_pause, **_BTN)
        self._resume_pause_btn.pack(side="left")

        self._pause_log = ctk.CTkTextbox(
            tab, fg_color=PANEL_2, text_color=TEXT, corner_radius=8,
            font=("Consolas", 12), state="disabled", height=100,
        )
        self._pause_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def refresh_pause_status(self):
        threading.Thread(target=self._pause_status_worker, daemon=True).start()

    def _pause_status_worker(self):
        expiry = get_pause_expiry()
        self._block_queue.put(("pause_status", expiry))

    def _on_pause_status(self, expiry: Optional[datetime.datetime]):
        if expiry:
            days_left = max(0, (expiry - datetime.datetime.utcnow()).days)
            self._pause_status_lbl.configure(
                text=f"⏸ Paused until {expiry.strftime('%Y-%m-%d')} ({days_left} day(s) left)",
                text_color=ACCENT,
            )
            self._pause_btn.configure(state="disabled")
            self._resume_pause_btn.configure(state="normal")
        else:
            self._pause_status_lbl.configure(text="🟢 Not paused", text_color=SUCCESS)
            self._pause_btn.configure(state="normal")
            self._resume_pause_btn.configure(state="disabled")

    def _do_pause(self):
        try:
            days = int(self._pause_days_var.get())
        except ValueError:
            days = 7
        self._append_pause_log(f"Pausing updates for {days} day(s)…")
        self._pause_btn.configure(state="disabled")
        self._resume_pause_btn.configure(state="disabled")
        threading.Thread(target=self._pause_worker, args=(days,), daemon=True).start()

    def _do_resume_pause(self):
        self._append_pause_log("Resuming updates…")
        self._pause_btn.configure(state="disabled")
        self._resume_pause_btn.configure(state="disabled")
        threading.Thread(target=self._resume_pause_worker, daemon=True).start()

    def _pause_worker(self, days: int):
        errors = pause_updates(days)
        self._block_queue.put(("pause_done", errors))

    def _resume_pause_worker(self):
        errors = resume_updates_from_pause()
        self._block_queue.put(("resume_pause_done", errors))

    def _on_pause_action_done(self, errors: List[str]):
        if errors:
            self._append_pause_log(f"⚠ Done with {len(errors)} error(s):")
            for e in errors:
                self._append_pause_log(f"  {e}")
            if not is_admin():
                self._append_pause_log("  This usually means the app needs to run as Administrator.")
        else:
            self._append_pause_log("✓ Done.")
        self.refresh_pause_status()

    def _append_pause_log(self, text: str):
        self._pause_log.configure(state="normal")
        self._pause_log.insert("end", text + "\n")
        self._pause_log.see("end")
        self._pause_log.configure(state="disabled")

    # ── Uninstall tab ────────────────────────────────────────────────────

    def _build_uninstall_tab(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(top, text="Installed updates", font=("Segoe UI", 15, "bold"), text_color=TEXT
                      ).pack(side="left")
        self._refresh_updates_btn = _make_btn(top, "Refresh List", self._load_updates, width=110)
        self._refresh_updates_btn.pack(side="right")

        self._filter_var = ctk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._render_updates())
        filter_entry = ctk.CTkEntry(
            tab, textvariable=self._filter_var, placeholder_text="Filter by KB number or keyword…",
            fg_color=PANEL_2, border_color=PANEL_2, text_color=TEXT, height=32, corner_radius=8,
        )
        filter_entry.pack(fill="x", padx=10, pady=(0, 6))

        self._updates_frame = ctk.CTkScrollableFrame(tab, fg_color=PANEL_2, corner_radius=8)
        self._updates_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self._uninstall_log = ctk.CTkTextbox(
            tab, fg_color=PANEL_2, text_color=TEXT, corner_radius=8,
            font=("Consolas", 12), state="disabled", height=90,
        )
        self._uninstall_log.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self._load_updates()

    def _load_updates(self):
        self._refresh_updates_btn.configure(state="disabled", text="Loading…")
        for child in self._updates_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(self._updates_frame, text="Loading installed updates…", text_color=MUTED
                      ).pack(padx=10, pady=10)
        threading.Thread(target=self._load_updates_worker, daemon=True).start()

    def _load_updates_worker(self):
        updates = list_installed_updates()
        self._block_queue.put(("updates_loaded", updates))

    def _on_updates_loaded(self, updates: List[InstalledUpdate]):
        self._updates = updates
        self._refresh_updates_btn.configure(state="normal", text="Refresh List")
        self._render_updates()

    def _render_updates(self):
        for child in self._updates_frame.winfo_children():
            child.destroy()

        if not self._updates:
            ctk.CTkLabel(self._updates_frame, text="No updates found (or unable to query Get-HotFix).",
                          text_color=MUTED).pack(padx=10, pady=10)
            return

        query = self._filter_var.get().strip().lower()
        shown = [
            u for u in self._updates
            if not query or query in u.kb_id.lower() or query in u.title.lower()
            or query in u.category.lower()
        ]
        if not shown:
            ctk.CTkLabel(self._updates_frame, text="No updates match that filter.",
                          text_color=MUTED).pack(padx=10, pady=10)
            return

        for u in shown:
            row = ctk.CTkFrame(self._updates_frame, fg_color="transparent")
            row.pack(fill="x", pady=3, padx=4)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)

            head = ctk.CTkFrame(info, fg_color="transparent")
            head.pack(fill="x")
            ctk.CTkLabel(head, text=u.kb_id, font=("Segoe UI", 13, "bold"), text_color=TEXT,
                          anchor="w").pack(side="left")
            ctk.CTkLabel(head, text=f"  ·  {u.category}", text_color=MUTED, anchor="w"
                          ).pack(side="left")

            # What the update is actually for. Falls back plainly when the
            # Update Agent history didn't have a matching entry (e.g. an
            # update installed by a source other than Windows Update).
            what_text = u.title or "No description available — see Microsoft's KB page for details."
            ctk.CTkLabel(info, text=what_text, text_color=TEXT, anchor="w",
                          wraplength=420, justify="left").pack(fill="x", pady=(2, 0))

            sub = f"Installed {u.installed_on}" if u.installed_on else "Install date unknown"
            ctk.CTkLabel(info, text=sub, text_color=MUTED, anchor="w").pack(fill="x")

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=4)
            ctk.CTkButton(btns, text="More info ↗", width=90,
                           command=lambda kb=u.kb_id: webbrowser.open(kb_support_url(kb)),
                           **_BTN).pack(side="top", pady=(0, 4))
            ctk.CTkButton(btns, text="Uninstall", width=90,
                           command=lambda kb=u.kb_id: self._confirm_uninstall(kb),
                           **_BTN_DANGER).pack(side="top")

    def _confirm_uninstall(self, kb_id: str):
        if self._busy:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Confirm uninstall")
        dialog.geometry("400x190")
        dialog.configure(fg_color=BG)
        dialog.transient(self.winfo_toplevel())
        self.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - 400) // 2
        y = root.winfo_rooty() + (root.winfo_height() - 190) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(10, dialog.focus_force)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, justify="left", anchor="w", wraplength=360, text_color=TEXT,
            text=(f"Uninstall {kb_id}? This tries wusa.exe first, then falls back to DISM "
                  f"for cumulative updates. May require a restart to finish, and can take a "
                  f"few minutes if DISM is needed. Some superseded updates still can't be removed."),
        ).pack(fill="x", padx=16, pady=(16, 6))

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(side="bottom", pady=16)
        _make_btn(btns, "Cancel", dialog.destroy, width=100).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Uninstall", width=100,
                       command=lambda: (dialog.destroy(), self._start_uninstall(kb_id)),
                       **_BTN_DANGER).pack(side="left", padx=8)

    def _start_uninstall(self, kb_id: str):
        self._busy = True
        self._append_uninstall_log(f"Starting uninstall of {kb_id}…")
        self._uninstall_queue = uninstall_update_async(kb_id)

    def _append_uninstall_log(self, text: str):
        self._uninstall_log.configure(state="normal")
        self._uninstall_log.insert("end", text + "\n")
        self._uninstall_log.see("end")
        self._uninstall_log.configure(state="disabled")

    # ── History tab ──────────────────────────────────────────────────────

    def _build_history_tab(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(top, text="Full update history", font=("Segoe UI", 15, "bold"), text_color=TEXT
                      ).pack(side="left")
        self._refresh_history_btn = _make_btn(top, "Refresh", self._load_history, width=90)
        self._refresh_history_btn.pack(side="right")

        self._history_filter_var = ctk.StringVar()
        self._history_filter_var.trace_add("write", lambda *_: self._render_history())
        ctk.CTkEntry(
            tab, textvariable=self._history_filter_var, placeholder_text="Filter by KB number or keyword…",
            fg_color=PANEL_2, border_color=PANEL_2, text_color=TEXT, height=32, corner_radius=8,
        ).pack(fill="x", padx=10, pady=(0, 6))

        self._history_frame = ctk.CTkScrollableFrame(tab, fg_color=PANEL_2, corner_radius=8)
        self._history_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._load_history()

    def _load_history(self):
        self._refresh_history_btn.configure(state="disabled", text="Loading…")
        for child in self._history_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(self._history_frame, text="Loading update history…", text_color=MUTED
                      ).pack(padx=10, pady=10)
        threading.Thread(target=self._load_history_worker, daemon=True).start()

    def _load_history_worker(self):
        entries = get_full_history()
        self._block_queue.put(("history_loaded", entries))

    def _on_history_loaded(self, entries: List[HistoryEntry]):
        self._history = entries
        self._refresh_history_btn.configure(state="normal", text="Refresh")
        self._render_history()

    def _render_history(self):
        for child in self._history_frame.winfo_children():
            child.destroy()

        if not self._history:
            ctk.CTkLabel(self._history_frame, text="No history found (or unable to query it).",
                          text_color=MUTED).pack(padx=10, pady=10)
            return

        query = self._history_filter_var.get().strip().lower()
        shown = [
            e for e in self._history
            if not query or query in e.kb_id.lower() or query in e.title.lower()
        ]
        if not shown:
            ctk.CTkLabel(self._history_frame, text="No entries match that filter.",
                          text_color=MUTED).pack(padx=10, pady=10)
            return

        for e in shown:
            row = ctk.CTkFrame(self._history_frame, fg_color="transparent")
            row.pack(fill="x", pady=3, padx=4)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)

            head = ctk.CTkFrame(info, fg_color="transparent")
            head.pack(fill="x")
            if e.succeeded:
                result_color = SUCCESS
            elif e.result in ("Not started", "In progress"):
                result_color = MUTED
            else:
                result_color = DANGER
            ctk.CTkLabel(head, text=e.result, text_color=result_color,
                          font=("Segoe UI", 12, "bold")).pack(side="left")
            tail = f"  ·  {e.kb_id}" if e.kb_id else ""
            tail += f"  ·  {e.date}" if e.date else ""
            ctk.CTkLabel(head, text=tail, text_color=MUTED).pack(side="left")

            ctk.CTkLabel(info, text=e.title, text_color=TEXT, anchor="w",
                          wraplength=460, justify="left").pack(fill="x", pady=(2, 0))

            if e.kb_id:
                ctk.CTkButton(row, text="More info ↗", width=90,
                               command=lambda kb=e.kb_id: webbrowser.open(kb_support_url(kb)),
                               **_BTN).pack(side="right", padx=4)

    # ── Shared plumbing ──────────────────────────────────────────────────

    def _restart_as_admin(self):
        if relaunch_as_admin():
            self.manager.container.winfo_toplevel().destroy()

    def _poll_queue(self):
        try:
            while True:
                item = self._block_queue.get_nowait()
                kind = item[0]
                if kind == "status":
                    self._on_status(item[1])
                elif kind in ("block_done", "unblock_done"):
                    self._on_block_done(kind, item[1])
                elif kind == "updates_loaded":
                    self._on_updates_loaded(item[1])
                elif kind == "pause_status":
                    self._on_pause_status(item[1])
                elif kind in ("pause_done", "resume_pause_done"):
                    self._on_pause_action_done(item[1])
                elif kind == "history_loaded":
                    self._on_history_loaded(item[1])
        except queue.Empty:
            pass

        if self._uninstall_queue is not None:
            try:
                while True:
                    event: ProgressEvent = self._uninstall_queue.get_nowait()
                    if event.kind == "log":
                        self._append_uninstall_log(event.message)
                    elif event.kind == "fatal_error":
                        self._append_uninstall_log(f"⚠ {event.message}")
                        self._busy = False
                        self._uninstall_queue = None
                    elif event.kind == "done":
                        prefix = "✓" if event.success else "⚠"
                        self._append_uninstall_log(f"{prefix} {event.message}")
                        self._busy = False
                        self._uninstall_queue = None
                        self._load_updates()
            except queue.Empty:
                pass

        self.after(150, self._poll_queue)
