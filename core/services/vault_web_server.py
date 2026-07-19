# core/services/vault_web_server.py
#
# A small, dependency-free HTTP server (stdlib only) that serves a
# mobile-friendly view of the vault + authenticator codes, meant to be
# reached from your phone via `tailscale serve` (see tailscale_service.py)
# — NOT exposed on the LAN or the open internet.
#
# Security model:
#   - Binds to 127.0.0.1 ONLY. It is never reachable except through the
#     Tailscale HTTPS proxy running on the same machine, which only
#     accepts connections from other devices on your own tailnet.
#   - Every page/API call requires the vault master password. A
#     successful login issues a random session token (HttpOnly,
#     SameSite=Strict cookie) that expires after IDLE_TIMEOUT_SECONDS
#     of inactivity.
#   - Failed logins are rate-limited with a short lockout so the login
#     form can't be brute-forced.
#   - Logging in from the phone unlocks the same vault the desktop app
#     uses (it's one master password) — the Settings tab explains this.

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

IDLE_TIMEOUT_SECONDS = 20 * 60   # session expires after 20 min of inactivity
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60

# In-memory session store. Cleared automatically on server stop/restart —
# by design nothing here ever touches disk.
_sessions = {}
_sessions_lock = threading.Lock()

_failed_attempts = {"count": 0, "locked_until": 0}
_failed_lock = threading.Lock()


def _new_session():
    token = secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[token] = time.time()
    return token


def _touch_session(token):
    with _sessions_lock:
        if token in _sessions:
            _sessions[token] = time.time()
            return True
    return False


def _session_valid(token):
    if not token:
        return False
    with _sessions_lock:
        last_seen = _sessions.get(token)
        if last_seen is None:
            return False
        if time.time() - last_seen > IDLE_TIMEOUT_SECONDS:
            del _sessions[token]
            return False
    return _touch_session(token)


def _drop_session(token):
    with _sessions_lock:
        _sessions.pop(token, None)


def _login_locked():
    with _failed_lock:
        return time.time() < _failed_attempts["locked_until"]


def _record_failed_login():
    with _failed_lock:
        _failed_attempts["count"] += 1
        if _failed_attempts["count"] >= MAX_FAILED_ATTEMPTS:
            _failed_attempts["locked_until"] = time.time() + LOCKOUT_SECONDS
            _failed_attempts["count"] = 0


def _record_successful_login():
    with _failed_lock:
        _failed_attempts["count"] = 0
        _failed_attempts["locked_until"] = 0


def _cookie_from_headers(headers):
    raw = headers.get("Cookie", "")
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith("vault_session="):
            return part.split("=", 1)[1]
    return None


def _bearer_from_headers(headers):
    # The Zs Multi Tool browser extension can't rely on the SameSite=Strict
    # session cookie (an extension popup/background page is a different
    # "site" than 127.0.0.1, so Strict cookies never get attached to its
    # requests). It authenticates with a plain bearer token instead — same
    # session store, same expiry, just carried in a header instead of a
    # cookie. This is only ever readable on 127.0.0.1 loopback traffic.
    raw = headers.get("Authorization", "")
    if raw.startswith("Bearer "):
        return raw[len("Bearer "):].strip()
    return None


class _Handler(BaseHTTPRequestHandler):

    server_version = "VaultWeb/1.0"

    # Silence default stderr request logging — noisy for a background service.
    def log_message(self, fmt, *args):
        pass

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _services(self):
        return self.server.app_services

    def _cors_headers(self):
        # Loopback-only server (127.0.0.1), so a permissive CORS policy here
        # doesn't expose anything beyond what's already reachable by any
        # process on this same machine. Needed so the browser extension's
        # popup/background page (origin "chrome-extension://...") and, for
        # Firefox, its content-script fetches can talk to this API.
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _send_json(self, status, payload, set_cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            try:
                return {k: v[0] for k, v in parse_qs(raw).items()}
            except Exception:
                return {}

    def _authed(self):
        token = _cookie_from_headers(self.headers) or _bearer_from_headers(self.headers)
        return _session_valid(token)

    # -------------------------------------------------
    # routing
    # -------------------------------------------------

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_html(200, _PAGE_SHELL)
        elif self.path == "/api/session":
            self._send_json(200, {"authed": self._authed()})
        elif self.path == "/api/entries":
            if not self._authed():
                self._send_json(401, {"error": "not authenticated"})
                return
            self._handle_entries()
        elif self.path == "/api/totp":
            if not self._authed():
                self._send_json(401, {"error": "not authenticated"})
                return
            self._handle_totp()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/login":
            self._handle_login()
        elif self.path == "/api/logout":
            token = _cookie_from_headers(self.headers) or _bearer_from_headers(self.headers)
            if token:
                _drop_session(token)
            self._send_json(200, {"ok": True}, set_cookie="vault_session=; Path=/; Max-Age=0")
        else:
            self._send_json(404, {"error": "not found"})

    # -------------------------------------------------
    # handlers
    # -------------------------------------------------

    def _handle_login(self):
        if _login_locked():
            self._send_json(429, {"error": "Too many attempts. Try again in a minute."})
            return

        body = self._read_json_body()
        password = (body.get("password") or "").strip()
        auth_service = self._services()["auth_service"]
        alert_service = self._services().get("alert_service")
        client_ip = self.client_address[0] if self.client_address else "unknown"

        if not password or not auth_service.verify_master_password(password):
            _record_failed_login()
            if alert_service:
                alert_service.remote_login_attempt(False, client_ip)
            self._send_json(401, {"error": "Incorrect master password."})
            return

        _record_successful_login()
        if alert_service:
            alert_service.remote_login_attempt(True, client_ip)
        token = _new_session()
        cookie = f"vault_session={token}; Path=/; HttpOnly; SameSite=Strict"
        self._send_json(200, {"ok": True, "token": token}, set_cookie=cookie)

    def _handle_entries(self):
        vault_service = self._services()["vault_service"]
        entries = vault_service.get_entries()
        safe = [
            {
                "id": e.get("id"),
                "site": e.get("site", ""),
                "username": e.get("username", ""),
                "password": e.get("password", ""),
                "category": e.get("category", ""),
                "favorite": e.get("favorite", False),
            }
            for e in entries
        ]
        self._send_json(200, {"entries": safe})

    def _handle_totp(self):
        from core.services import totp_service as totp
        totp_service = self._services()["totp_service"]
        entries = totp_service.get_entries()
        codes = [
            {
                "id": e.get("id"),
                "name": e.get("name", ""),
                "issuer": e.get("issuer", ""),
                "code": totp.generate_code(e["secret"]),
            }
            for e in entries
        ]
        self._send_json(200, {"codes": codes, "period": totp.DEFAULT_PERIOD,
                               "seconds_remaining": totp.seconds_remaining()})


class VaultWebServer:
    """
    Owns the background HTTP server thread. `services` is a dict with
    auth_service / vault_service / totp_service / alert_service
    references — pulled from the app container so the web server always
    reads the same live vault the desktop UI does, and fires the same
    login alerts.
    """

    def __init__(self, services):
        self.services = services
        self._httpd = None
        self._thread = None
        self.port = None

    def is_running(self):
        return self._httpd is not None

    def start(self, port):
        if self.is_running():
            return True, f"Already running on port {self.port}."
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        except OSError as e:
            return False, f"Couldn't bind to port {port}: {e}"

        httpd.app_services = self.services
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        self._httpd = httpd
        self._thread = thread
        self.port = port
        return True, f"Serving on 127.0.0.1:{port} (local only)."

    def stop(self):
        if not self._httpd:
            return True, "Already stopped."
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None
        self.port = None
        with _sessions_lock:
            _sessions.clear()
        return True, "Stopped."


# =====================================================
# MOBILE PAGE (single file, no build step, no external requests)
# =====================================================

_PAGE_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Security Vault</title>
<style>
  :root {
    --bg:#0f1115; --panel:#151922; --card:#1b2030; --accent:#a78bfa;
    --text:#e8ecf1; --muted:#8a93a6; --danger:#b33939; --success:#3ecf8e;
  }
  * { box-sizing: border-box; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-tap-highlight-color: transparent;
  }
  .wrap { max-width:520px; margin:0 auto; padding:20px 16px 60px; }
  h1 { font-size:22px; margin:10px 0 20px; }
  .panel { background:var(--panel); border-radius:14px; padding:16px; margin-bottom:14px; }
  input {
    width:100%; padding:14px; border-radius:10px; border:1px solid #252d3d;
    background:var(--card); color:var(--text); font-size:16px; margin-bottom:10px;
  }
  button {
    width:100%; padding:14px; border-radius:10px; border:none;
    background:var(--accent); color:#0b0d10; font-weight:700; font-size:16px;
  }
  button.secondary { background:var(--card); color:var(--text); }
  .tabs { display:flex; gap:8px; margin-bottom:14px; }
  .tabs button { flex:1; background:var(--card); color:var(--muted); font-weight:600; }
  .tabs button.active { background:var(--accent); color:#0b0d10; }
  .card {
    background:var(--card); border-radius:12px; padding:14px; margin-bottom:10px;
  }
  .card .site { font-weight:700; font-size:16px; }
  .card .meta { color:var(--muted); font-size:13px; margin-top:2px; }
  .row { display:flex; gap:8px; margin-top:10px; }
  .row button { padding:10px; font-size:13px; }
  .code { font-family:Consolas,monospace; font-size:26px; letter-spacing:2px; color:var(--accent); }
  .error { color:var(--danger); font-size:14px; margin:-4px 0 10px; }
  .muted { color:var(--muted); font-size:13px; }
  #logoutBtn { background:transparent; color:var(--muted); border:1px solid #252d3d; }
</style>
</head>
<body>
<div class="wrap" id="app"></div>
<script>
const app = document.getElementById('app');
let state = { authed: false, tab: 'passwords' };

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}));
  let data = {};
  try { data = await res.json(); } catch (e) {}
  return { ok: res.ok, status: res.status, data };
}

function renderFatalError(err) {
  app.innerHTML = `
    <h1>&#128274; Security Vault</h1>
    <div class="panel">
      <div class="error">Something went wrong loading this page.</div>
      <div class="muted" style="margin-bottom:10px;">${escapeHtml(String(err && err.message ? err.message : err))}</div>
      <button id="retryBtn">Retry</button>
    </div>
  `;
  const retry = document.getElementById('retryBtn');
  if (retry) retry.onclick = () => location.reload();
}

function renderLogin(error) {
  app.innerHTML = `
    <h1>&#128274; Security Vault</h1>
    <div class="panel">
      <input id="pw" type="password" placeholder="Master password" autofocus>
      ${error ? `<div class="error">${error}</div>` : ''}
      <button id="loginBtn">Unlock</button>
    </div>
    <div class="muted">Reachable only from devices on your Tailscale network.</div>
  `;
  document.getElementById('loginBtn').onclick = doLogin;
  document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
}

async function doLogin() {
  const password = document.getElementById('pw').value;
  const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ password }) });
  if (r.ok) { state.authed = true; renderMain(); }
  else renderLogin(r.data.error || 'Login failed.');
}

async function doLogout() {
  await api('/api/logout', { method: 'POST' });
  state.authed = false;
  renderLogin();
}

function maskPw() { return '\u2022'.repeat(12); }

async function renderMain() {
  app.innerHTML = `
    <h1>&#128274; Security Vault</h1>
    <div class="tabs">
      <button id="tabPw" class="${state.tab==='passwords'?'active':''}">Passwords</button>
      <button id="tabTotp" class="${state.tab==='totp'?'active':''}">Authenticator</button>
    </div>
    <div id="list"></div>
    <button id="logoutBtn">Lock</button>
  `;
  document.getElementById('tabPw').onclick = () => { state.tab = 'passwords'; renderMain(); };
  document.getElementById('tabTotp').onclick = () => { state.tab = 'totp'; renderMain(); };
  document.getElementById('logoutBtn').onclick = doLogout;

  if (state.tab === 'passwords') await loadPasswords();
  else await loadTotp();
}

async function loadPasswords() {
  const r = await api('/api/entries');
  if (r.status === 401) { renderLogin(); return; }
  const list = document.getElementById('list');
  const entries = r.data.entries || [];
  if (entries.length === 0) {
    list.innerHTML = '<div class="muted">No entries yet.</div>';
    return;
  }
  list.innerHTML = entries.map(e => `
    <div class="card">
      <div class="site">${escapeHtml(e.site)}</div>
      <div class="meta">${escapeHtml(e.username)} &middot; ${escapeHtml(e.category)}</div>
      <div class="meta" data-pw="${encodeURIComponent(e.password)}" id="pw-${e.id}">${maskPw()}</div>
      <div class="row">
        <button class="secondary" onclick="togglePw('${e.id}')">Show</button>
        <button class="secondary" onclick="copyText('${e.id}', 'pw')">Copy pw</button>
        <button class="secondary" onclick="copyPlain('${encodeURIComponent(e.username)}')">Copy user</button>
      </div>
    </div>
  `).join('');
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function togglePw(id) {
  const el = document.getElementById('pw-' + id);
  const real = decodeURIComponent(el.getAttribute('data-pw'));
  if (el.textContent === maskPw()) el.textContent = real;
  else el.textContent = maskPw();
}

function copyText(id, kind) {
  const el = document.getElementById('pw-' + id);
  const real = decodeURIComponent(el.getAttribute('data-pw'));
  navigator.clipboard && navigator.clipboard.writeText(real);
}

function copyPlain(encoded) {
  navigator.clipboard && navigator.clipboard.writeText(decodeURIComponent(encoded));
}

let totpTimer = null;
async function loadTotp() {
  if (totpTimer) clearInterval(totpTimer);
  const r = await api('/api/totp');
  if (r.status === 401) { renderLogin(); return; }
  renderTotpList(r.data);
  totpTimer = setInterval(async () => {
    if (state.tab !== 'totp') { clearInterval(totpTimer); return; }
    const rr = await api('/api/totp');
    if (rr.status === 401) { clearInterval(totpTimer); renderLogin(); return; }
    renderTotpList(rr.data);
  }, 3000);
}

function renderTotpList(data) {
  const list = document.getElementById('list');
  if (!list) return;
  const codes = data.codes || [];
  if (codes.length === 0) {
    list.innerHTML = '<div class="muted">No authenticator codes yet.</div>';
    return;
  }
  list.innerHTML = codes.map(c => `
    <div class="card">
      <div class="site">${escapeHtml(c.name)}${c.issuer ? ' &middot; ' + escapeHtml(c.issuer) : ''}</div>
      <div class="code">${c.code.slice(0,3)} ${c.code.slice(3)}</div>
    </div>
  `).join('') + `<div class="muted">Refreshes automatically &middot; ${data.seconds_remaining}s left in this cycle</div>`;
}

(async function init() {
  try {
    const r = await api('/api/session');
    if (r.data && r.data.authed) { state.authed = true; renderMain(); }
    else renderLogin();
  } catch (err) {
    renderFatalError(err);
  }
})();

window.addEventListener('error', e => {
  if (!app.innerHTML.trim()) renderFatalError(e.error || e.message || 'Unknown error');
});
window.addEventListener('unhandledrejection', e => {
  if (!app.innerHTML.trim()) renderFatalError(e.reason || 'Unknown error');
});
</script>
</body>
</html>
"""