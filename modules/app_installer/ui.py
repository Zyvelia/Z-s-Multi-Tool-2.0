import os
import json
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

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


class AppInstallerModule(tk.Frame):
    """
    Tkinter module for the plugin framework.
    Browses a shared apps.json database (kept in this same folder so it can
    be committed to git / shared with others) and installs apps via winget,
    or runs custom install commands.
    """

    def __init__(self, container, manager=None):
        super().__init__(container)
        self.manager = manager
        self.db = load_database()
        self.check_vars = {}      # winget id -> tk.BooleanVar
        self.entry_lookup = {}    # tree row id -> (winget id, category, app dict)

        self._build_ui()
        self._populate_tree()

        if not winget_available():
            self._log("⚠️  winget was not found on PATH. Installs will fail until it's available.\n")

    # ---------- UI construction ----------

    def _build_ui(self):
        self.pack(fill="both", expand=True)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_tree())
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=6)

        ttk.Button(top, text="Add App to DB", command=self._add_app_dialog).pack(side="left", padx=2)
        ttk.Button(top, text="Reload DB", command=self._reload_db).pack(side="left", padx=2)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        columns = ("selected", "name", "id", "category", "desc")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
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

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._toggle_selected_rows)

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", padx=8, pady=4)
        ttk.Button(action_frame, text="Install Checked", command=self._install_checked).pack(side="left")
        ttk.Button(action_frame, text="Check All Visible", command=lambda: self._set_all_visible(True)).pack(side="left", padx=4)
        ttk.Button(action_frame, text="Uncheck All", command=lambda: self._set_all_visible(False)).pack(side="left")

        custom_frame = ttk.LabelFrame(self, text="Run a custom install command")
        custom_frame.pack(fill="x", padx=8, pady=4)
        self.custom_cmd_var = tk.StringVar()
        ttk.Entry(custom_frame, textvariable=self.custom_cmd_var).pack(
            side="left", fill="x", expand=True, padx=(6, 4), pady=6
        )
        ttk.Button(custom_frame, text="Run", command=self._run_custom_command).pack(side="left", padx=(0, 6))

        log_frame = ttk.LabelFrame(self, text="Output")
        log_frame.pack(fill="both", expand=False, padx=8, pady=(4, 8))
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    # ---------- Data / tree ----------

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
            checked = self.check_vars.get(wid, tk.BooleanVar(value=False))
            self.check_vars[wid] = checked
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

    # ---------- Database editing ----------

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
        self._log(f"Added {name} ({wid}) to {category}. Commit apps.json to share it on GitHub.\n")

    def _reload_db(self):
        self.db = load_database()
        self._populate_tree()
        self._log("Database reloaded from apps.json.\n")

    # ---------- Installing ----------

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

    # ---------- Logging ----------

    def _log(self, msg):
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, append)