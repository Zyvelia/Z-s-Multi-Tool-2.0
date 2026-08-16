"""
page.py
CustomTkinter GUI page for the AI Terminal module.

Integrates client.py (API logic), builder.py (AI project builder),
commands.py (slash-command routing) and security.py (memory-only key
handling, safe path checks) into a single embeddable page/frame that
fits into an existing Multi Tool app that switches between page frames.

Usage from your main app:

    from modules.ai_terminal.page import AITerminalPage

    page = AITerminalPage(master=content_container)
    page.pack(fill="both", expand=True)   # or .grid(...) per your app's convention

No API key is ever written to disk, logs, config files, or a database -
see security.InMemorySecret for details. The key only ever lives in a
CTkEntry widget and an InMemorySecret instance for the life of the process.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from datetime import datetime
from tkinter import filedialog
from typing import List

import customtkinter as ctk

from .client import AIClient, AIClientConfig, ChatMessage, AIClientError, DEFAULT_BASE_URL, DEFAULT_MODEL
from .builder import AIProjectBuilder, BuildError
from .commands import parse, CommandRouter, HELP_TEXT
from .security import InMemorySecret

try:
    # Optional: lets the chosen output folder persist across restarts via
    # the app's normal %APPDATA%\ZsMultiTool\... settings location. Not a
    # hard dependency - this module still works standalone (falling back
    # to an in-memory-only setting) if core.paths isn't importable for
    # whatever reason.
    from core import paths as app_paths
except Exception:  # noqa: BLE001
    app_paths = None

# AI_Projects lives at the application root, two levels above this file:
# modules/ai_terminal/page.py -> modules/ai_terminal -> modules -> app root
_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_PROJECTS_ROOT = os.path.join(_APP_ROOT, "AI_Projects")

# -- terminal color palette (dark theme) -------------------------------------
COLOR_BG = "#0d1117"
COLOR_PANEL = "#161b22"
COLOR_BORDER = "#30363d"
COLOR_TEXT = "#c9d1d9"
COLOR_USER = "#58a6ff"
COLOR_AI = "#3fb950"
COLOR_SYSTEM = "#8b949e"
COLOR_ERROR = "#f85149"
COLOR_BUILD = "#d29922"
COLOR_ACCENT = "#238636"
COLOR_ACCENT_HOVER = "#2ea043"
COLOR_DANGER = "#da3633"
COLOR_DANGER_HOVER = "#f85149"
COLOR_NEUTRAL = "#21262d"
COLOR_NEUTRAL_HOVER = "#3a4048"


class AITerminalModule(ctk.CTkFrame):
    """
    AI Terminal plugin module for the Mega Multi Tool.

    Constructed the same way as the app's other plugin modules:
        AITerminalModule(manager.container, manager)

    `container` is used as the CTkFrame's master/parent.
    `manager` is the plugin manager / app instance and is kept on
    self.manager in case other parts of the app (theme, navigation,
    shared settings, logging) need to be reached later - this module
    does not assume anything about its API beyond `.container`.
    """

    def __init__(self, container, manager=None, projects_root: str = DEFAULT_PROJECTS_ROOT, **kwargs):
        super().__init__(container, fg_color=COLOR_BG, **kwargs)
        self.manager = manager

        self._settings_path = (
            app_paths.data_path("ai_terminal", "settings.json") if app_paths else None
        )
        saved_root = self._load_output_folder_setting()

        self.client = AIClient(AIClientConfig(base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL))
        self.builder = AIProjectBuilder(self.client, saved_root or projects_root)
        self.last_project_dir: str | None = None

        self.history: List[ChatMessage] = []
        self.stop_event = threading.Event()
        self.msg_queue: "queue.Queue[tuple]" = queue.Queue()
        self.is_busy = False

        self.router = CommandRouter()
        self._register_commands()

        self._build_ui()
        self._poll_queue()

    # -------------------------------------------------------- settings

    def _load_output_folder_setting(self) -> str | None:
        if not self._settings_path or not os.path.exists(self._settings_path):
            return None
        try:
            with open(self._settings_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            root = data.get("projects_root")
            return root if root and isinstance(root, str) else None
        except Exception:
            return None

    def _save_output_folder_setting(self, projects_root: str) -> None:
        if not self._settings_path:
            return
        try:
            with open(self._settings_path, "w", encoding="utf-8") as fh:
                json.dump({"projects_root": projects_root}, fh, indent=2)
        except Exception as e:
            self._append_line(f"Could not save output folder setting: {e}", "error")

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_config_panel()
        self._build_output_settings_panel()
        self._build_output_panel()
        self._build_input_panel()

    def _build_config_panel(self) -> None:
        panel = ctk.CTkFrame(
            self, fg_color=COLOR_PANEL, corner_radius=8, border_width=1, border_color=COLOR_BORDER
        )
        panel.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        for col in range(8):
            panel.grid_columnconfigure(col, weight=1 if col in (1, 3, 6) else 0)

        ctk.CTkLabel(panel, text="Provider:", text_color=COLOR_TEXT).grid(
            row=0, column=0, padx=(10, 4), pady=10, sticky="w"
        )
        self.provider_entry = ctk.CTkEntry(panel, placeholder_text=DEFAULT_BASE_URL)
        self.provider_entry.insert(0, DEFAULT_BASE_URL)
        self.provider_entry.grid(row=0, column=1, padx=4, pady=10, sticky="ew")

        ctk.CTkLabel(panel, text="API Key:", text_color=COLOR_TEXT).grid(
            row=0, column=2, padx=(10, 4), pady=10, sticky="w"
        )
        self.key_entry = ctk.CTkEntry(panel, placeholder_text="sk-...", show="\u2022")
        self.key_entry.grid(row=0, column=3, padx=4, pady=10, sticky="ew")

        self.show_key_var = ctk.BooleanVar(value=False)
        self.show_key_btn = ctk.CTkButton(
            panel, text="Show", width=60, fg_color=COLOR_NEUTRAL, hover_color=COLOR_NEUTRAL_HOVER,
            command=self._toggle_key_visibility,
        )
        self.show_key_btn.grid(row=0, column=4, padx=4, pady=10)

        ctk.CTkLabel(panel, text="Model:", text_color=COLOR_TEXT).grid(
            row=0, column=5, padx=(10, 4), pady=10, sticky="w"
        )
        self.model_entry = ctk.CTkEntry(panel, placeholder_text=DEFAULT_MODEL)
        self.model_entry.insert(0, DEFAULT_MODEL)
        self.model_entry.grid(row=0, column=6, padx=4, pady=10, sticky="ew")

        self.connect_btn = ctk.CTkButton(
            panel, text="Connect / Test", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            command=self._on_connect_clicked,
        )
        self.connect_btn.grid(row=0, column=7, padx=10, pady=10)

        self.status_label = ctk.CTkLabel(panel, text="\u25cf Not connected", text_color=COLOR_ERROR, anchor="w")
        self.status_label.grid(row=1, column=0, columnspan=8, padx=10, pady=(0, 8), sticky="w")

    def _build_output_settings_panel(self) -> None:
        """Where /build writes projects, plus quick access to it - so you
        don't have to dig into a temp/AppData folder by hand to see what
        got generated."""
        panel = ctk.CTkFrame(
            self, fg_color=COLOR_PANEL, corner_radius=8, border_width=1, border_color=COLOR_BORDER
        )
        panel.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Output Folder:", text_color=COLOR_TEXT).grid(
            row=0, column=0, padx=(10, 4), pady=8, sticky="w"
        )

        self.output_folder_entry = ctk.CTkEntry(panel)
        self.output_folder_entry.insert(0, self.builder.projects_root)
        self.output_folder_entry.grid(row=0, column=1, padx=4, pady=8, sticky="ew")

        ctk.CTkButton(
            panel, text="Browse...", width=90, fg_color=COLOR_NEUTRAL, hover_color=COLOR_NEUTRAL_HOVER,
            command=self._on_browse_output_folder,
        ).grid(row=0, column=2, padx=3, pady=8)

        ctk.CTkButton(
            panel, text="Apply", width=70, fg_color=COLOR_NEUTRAL, hover_color=COLOR_NEUTRAL_HOVER,
            command=self._on_apply_output_folder,
        ).grid(row=0, column=3, padx=3, pady=8)

        ctk.CTkButton(
            panel, text="Open Folder", width=100, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            command=self._on_open_output_folder,
        ).grid(row=0, column=4, padx=(3, 10), pady=8)

    def _build_output_panel(self) -> None:
        outer = ctk.CTkFrame(
            self, fg_color=COLOR_PANEL, corner_radius=8, border_width=1, border_color=COLOR_BORDER
        )
        outer.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self.output = ctk.CTkTextbox(
            outer, fg_color=COLOR_BG, text_color=COLOR_TEXT,
            font=ctk.CTkFont(family="Consolas", size=13),
            wrap="word", activate_scrollbars=True,
        )
        self.output.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.output.configure(state="disabled")

        self._configure_tags()
        self._append_line(
            "AI Terminal ready. Type /help for commands, or just start chatting.", "system"
        )

    def _configure_tags(self) -> None:
        """Best-effort colored tags on the underlying tkinter Text widget."""
        try:
            tk_text = self.output._textbox  # customtkinter internal Text widget
            tk_text.tag_config("user", foreground=COLOR_USER)
            tk_text.tag_config("ai", foreground=COLOR_AI)
            tk_text.tag_config("system", foreground=COLOR_SYSTEM)
            tk_text.tag_config("error", foreground=COLOR_ERROR)
            tk_text.tag_config("build", foreground=COLOR_BUILD)
        except Exception:
            pass  # fall back to plain (default-colored) text if internals differ

    def _build_input_panel(self) -> None:
        panel = ctk.CTkFrame(self, fg_color="transparent")
        panel.grid(row=3, column=0, sticky="ew", padx=10, pady=(5, 10))
        panel.grid_columnconfigure(0, weight=1)

        self.input_entry = ctk.CTkEntry(
            panel, placeholder_text="Type a message or /command  (Enter to send)",
            font=ctk.CTkFont(family="Consolas", size=13),
        )
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.input_entry.bind("<Return>", lambda e: self._on_send_clicked())

        self.send_btn = ctk.CTkButton(
            panel, text="Send", width=80, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            command=self._on_send_clicked,
        )
        self.send_btn.grid(row=0, column=1, padx=3)

        self.stop_btn = ctk.CTkButton(
            panel, text="Stop", width=80, fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER,
            command=self._on_stop_clicked, state="disabled",
        )
        self.stop_btn.grid(row=0, column=2, padx=3)

        self.clear_btn = ctk.CTkButton(
            panel, text="Clear", width=80, fg_color=COLOR_NEUTRAL, hover_color=COLOR_NEUTRAL_HOVER,
            command=self._on_clear_clicked,
        )
        self.clear_btn.grid(row=0, column=3, padx=3)

        self.new_session_btn = ctk.CTkButton(
            panel, text="New Session", width=110, fg_color=COLOR_NEUTRAL, hover_color=COLOR_NEUTRAL_HOVER,
            command=self._on_new_session_clicked,
        )
        self.new_session_btn.grid(row=0, column=4, padx=(3, 0))

    # ------------------------------------------------------------- helpers

    def _toggle_key_visibility(self) -> None:
        showing = self.show_key_var.get()
        self.show_key_var.set(not showing)
        self.key_entry.configure(show="" if not showing else "\u2022")
        self.show_key_btn.configure(text="Hide" if not showing else "Show")

    def _append_line(self, text: str, tag: str = "system") -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text.rstrip("\n") + "\n", tag)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _append_inline(self, text: str, tag: str = "ai") -> None:
        """Append without forcing a newline first - used for streaming tokens."""
        self.output.configure(state="normal")
        self.output.insert("end", text, tag)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        state_send = "disabled" if busy else "normal"
        state_stop = "normal" if busy else "disabled"
        self.send_btn.configure(state=state_send)
        self.stop_btn.configure(state=state_stop)
        self.input_entry.configure(state=state_send)

    # -------------------------------------------------------- queue polling

    def _poll_queue(self) -> None:
        """
        Drains messages posted by background threads and applies them to
        the GUI on the main thread. This is the ONLY place background
        thread results are allowed to touch widgets.
        """
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "line":
                    text, tag = payload
                    self._append_line(text, tag)
                elif kind == "inline":
                    text, tag = payload
                    self._append_inline(text, tag)
                elif kind == "status":
                    text, color = payload
                    self.status_label.configure(text=text, text_color=color)
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        finally:
            self.after(80, self._poll_queue)

    # ------------------------------------------------------------- commands

    def _register_commands(self) -> None:
        self.router.register("help", self._cmd_help)
        self.router.register("clear", self._cmd_clear)
        self.router.register("new", self._cmd_new)
        self.router.register("build", self._cmd_build)
        self.router.register("models", self._cmd_models)
        self.router.register("test", self._cmd_test)
        self.router.register("output", self._cmd_output)
        self.router.register("openlast", self._cmd_openlast)

    def _cmd_help(self, _arg: str) -> None:
        self._append_line(HELP_TEXT, "system")

    def _cmd_clear(self, _arg: str) -> None:
        self._on_clear_clicked()

    def _cmd_new(self, _arg: str) -> None:
        self._on_new_session_clicked()

    def _cmd_build(self, arg: str) -> None:
        if not arg.strip():
            self._append_line("Usage: /build <description of the project to generate>", "error")
            return
        self._start_build(arg.strip())

    def _cmd_models(self, _arg: str) -> None:
        self._start_background(self._task_list_models)

    def _cmd_test(self, _arg: str) -> None:
        self._start_background(self._task_test_connection)

    # -------------------------------------------------------- button events

    def _on_connect_clicked(self) -> None:
        base_url = self.provider_entry.get().strip() or DEFAULT_BASE_URL
        api_key = self.key_entry.get().strip()
        model = self.model_entry.get().strip() or DEFAULT_MODEL

        if not api_key:
            self._append_line("Enter an API key before connecting.", "error")
            return

        # Key is handed straight to AIClient/InMemorySecret; never stored anywhere else.
        self.client.configure(base_url=base_url, api_key=api_key, model=model)
        self._append_line(f"[{self._timestamp()}] Configured provider={base_url}  model={model}", "system")
        self._start_background(self._task_test_connection)

    def _on_send_clicked(self) -> None:
        if self.is_busy:
            return
        text = self.input_entry.get().strip()
        if not text:
            return
        self.input_entry.delete(0, "end")

        command = parse(text)
        if command is not None:
            self._append_line(f"[{self._timestamp()}] > {text}", "user")
            handled = self.router.dispatch(command)
            if not handled:
                self._append_line(f"Unknown command: /{command.name}  (type /help for a list)", "error")
            return

        self._append_line(f"[{self._timestamp()}] You: {text}", "user")
        self._start_chat(text)

    def _on_browse_output_folder(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose AI Terminal output folder",
            initialdir=self.builder.projects_root if os.path.isdir(self.builder.projects_root) else _APP_ROOT,
        )
        if chosen:
            self.output_folder_entry.delete(0, "end")
            self.output_folder_entry.insert(0, chosen)
            self._on_apply_output_folder()

    def _on_apply_output_folder(self) -> None:
        new_root = self.output_folder_entry.get().strip()
        if not new_root:
            self._append_line("Output folder cannot be empty.", "error")
            return
        try:
            self.builder.set_projects_root(new_root)
        except Exception as e:
            self._append_line(f"Could not use that output folder: {e}", "error")
            return
        self.output_folder_entry.delete(0, "end")
        self.output_folder_entry.insert(0, self.builder.projects_root)
        self._save_output_folder_setting(self.builder.projects_root)
        self._append_line(f"Output folder set to: {self.builder.projects_root}", "system")

    def _on_open_output_folder(self) -> None:
        self._open_in_explorer(self.builder.projects_root, label="output folder")

    def _open_in_explorer(self, path: str, label: str) -> None:
        if not path or not os.path.isdir(path):
            self._append_line(f"Can't open {label} - folder doesn't exist yet: {path}", "error")
            return
        try:
            os.startfile(path)  # Windows-only, matches the rest of this app
        except Exception as e:
            self._append_line(f"Could not open {label}: {e}", "error")

    def _cmd_output(self, _arg: str) -> None:
        self._open_in_explorer(self.builder.projects_root, label="output folder")

    def _cmd_openlast(self, _arg: str) -> None:
        if not self.last_project_dir:
            self._append_line("No project has been built yet this session. Use /build first.", "error")
            return
        self._open_in_explorer(self.last_project_dir, label="last built project's folder")

    def _on_stop_clicked(self) -> None:
        self.stop_event.set()
        self._append_line("Stopping generation...", "system")

    def _on_clear_clicked(self) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._append_line("Terminal cleared. Conversation history preserved.", "system")

    def _on_new_session_clicked(self) -> None:
        self.history.clear()
        self.stop_event.set()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._append_line("New session started. Conversation history cleared.", "system")

    # --------------------------------------------------------- background ops

    def _start_background(self, target) -> None:
        if self.is_busy:
            self._append_line("Please wait for the current operation to finish.", "error")
            return
        self.stop_event = threading.Event()
        self._set_busy(True)
        threading.Thread(target=target, daemon=True).start()

    def _task_test_connection(self) -> None:
        try:
            if not self.client.has_key():
                raise AIClientError("No API key set.")
            result = self.client.test_connection()
            self.msg_queue.put(("status", ("\u25cf Connected", COLOR_AI)))
            self.msg_queue.put(("line", (result, "system")))
        except AIClientError as e:
            self.msg_queue.put(("status", ("\u25cf Connection failed", COLOR_ERROR)))
            self.msg_queue.put(("line", (f"Connection test failed: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _task_list_models(self) -> None:
        try:
            models = self.client.list_models()
            if models:
                listing = "\n".join(f"  - {m}" for m in models)
                self.msg_queue.put(("line", (f"Available models:\n{listing}", "system")))
            else:
                self.msg_queue.put(("line", ("Provider returned no models.", "system")))
        except AIClientError as e:
            self.msg_queue.put(("line", (f"Could not list models: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _start_chat(self, user_text: str) -> None:
        if self.is_busy:
            self._append_line("Please wait for the current response to finish.", "error")
            return
        if not self.client.has_key():
            self._append_line("No API key set. Enter a key and click Connect / Test first.", "error")
            return

        self.history.append(ChatMessage(role="user", content=user_text))
        self.stop_event = threading.Event()
        self._set_busy(True)
        threading.Thread(target=self._task_stream_chat, daemon=True).start()

    def _task_stream_chat(self) -> None:
        self.msg_queue.put(("line", (f"[{self._timestamp()}] AI:", "ai")))
        try:
            def on_delta(chunk: str) -> None:
                self.msg_queue.put(("inline", (chunk, "ai")))

            full_text = self.client.stream_chat(
                messages=list(self.history),
                on_delta=on_delta,
                stop_event=self.stop_event,
            )
            self.msg_queue.put(("inline", ("\n", "ai")))
            if full_text:
                self.history.append(ChatMessage(role="assistant", content=full_text))
            if self.stop_event.is_set():
                self.msg_queue.put(("line", ("(generation stopped)", "system")))
        except AIClientError as e:
            self.msg_queue.put(("line", (f"Error: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    # ------------------------------------------------------------- /build

    def _start_build(self, prompt: str) -> None:
        if self.is_busy:
            self._append_line("Please wait for the current operation to finish.", "error")
            return
        if not self.client.has_key():
            self._append_line("No API key set. Enter a key and click Connect / Test first.", "error")
            return

        self.stop_event = threading.Event()
        self._set_busy(True)
        self._append_line(f"[{self._timestamp()}] /build {prompt}", "build")
        threading.Thread(target=self._task_build, args=(prompt,), daemon=True).start()

    def _task_build(self, prompt: str) -> None:
        def progress(msg: str) -> None:
            self.msg_queue.put(("line", (msg, "build")))

        try:
            project_dir = self.builder.build(prompt, progress)
            self.last_project_dir = project_dir
        except BuildError as e:
            self.msg_queue.put(("line", (f"Build failed: {e}", "error")))
        except Exception as e:  # noqa: BLE001
            self.msg_queue.put(("line", (f"Unexpected build error: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))