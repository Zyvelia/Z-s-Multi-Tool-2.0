"""Microsoft/Xbox/Minecraft authentication for direct Minecraft launches."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlencode

import requests

CLIENT_ID = "00000000402b5328"
MS_AUTH_URL = "https://login.live.com/oauth20_authorize.srf"
MS_TOKEN_URL = "https://login.live.com/oauth20_token.srf"
MS_REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"
MS_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
UA = "Game Server Manager/1.0"

try:
    from core import paths

    def _auth_file() -> Path:
        p = Path(paths.data_path("minecraft_auth", "account.json"))
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
except Exception:
    def _auth_file() -> Path:
        p = Path(os.environ.get("APPDATA", str(Path.home()))) / "ZsMultiTool" / "minecraft_auth" / "account.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def load_auth() -> dict | None:
    p = _auth_file()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def logout() -> None:
    try:
        _auth_file().unlink(missing_ok=True)
    except OSError:
        pass


def _save(data: dict) -> None:
    p = _auth_file()
    # Restrict permissions where the platform supports it. Windows ACLs are
    # handled by the user's profile; no Microsoft password is ever stored.
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _post_json(url: str, stage: str = "Authentication request", **kwargs) -> dict:
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", UA)
    r = requests.post(url, headers=headers, timeout=45, **kwargs)
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:1000].strip() or "(empty response body)"
        raise RuntimeError(f"{stage} failed ({r.status_code}): {detail}")
    return r.json()


def _xbl_authenticate(rps_ticket: str) -> dict:
    return _post_json(
        XBL_URL,
        stage="Xbox Live sign-in",
        json={
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": rps_ticket,
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )


def _exchange_ms_token(ms_access_token: str) -> tuple[str, str]:
    # Xbox Live's user/authenticate endpoint is inconsistent about whether it
    # wants the access token prefixed with "d=" or raw - which one an account
    # needs isn't predictable ahead of time, and sending the wrong one is
    # rejected outright with an empty-body 401. Try "d=" first (the documented
    # default for this client), then fall back to the bare token.
    try:
        xbl = _xbl_authenticate(f"d={ms_access_token}")
    except RuntimeError as first_error:
        try:
            xbl = _xbl_authenticate(ms_access_token)
        except RuntimeError:
            raise first_error

    xsts_r = requests.post(
        XSTS_URL,
        json={
            "Properties": {
                "SandboxId": "RETAIL",
                "UserTokens": [xbl["Token"]],
            },
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        },
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA},
        timeout=45,
    )
    # XSTS returns HTTP 401 (not 200) when authorization is denied, but the
    # body still carries the specific XErr reason - parse it before treating
    # this as a generic failure, or the XErr messages below are unreachable.
    try:
        xsts = xsts_r.json()
    except ValueError:
        xsts = {}
    if not xsts_r.ok and not xsts.get("XErr"):
        detail = xsts_r.text[:1000].strip() or "(empty response body)"
        raise RuntimeError(f"Xbox security token service failed ({xsts_r.status_code}): {detail}")

    if xsts.get("XErr"):
        code = int(xsts["XErr"])
        messages = {
            2148916233: "This Microsoft account does not have an Xbox account attached.",
            2148916235: "Xbox Live is not available for this account's country/region.",
            2148916238: "This is a child Microsoft account and needs family approval.",
        }
        raise RuntimeError(messages.get(code, f"Xbox authentication failed (XErr {code})."))

    try:
        uhs = xsts["DisplayClaims"]["xui"][0]["uhs"]
        xsts_token = xsts["Token"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Microsoft sign-in succeeded, but Xbox authentication returned an invalid response.")

    mc = _post_json(
        MC_LOGIN_URL,
        stage="Minecraft Services login",
        json={"identityToken": f"XBL3.0 x={uhs};{xsts_token}"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    mc_token = str(mc.get("access_token") or "")
    if not mc_token:
        raise RuntimeError("Xbox sign-in succeeded, but Minecraft Services did not return a game token.")

    profile_r = requests.get(
        MC_PROFILE_URL,
        headers={"Authorization": f"Bearer {mc_token}", "User-Agent": UA},
        timeout=30,
    )
    if profile_r.status_code == 404:
        raise RuntimeError("This Microsoft account does not own Minecraft: Java Edition.")
    if not profile_r.ok:
        raise RuntimeError(f"Minecraft profile lookup failed ({profile_r.status_code}).")
    profile = profile_r.json()

    return mc_token, profile



def _try_launcher_token_directly(token: str) -> tuple[str, dict] | None:
    """The official launcher's launcher_accounts.json accessToken is already
    a fully Xbox/XSTS-exchanged Minecraft Services token, not a raw Microsoft
    OAuth (RPS) token. Try it straight against the profile endpoint first;
    only fall back to a full MSA exchange if the launcher's session itself
    has actually gone stale.
    """
    try:
        r = requests.get(
            MC_PROFILE_URL,
            headers={"Authorization": f"Bearer {token}", "User-Agent": UA},
            timeout=15,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    try:
        profile = r.json()
    except ValueError:
        return None
    if not profile.get("name") or not profile.get("id"):
        return None
    return token, profile


def _launcher_account_paths() -> list[Path]:
    """Return standard Windows Minecraft Launcher account databases."""
    paths: list[Path] = []
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    for root in (
        appdata / ".minecraft",
        home / ".minecraft",
    ):
        paths.append(root / "launcher_accounts.json")

    package = local / "Packages" / "Microsoft.4297127D64EC_8wekyb3d8bbwe"
    for sub in (
        "LocalCache/Roaming/.minecraft",
        "LocalCache/Local/.minecraft",
        "LocalState/.minecraft",
    ):
        paths.append(package / Path(sub) / "launcher_accounts.json")

    seen: set[str] = set()
    result = []
    for p in paths:
        key = os.path.normcase(os.path.abspath(str(p)))
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


def import_official_launcher_account() -> dict:
    """Import the user's existing official Minecraft Launcher session.

    This avoids requiring Z's Multi Tool to register its own Microsoft Entra
    application. The official launcher already owns the Microsoft OAuth
    session; we reuse only the launcher-issued token/refresh token and then
    exchange it with Xbox Live and Minecraft Services. No password is read.
    """
    candidates = _launcher_account_paths()
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        accounts = data.get("accounts")
        if not isinstance(accounts, dict):
            continue

        active = data.get("activeAccountUuid") or data.get("activeAccount")
        ordered = []
        if active and isinstance(accounts.get(active), dict):
            ordered.append(accounts[active])
        ordered.extend(v for k, v in accounts.items() if k != active and isinstance(v, dict))

        for acc in ordered:
            if not isinstance(acc, dict):
                continue
            access = str(acc.get("accessToken") or "").strip()
            refresh = str(acc.get("refreshToken") or acc.get("refresh_token") or "").strip()
            if not access:
                continue

            # The launcher's accessToken is normally already a live Minecraft
            # Services token; use it as-is first.
            direct = _try_launcher_token_directly(access)
            if direct is not None:
                mc_token, profile = direct
            else:
                # Fall back: maybe this really is a Microsoft OAuth token (or
                # the launcher's session went stale), so try the full
                # Xbox/XSTS exchange, then the refresh token, before giving up
                # on this account.
                try:
                    mc_token, profile = _exchange_ms_token(access)
                except Exception as first_error:
                    if not refresh:
                        continue
                    try:
                        refreshed = _post_json(
                            MS_TOKEN_URL,
                            stage="Microsoft token refresh",
                            data={
                                "grant_type": "refresh_token",
                                "client_id": CLIENT_ID,
                                "refresh_token": refresh,
                                "redirect_uri": MS_REDIRECT_URI,
                                "scope": MS_SCOPE,
                            },
                            headers={"Content-Type": "application/x-www-form-urlencoded"},
                        )
                        access = str(refreshed.get("access_token") or "")
                        refresh = str(refreshed.get("refresh_token") or refresh)
                        if not access:
                            continue
                        mc_token, profile = _exchange_ms_token(access)
                    except Exception:
                        continue

            saved = {
                "refresh_token": refresh,
                "minecraft_token": mc_token,
                "name": profile.get("name", ""),
                "uuid": str(profile.get("id", "")).replace("-", ""),
                "updated_at": int(time.time()),
                "source": "official_minecraft_launcher",
            }
            if saved["name"] and saved["uuid"]:
                _save(saved)
                return saved

    raise RuntimeError(
        "No usable Minecraft Launcher account was found. Open the official "
        "Minecraft Launcher, sign in with the Microsoft account that owns "
        "Minecraft Java Edition, let it finish loading, then click Sign in "
        "with Microsoft in Z's Multi Tool again."
    )


def refresh_account() -> dict:
    data = load_auth()
    if not data or not data.get("refresh_token"):
        raise RuntimeError("No saved Microsoft session. Sign in to Minecraft first.")

    token = _post_json(
        MS_TOKEN_URL,
        stage="Microsoft token refresh",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": data["refresh_token"],
            "redirect_uri": MS_REDIRECT_URI,
            "scope": MS_SCOPE,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    access = token.get("access_token")
    refresh = token.get("refresh_token") or data["refresh_token"]
    if not access:
        raise RuntimeError("Microsoft did not return a refreshed access token.")

    mc_token, profile = _exchange_ms_token(access)
    saved = {
        "refresh_token": refresh,
        "minecraft_token": mc_token,
        "name": profile.get("name", ""),
        "uuid": str(profile.get("id", "")).replace("-", ""),
        "updated_at": int(time.time()),
    }
    _save(saved)
    return saved


def build_authorize_url() -> tuple[str, str]:
    """Build the Microsoft sign-in URL for this app's CLIENT_ID.

    CLIENT_ID here is Microsoft's own legacy "Minecraft Launcher" public
    client, which only supports the implicit token flow (response_type=token)
    - it has no client secret, so it can't do an authorization-code exchange.
    With response_type=token, after sign-in the browser lands on
    oauth20_desktop.srf with access_token/refresh_token in the URL fragment
    (after '#') rather than a code to exchange.
    """
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "token",
        "redirect_uri": MS_REDIRECT_URI,
        "scope": MS_SCOPE,
        "display": "touch",
        "locale": "en",
    }
    return f"{MS_AUTH_URL}?{urlencode(params)}", state


def _parse_url_params(raw: str) -> dict[str, str]:
    """Parse 'a=1&b=2' style params without treating '+' as a space.

    urllib.parse.parse_qs uses unquote_plus (form-encoding rules), which
    silently turns literal '+' characters into spaces. Access tokens are
    base64-ish blobs that often legitimately contain '+', so that corrupts
    them into a token that looks almost right but fails auth. We only want
    %XX escapes decoded, not '+' touched.
    """
    result: dict[str, str] = {}
    for pair in raw.split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        result[unquote(k)] = unquote(v)
    return result


def _extract_tokens(pasted: str) -> tuple[str, str]:
    """Pull access_token/refresh_token out of the pasted redirect URL.

    They're in the URL fragment (after '#'), not the query string, since
    this uses the implicit flow.
    """
    pasted = pasted.strip()
    if not pasted:
        raise RuntimeError("No URL was entered.")

    if "#" in pasted:
        raw = pasted.split("#", 1)[1]
    elif "?" in pasted:
        raw = pasted.split("?", 1)[1]
    else:
        raw = pasted

    qs = _parse_url_params(raw)
    if qs.get("error"):
        raise RuntimeError(f"Microsoft sign-in failed: {qs.get('error_description') or qs['error']}")
    if qs.get("removed") == "true" or (not qs and "removed=true" in pasted):
        raise RuntimeError(
            "That link has already been scrubbed by Microsoft's sign-in page "
            "(it shows '?removed=true') and no longer contains the token. "
            "Sign in again and copy the address bar contents immediately "
            "after the redirect happens, before the page finishes loading."
        )
    access = qs.get("access_token", "")
    refresh = qs.get("refresh_token", "")
    if not access:
        raise RuntimeError(
            "Could not find an access token in that URL. Make sure you copied "
            "the FULL address after signing in, including everything after the '#'."
        )
    return access, refresh


def complete_interactive_sign_in(pasted_redirect: str) -> dict:
    """Finish the browser sign-in flow given the user's pasted redirect URL."""
    access, refresh = _extract_tokens(pasted_redirect)

    mc_token, profile = _exchange_ms_token(access)
    saved = {
        "refresh_token": refresh,
        "minecraft_token": mc_token,
        "name": profile.get("name", ""),
        "uuid": str(profile.get("id", "")).replace("-", ""),
        "updated_at": int(time.time()),
        "source": "oauth_browser",
    }
    if not (saved["name"] and saved["uuid"]):
        raise RuntimeError("Signed in, but Minecraft did not return a valid profile.")
    _save(saved)
    return saved


def sign_in(
    on_code: Callable[[str], str | None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """Sign in with the Microsoft account that owns Minecraft: Java Edition.

    First tries to reuse an existing official Minecraft Launcher session
    (cheap, no browser needed - works on older launcher installs that still
    write launcher_accounts.json). If that isn't available, falls back to a
    real Microsoft OAuth sign-in: a browser window opens for the user to sign
    in directly with Microsoft, then `on_code` is called with the auth URL and
    must return whatever redirect URL/code the user pastes back (or None if
    they cancel).
    """
    if on_status:
        on_status("Checking for an existing Minecraft Launcher session…")
    try:
        account = import_official_launcher_account()
        if on_status:
            on_status(f"Signed in as {account['name']}")
        return account
    except Exception:
        pass

    if on_code is None:
        raise RuntimeError(
            "No existing Minecraft Launcher session was found, and this call "
            "site didn't provide a way to complete Microsoft sign-in in a "
            "browser. Pass an on_code callback."
        )

    auth_url, _state = build_authorize_url()
    if on_status:
        on_status("Opening Microsoft sign-in in your browser…")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    pasted = on_code(auth_url)
    if not pasted:
        raise RuntimeError("Sign-in was cancelled.")

    if on_status:
        on_status("Verifying with Xbox Live and Minecraft Services…")
    account = complete_interactive_sign_in(pasted)
    if on_status:
        on_status(f"Signed in as {account['name']}")
    return account


def get_account(refresh: bool = True) -> dict | None:
    data = load_auth()
    if not data:
        return None
    if refresh and data.get("refresh_token"):
        try:
            return refresh_account()
        except Exception:
            # Keep the cached profile available; the launcher can report a
            # useful token error rather than falsely claiming the user is logged out.
            pass
    return data