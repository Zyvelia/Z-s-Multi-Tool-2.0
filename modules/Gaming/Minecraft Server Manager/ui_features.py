"""Feature mixin for GameServerManagerModule — keeps ui.py from growing without bound."""

from __future__ import annotations

import shutil
import threading
import time
import webbrowser
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import psutil

from . import backend as mc
from . import server_files as sf
from .adapters import get_adapter
from .core.module_prefs import TERMINAL_SCHEMES, save_prefs, scheme_colors
from .adapters.games import normalize_terraria_world_file, resolve_terraria_world, terraria_client_worlds_dir
from .core.palworld_rcon import PalworldRconClient, PalworldRconError
from .dialogs import FileEditorDialog
from core import theme as t

_IP_MASK = "•" * 13


class GameServerFeaturesMixin:
    """Methods mixed into GameServerManagerModule."""

    # ------------------------------------------------------------------ init hook

    def _init_features(self) -> None:
        self._command_history: dict[str, deque[str]] = {}
        self._command_history_pos: dict[str, int] = {}
        self._console_search = ctk.StringVar(value="")
        self._files_subpath = "."
        self._backup_rows: list[dict] = []
        self._last_scheduled_backup: dict[str, float] = {}
        self._scroll_busy_until = 0.0
        self._monitor_cache: dict[str, str] = {}
        self._config_tab_server_id: str | None = None
        self._config_tab_cache_key: tuple | None = None
        self._config_status_ts = 0.0
        self._uptime_cache = ""
        self._console_deferred = False
        self._console_last_tag: dict[str, str] = {}
        self._rcon_player_rows: dict[str, dict] = {}
        self._rcon_last_poll = 0.0
        self._rcon_poll_busy = False

    def _invalidate_config_tab(self) -> None:
        self._config_tab_server_id = None
        self._config_tab_cache_key = None

    @staticmethod
    def _config_tab_key(srv: dict) -> tuple:
        return (srv["id"], srv.get("game_type"), srv.get("server_dir", ""))

    def _sync_active_tab(self) -> None:
        try:
            current = self.tabview.get()
            if current:
                self._active_tab = current
        except Exception:
            pass

    def _on_server_context_changed(self) -> None:
        """Reset tab caches and refresh all dashboard panels for the newly selected server."""
        self._sync_terraria_mode_from_folder()
        self._warn_terraria_mixed_folder()
        self._files_subpath = "."
        self._invalidate_config_tab()
        self._monitor_cache.clear()
        self._sync_active_tab()
        self._refresh_dashboard(full=True)

    def _warn_terraria_mixed_folder(
        self,
        srv: dict | None = None,
        *,
        force: bool = False,
    ) -> bool:
        """Show a popup when vanilla and tModLoader files share one folder."""
        from tkinter import messagebox

        from .adapters.games import terraria_install_warning

        srv = srv or self._current_server()
        if not srv or srv.get("game_type") != "terraria":
            return False

        server_dir = self._server_dir(srv)
        warning = terraria_install_warning(server_dir)
        key = str(server_dir.resolve()).lower()
        if not warning:
            self._terraria_mixed_warned.discard(key)
            return False
        if not force and key in self._terraria_mixed_warned:
            return True
        if not force:
            self._terraria_mixed_warned.add(key)
        messagebox.showwarning(
            "Mixed Terraria install",
            warning,
            parent=self.winfo_toplevel(),
        )
        return True

    def _sync_terraria_mode_from_folder(self, srv: dict | None = None) -> bool:
        """Align saved Terraria server type with files on disk."""
        srv = srv or self._current_server()
        if not srv or srv.get("game_type") != "terraria":
            return False
        from .adapters.games import sync_terraria_server_mode
        from .core.settings import align_terraria_server_folder

        changed, detected = sync_terraria_server_mode(
            self._server_dir(srv),
            srv.setdefault("config", {}),
        )
        folder_changed = align_terraria_server_folder(srv)
        if not changed and not folder_changed:
            return False
        self._persist()
        self._invalidate_config_tab()
        if changed:
            self._append_console_line(f"[Manager] Detected {detected} install — server type updated.")
        if folder_changed:
            self._append_console_line(
                f"[Manager] Server folder set to {srv.get('name', 'Terraria')} ({srv.get('server_dir')}). "
                "Use Install Server Files on Config if this folder is not set up yet.",
            )
        return True

    def _sync_all_terraria_modes_on_load(self) -> None:
        from pathlib import Path

        from .adapters.games import sync_terraria_server_mode
        from .core.settings import align_terraria_server_folder

        changed = False
        for srv in self.servers:
            if srv.get("game_type") != "terraria":
                continue
            folder = str(srv.get("server_dir", "")).strip()
            if not folder:
                continue
            did_change, _mode = sync_terraria_server_mode(
                Path(folder),
                srv.setdefault("config", {}),
            )
            changed = changed or did_change or align_terraria_server_folder(srv)
        if changed:
            self._persist()

    def _mark_scrolling(self, _event=None) -> None:
        self._scroll_busy_until = time.time() + 0.55

    def _is_scrolling(self) -> bool:
        return time.time() < self._scroll_busy_until

    def _bind_wheel_target(self, target) -> None:
        if target is None:
            return
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<B1-Motion>"):
            try:
                target.bind(seq, self._mark_scrolling, add="+")
            except Exception:
                pass

    def _hook_canvas_scroll(self, canvas) -> None:
        if canvas is None or getattr(canvas, "_gsm_scroll_hooked", False):
            return
        try:
            orig = canvas.cget("yscrollcommand")

            def _wrapped(first, last, _orig=orig):
                self._mark_scrolling()
                if callable(_orig):
                    _orig(first, last)
                elif _orig:
                    canvas.tk.call(_orig, first, last)

            canvas.configure(yscrollcommand=_wrapped)
            canvas._gsm_scroll_hooked = True
        except Exception:
            pass

    def _bind_scroll_children(self, parent) -> None:
        stack = [parent]
        seen: set[str] = set()
        while stack:
            widget = stack.pop()
            wid = str(widget)
            if wid in seen:
                continue
            seen.add(wid)
            self._bind_wheel_target(widget)
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                pass

    def _bind_scroll_pause(self, widget) -> None:
        self._bind_wheel_target(widget)
        canvas = getattr(widget, "_parent_canvas", None)
        inner = getattr(widget, "_scrollable_frame", None)
        self._bind_wheel_target(canvas)
        self._bind_wheel_target(inner)
        self._bind_wheel_target(getattr(widget, "_scrollbar", None))
        self._hook_canvas_scroll(canvas)

        def _bind_descendants() -> None:
            if inner is not None:
                self._bind_scroll_children(inner)
            elif widget is not None:
                self._bind_scroll_children(widget)

        try:
            widget.after_idle(_bind_descendants)
        except Exception:
            _bind_descendants()

    # ------------------------------------------------------------------ terminal scheme

    def _console_tk_text(self):
        """CustomTkinter CTkTextbox tag colors must be set on the inner tk Text widget."""
        return getattr(self.console_box, "_textbox", self.console_box)

    def _configure_console_tags(self, colors: dict[str, str] | None = None) -> None:
        if not hasattr(self, "console_box"):
            return
        if colors is None:
            scheme = self._module_prefs.get("terminal_scheme", "default")
            colors = scheme_colors(scheme)
        tk_text = self._console_tk_text()
        try:
            for tag, color in colors.items():
                tk_text.tag_config(tag, foreground=color)
            default = colors.get("log_default", "#b0b8c8")
            self.console_box.configure(text_color=default)
        except Exception:
            pass

    def _apply_terminal_scheme(self) -> None:
        if not hasattr(self, "console_box"):
            return
        self._configure_console_tags()
        if self._selected_id:
            self._render_console_from_buffer()

    def _on_terminal_scheme_changed(self, label: str) -> None:
        key = label.lower().replace(" ", "_")
        if key not in TERMINAL_SCHEMES:
            key = "default"
        self._module_prefs["terminal_scheme"] = key
        save_prefs(self._module_prefs)
        self._apply_terminal_scheme()

    # ------------------------------------------------------------------ console buffer

    def _render_console_from_buffer(self) -> None:
        if not self._selected_id:
            return
        query = self._console_search.get().strip().lower()
        self.console_box.configure(state="normal")
        self.console_box.delete("1.0", "end")
        count = 0
        prev_tag: str | None = None
        for line, _stored_tag in self._console_buffer.lines(self._selected_id):
            if query and query not in line.lower():
                continue
            tag = self._line_tag(line, prev_tag)
            if line.strip() and tag != "log_default":
                prev_tag = tag
            self.console_box.insert("end", line + "\n", tag)
            count += 1
        self._console_lines = count
        if self._autoscroll.get():
            self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def _on_console_search_changed(self, *_args) -> None:
        self._render_console_from_buffer()

    def _record_console_line(self, server_id: str, line: str, tag: str) -> None:
        self._console_buffer.append(server_id, line, tag)

    def _clear_console_for_server(self, server_id: str | None = None) -> None:
        sid = server_id or self._selected_id
        if sid:
            self._console_buffer.clear(sid)
            self._console_last_tag.pop(sid, None)
        if sid == self._selected_id:
            self.console_box.configure(state="normal")
            self.console_box.delete("1.0", "end")
            self._console_lines = 0
            self.console_box.configure(state="disabled")

    # ------------------------------------------------------------------ command history

    def _history_for_server(self, server_id: str) -> deque[str]:
        if server_id not in self._command_history:
            self._command_history[server_id] = deque(maxlen=50)
            self._command_history_pos[server_id] = -1
        return self._command_history[server_id]

    def _push_command_history(self, cmd: str) -> None:
        if not self._selected_id or not cmd.strip():
            return
        hist = self._history_for_server(self._selected_id)
        if not hist or hist[-1] != cmd:
            hist.append(cmd)
        self._command_history_pos[self._selected_id] = len(hist)

    def _on_command_history_key(self, event) -> str | None:
        if not self._selected_id:
            return None
        hist = self._history_for_server(self._selected_id)
        if not hist:
            return None
        pos = self._command_history_pos.get(self._selected_id, len(hist))
        if event.keysym == "Up":
            pos = max(0, pos - 1)
            self._command_history_pos[self._selected_id] = pos
            self.command_entry.delete(0, "end")
            self.command_entry.insert(0, hist[pos])
            return "break"
        if event.keysym == "Down":
            if pos >= len(hist) - 1:
                self._command_history_pos[self._selected_id] = len(hist)
                self.command_entry.delete(0, "end")
            else:
                pos += 1
                self._command_history_pos[self._selected_id] = pos
                self.command_entry.delete(0, "end")
                self.command_entry.insert(0, hist[pos])
            return "break"
        return None

    # ------------------------------------------------------------------ addresses

    def _copy_lan_address(self) -> None:
        if self._lan_ip and self._ip_visible.get():
            self.clipboard_clear()
            self.clipboard_append(f"{self._lan_ip}:{self._port()}")

    def _update_lan_display(self) -> None:
        self._lan_ip = sf.get_lan_ip()
        port = self._port()
        if self._lan_ip:
            if self._ip_visible.get():
                self.lan_label.configure(text=f"{self._lan_ip}:{port}", text_color=t.SUCCESS)
                self.lan_copy_btn.configure(state="normal")
            else:
                self.lan_label.configure(text=f"{_IP_MASK}:{port}", text_color=t.TEXT)
                self.lan_copy_btn.configure(state="disabled")
        else:
            self.lan_label.configure(text="LAN unavailable", text_color=t.MUTED)
            self.lan_copy_btn.configure(state="disabled")

    # ------------------------------------------------------------------ overview monitoring

    def _update_monitoring(self) -> None:
        if self._is_scrolling():
            return
        srv = self._current_server()
        if not srv:
            return
        proc = self._process(srv["id"])
        if not proc.running:
            idle = (
                ("cpu", self.monitor_cpu_label, "CPU: —"),
                ("mem", self.monitor_mem_label, "RAM: —"),
                ("size", self.monitor_size_label, "Folder: —"),
                ("disk", self.monitor_disk_label, "Disk free: —"),
            )
            for key, label, text in idle:
                if self._monitor_cache.get(key) != text:
                    self._monitor_cache[key] = text
                    label.configure(text=text)
            return

        root = self._server_dir(srv)
        size = sf.folder_size(root)
        size_text = f"Folder: {_human_size(size)}"
        if self._monitor_cache.get("size") != size_text:
            self._monitor_cache["size"] = size_text
            self.monitor_size_label.configure(text=size_text)

        mem_text = "RAM: —"
        cpu_text = "CPU: —"
        if proc.proc and proc.proc.pid:
            try:
                p = psutil.Process(proc.proc.pid)
                mem_text = f"RAM: {_human_size(p.memory_info().rss)}"
                cpu_text = f"CPU: {p.cpu_percent(interval=None):.1f}%"
            except (psutil.Error, OSError):
                pass
        if self._monitor_cache.get("mem") != mem_text:
            self._monitor_cache["mem"] = mem_text
            self.monitor_mem_label.configure(text=mem_text)
        if self._monitor_cache.get("cpu") != cpu_text:
            self._monitor_cache["cpu"] = cpu_text
            self.monitor_cpu_label.configure(text=cpu_text)

        try:
            usage = shutil.disk_usage(root if root.exists() else root.anchor)
            disk_text = f"Disk free: {_human_size(usage.free)}"
        except OSError:
            disk_text = "Disk free: —"
        if self._monitor_cache.get("disk") != disk_text:
            self._monitor_cache["disk"] = disk_text
            self.monitor_disk_label.configure(text=disk_text)

    # ------------------------------------------------------------------ auto-start

    def _auto_start_servers(self) -> None:
        for srv in self.servers:
            if srv.get("config", {}).get("auto_start"):
                self._start_server_record(srv)

    def _start_server_record(self, srv: dict) -> None:
        adapter = get_adapter(srv["game_type"])
        if not adapter:
            return
        proc = self._process(srv["id"])
        if proc.running:
            return
        config = self._build_start_config(srv, adapter)
        error = proc.start(self._server_dir(srv), config, adapter)
        if error and srv["id"] == self._selected_id:
            self._append_console_line(f"[Manager] {error}")

    def _toggle_auto_start(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        cfg = srv.setdefault("config", {})
        cfg["auto_start"] = self.auto_start_var.get()
        self._persist()

    # ------------------------------------------------------------------ scheduled backups

    def _toggle_scheduled_backup(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        cfg = srv.setdefault("config", {})
        cfg["backup_enabled"] = self.backup_enabled_var.get()
        self._persist()

    def _save_backup_settings(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        cfg = srv.setdefault("config", {})
        try:
            cfg["backup_interval_hours"] = max(1, int(self.backup_interval_var.get()))
            cfg["backup_keep_count"] = max(1, int(self.backup_keep_var.get()))
        except ValueError:
            messagebox.showwarning("Backups", "Interval and keep count must be numbers.")
            return
        self._persist()
        messagebox.showinfo("Backups", "Scheduled backup settings saved.")

    def _check_scheduled_backups(self) -> None:
        now = time.time()
        for srv in self.servers:
            cfg = srv.get("config", {})
            if not cfg.get("backup_enabled"):
                continue
            proc = self._process(srv["id"])
            if not proc.running:
                continue
            interval = float(cfg.get("backup_interval_hours", 6)) * 3600
            last = float(cfg.get("last_backup_at", 0) or self._last_scheduled_backup.get(srv["id"], 0))
            if now - last < interval:
                continue
            self._create_backup_for_server(srv, silent=True)
            cfg["last_backup_at"] = now
            self._last_scheduled_backup[srv["id"]] = now
            self._persist()

    def _create_backup_for_server(self, srv: dict, silent: bool = False) -> None:
        root = Path(srv["server_dir"])
        if not root.exists():
            return
        dest_dir = root / "_backups"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = dest_dir / f"{srv['name'].replace(' ', '_')}_{stamp}.zip"

        def work():
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in root.rglob("*"):
                        if "_backups" in p.parts or not p.is_file():
                            continue
                        zf.write(p, p.relative_to(root))
                msg = f"Backup saved: {zip_path.name}"
                keep = int(srv.get("config", {}).get("backup_keep_count", 5))
                sf.prune_backups(dest_dir, keep)
            except OSError as e:
                msg = f"Backup failed: {e}"
            self.after(0, lambda: self._backup_done(msg, srv["id"]))

        if not silent and srv["id"] == self._selected_id:
            self._append_console_line("[Manager] Creating backup…")
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ backup restore / delete

    def _restore_backup(self, zip_path: Path) -> None:
        srv = self._current_server()
        if not srv:
            return
        proc = self._process(srv["id"])
        if proc.running:
            messagebox.showwarning("Restore", "Stop the server before restoring a backup.")
            return
        if not messagebox.askyesno(
            "Restore Backup",
            f"Restore from {zip_path.name}?\n\nThis overwrites files in the server folder.",
            icon="warning",
        ):
            return

        def work():
            try:
                sf.restore_backup_zip(self._server_dir(srv), zip_path)
                msg = f"Restored from {zip_path.name}"
            except OSError as e:
                msg = f"Restore failed: {e}"
            self.after(0, lambda: self._append_console_line(f"[Manager] {msg}"))

        threading.Thread(target=work, daemon=True).start()

    def _delete_backup(self, zip_path: Path) -> None:
        if not messagebox.askyesno("Delete Backup", f"Delete {zip_path.name}?", icon="warning"):
            return
        try:
            zip_path.unlink()
            self._refresh_backups()
        except OSError as e:
            messagebox.showerror("Delete failed", str(e))

    # ------------------------------------------------------------------ custom quick commands

    def _add_custom_quick_command(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        label = self.custom_cmd_label.get().strip()
        cmd = self.custom_cmd_text.get().strip()
        if not label or not cmd:
            messagebox.showwarning("Quick command", "Enter a button label and command.")
            return
        cfg = srv.setdefault("config", {})
        custom = list(cfg.get("custom_quick_commands", []))
        custom.append({"label": label, "cmd": cmd})
        cfg["custom_quick_commands"] = custom
        self._persist()
        self.custom_cmd_label.delete(0, "end")
        self.custom_cmd_text.delete(0, "end")
        self._rebuild_quick_commands()

    def _all_quick_commands(self) -> list[tuple[str, str]]:
        adapter = self._current_adapter()
        commands: list[tuple[str, str]] = list(adapter.quick_commands()) if adapter else []
        srv = self._current_server()
        if srv:
            for item in srv.get("config", {}).get("custom_quick_commands", []):
                if isinstance(item, dict) and item.get("label") and item.get("cmd"):
                    commands.append((item["label"], item["cmd"]))
        return commands

    # ------------------------------------------------------------------ whitelist / allowlist

    def _refresh_access_list(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        gt = srv["game_type"]
        for child in self.access_list_frame.winfo_children():
            child.destroy()
        if gt not in ("minecraft_java", "minecraft_bedrock"):
            ctk.CTkLabel(
                self.access_list_frame, text="Whitelist/allowlist is only available for Minecraft servers.",
                text_color=t.MUTED, font=t.font(11),
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return
        title = "Whitelist" if gt == "minecraft_java" else "Allowlist"
        names = sf.read_player_list(self._server_dir(srv), gt)
        if not names:
            ctk.CTkLabel(
                self.access_list_frame, text=f"No players on the {title.lower()} yet.",
                text_color=t.MUTED, font=t.font(11),
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        for i, name in enumerate(names):
            row = ctk.CTkFrame(self.access_list_frame, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=6, pady=2)
            ctk.CTkLabel(row, text=name, font=t.font(12), text_color=t.TEXT).pack(side="left")
            ctk.CTkButton(
                row, text="Remove", width=70, height=22, **t.danger_button_style(),
                command=lambda n=name: self._remove_access_name(n),
            ).pack(side="right")

    def _add_access_name(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        gt = srv["game_type"]
        if gt not in ("minecraft_java", "minecraft_bedrock"):
            return
        name = self.access_add_entry.get().strip()
        if not name:
            return
        sf.add_player_list_name(self._server_dir(srv), gt, name)
        reload_cmd = "whitelist reload" if gt == "minecraft_java" else "allowlist reload"
        if self._process(srv["id"]).running:
            self._process(srv["id"]).send(reload_cmd)
        self.access_add_entry.delete(0, "end")
        self._refresh_access_list()
        self._append_console_line(f"[Manager] Added {name} to {'whitelist' if gt == 'minecraft_java' else 'allowlist'}.")

    def _remove_access_name(self, name: str) -> None:
        srv = self._current_server()
        if not srv:
            return
        gt = srv["game_type"]
        sf.remove_player_list_name(self._server_dir(srv), gt, name)
        reload_cmd = "whitelist reload" if gt == "minecraft_java" else "allowlist reload"
        if self._process(srv["id"]).running:
            self._process(srv["id"]).send(reload_cmd)
        self._refresh_access_list()

    # ------------------------------------------------------------------ player session time

    def _format_session_time(self, seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m}m {s}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

    # ------------------------------------------------------------------ files editor / browse

    def _files_root(self) -> Path:
        srv = self._current_server()
        if not srv:
            return Path(".")
        root = self._server_dir(srv)
        sub = self._files_subpath.strip("/\\") or "."
        return (root / sub).resolve() if sub != "." else root.resolve()

    def _refresh_files_listing(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        self._refresh_terraria_world_panel()
        root = self._server_dir(srv)
        current = self._files_root()
        self.files_path_label.configure(text=str(current.relative_to(root)) if current != root else "/")

        lines = []
        if self._files_subpath not in (".", ""):
            lines.append("📁  ..")
        if current.exists():
            try:
                entries = sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError:
                entries = []
            for p in entries:
                icon = "📁" if p.is_dir() else "📄"
                try:
                    extra = f"  ({_human_size(p.stat().st_size)})" if p.is_file() else ""
                except OSError:
                    extra = ""
                lines.append(f"{icon}  {p.name}{extra}")
        else:
            lines.append("(folder does not exist)")
        self._files_listing = lines
        self._render_files_box()

    def _render_files_box(self) -> None:
        self.files_box.configure(state="normal")
        self.files_box.delete("1.0", "end")
        for line in self._files_listing:
            if line.startswith("📁"):
                tag = "folder"
            elif line.startswith("📄") and ".wld" in line.lower():
                tag = "world"
            elif line.startswith("📄"):
                tag = "file"
            else:
                tag = "muted"
            self.files_box.insert("end", line + "\n", tag)
        self.files_box.configure(state="disabled")

    def _on_files_double_click(self, _event=None) -> None:
        idx = self.files_box.index("insert").split(".")[0]
        try:
            line_no = int(idx) - 1
        except ValueError:
            return
        if line_no < 0 or line_no >= len(self._files_listing):
            return
        line = self._files_listing[line_no]
        name = line.split("  ", 1)[-1].split("  (")[0].strip()
        if name == "..":
            parent = Path(self._files_subpath).parent
            self._files_subpath = "." if str(parent) in (".", "") else str(parent).replace("\\", "/")
            self._refresh_files_listing()
            return
        if line.startswith("📁"):
            sub = Path(self._files_subpath)
            self._files_subpath = str(sub / name).replace("\\", "/")
            self._refresh_files_listing()
            return
        if line.startswith("📄"):
            path = self._files_root() / name
            if sf.is_editable_file(path):
                FileEditorDialog(self, path, on_saved=self._refresh_files_listing)

    def _edit_selected_file(self) -> None:
        idx = self.files_box.index("insert").split(".")[0]
        try:
            line_no = int(idx) - 1
        except ValueError:
            return
        if line_no < 0 or line_no >= len(self._files_listing):
            return
        line = self._files_listing[line_no]
        if not line.startswith("📄"):
            messagebox.showinfo("Edit file", "Select a file line to edit.")
            return
        name = line.split("  ", 1)[-1].split("  (")[0].strip()
        path = self._files_root() / name
        if not sf.is_editable_file(path):
            messagebox.showinfo("Edit file", "That file type isn't supported for in-app editing.")
            return
        FileEditorDialog(self, path, on_saved=self._refresh_files_listing)

    def _refresh_terraria_world_panel(self) -> None:
        if not hasattr(self, "terraria_world_panel"):
            return
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter or adapter.game_type != "terraria":
            self.terraria_world_panel.grid_remove()
            return
        self.terraria_world_panel.grid()
        server_dir = self._server_dir(srv)
        config = srv.setdefault("config", {})
        world_name = str(config.get("world_file", "world.wld"))
        world_path, resolved_name, discovered = resolve_terraria_world(server_dir, world_name)
        normalized_name = normalize_terraria_world_file(world_name)

        if resolved_name != normalized_name or world_name != resolved_name:
            config["world_file"] = resolved_name
            self._persist()
            if "world_file" in self._config_vars:
                self._config_vars["world_file"].set(resolved_name)
            world_name = resolved_name
            if hasattr(self, "_refresh_overview"):
                self._refresh_overview()

        if world_path is not None:
            self.terraria_world_status.configure(
                text=f"✅  {resolved_name} is ready in the server folder.",
                text_color=t.SUCCESS,
            )
        elif discovered:
            names = ", ".join(path.name for path in discovered)
            self.terraria_world_status.configure(
                text=(
                    f"⚠️  Config expects {Path(world_name).name}, but found: {names}. "
                    "Update world_file in Config or import/copy the correct file."
                ),
                text_color=t.ACCENT,
            )
        else:
            self.terraria_world_status.configure(
                text=(
                    f"⚠️  No .wld found in {server_dir}. "
                    "Import a world or copy one into this folder."
                ),
                text_color=t.ACCENT,
            )
        saves = terraria_client_worlds_dir()
        self.terraria_world_hint.configure(
            text=(
                "World file can be any name — the app auto-detects a single .wld in the server folder. "
                f"Default Terraria saves: {saves}"
            ),
        )

    def _import_terraria_world(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        saves = terraria_client_worlds_dir()
        chosen = filedialog.askopenfilename(
            title="Select Terraria world (.wld)",
            initialdir=str(saves if saves.is_dir() else self._server_dir(srv)),
            filetypes=[("Terraria world", "*.wld"), ("All files", "*.*")],
        )
        if not chosen:
            return
        src = Path(chosen)
        if src.suffix.lower() != ".wld":
            messagebox.showwarning("Import world", "Choose a Terraria world file (.wld).")
            return
        dest_dir = self._server_dir(srv)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            messagebox.showerror("Import world", f"Could not copy world file:\n{exc}")
            return
        srv.setdefault("config", {})["world_file"] = dest.name
        self._persist()
        if "world_file" in self._config_vars:
            self._config_vars["world_file"].set(dest.name)
        self._refresh_terraria_world_panel()
        self._refresh_files_listing()
        if hasattr(self, "_refresh_config_tab"):
            ok, msg = self._current_adapter().readiness_message(dest_dir, srv.get("config", {}))
            self.config_status.configure(
                text=f"{'✅' if ok else '⚠️'} {msg}",
                text_color=t.SUCCESS if ok else t.ACCENT,
            )

    def _open_terraria_client_worlds(self) -> None:
        path = terraria_client_worlds_dir()
        path.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(path))

    # ------------------------------------------------------------------ jar update check

    def _check_java_update(self) -> None:
        srv = self._current_server()
        if not srv or srv["game_type"] != "minecraft_java":
            return
        installed = srv.get("config", {}).get("installed_version", "")

        def work():
            versions, err = mc.list_versions()
            if err:
                self.after(0, lambda: self.update_status_label.configure(text=f"⚠️ {err}", text_color=t.DANGER))
                return
            releases = [v for v in versions if v.type == "release"]
            latest = releases[0].id if releases else ""
            if not latest:
                self.after(0, lambda: self.update_status_label.configure(text="Could not determine latest version.", text_color=t.MUTED))
                return
            if installed == latest:
                text = f"✅ Up to date ({latest})"
                color = t.SUCCESS
            else:
                text = f"Update available: {installed or 'unknown'} → {latest}"
                color = t.ACCENT
            self.after(0, lambda: self.update_status_label.configure(text=text, text_color=color))
            self._mc_versions = versions

        self.update_status_label.configure(text="Checking Mojang manifest…", text_color=t.MUTED)
        threading.Thread(target=work, daemon=True).start()

    def _apply_java_update(self) -> None:
        srv = self._current_server()
        if not srv or srv["game_type"] != "minecraft_java":
            return
        if self._process(srv["id"]).running:
            messagebox.showwarning("Update", "Stop the server before updating server.jar.")
            return
        if not self._mc_versions:
            self._check_java_update()
            messagebox.showinfo("Update", "Fetching version list — try again in a moment.")
            return
        releases = [v for v in self._mc_versions if v.type == "release"]
        if not releases:
            return
        latest = releases[0]
        if not messagebox.askyesno("Update server.jar", f"Download and install {latest.id}?", icon="question"):
            return
        self._mc_selected_version = latest
        self._start_mc_download()

    # ------------------------------------------------------------------ mod browser

    def _open_mod_browser(self, site: str) -> None:
        adapter = self._current_adapter()
        urls = adapter.mods_browser_urls() if adapter else {}
        if not urls:
            urls = {
                "modrinth": "https://modrinth.com/mods?q=minecraft",
                "curseforge": "https://www.curseforge.com/minecraft/mc-mods",
            }
        url = urls.get(site)
        if url:
            webbrowser.open(url)

    # ------------------------------------------------------------------ palworld settings editor

    def _edit_palworld_settings(self) -> None:
        from .adapters.palworld import ensure_settings_file
        from .dialogs import FileEditorDialog

        srv = self._current_server()
        if not srv:
            return
        path = ensure_settings_file(self._server_dir(srv))
        FileEditorDialog(self, path, on_saved=self._refresh_config_tab)

    # ------------------------------------------------------------------ palworld RCON admin

    def _palworld_rcon_ready(self) -> bool:
        from .adapters.palworld import palworld_rcon_ready

        srv = self._current_server()
        if not srv or srv.get("game_type") != "palworld":
            return False
        return palworld_rcon_ready(srv.get("config", {}))

    def _palworld_rcon_client(self) -> PalworldRconClient | None:
        from .adapters.palworld import palworld_rcon_client

        srv = self._current_server()
        if not srv or not self._palworld_rcon_ready():
            return None
        return palworld_rcon_client(srv.get("config", {}))

    def _refresh_rcon_panel(self) -> None:
        if not hasattr(self, "rcon_panel"):
            return
        active = self._palworld_rcon_ready()
        if active:
            self.rcon_panel.grid()
            self.players_frame.grid_remove()
            if hasattr(self, "access_panel"):
                self.access_panel.grid_remove()
            proc = self._process()
            if proc.running:
                self.rcon_status_label.configure(
                    text=f"RCON connected to 127.0.0.1:{self._current_server().get('config', {}).get('rcon_port', '25575')}",
                    text_color=t.SUCCESS,
                )
            else:
                self.rcon_status_label.configure(
                    text="Start the server to query players via RCON.",
                    text_color=t.MUTED,
                )
            self._refresh_rcon_players_async()
        else:
            self.rcon_panel.grid_remove()
            self.players_frame.grid()
            srv = self._current_server()
            adapter = self._current_adapter()
            if hasattr(self, "access_panel"):
                if srv and adapter and adapter.game_type == "palworld":
                    self.access_panel.grid_remove()
                else:
                    self.access_panel.grid()
            if srv and adapter and adapter.game_type == "palworld":
                self.rcon_status_label.configure(
                    text="Enable RCON and set an Admin password in Config.",
                    text_color=t.MUTED,
                )

    def _refresh_rcon_players_async(self) -> None:
        if self._rcon_poll_busy or not self._palworld_rcon_ready():
            return
        proc = self._process()
        if not proc.running:
            self._clear_rcon_player_rows()
            self.rcon_no_players_label.configure(text="Server is offline.")
            self.rcon_no_players_label.grid()
            return

        client = self._palworld_rcon_client()
        if client is None:
            return

        self._rcon_poll_busy = True

        def _worker() -> None:
            err = ""
            players = []
            try:
                players = client.show_players()
            except PalworldRconError as e:
                err = str(e)
            except OSError as e:
                err = f"RCON connection failed: {e}"
            self.after(0, lambda: self._apply_rcon_players(players, err))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_rcon_players(self, players, error: str) -> None:
        self._rcon_poll_busy = False
        if not self._palworld_rcon_ready() or self._active_tab != "Players":
            return
        if error:
            self.rcon_status_label.configure(text=error, text_color=t.DANGER)
            return

        self.rcon_status_label.configure(
            text=f"{len(players)} player(s) online via RCON",
            text_color=t.SUCCESS if players else t.MUTED,
        )

        seen = {p.steam_id for p in players}
        for sid in list(self._rcon_player_rows):
            if sid not in seen:
                row = self._rcon_player_rows.pop(sid)
                row["frame"].destroy()

        if not players:
            self.rcon_no_players_label.configure(text="No players online.")
            self.rcon_no_players_label.grid()
        else:
            self.rcon_no_players_label.grid_remove()
            for i, player in enumerate(players):
                if player.steam_id in self._rcon_player_rows:
                    widgets = self._rcon_player_rows[player.steam_id]
                    widgets["name"].configure(text=player.name)
                    widgets["meta"].configure(text=f"UID {player.player_uid}")
                    continue
                row = ctk.CTkFrame(self.rcon_players_frame, fg_color="transparent")
                row.grid(row=i + 1, column=0, sticky="ew", padx=8, pady=3)
                ctk.CTkLabel(row, text="●", font=t.font(10), text_color=t.SUCCESS, width=12).pack(side="left")
                name_lbl = ctk.CTkLabel(row, text=player.name, font=t.font(12), text_color=t.TEXT)
                name_lbl.pack(side="left", padx=(4, 8))
                meta = ctk.CTkLabel(row, text=f"UID {player.player_uid}", font=t.font(10), text_color=t.MUTED)
                meta.pack(side="left")
                ctk.CTkButton(
                    row, text="Kick", width=56, height=22, **t.danger_button_style(),
                    command=lambda sid=player.steam_id, n=player.name: self._rcon_kick_player(sid, n),
                ).pack(side="right")
                self._rcon_player_rows[player.steam_id] = {
                    "frame": row, "name": name_lbl, "meta": meta,
                }

        self.players_header.configure(
            text=f"Players Online ({len(players)})" if players else "Players Online",
        )

    def _clear_rcon_player_rows(self) -> None:
        for widgets in self._rcon_player_rows.values():
            widgets["frame"].destroy()
        self._rcon_player_rows.clear()

    def _rcon_kick_player(self, steam_id: str, name: str) -> None:
        client = self._palworld_rcon_client()
        if not client:
            return

        def _worker() -> None:
            try:
                client.kick_player(steam_id)
                msg = f"[Manager] Kicked {name} via RCON."
            except (PalworldRconError, OSError) as e:
                msg = f"[Manager] RCON kick failed: {e}"
            self.after(0, lambda: (self._append_console_line(msg), self._refresh_rcon_players_async()))

        threading.Thread(target=_worker, daemon=True).start()

    def _rcon_broadcast(self) -> None:
        text = self.rcon_broadcast_entry.get().strip()
        if not text:
            return
        client = self._palworld_rcon_client()
        if not client:
            return

        def _worker() -> None:
            try:
                client.broadcast(text)
                msg = f"[Manager] Broadcast sent: {text}"
            except (PalworldRconError, OSError) as e:
                msg = f"[Manager] RCON broadcast failed: {e}"
            self.after(0, lambda: (self._append_console_line(msg), self.rcon_broadcast_entry.delete(0, "end")))

        threading.Thread(target=_worker, daemon=True).start()

    def _rcon_send_command(self) -> None:
        text = self.rcon_cmd_entry.get().strip()
        if not text:
            return
        client = self._palworld_rcon_client()
        if not client:
            return

        def _worker() -> None:
            try:
                result = client.execute(text)
                msg = f"[RCON] {result.strip()}" if result.strip() else f"[RCON] > {text} (ok)"
            except (PalworldRconError, OSError) as e:
                msg = f"[Manager] RCON failed: {e}"
            self.after(0, lambda: (
                self._append_console_line(msg),
                self.rcon_cmd_entry.delete(0, "end"),
            ))

        threading.Thread(target=_worker, daemon=True).start()

    def _confirm_palworld_save(self, running: bool) -> bool:
        if self._module_prefs.get("palworld_save_hint_dismissed"):
            return True
        from .dialogs import PalworldSaveHintDialog

        dlg = PalworldSaveHintDialog(self, running=running)
        self.wait_window(dlg)
        if dlg.dismiss_forever:
            self._module_prefs["palworld_save_hint_dismissed"] = True
            save_prefs(self._module_prefs)
        return dlg.proceed

    # ------------------------------------------------------------------ import server

    def _open_import_wizard(self) -> None:
        self._open_add_wizard(import_mode=True)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"
