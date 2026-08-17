# modules/AI/local_model_runner/ui.py
#
# Front-end for locally-running models (Ollama / llama.cpp / any
# OpenAI-compatible local server) — no API key, no internet required.
# Separate module from "AI Chat" (modules/AI/AI Chat) on purpose: that
# one is built around a hosted, key-authenticated provider and mixing
# the two concerns would complicate both.

import queue
import threading
from datetime import datetime

import customtkinter as ctk

from core import theme
from . import backend, storage
from .backend import ChatMessage, LocalModelError


class LocalModelRunnerUI(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager

        self.settings = storage.load_settings()
        self.history = []
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self.is_busy = False

        self._build_ui()
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

        self.refresh_btn = ctk.CTkButton(
            row, text="⟳ Refresh", width=100, height=32,
            command=self.refresh_models, **theme.secondary_button_style()
        )
        self.refresh_btn.grid(row=1, column=0, pady=(8, 0), sticky="w")

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

        ctk.CTkButton(
            panel, text="New Chat", width=100, height=36,
            command=self._on_new_chat, **theme.secondary_button_style()
        ).grid(row=0, column=3, padx=3)

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

    def _save_settings(self):
        model = self.model_menu.get()
        storage.save_settings({
            "backend": self._current_backend(),
            "base_url": self._current_base_url(),
            "model": model if model != "(click Refresh)" else "",
            "system_prompt": "",
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
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        finally:
            self.after(80, self._poll_queue)

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
            models = backend.list_models(base_url, current_backend)
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

        self.stop_event = threading.Event()
        self._set_busy(True)
        threading.Thread(target=self._task_stream_chat, args=(model,), daemon=True).start()

    def _task_stream_chat(self, model):
        self.msg_queue.put(("line", (f"[{self._timestamp()}] AI:", "ai")))
        base_url = self._current_base_url()
        current_backend = self._current_backend()

        try:
            def on_delta(chunk):
                self.msg_queue.put(("inline", (chunk, "ai")))

            full_text = backend.stream_chat(
                base_url, current_backend, model,
                list(self.history), on_delta, self.stop_event,
            )
            self.msg_queue.put(("inline", ("\n", "ai")))
            if full_text:
                self.history.append(ChatMessage(role="assistant", content=full_text))
            if self.stop_event.is_set():
                self.msg_queue.put(("line", ("(generation stopped)", "system")))
        except LocalModelError as e:
            self.msg_queue.put(("line", (f"Error: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _on_stop_clicked(self):
        self.stop_event.set()
        self._append_line("Stopping generation...", "system")

    def _on_new_chat(self):
        if self.is_busy:
            self.stop_event.set()
        self.history.clear()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._append_line("New chat started. History cleared.", "system")
