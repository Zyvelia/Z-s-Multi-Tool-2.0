"""Loopback HTTP for the phone: chat + optional agent on this PC."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from core import paths
from core.services import device_trust

from . import session
from .agent_tools import ensure_registered
from .local_model_runner import storage as local_storage

LOOPBACK_PORT = 8772
HISTORY_FILE = Path(paths.data_path("ai_terminal", "phone_history.json"))
SETTINGS_FILE = Path(paths.data_path("ai_terminal", "settings.json"))
LOCAL_DUMMY_KEY = "local"
MAX_HISTORY = 80


def _load_json(path: Path, fallback):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return fallback


def _terminal_settings() -> dict:
    data = _load_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def _load_history() -> list[dict]:
    data = _load_json(HISTORY_FILE, [])
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("role") and "content" in item:
            out.append({"role": item["role"], "content": str(item.get("content") or "")})
    return out[-MAX_HISTORY:]


def _save_history(rows: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(rows[-MAX_HISTORY:], indent=2), encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "AiChatWeb/1.0"

    def log_message(self, *_args):
        return

    def _srv(self):
        return self.server.owner

    def _cors(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code, X-Device-Id, X-Device-Ts, X-Device-Sig")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def _code_ok(self) -> bool:
        required = (self._srv().access_code or "").strip()
        if not required:
            return True
        sent = (self.headers.get("X-Access-Code") or "").strip()
        return sent == required

    def do_GET(self):
        if not device_trust.allow_handler(self):
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            return self._json(200, self._srv().status())
        if path == "/api/history":
            return self._json(200, {"ok": True, "messages": _load_history()})
        if path == "/api/models":
            return self._json(200, self._srv().list_models())
        if path == "/api/pending_confirm":
            from core.services import agent_confirm
            pending = agent_confirm.snapshot()
            return self._json(200, {"ok": True, "pending": pending})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not device_trust.allow_handler(self):
            return
        if not self._code_ok():
            return self._json(401, {"ok": False, "error": "wrong or missing access code"})
        path = urlsplit(self.path).path
        body = self._body()
        if body is None:
            return self._json(400, {"ok": False, "error": "invalid JSON body"})
        if path == "/api/connect":
            return self._json(200, self._srv().connect(body))
        if path == "/api/chat":
            return self._json(200, self._srv().chat(body.get("text") or "", agent=body.get("agent", True)))
        if path == "/api/build":
            return self._json(200, self._srv().build(body.get("prompt") or body.get("text") or ""))
        if path == "/api/clear":
            self._srv().clear()
            return self._json(200, {"ok": True})
        if path == "/api/openlast":
            return self._json(200, self._srv().open_last())
        if path == "/api/confirm":
            from core.services import agent_confirm
            ok = agent_confirm.answer(str(body.get("id") or ""), bool(body.get("ok")))
            return self._json(200 if ok else 404, {"ok": ok})
        return self._json(404, {"ok": False, "error": "not found"})


class ChatWebServer:
    def __init__(self):
        self.access_code = ""
        self.port = None
        self._httpd = None
        self._thread = None
        self._busy = threading.Lock()
        self._history = _load_history()

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self, port: int = LOOPBACK_PORT):
        if self.is_running():
            return True, "already running"
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
        except OSError as e:
            return False, f"couldn't bind to 127.0.0.1:{port} — {e}"
        httpd.owner = self
        httpd.daemon_threads = True
        self._httpd = httpd
        self.port = int(port)
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return True, f"listening on 127.0.0.1:{port}"

    def stop(self):
        if not self.is_running():
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        self._httpd = None
        self.port = None

    def status(self) -> dict:
        ready, source, model, err = self._resolve()
        saved = _terminal_settings()
        return {
            "ok": True,
            "ready": ready,
            "source": source,
            "model": model,
            "error": err,
            "hosted_base_url": saved.get("hosted_base_url") or "",
            "last_project": saved.get("last_project_dir") or "",
        }

    def connect(self, body: dict) -> dict:
        source = (body.get("source") or "hosted").strip().lower()
        if source == "local":
            built, err = self._local_client(local_storage.load_settings())
            if built is None:
                return {"ok": False, "error": err, "source": "local"}
            session.set_live(built, "local")
            self._save_terminal(source="local")
            return self.status()
        try:
            from .client import AIClient, AIClientConfig, DEFAULT_BASE_URL, DEFAULT_MODEL
        except Exception as e:
            return {"ok": False, "error": f"openai package missing on the PC: {e}"}
        key = (body.get("api_key") or body.get("key") or "").strip()
        if not key:
            return {"ok": False, "error": "api_key required for hosted."}
        url = (body.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        model = (body.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        client = AIClient(AIClientConfig())
        client.configure(base_url=url, api_key=key, model=model)
        try:
            client.test_connection()
        except Exception as e:
            return {"ok": False, "error": str(e), "source": "hosted"}
        session.set_live(client, "hosted")
        self._save_terminal(source="hosted", hosted_base_url=url, hosted_model=model)
        return self.status()

    def list_models(self) -> dict:
        client, _source, err = self._client()
        if client is None:
            return {"ok": False, "error": err or "not connected", "models": []}
        try:
            return {"ok": True, "models": client.list_models()}
        except Exception as e:
            return {"ok": False, "error": str(e), "models": []}

    def build(self, prompt: str) -> dict:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt required"}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "error": "Already busy (chat or build)."}
        try:
            client, _source, err = self._client()
            if client is None:
                return {"ok": False, "error": err or "Connect first."}
            from .builder import AIProjectBuilder, BuildError
            root = self._projects_root()
            log: list[str] = []
            builder = AIProjectBuilder(client, str(root))
            try:
                path = builder.build(prompt, log.append)
            except BuildError as e:
                return {"ok": False, "error": str(e), "log": log}
            self._save_terminal(last_project_dir=path)
            self._history.append({"role": "user", "content": f"/build {prompt}"})
            self._history.append({"role": "assistant", "content": f"Built on the PC:\n{path}\n" + "\n".join(log[-12:])})
            _save_history(self._history)
            return {"ok": True, "path": path, "log": log, "reply": f"Built on the PC:\n{path}"}
        finally:
            self._busy.release()

    def open_last(self) -> dict:
        path = (_terminal_settings().get("last_project_dir") or "").strip()
        if not path or not Path(path).is_dir():
            return {"ok": False, "error": "No last project yet. /build something first."}
        try:
            import os
            os.startfile(path)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": path}

    def _projects_root(self) -> Path:
        saved = (_terminal_settings().get("projects_root") or "").strip()
        if saved:
            return Path(saved)
        return Path(__file__).resolve().parents[2] / "AI_Projects"

    def _save_terminal(self, **updates) -> None:
        data = _terminal_settings()
        data.update(updates)
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self._history = []
        _save_history(self._history)

    def chat(self, text: str, *, agent: bool = True) -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "text required"}
        slash = self._slash(text)
        if slash is not None:
            return slash
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "error": "Already answering another message."}
        try:
            client, source, err = self._client()
            if client is None:
                return {"ok": False, "error": err or "AI Chat is not ready on the PC."}
            from .client import ChatMessage, AIClientError
            from core.services.agent_loop import run_agent_turn
            from core.services.agent_registry import get_registry

            ensure_registered()
            self._history.append({"role": "user", "content": text})
            history = [
                ChatMessage(role=m["role"], content=m["content"])
                for m in self._history
                if m.get("role") in ("user", "assistant")
            ]
            tools: list[dict] = []
            stop = threading.Event()

            def on_delta(_chunk: str) -> None:
                return

            def on_tool(name: str, _args: dict, result: dict) -> None:
                ok = bool(result.get("ok", False))
                hint = result.get("error") or result.get("name") or result.get("backup") or ("ok" if ok else "failed")
                tools.append({"name": name, "ok": ok, "detail": str(hint)[:180]})

            try:
                if agent:
                    from core.services.agent_confirm import phone_scope
                    with phone_scope():
                        reply = run_agent_turn(
                            client,
                            history,
                            get_registry(),
                            chat_message_cls=ChatMessage,
                            on_delta=on_delta,
                            on_tool=on_tool,
                            stop_event=stop,
                        )
                else:
                    reply = client.simple_chat(history)
            except AIClientError as e:
                msg = str(e)
                if agent and source == "local" and ("tool" in msg.lower() or "400" in msg or "invalid" in msg.lower()):
                    try:
                        reply = client.simple_chat(history)
                        tools.append({"name": "agent", "ok": False, "detail": "Local model skipped tools — chat only."})
                    except AIClientError as e2:
                        return {"ok": False, "error": str(e2)}
                else:
                    return {"ok": False, "error": msg}
            except Exception as e:
                return {"ok": False, "error": str(e)}

            reply = (reply or "").strip()
            if reply:
                self._history.append({"role": "assistant", "content": reply})
            for tool in tools:
                mark = "ok" if tool.get("ok") else "fail"
                self._history.append({
                    "role": "tool",
                    "content": f"{tool.get('name')} → {mark}: {tool.get('detail')}",
                })
            _save_history(self._history)
            return {
                "ok": True,
                "reply": reply,
                "tools": tools,
                "source": source,
                "model": getattr(getattr(client, "config", None), "model", "") or "",
            }
        finally:
            self._busy.release()

    def _slash(self, text: str) -> dict | None:
        from .commands import parse, HELP_TEXT
        cmd = parse(text)
        if cmd is None:
            return None
        name, arg = cmd.name, cmd.argument
        if name in ("help",):
            return {"ok": True, "reply": HELP_TEXT, "tools": []}
        if name in ("clear", "new"):
            self.clear()
            return {"ok": True, "reply": "Cleared.", "tools": [], "cleared": True}
        if name == "build":
            if not arg:
                return {"ok": False, "error": "Usage: /build what to make on the PC"}
            return self.build(arg)
        if name == "test":
            client, _source, err = self._client()
            if client is None:
                return {"ok": False, "error": err or "Connect first."}
            try:
                return {"ok": True, "reply": client.test_connection(), "tools": []}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if name == "models":
            listed = self.list_models()
            names = listed.get("models") or []
            listed["reply"] = "\n".join(f"  - {m}" for m in names) if names else (listed.get("error") or "No models.")
            listed.setdefault("ok", True)
            listed.setdefault("tools", [])
            return listed
        if name == "source":
            want = (arg or "").strip().lower()
            if want not in ("hosted", "local"):
                return {"ok": False, "error": "Usage: /source hosted   or   /source local"}
            if want == "local":
                return self.connect({"source": "local"})
            return {"ok": True, "reply": "Hosted: use Connect on the phone and send the API key. It stays in PC memory only.", "tools": []}
        if name in ("openlast", "output"):
            return self.open_last()
        if name == "agent":
            return {"ok": True, "reply": "Toggle Agent on the phone Chat bar. It runs tools on this PC.", "tools": []}
        return {"ok": False, "error": f"Unknown command /{name}. Try /help."}

    def _resolve(self) -> tuple[bool, str, str, str]:
        client, source, err = self._client()
        model = ""
        if client is not None:
            model = getattr(getattr(client, "config", None), "model", "") or ""
        return client is not None, source, model, err

    def _client(self):
        live = session.live_client()
        source = session.live_source()
        if live is not None and live.has_key():
            return live, source, ""

        saved = _terminal_settings()
        prefer = (saved.get("source") or "hosted").strip().lower()
        local_cfg = local_storage.load_settings()
        local_model = (local_cfg.get("model") or "").strip()
        if prefer == "local" or (prefer != "hosted" and local_model):
            built, err = self._local_client(local_cfg)
            return built, "local", err

        if prefer == "hosted":
            return None, "hosted", (
                "Open AI Chat on the PC, paste the hosted key, and tap Connect. "
                "The key stays in memory on this PC — it is never written to disk."
            )
        built, err = self._local_client(local_cfg)
        return built, "local", err

    def _local_client(self, local_cfg: dict):
        try:
            from .client import AIClient, AIClientConfig
        except Exception as e:
            return None, f"openai package missing on the PC: {e}"
        model = (local_cfg.get("model") or "").strip()
        if not model:
            return None, "Pick a local model in AI Chat on the PC (Refresh local models)."
        url = (local_cfg.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        if not url.endswith("/v1"):
            url = url + "/v1"
        client = AIClient(AIClientConfig())
        client.configure(base_url=url, api_key=LOCAL_DUMMY_KEY, model=model, timeout=300.0)
        return client, ""
