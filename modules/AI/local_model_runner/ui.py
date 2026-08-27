# modules/AI/local_model_runner/ui.py
#
# Front-end for locally-running models (Ollama / llama.cpp / any
# OpenAI-compatible local server) — no API key, no internet required.
# Separate module from "AI Chat" (modules/AI/AI Chat) on purpose: that
# one is built around a hosted, key-authenticated provider and mixing
# the two concerns would complicate both.

import queue
import re
import threading
import time
from datetime import datetime

import customtkinter as ctk

from core import theme
from . import backend, storage
from .backend import ChatMessage, GenOptions, LocalModelError


class LocalModelRunnerUI(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager

        self.settings = storage.load_settings()
        self.presets = storage.load_presets()
        self.history = []
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self.is_busy = False
        self.last_ai_response = ""

        self._build_ui()
        self._restore_history()
        self._poll_queue()
        self.after(200, self.refresh_models)

    # =====================================================
    # LAYOUT
    # =====================================================

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        ctk.CTkLabel(
            header, text="🖥️  Local Model Runner", font=theme.font(22, "bold"),
            text_color=theme.TEXT
        ).pack(side="left", padx=theme.PAD_LG, pady=14)

        self.status_label = ctk.CTkLabel(
            header, text="○ Not connected", font=theme.font(12, "bold"), text_color=theme.ERROR
        )
        self.status_label.pack(side="right", padx=(0, theme.PAD_LG), pady=14)

        self._build_config_panel()
        self._build_advanced_panel()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self._build_chat_panel(body)
        self._build_input_panel()

    def _build_config_panel(self):
        panel = ctk.CTkFrame(self, **theme.panel_style())
        panel.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD))

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=theme.PAD, pady=theme.PAD)
        row.grid_columnconfigure(2, weight=1)
        row.grid_columnconfigure(3, weight=1)

        backend_wrap = ctk.CTkFrame(row, fg_color="transparent")
        backend_wrap.grid(row=0, column=0, sticky="w", padx=(0, 10))
        ctk.CTkLabel(
            backend_wrap, text="Backend", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.backend_menu = ctk.CTkOptionMenu(
            backend_wrap, values=list(backend.BACKEND_LABELS.values()), width=210,
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.PANEL_HOVER, dropdown_fg_color=theme.PANEL,
            text_color=theme.TEXT, font=theme.font(12),
            command=self._on_backend_changed
        )
        self.backend_menu.set(backend.BACKEND_LABELS[self.settings["backend"]])
        self.backend_menu.pack()

        url_wrap = ctk.CTkFrame(row, fg_color="transparent")
        url_wrap.grid(row=0, column=1, sticky="w", padx=(0, 10))
        ctk.CTkLabel(
            url_wrap, text="Base URL", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.url_entry = ctk.CTkEntry(
            url_wrap, width=220, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
        )
        self.url_entry.insert(0, self.settings["base_url"])
        self.url_entry.pack()

        model_wrap = ctk.CTkFrame(row, fg_color="transparent")
        model_wrap.grid(row=0, column=2, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(
            model_wrap, text="Model", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.model_menu = ctk.CTkOptionMenu(
            model_wrap, values=["(click Refresh)"],
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.PANEL_HOVER, dropdown_fg_color=theme.PANEL,
            text_color=theme.TEXT, font=theme.font(12)
        )
        self.model_menu.pack(fill="x")

        btn_wrap = ctk.CTkFrame(row, fg_color="transparent")
        btn_wrap.grid(row=0, column=4, sticky="e")
        ctk.CTkLabel(btn_wrap, text=" ", font=theme.font(10)).pack(anchor="w")  # spacer to align with entries
        btn_row = ctk.CTkFrame(btn_wrap, fg_color="transparent")
        btn_row.pack()
        self.info_btn = ctk.CTkButton(
            btn_row, text="ℹ Info", width=65, height=28,
            command=self._on_info_clicked, **theme.secondary_button_style()
        )
        self.info_btn.pack(side="left", padx=(0, 4))
        self.unload_btn = ctk.CTkButton(
            btn_row, text="⏏ Unload", width=75, height=28,
            command=self._on_unload_clicked, **theme.secondary_button_style()
        )
        self.unload_btn.pack(side="left")

        self.refresh_btn = ctk.CTkButton(
            row, text="⟳ Refresh", width=100, height=32,
            command=self.refresh_models, **theme.secondary_button_style()
        )
        self.refresh_btn.grid(row=1, column=0, pady=(8, 0), sticky="w")

    def _build_advanced_panel(self):
        panel = ctk.CTkFrame(self, **theme.panel_style())
        panel.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=theme.PAD, pady=(theme.PAD, 4))
        ctk.CTkLabel(
            top, text="System prompt", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.system_prompt_entry = ctk.CTkEntry(
            top, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT,
            placeholder_text="Optional — sent as the system message every turn"
        )
        self.system_prompt_entry.insert(0, self.settings.get("system_prompt", ""))
        self.system_prompt_entry.pack(fill="x")

        preset_row = ctk.CTkFrame(panel, fg_color="transparent")
        preset_row.pack(fill="x", padx=theme.PAD, pady=(0, 4))
        ctk.CTkLabel(
            preset_row, text="Preset", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(side="left", padx=(0, 6))
        preset_names = list(self.presets.keys()) + ["Custom"]
        self.preset_menu = ctk.CTkOptionMenu(
            preset_row, values=preset_names, width=160,
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.PANEL_HOVER, dropdown_fg_color=theme.PANEL,
            text_color=theme.TEXT, font=theme.font(12),
            command=self._on_preset_selected
        )
        active = self.settings.get("active_preset", "Custom")
        self.preset_menu.set(active if active in self.presets else "Custom")
        self.preset_menu.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            preset_row, text="💾 Save", width=70, height=28,
            command=self._on_save_preset_clicked, **theme.secondary_button_style()
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            preset_row, text="🗑 Delete", width=75, height=28,
            command=self._on_delete_preset_clicked, **theme.secondary_button_style()
        ).pack(side="left")

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=theme.PAD, pady=(4, theme.PAD))

        def _param(col, label, key, width=80):
            wrap = ctk.CTkFrame(row, fg_color="transparent")
            wrap.grid(row=0, column=col, sticky="w", padx=(0, 10))
            ctk.CTkLabel(
                wrap, text=label, font=theme.font(10), text_color=theme.MUTED, anchor="w"
            ).pack(anchor="w")
            entry = ctk.CTkEntry(
                wrap, width=width, fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
            )
            entry.insert(0, str(self.settings.get(key, "")))
            entry.bind("<KeyRelease>", lambda e: self.preset_menu.set("Custom"))
            entry.pack()
            return entry

        self.temp_entry = _param(0, "Temperature", "temperature")
        self.top_p_entry = _param(1, "Top P", "top_p")
        self.num_predict_entry = _param(2, "Max tokens (-1=∞)", "num_predict")
        self.num_ctx_entry = _param(3, "Context size", "num_ctx")
        self.keep_alive_entry = _param(4, "Keep alive", "keep_alive", width=70)

    def _build_chat_panel(self, parent):
        outer = ctk.CTkFrame(parent, **theme.panel_style())
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self.output = ctk.CTkTextbox(
            outer, fg_color=theme.BG, text_color=theme.TEXT,
            font=theme.mono(13), wrap="word", activate_scrollbars=True
        )
        self.output.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.output.configure(state="disabled")
        self._configure_tags()
        self._append_line(
            "Ready. Pick a backend + model above, hit Refresh, then start chatting. "
            "Nothing here leaves your machine.", "system"
        )

    def _configure_tags(self):
        try:
            tk_text = self.output._textbox
            tk_text.tag_config("user", foreground="#58a6ff")
            tk_text.tag_config("ai", foreground=theme.ACCENT)
            tk_text.tag_config("system", foreground=theme.MUTED)
            tk_text.tag_config("error", foreground=theme.ERROR)
            tk_text.tag_config("bold", font=theme.font(13, "bold"))
            tk_text.tag_config("inline_code", foreground=theme.ACCENT, background=theme.PANEL_2)
            tk_text.tag_config("code_block", foreground=theme.TEXT, background=theme.PANEL_2, font=theme.mono(12))
        except Exception:
            pass

    def _build_input_panel(self):
        panel = ctk.CTkFrame(self, fg_color="transparent")
        panel.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        panel.grid_columnconfigure(0, weight=1)

        self.input_entry = ctk.CTkEntry(
            panel, placeholder_text="Message the local model... (Enter to send)",
            fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT,
            font=theme.font(13), height=36
        )
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.input_entry.bind("<Return>", lambda e: self._on_send_clicked())

        self.send_btn = ctk.CTkButton(
            panel, text="Send", width=90, height=36,
            command=self._on_send_clicked, **theme.primary_button_style()
        )
        self.send_btn.grid(row=0, column=1, padx=3)

        self.stop_btn = ctk.CTkButton(
            panel, text="Stop", width=80, height=36, state="disabled",
            command=self._on_stop_clicked, **theme.danger_button_style()
        )
        self.stop_btn.grid(row=0, column=2, padx=3)

        self.copy_btn = ctk.CTkButton(
            panel, text="Copy reply", width=100, height=36,
            command=self._on_copy_clicked, **theme.secondary_button_style()
        )
        self.copy_btn.grid(row=0, column=3, padx=3)

        ctk.CTkButton(
            panel, text="New Chat", width=100, height=36,
            command=self._on_new_chat, **theme.secondary_button_style()
        ).grid(row=0, column=4, padx=3)

    # =====================================================
    # SETTINGS HELPERS
    # =====================================================

    def _current_backend(self):
        label = self.backend_menu.get()
        for key, val in backend.BACKEND_LABELS.items():
            if val == label:
                return key
        return backend.BACKEND_OLLAMA

    def _current_base_url(self):
        return self.url_entry.get().strip() or backend.DEFAULT_URLS[self._current_backend()]

    def _on_backend_changed(self, _label):
        new_backend = self._current_backend()
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, backend.DEFAULT_URLS[new_backend])
        self.model_menu.configure(values=["(click Refresh)"])
        self.model_menu.set("(click Refresh)")

    def _current_gen_options(self) -> GenOptions:
        def _f(entry, cast, default=None):
            raw = entry.get().strip()
            if not raw:
                return default
            try:
                return cast(raw)
            except ValueError:
                return default

        return GenOptions(
            temperature=_f(self.temp_entry, float),
            top_p=_f(self.top_p_entry, float),
            num_predict=_f(self.num_predict_entry, int),
            num_ctx=_f(self.num_ctx_entry, int),
            keep_alive=self.keep_alive_entry.get().strip() or None,
        )

    def _save_settings(self):
        model = self.model_menu.get()
        opts = self._current_gen_options()
        storage.save_settings({
            "backend": self._current_backend(),
            "base_url": self._current_base_url(),
            "model": model if model != "(click Refresh)" else "",
            "system_prompt": self.system_prompt_entry.get().strip(),
            "temperature": opts.temperature,
            "top_p": opts.top_p,
            "num_predict": opts.num_predict,
            "num_ctx": opts.num_ctx,
            "keep_alive": opts.keep_alive,
        })

    # =====================================================
    # OUTPUT HELPERS
    # =====================================================

    def _append_line(self, text, tag="system"):
        self.output.configure(state="normal")
        self.output.insert("end", text.rstrip("\n") + "\n", tag)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _append_inline(self, text, tag="ai"):
        self.output.configure(state="normal")
        self.output.insert("end", text, tag)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _timestamp(self):
        return datetime.now().strftime("%H:%M:%S")

    _INLINE_PATTERN = re.compile(r'(`[^`]+`|\*\*[^*]+\*\*)')

    def _insert_inline_formatted(self, line, base_tag):
        parts = self._INLINE_PATTERN.split(line)
        for part in parts:
            if not part:
                continue
            if part.startswith("`") and part.endswith("`") and len(part) >= 2:
                self.output.insert("end", part[1:-1], "inline_code")
            elif part.startswith("**") and part.endswith("**") and len(part) >= 4:
                self.output.insert("end", part[2:-2], (base_tag, "bold"))
            else:
                self.output.insert("end", part, base_tag)

    def _insert_formatted(self, text, base_tag="ai"):
        """Renders a limited markdown subset — fenced code blocks, inline
        code, and **bold** — into the output box with matching tags."""
        self.output.configure(state="normal")
        lines = text.split("\n")
        in_code_block = False
        for idx, line in enumerate(lines):
            is_last = idx == len(lines) - 1
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                if not is_last:
                    self.output.insert("end", "\n")
                continue
            if in_code_block:
                self.output.insert("end", line + ("" if is_last else "\n"), "code_block")
                continue
            self._insert_inline_formatted(line, base_tag)
            if not is_last:
                self.output.insert("end", "\n", base_tag)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _set_busy(self, busy):
        self.is_busy = busy
        self.send_btn.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="normal" if busy else "disabled")
        self.input_entry.configure(state="disabled" if busy else "normal")

    def _poll_queue(self):
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
                elif kind == "models":
                    self._apply_models(payload)
                elif kind == "mark":
                    self.output._textbox.mark_set(payload, "end-1c")
                elif kind == "render_final":
                    mark_name, text = payload
                    self.output.configure(state="normal")
                    try:
                        self.output._textbox.delete(mark_name, "end")
                    except Exception:
                        pass
                    self.output.configure(state="disabled")
                    self._insert_formatted(text, base_tag="ai")
                    try:
                        self.output._textbox.mark_unset(mark_name)
                    except Exception:
                        pass
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        finally:
            self.after(80, self._poll_queue)

    # =====================================================
    # HISTORY PERSISTENCE
    # =====================================================

    def _restore_history(self):
        saved = storage.load_history()
        if not saved:
            return
        for m in saved:
            self.history.append(ChatMessage(role=m["role"], content=m["content"]))
            tag = "user" if m["role"] == "user" else "ai"
            prefix = "You: " if m["role"] == "user" else "AI: "
            self._append_line(prefix + m["content"], tag)
        self._append_line("— restored previous session —", "system")

    def _persist_history(self):
        storage.save_history(self.history)

    # =====================================================
    # MODEL REFRESH
    # =====================================================

    def refresh_models(self):
        if self.is_busy:
            return
        self._set_busy(True)
        self.msg_queue.put(("status", ("● Connecting…", theme.MUTED)))
        threading.Thread(target=self._task_refresh_models, daemon=True).start()

    def _task_refresh_models(self):
        base_url = self._current_base_url()
        current_backend = self._current_backend()
        try:
            try:
                models = backend.list_models(base_url, current_backend, timeout=3.0)
            except LocalModelError:
                # Nothing answered on the first try — if this is Ollama on
                # localhost, attempt to launch it ourselves before giving up.
                launched = backend.ensure_ollama_running(base_url, current_backend)
                if launched:
                    self.msg_queue.put(("status", ("● Starting Ollama…", theme.MUTED)))
                models = backend.list_models_with_retry(base_url, current_backend, attempts=3, delay=1.5)
            self.msg_queue.put(("status", (f"● Connected ({len(models)} model{'s' if len(models) != 1 else ''})", theme.SUCCESS)))
            self.msg_queue.put(("models", models))
        except LocalModelError as e:
            self.msg_queue.put(("status", ("○ Not connected", theme.ERROR)))
            self.msg_queue.put(("line", (str(e), "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _apply_models(self, models):
        if not models:
            self.model_menu.configure(values=["(no models found)"])
            self.model_menu.set("(no models found)")
            return
        self.model_menu.configure(values=models)
        preferred = self.settings.get("model")
        self.model_menu.set(preferred if preferred in models else models[0])

    # =====================================================
    # PRESETS
    # =====================================================

    def _set_param_entries(self, values: dict):
        def _set(entry, key):
            if key not in values:
                return
            entry.delete(0, "end")
            entry.insert(0, str(values[key]))

        _set(self.temp_entry, "temperature")
        _set(self.top_p_entry, "top_p")
        _set(self.num_predict_entry, "num_predict")
        _set(self.num_ctx_entry, "num_ctx")
        _set(self.keep_alive_entry, "keep_alive")

    def _refresh_preset_menu(self, select: str = None):
        names = list(self.presets.keys()) + ["Custom"]
        self.preset_menu.configure(values=names)
        if select:
            self.preset_menu.set(select)

    def _on_preset_selected(self, name):
        if name == "Custom" or name not in self.presets:
            return
        self._set_param_entries(self.presets[name])
        self._save_settings()

    def _on_save_preset_clicked(self):
        dialog = ctk.CTkInputDialog(text="Preset name:", title="Save preset")
        name = dialog.get_input()
        if not name:
            return
        name = name.strip()
        if not name:
            return
        opts = self._current_gen_options()
        self.presets[name] = {
            "temperature": opts.temperature,
            "top_p": opts.top_p,
            "num_predict": opts.num_predict,
            "num_ctx": opts.num_ctx,
            "keep_alive": opts.keep_alive,
        }
        storage.save_presets(self.presets)
        self._refresh_preset_menu(select=name)
        self._save_settings()
        self._append_line(f"Saved preset '{name}'.", "system")

    def _on_delete_preset_clicked(self):
        name = self.preset_menu.get()
        if name == "Custom" or name not in self.presets:
            return
        if len(self.presets) <= 1:
            self._append_line("Can't delete the last remaining preset.", "error")
            return
        del self.presets[name]
        storage.save_presets(self.presets)
        remaining = next(iter(self.presets))
        self._set_param_entries(self.presets[remaining])
        self._refresh_preset_menu(select=remaining)
        self._save_settings()
        self._append_line(f"Deleted preset '{name}'.", "system")

    # =====================================================
    # MODEL INFO
    # =====================================================

    def _on_info_clicked(self):
        if self.is_busy:
            return
        model = self.model_menu.get()
        if not model or model in ("(click Refresh)", "(no models found)"):
            self._append_line("Pick a model first.", "error")
            return
        self._set_busy(True)
        threading.Thread(target=self._task_model_info, args=(model,), daemon=True).start()

    def _task_model_info(self, model):
        base_url = self._current_base_url()
        current_backend = self._current_backend()
        try:
            info = backend.get_model_info(base_url, current_backend, model)
            if not info:
                self.msg_queue.put(("line", (f"No extra info available for {model} on this backend.", "system")))
            else:
                parts = ", ".join(f"{k}: {v}" for k, v in info.items())
                self.msg_queue.put(("line", (f"{model} — {parts}", "system")))
        except LocalModelError as e:
            self.msg_queue.put(("line", (str(e), "error")))
        finally:
            self.msg_queue.put(("done", None))

    # =====================================================
    # UNLOAD
    # =====================================================

    def _on_unload_clicked(self):
        if self.is_busy:
            return
        model = self.model_menu.get()
        if not model or model in ("(click Refresh)", "(no models found)"):
            self._append_line("Pick a model first.", "error")
            return
        if self._current_backend() != backend.BACKEND_OLLAMA:
            self._append_line("Unload is only supported for the Ollama backend.", "error")
            return
        self._set_busy(True)
        threading.Thread(target=self._task_unload, args=(model,), daemon=True).start()

    def _task_unload(self, model):
        base_url = self._current_base_url()
        current_backend = self._current_backend()
        try:
            backend.unload_model(base_url, current_backend, model)
            self.msg_queue.put(("line", (f"Unloaded {model} from memory.", "system")))
        except LocalModelError as e:
            self.msg_queue.put(("line", (str(e), "error")))
        finally:
            self.msg_queue.put(("done", None))

    # =====================================================
    # CHAT
    # =====================================================

    def _on_send_clicked(self):
        if self.is_busy:
            return
        text = self.input_entry.get().strip()
        if not text:
            return

        model = self.model_menu.get()
        if not model or model in ("(click Refresh)", "(no models found)"):
            self._append_line("Pick a model (click Refresh first) before sending.", "error")
            return

        self.input_entry.delete(0, "end")
        self._save_settings()

        self._append_line(f"[{self._timestamp()}] You: {text}", "user")
        self.history.append(ChatMessage(role="user", content=text))
        self._persist_history()

        self.stop_event = threading.Event()
        self._set_busy(True)
        mark_name = f"ai_msg_{threading.get_ident()}_{int(time.time() * 1000)}"
        threading.Thread(target=self._task_stream_chat, args=(model, mark_name), daemon=True).start()

    def _messages_for_request(self):
        system_prompt = self.system_prompt_entry.get().strip()
        if system_prompt:
            return [ChatMessage(role="system", content=system_prompt)] + list(self.history)
        return list(self.history)

    def _task_stream_chat(self, model, mark_name):
        self.msg_queue.put(("line", (f"[{self._timestamp()}] AI:", "ai")))
        self.msg_queue.put(("mark", mark_name))
        base_url = self._current_base_url()
        current_backend = self._current_backend()
        options = self._current_gen_options()

        try:
            def on_delta(chunk):
                self.msg_queue.put(("inline", (chunk, "ai")))

            full_text, stats = backend.stream_chat(
                base_url, current_backend, model,
                self._messages_for_request(), on_delta, self.stop_event,
                options=options,
            )
            if full_text:
                self.history.append(ChatMessage(role="assistant", content=full_text))
                self.last_ai_response = full_text
                self._persist_history()
                # Replace the raw streamed text with markdown-formatted output
                # (code blocks, inline code, bold) now that it's complete.
                self.msg_queue.put(("render_final", (mark_name, full_text)))
            else:
                self.msg_queue.put(("inline", ("\n", "ai")))
            if stats.tokens and stats.seconds:
                self.msg_queue.put((
                    "line",
                    (f"({stats.tokens} tokens, {stats.seconds:.1f}s, {stats.tokens_per_sec:.1f} tok/s)", "system")
                ))
            if self.stop_event.is_set():
                self.msg_queue.put(("line", ("(generation stopped)", "system")))
        except LocalModelError as e:
            self.msg_queue.put(("line", (f"Error: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _on_stop_clicked(self):
        self.stop_event.set()
        self._append_line("Stopping generation...", "system")

    def _on_copy_clicked(self):
        if not self.last_ai_response:
            self._append_line("Nothing to copy yet.", "error")
            return
        self.clipboard_clear()
        self.clipboard_append(self.last_ai_response)
        self._append_line("Copied last reply to clipboard.", "system")

    def _on_new_chat(self):
        if self.is_busy:
            self.stop_event.set()
        self.history.clear()
        self.last_ai_response = ""
        storage.clear_history()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._append_line("New chat started. History cleared.", "system")
