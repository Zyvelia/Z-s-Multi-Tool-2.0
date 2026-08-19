import os
import json
import shutil
import subprocess
import threading

import customtkinter as ctk
from tkinter import messagebox, simpledialog, ttk

from core import theme

DB_FILENAME = "apps.json"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_FILENAME)


def load_database():
    if not os.path.exists(DB_PATH):
        return {"categories": {}}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_database(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def winget_available():
    return shutil.which("winget") is not None


class AppInstallerModule(ctk.CTkFrame):
    """Browse apps.json and install via winget or custom commands."""

    def __init__(self, container, manager=None):
        super().__init__(container, fg_color=theme.BG)
        self.manager = manager
        self.db = load_database()
        self.check_vars = {}
        self.entry_lookup = {}

        self._build_ui()
        self._populate_tree()

        if not winget_available():
            self._log("winget was not found on PATH. Installs will fail until it's available.\n")

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(top, text="Search:", text_color=theme.MUTED).grid(row=0, column=0, padx=(0, 8))
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_tree())
        ctk.CTkEntry(top, textvariable=self.search_var, fg_color=theme.PANEL_2,
                     border_color=theme.BORDER, text_color=theme.TEXT).grid(
            row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(top, text="Add App to DB", command=self._add_app_dialog,
                      **theme.secondary_button_kwargs()).grid(row=0, column=2, padx=4)
        ctk.CTkButton(top, text="Reload DB", command=self._reload_db,
                      **theme.secondary_button_kwargs()).grid(row=0, column=3)

        tree_wrap = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS,
                                 border_width=1, border_color=theme.BORDER)
        tree_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

        columns = ("selected", "name", "id", "category", "desc")
        self.tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("selected", text="✔")
        self.tree.heading("name", text="App")
        self.tree.heading("id", text="Winget ID")
        self.tree.heading("category", text="Category")
        self.tree.heading("desc", text="Description")
        self.tree.column("selected", width=30, anchor="center")
        self.tree.column("name", width=160)
        self.tree.column("id", width=160)
        self.tree.column("category", width=100)
        self.tree.column("desc", width=260)

        style = ttk.Style(self.tree)
        style.theme_use("clam")
        style.configure("Treeview",
                        background=theme.PANEL_2, foreground=theme.TEXT,
                        fieldbackground=theme.PANEL_2, bordercolor=theme.BORDER,
                        rowheight=26)
        style.map("Treeview", background=[("selected", theme.ACCENT_GLOW)],
                  foreground=[("selected", theme.ACCENT)])
        style.configure("Treeview.Heading", background=theme.PANEL, foreground=theme.MUTED,
                        relief="flat")
        style.configure("Vertical.TScrollbar", background=theme.PANEL_2, troughcolor=theme.PANEL,
                        bordercolor=theme.BORDER)

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        vsb.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._toggle_selected_rows)

        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        ctk.CTkButton(action_frame, text="Install Checked", command=self._install_checked,
                      **theme.primary_button_kwargs()).pack(side="left")
        ctk.CTkButton(action_frame, text="Check All Visible",
                      command=lambda: self._set_all_visible(True),
                      **theme.secondary_button_kwargs()).pack(side="left", padx=6)
        ctk.CTkButton(action_frame, text="Uncheck All",
                      command=lambda: self._set_all_visible(False),
                      **theme.secondary_button_kwargs()).pack(side="left")

        custom_frame = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS,
                                    border_width=1, border_color=theme.BORDER)
        custom_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        custom_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(custom_frame, text="Run a custom install command",
                     text_color=theme.TEXT, font=theme.font(13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))
        self.custom_cmd_var = ctk.StringVar()
        ctk.CTkEntry(custom_frame, textvariable=self.custom_cmd_var, fg_color=theme.PANEL_2,
                     border_color=theme.BORDER, text_color=theme.TEXT).grid(
            row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        ctk.CTkButton(custom_frame, text="Run", command=self._run_custom_command,
                      **theme.secondary_button_kwargs(), width=80).grid(
            row=1, column=1, padx=(0, 12), pady=(0, 10))

        log_frame = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS,
                                 border_width=1, border_color=theme.BORDER)
        log_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 12))
        log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log_frame, text="Output", text_color=theme.MUTED,
                     font=theme.font(12, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))
        self.log_text = ctk.CTkTextbox(log_frame, height=120, fg_color=theme.PANEL_2,
                                       text_color=theme.TEXT, font=theme.mono(11))
        self.log_text.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.log_text.configure(state="disabled")

    def _iter_apps(self):
        for category, apps in self.db.get("categories", {}).items():
            for app in apps:
                yield category, app

    def _populate_tree(self):
        query = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self.entry_lookup.clear()

        for category, app in self._iter_apps():
            haystack = f"{app.get('name','')} {app.get('id','')} {category} {app.get('desc','')}".lower()
            if query and query not in haystack:
                continue
            wid = app["id"]
            if wid not in self.check_vars:
                self.check_vars[wid] = ctk.BooleanVar(value=False)
            checked = self.check_vars[wid]
            mark = "☑" if checked.get() else "☐"
            row_id = self.tree.insert(
                "", "end", values=(mark, app.get("name", ""), wid, category, app.get("desc", ""))
            )
            self.entry_lookup[row_id] = (wid, category, app)

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id or col != "#1":
            return
        self._toggle_row(row_id)

    def _toggle_selected_rows(self, event):
        for row_id in self.tree.selection():
            self._toggle_row(row_id)

    def _toggle_row(self, row_id):
        if row_id not in self.entry_lookup:
            return
        wid, _, _ = self.entry_lookup[row_id]
        var = self.check_vars[wid]
        var.set(not var.get())
        vals = list(self.tree.item(row_id, "values"))
        vals[0] = "☑" if var.get() else "☐"
        self.tree.item(row_id, values=vals)

    def _set_all_visible(self, state):
        for row_id in self.tree.get_children():
            wid, _, _ = self.entry_lookup[row_id]
            self.check_vars[wid].set(state)
            vals = list(self.tree.item(row_id, "values"))
            vals[0] = "☑" if state else "☐"
            self.tree.item(row_id, values=vals)

    def _add_app_dialog(self):
        name = simpledialog.askstring("App name", "Display name:", parent=self)
        if not name:
            return
        wid = simpledialog.askstring("Winget ID", "Exact winget package ID (e.g. Google.Chrome):", parent=self)
        if not wid:
            return
        category = simpledialog.askstring("Category", "Category (e.g. Browsers):", parent=self) or "Uncategorized"
        desc = simpledialog.askstring("Description", "Short description:", parent=self) or ""

        self.db.setdefault("categories", {}).setdefault(category, [])
        for existing in self.db["categories"][category]:
            if existing["id"] == wid:
                messagebox.showinfo("Already exists", f"{wid} is already in {category}.")
                return
        self.db["categories"][category].append({"name": name, "id": wid, "desc": desc})
        save_database(self.db)
        self._populate_tree()
        self._log(f"Added {name} ({wid}) to {category}.\n")

    def _reload_db(self):
        self.db = load_database()
        self._populate_tree()
        self._log("Database reloaded from apps.json.\n")

    def _install_checked(self):
        selected_ids = [wid for wid, var in self.check_vars.items() if var.get()]
        if not selected_ids:
            messagebox.showinfo("Nothing selected", "Check at least one app first.")
            return
        if not winget_available():
            messagebox.showerror("winget not found", "winget isn't available on this machine's PATH.")
            return
        threading.Thread(target=self._install_worker, args=(selected_ids,), daemon=True).start()

    def _install_worker(self, ids):
        for wid in ids:
            self._log(
                f"\n$ winget install --id {wid} -e --silent "
                f"--accept-source-agreements --accept-package-agreements\n"
            )
            try:
                proc = subprocess.Popen(
                    [
                        "winget", "install", "--id", wid, "-e", "--silent",
                        "--accept-source-agreements", "--accept-package-agreements",
                    ],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                for line in proc.stdout:
                    self._log(line)
                proc.wait()
                status = "OK" if proc.returncode == 0 else f"FAILED (code {proc.returncode})"
                self._log(f"--- {wid}: {status} ---\n")
            except Exception as e:
                self._log(f"--- {wid}: ERROR: {e} ---\n")

    def _run_custom_command(self):
        cmd = self.custom_cmd_var.get().strip()
        if not cmd:
            return
        threading.Thread(target=self._run_custom_worker, args=(cmd,), daemon=True).start()

    def _run_custom_worker(self, cmd):
        self._log(f"\n$ {cmd}\n")
        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                self._log(line)
            proc.wait()
            self._log(f"--- exit code {proc.returncode} ---\n")
        except Exception as e:
            self._log(f"--- ERROR: {e} ---\n")

    def _log(self, msg):
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, append)
