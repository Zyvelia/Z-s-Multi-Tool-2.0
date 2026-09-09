"""Qt AI Chat — hosted/local terminal + prompt library."""

from __future__ import annotations

import json
import os
import queue
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modules.AI.commands import HELP_TEXT, CommandRouter, parse
from modules.AI.agent_tools import ensure_registered
from modules.AI import session as ai_session
from modules.AI.local_model_runner import backend as local_backend
from modules.AI.local_model_runner import storage as local_storage
from modules.AI.prompt_library import storage as prompt_store

try:
    from modules.AI.client import (
        AIClient, AIClientConfig, ChatMessage, AIClientError, DEFAULT_BASE_URL, DEFAULT_MODEL,
    )
    from modules.AI.builder import AIProjectBuilder, BuildError
    _HOSTED_OK = True
    _HOSTED_ERR = None
except Exception as e:
    AIClient = AIClientConfig = ChatMessage = AIClientError = None
    DEFAULT_BASE_URL = DEFAULT_MODEL = ""
    AIProjectBuilder = BuildError = None
    _HOSTED_OK = False
    _HOSTED_ERR = str(e)

try:
    from core import paths as app_paths
except Exception:
    app_paths = None

_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PROJECTS_ROOT = os.path.join(_APP_ROOT, "AI_Projects")
SOURCE_HOSTED = "Hosted (API key)"
SOURCE_LOCAL = "Local (this PC)"
LOCAL_DUMMY_KEY = "local"

_COLORS = {
    "user": "#58a6ff",
    "ai": "#3fb950",
    "system": "#8b949e",
    "error": "#f85149",
    "build": "#d29922",
    "tool": "#d2a8ff",
}


class AIChatModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        tabs = QTabWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(tabs)
        if _HOSTED_OK:
            tabs.addTab(AITerminal(self, manager), "Chat")
        else:
            notice = QLabel(
                f"Hosted Chat is unavailable — the openai package didn't import.\n\n{_HOSTED_ERR}\n\n"
                "Run: pip install openai\nPrompt Library still works. Switch Chat on: Local if you only need Ollama."
            )
            notice.setWordWrap(True)
            notice.setObjectName("Muted")
            wrap = QWidget()
            QVBoxLayout(wrap).addWidget(notice)
            tabs.addTab(wrap, "Chat")
        tabs.addTab(PromptLibrary(self, manager), "Prompt Library")


class AITerminal(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._settings_path = (
            app_paths.data_path("ai_terminal", "settings.json") if app_paths else None
        )
        saved = self._load_settings()
        self._source = saved.get("source") or "hosted"
        self._local_cfg = local_storage.load_settings()
        self.client = AIClient(AIClientConfig(base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL))
        self.builder = AIProjectBuilder(self.client, saved.get("projects_root") or DEFAULT_PROJECTS_ROOT)
        self.last_project_dir = None
        self.history = []
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self.is_busy = False
        self.agent_enabled = True
        self.router = CommandRouter()
        self._register_commands()
        ensure_registered(self._plugin_manager())

        root = QVBoxLayout(self)
        src = QHBoxLayout()
        src.addWidget(QLabel("Chat on:"))
        self.source = QComboBox()
        self.source.addItems([SOURCE_HOSTED, SOURCE_LOCAL])
        self.source.setCurrentText(SOURCE_LOCAL if self._source == "local" else SOURCE_HOSTED)
        self.source.currentTextChanged.connect(self._on_source_changed)
        src.addWidget(self.source)
        src.addStretch(1)
        root.addLayout(src)

        self.hosted_row = QWidget()
        hr = QHBoxLayout(self.hosted_row)
        hr.setContentsMargins(0, 0, 0, 0)
        self.provider = QLineEdit(saved.get("hosted_base_url") or DEFAULT_BASE_URL)
        self.provider.setPlaceholderText("Provider URL")
        self.key = QLineEdit()
        self.key.setPlaceholderText("API key (memory only)")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit(saved.get("hosted_model") or DEFAULT_MODEL)
        self.model.setPlaceholderText("Model")
        hr.addWidget(self.provider, 2)
        hr.addWidget(self.key, 2)
        hr.addWidget(self.model, 1)
        root.addWidget(self.hosted_row)

        self.local_row = QWidget()
        lr = QHBoxLayout(self.local_row)
        lr.setContentsMargins(0, 0, 0, 0)
        self.local_backend = QComboBox()
        for key, label in local_backend.BACKEND_LABELS.items():
            self.local_backend.addItem(label, key)
        self.local_url = QLineEdit(self._local_cfg.get("base_url") or "")
        self.local_model = QComboBox()
        self.local_model.addItem("(Refresh)")
        self.refresh_local = QPushButton("Refresh models")
        self.refresh_local.clicked.connect(self._refresh_local_models)
        lr.addWidget(self.local_backend)
        lr.addWidget(self.local_url, 2)
        lr.addWidget(self.local_model, 1)
        lr.addWidget(self.refresh_local)
        root.addWidget(self.local_row)

        actions = QHBoxLayout()
        self.connect_btn = QPushButton("Connect / Test")
        self.connect_btn.clicked.connect(self._on_connect)
        self.status = QLabel("Idle")
        self.status.setObjectName("Muted")
        actions.addWidget(self.connect_btn)
        actions.addWidget(self.status)
        actions.addStretch(1)
        root.addLayout(actions)

        out_row = QHBoxLayout()
        self.output_folder = QLineEdit(self.builder.projects_root)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_output)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_output)
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(lambda: self._open_explorer(self.builder.projects_root, "output folder"))
        out_row.addWidget(QLabel("Projects"))
        out_row.addWidget(self.output_folder, 1)
        out_row.addWidget(browse)
        out_row.addWidget(apply_btn)
        out_row.addWidget(open_btn)
        root.addLayout(out_row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        root.addWidget(self.output, 1)

        inp = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Message or /help")
        self.input.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._on_send)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._on_clear)
        new = QPushButton("New session")
        new.clicked.connect(self._on_new)
        self.agent_box = QCheckBox("Agent")
        self.agent_box.setChecked(True)
        self.agent_box.toggled.connect(self._on_agent)
        inp.addWidget(self.input, 1)
        inp.addWidget(self.send_btn)
        inp.addWidget(self.stop_btn)
        inp.addWidget(clear)
        inp.addWidget(new)
        inp.addWidget(self.agent_box)
        root.addLayout(inp)

        self._apply_source_ui()
        self._poll = QTimer(self)
        self._poll.setInterval(80)
        self._poll.timeout.connect(self._poll_queue)
        self._poll.start()
        if self._is_local():
            QTimer.singleShot(300, self._refresh_local_models)

    def _plugin_manager(self):
        manager = self.manager
        if manager is None:
            return None
        container = getattr(manager, "container", None)
        if container is not None:
            pm = getattr(container, "plugin_manager", None)
            if pm is not None:
                return pm
        return getattr(manager, "plugin_manager", None)

    def _load_settings(self):
        if not self._settings_path or not os.path.exists(self._settings_path):
            return {}
        try:
            with open(self._settings_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_settings(self, **updates):
        if not self._settings_path:
            return
        data = self._load_settings()
        data.update(updates)
        try:
            os.makedirs(os.path.dirname(self._settings_path), exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as e:
            self._append(f"Could not save settings: {e}", "error")

    def _is_local(self):
        return self._source == "local"

    def _on_source_changed(self, label):
        self._source = "local" if label == SOURCE_LOCAL else "hosted"
        self._save_settings(source=self._source)
        self._apply_source_ui()
        if self._is_local():
            self._append("Local mode — Ollama / llama.cpp on this PC. No API key.", "system")
            self._refresh_local_models()
        else:
            self._append("Hosted mode — enter a provider URL and API key, then Connect.", "system")

    def _apply_source_ui(self):
        self.hosted_row.setVisible(not self._is_local())
        self.local_row.setVisible(self._is_local())
        self.connect_btn.setText("Test local" if self._is_local() else "Connect / Test")

    def _current_local_backend(self):
        return self.local_backend.currentData() or local_backend.BACKEND_OLLAMA

    def _local_base_url(self):
        return self.local_url.text().strip() or local_backend.DEFAULT_URLS[self._current_local_backend()]

    def _local_openai_url(self):
        url = self._local_base_url().rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        return url

    def _local_model_name(self):
        name = (self.local_model.currentText() or "").strip()
        if name in ("", "(Refresh)", "(no models found)"):
            return ""
        return name

    def _configure_local_client(self):
        model = self._local_model_name() or "local"
        self.client.configure(
            base_url=self._local_openai_url(),
            api_key=LOCAL_DUMMY_KEY,
            model=model,
            timeout=300.0,
        )
        local_storage.save_settings({
            **self._local_cfg,
            "backend": self._current_local_backend(),
            "base_url": self._local_base_url(),
            "model": self._local_model_name(),
        })
        ai_session.set_live(self.client, "local")

    def _register_commands(self):
        self.router.register("help", lambda _a: self._append(HELP_TEXT, "system"))
        self.router.register("clear", lambda _a: self._on_clear())
        self.router.register("new", lambda _a: self._on_new())
        self.router.register("build", self._cmd_build)
        self.router.register("agent", self._cmd_agent)
        self.router.register("source", self._cmd_source)
        self.router.register("models", lambda _a: self._refresh_local_models() if self._is_local() else self._start_bg(self._task_list_models))
        self.router.register("test", lambda _a: self._on_connect())
        self.router.register("output", lambda _a: self._open_explorer(self.builder.projects_root, "output folder"))
        self.router.register("openlast", self._cmd_openlast)

    def _cmd_build(self, arg):
        if not arg.strip():
            self._append("Usage: /build <description>", "error")
            return
        self._start_build(arg.strip())

    def _cmd_agent(self, arg):
        token = (arg or "").strip().lower()
        if token in ("on", "1", "true"):
            self.agent_box.setChecked(True)
        elif token in ("off", "0", "false"):
            self.agent_box.setChecked(False)
        elif token:
            self._append("Usage: /agent on   or   /agent off", "error")
        else:
            self.agent_box.setChecked(not self.agent_box.isChecked())

    def _cmd_source(self, arg):
        token = (arg or "").strip().lower()
        if token in ("local", "ollama", "llama"):
            self.source.setCurrentText(SOURCE_LOCAL)
        elif token in ("hosted", "api", "cloud"):
            self.source.setCurrentText(SOURCE_HOSTED)
        elif token:
            self._append("Usage: /source local   or   /source hosted", "error")
        else:
            self._append(f"Current source: {self.source.currentText()}", "system")

    def _cmd_openlast(self, _arg):
        if not self.last_project_dir:
            self._append("No project has been built yet this session.", "error")
            return
        self._open_explorer(self.last_project_dir, "last project")

    def _append(self, text, tag="system"):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_COLORS.get(tag, "#c9d1d9")))
        cur = self.output.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text.rstrip("\n") + "\n", fmt)
        self.output.setTextCursor(cur)
        self.output.ensureCursorVisible()

    def _append_inline(self, text, tag="ai"):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_COLORS.get(tag, "#c9d1d9")))
        cur = self.output.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text, fmt)
        self.output.setTextCursor(cur)
        self.output.ensureCursorVisible()

    def _timestamp(self):
        return datetime.now().strftime("%H:%M:%S")

    def _set_busy(self, busy):
        self.is_busy = busy
        self.send_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "line":
                    self._append(payload[0], payload[1])
                elif kind == "inline":
                    self._append_inline(payload[0], payload[1])
                elif kind == "status":
                    self.status.setText(payload)
                elif kind == "local_models":
                    self._apply_local_models(payload)
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass

    def _on_agent(self, on):
        self.agent_enabled = bool(on)
        self._append(
            "Agent is on. The model can run app actions."
            if self.agent_enabled else "Agent is off. Chat only.",
            "system",
        )

    def _on_connect(self):
        if self._is_local():
            self._configure_local_client()
            model = self._local_model_name() or "(none yet)"
            self._append(
                f"[{self._timestamp()}] Local {self._current_local_backend()}  {self._local_openai_url()}  model={model}",
                "system",
            )
            self._refresh_local_models()
            return
        base_url = self.provider.text().strip() or DEFAULT_BASE_URL
        api_key = self.key.text().strip()
        model = self.model.text().strip() or DEFAULT_MODEL
        if not api_key:
            self._append("Enter an API key before connecting.", "error")
            return
        self.client.configure(base_url=base_url, api_key=api_key, model=model)
        self._save_settings(hosted_base_url=base_url, hosted_model=model)
        ai_session.set_live(self.client, "hosted")
        self._append(f"[{self._timestamp()}] Configured provider={base_url}  model={model}", "system")
        self._start_bg(self._task_test)

    def _on_send(self):
        if self.is_busy:
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        command = parse(text)
        if command is not None:
            self._append(f"[{self._timestamp()}] > {text}", "user")
            if not self.router.dispatch(command):
                self._append(f"Unknown command: /{command.name}  (type /help)", "error")
            return
        self._append(f"[{self._timestamp()}] You: {text}", "user")
        self._start_chat(text)

    def _browse_output(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose AI output folder", self.builder.projects_root)
        if chosen:
            self.output_folder.setText(chosen)
            self._apply_output()

    def _apply_output(self):
        new_root = self.output_folder.text().strip()
        if not new_root:
            self._append("Output folder cannot be empty.", "error")
            return
        try:
            self.builder.set_projects_root(new_root)
        except Exception as e:
            self._append(f"Could not use that output folder: {e}", "error")
            return
        self.output_folder.setText(self.builder.projects_root)
        self._save_settings(projects_root=self.builder.projects_root)
        self._append(f"Output folder set to: {self.builder.projects_root}", "system")

    def _open_explorer(self, path, label):
        if not path or not os.path.isdir(path):
            self._append(f"Can't open {label}: {path}", "error")
            return
        try:
            os.startfile(path)
        except Exception as e:
            self._append(f"Could not open {label}: {e}", "error")

    def _on_stop(self):
        self.stop_event.set()
        self._append("Stopping generation...", "system")

    def _on_clear(self):
        self.output.clear()
        self._append("Terminal cleared. Conversation history preserved.", "system")

    def _on_new(self):
        self.history.clear()
        self.stop_event.set()
        self.output.clear()
        self._append("New session started.", "system")

    def _start_bg(self, target):
        if self.is_busy:
            self._append("Please wait for the current operation to finish.", "error")
            return
        self.stop_event = threading.Event()
        self._set_busy(True)
        threading.Thread(target=target, daemon=True).start()

    def _task_test(self):
        try:
            if not self.client.has_key():
                raise AIClientError("No API key set.")
            result = self.client.test_connection()
            self.msg_queue.put(("status", "Connected"))
            self.msg_queue.put(("line", (result, "system")))
        except AIClientError as e:
            self.msg_queue.put(("status", "Connection failed"))
            self.msg_queue.put(("line", (f"Connection test failed: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _task_list_models(self):
        try:
            models = self.client.list_models()
            listing = "\n".join(f"  - {m}" for m in models) if models else "Provider returned no models."
            self.msg_queue.put(("line", (f"Available models:\n{listing}", "system")))
        except AIClientError as e:
            self.msg_queue.put(("line", (f"Could not list models: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _refresh_local_models(self):
        if self.is_busy:
            return
        base_url = self._local_base_url()
        kind = self._current_local_backend()
        self._start_bg(lambda: self._task_refresh_local(base_url, kind))

    def _task_refresh_local(self, base_url, backend):
        try:
            names = local_backend.list_models(base_url, backend)
            self.msg_queue.put(("local_models", names))
        except Exception as e:
            self.msg_queue.put(("line", (f"Could not list local models: {e}", "error")))
            self.msg_queue.put(("local_models", []))
        finally:
            self.msg_queue.put(("done", None))

    def _apply_local_models(self, names):
        current = self._local_model_name()
        self.local_model.clear()
        if not names:
            self.local_model.addItem("(no models found)")
            return
        for name in names:
            self.local_model.addItem(name)
        if current in names:
            self.local_model.setCurrentText(current)

    def _start_chat(self, user_text):
        if self._is_local():
            if not self._local_model_name():
                self._append("Pick a local model (Refresh models) before sending.", "error")
                return
            self._configure_local_client()
        elif not self.client.has_key():
            self._append("No API key set. Connect / Test first, or switch to Local.", "error")
            return
        self.history.append(ChatMessage(role="user", content=user_text))
        self.stop_event = threading.Event()
        self._set_busy(True)
        threading.Thread(target=self._task_stream, daemon=True).start()

    def _task_stream(self):
        self.msg_queue.put(("line", (f"[{self._timestamp()}] AI:", "ai")))
        try:
            if self.agent_enabled:
                try:
                    self._task_agent()
                except AIClientError as e:
                    msg = str(e).lower()
                    if self._is_local() and ("tool" in msg or "400" in msg or "invalid" in msg):
                        self.msg_queue.put(("line", ("This local model skipped tools — chatting only.", "system")))
                        self._task_plain()
                    else:
                        raise
            else:
                self._task_plain()
            if self.stop_event.is_set():
                self.msg_queue.put(("line", ("(generation stopped)", "system")))
        except AIClientError as e:
            self.msg_queue.put(("line", (f"Error: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))

    def _task_plain(self):
        def on_delta(chunk):
            self.msg_queue.put(("inline", (chunk, "ai")))
        plain = [m for m in self.history if m.role in ("user", "assistant") and not getattr(m, "tool_calls", None)]
        full = self.client.stream_chat(messages=plain, on_delta=on_delta, stop_event=self.stop_event)
        self.msg_queue.put(("inline", ("\n", "ai")))
        if full:
            self.history.append(ChatMessage(role="assistant", content=full))

    def _task_agent(self):
        from core.services.agent_loop import run_agent_turn
        from core.services.agent_registry import get_registry

        def on_delta(chunk):
            self.msg_queue.put(("inline", (chunk, "ai")))

        def on_tool(name, args, result):
            ok = bool(result.get("ok", False))
            err = result.get("error")
            line = f"  ⚙ {name} → ok" if ok else f"  ⚙ {name} failed: {err or result}"
            self.msg_queue.put(("line", (line, "tool")))

        text = run_agent_turn(
            self.client, self.history, get_registry(),
            chat_message_cls=ChatMessage, on_delta=on_delta, on_tool=on_tool,
            stop_event=self.stop_event,
        )
        if text:
            self.msg_queue.put(("inline", ("\n", "ai")))

    def _start_build(self, prompt):
        if self.is_busy:
            self._append("Please wait for the current operation to finish.", "error")
            return
        if self._is_local():
            if not self._local_model_name():
                self._append("Pick a local model before /build.", "error")
                return
            self._configure_local_client()
        elif not self.client.has_key():
            self._append("No API key set.", "error")
            return
        self.stop_event = threading.Event()
        self._set_busy(True)
        self._append(f"[{self._timestamp()}] /build {prompt}", "build")
        threading.Thread(target=self._task_build, args=(prompt,), daemon=True).start()

    def _task_build(self, prompt):
        def progress(msg):
            self.msg_queue.put(("line", (msg, "build")))
        try:
            self.last_project_dir = self.builder.build(prompt, progress)
        except BuildError as e:
            self.msg_queue.put(("line", (f"Build failed: {e}", "error")))
        except Exception as e:
            self.msg_queue.put(("line", (f"Unexpected build error: {e}", "error")))
        finally:
            self.msg_queue.put(("done", None))


class PromptLibrary(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        split = QSplitter(Qt.Orientation.Horizontal)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        left = QWidget()
        ll = QVBoxLayout(left)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search prompts…")
        self.search.textChanged.connect(self._render)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        add = QPushButton("New prompt")
        add.clicked.connect(self._edit_new)
        ll.addWidget(self.search)
        ll.addWidget(self.list, 1)
        ll.addWidget(add)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.title = QLabel("Select a prompt")
        self.title.setObjectName("CardTitle")
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        row = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit_current)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        fav = QPushButton("Favorite")
        fav.clicked.connect(self._fav)
        row.addWidget(copy)
        row.addWidget(edit)
        row.addWidget(delete)
        row.addWidget(fav)
        row.addStretch(1)
        rl.addWidget(self.title)
        rl.addWidget(self.body, 1)
        rl.addLayout(row)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        self._current = None
        self._render()

    def _render(self):
        q = (self.search.text() or "").lower()
        self.list.clear()
        for p in prompt_store.load_all():
            title = p.get("title") or "Untitled"
            if q and q not in title.lower() and q not in (p.get("body") or "").lower():
                continue
            star = "★ " if p.get("favorite") else ""
            item = QListWidgetItem(f"{star}{title}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list.addItem(item)

    def _show(self, item):
        if item is None:
            return
        self._current = item.data(Qt.ItemDataRole.UserRole)
        self.title.setText(self._current.get("title") or "Untitled")
        self.body.setPlainText(self._current.get("body") or "")

    def _copy(self):
        if not self._current:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._current.get("body") or "")
        prompt_store.mark_used(self._current["id"])

    def _fav(self):
        if not self._current:
            return
        prompt_store.toggle_favorite(self._current["id"])
        self._render()

    def _delete(self):
        if not self._current:
            return
        if QMessageBox.question(self, "Delete prompt", "Delete this prompt?") != QMessageBox.StandardButton.Yes:
            return
        prompt_store.delete_prompt(self._current["id"])
        self._current = None
        self._render()

    def _edit_new(self):
        self._edit_dialog({})

    def _edit_current(self):
        if self._current:
            self._edit_dialog(dict(self._current))

    def _edit_dialog(self, prompt):
        dlg = QDialog(self)
        dlg.setWindowTitle("Prompt")
        form = QFormLayout(dlg)
        title = QLineEdit(prompt.get("title") or "")
        cat = QLineEdit(prompt.get("category") or "General")
        body = QPlainTextEdit(prompt.get("body") or "")
        form.addRow("Title", title)
        form.addRow("Category", cat)
        form.addRow("Body", body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        prompt_store.save_prompt({
            **prompt,
            "title": title.text(),
            "category": cat.text(),
            "body": body.toPlainText(),
        })
        self._render()
