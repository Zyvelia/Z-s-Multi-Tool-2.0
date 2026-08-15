"""
game_providers.py
Fetches player stats from game APIs using a stored key from crypto_store.

Two kinds of provider:
    - Built-in (Fortnite, Steam): a known, tested request shape — pick
      one, paste a key, go.
    - "custom": a generic REST path for any other API that takes a key
      + a player identifier. You supply the base URL, which header the
      key goes in, and how the identifier slots in. This is what makes
      "works for all games that have them" possible without a
      hand-coded integration for every single game.
"""

import datetime
import urllib.parse

import requests

REQUEST_TIMEOUT = 8


class GameStatsError(Exception):
    """Raised when stats can't be retrieved — message is safe to show as-is."""


def _get(url, headers=None, params=None):
    try:
        resp = requests.get(url, headers=headers or {}, params=params or {}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise GameStatsError(f"Couldn't reach the API: {exc}") from exc

    if resp.status_code in (401, 403):
        raise GameStatsError("That API key was rejected — check it's correct, active, and hasn't expired.")
    if resp.status_code == 404:
        raise GameStatsError("Player not found.")
    if resp.status_code == 429:
        raise GameStatsError("Rate limited by the API — wait a bit and try again.")
    if not resp.ok:
        raise GameStatsError(f"API returned status {resp.status_code}.")

    try:
        return resp.json()
    except ValueError as exc:
        raise GameStatsError("API didn't return valid JSON.") from exc


# ---------------------------------------------------------------------------
# Built-in providers
# ---------------------------------------------------------------------------

_FORTNITE_MODES = [
    ("solo", "Solo"),
    ("duo", "Duo"),
    ("squad", "Squad"),
    ("ltm", "LTM"),
]


def fetch_fortnite_stats(identifier, api_key, extra=None):
    data = _get(
        "https://fortnite-api.com/v2/stats/br/v2",
        headers={"Authorization": api_key},
        params={"name": identifier},
    )
    d = data.get("data") or {}
    account = d.get("account") or {}
    all_stats = (d.get("stats") or {}).get("all") or {}
    overall = all_stats.get("overall") or {}
    if not overall:
        raise GameStatsError("No stats found — either the name's wrong, stats are private, or they haven't played BR.")

    rows = [
        ("Wins", overall.get("wins", 0)),
        ("Kills", overall.get("kills", 0)),
        ("K/D ratio", overall.get("kd", 0)),
        ("Win rate", f"{overall.get('winRate', 0)}%"),
        ("Matches played", overall.get("matches", 0)),
        ("Top 10s", overall.get("top10", "—")),
        ("Top 25s", overall.get("top25", "—")),
        ("Minutes played", overall.get("minutesPlayed", "—")),
    ]

    # Per-mode breakdown — everything the free key exposes beyond the
    # combined "all" total.
    for mode_key, mode_label in _FORTNITE_MODES:
        m = all_stats.get(mode_key)
        if not m:
            continue
        rows.append((f"{mode_label} — Wins", m.get("wins", 0)))
        rows.append((f"{mode_label} — K/D", m.get("kd", 0)))
        rows.append((f"{mode_label} — Win rate", f"{m.get('winRate', 0)}%"))
        rows.append((f"{mode_label} — Matches", m.get("matches", 0)))

    battle_pass = d.get("battlePass") or {}
    if battle_pass:
        rows.append(("Battle Pass level", battle_pass.get("level", "—")))
        rows.append(("Battle Pass progress", f"{battle_pass.get('progress', '—')}%"))

    return {
        "player": account.get("name", identifier),
        "rows": rows,
    }


_STEAM_STATUS = {
    0: "Offline", 1: "Online", 2: "Busy", 3: "Away",
    4: "Snooze", 5: "Looking to trade", 6: "Looking to play",
}


def fetch_steam_stats(identifier, api_key, extra=None):
    data = _get(
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/",
        params={"key": api_key, "steamids": identifier},
    )
    players = (data.get("response") or {}).get("players") or []
    if not players:
        raise GameStatsError("No Steam player found for that SteamID64.")
    p = players[0]

    rows = [
        ("Status", _STEAM_STATUS.get(p.get("personastate"), "Unknown")),
        ("Profile", "Public" if p.get("communityvisibilitystate") == 3 else "Private"),
    ]
    if p.get("gameextrainfo"):
        rows.append(("Currently playing", p["gameextrainfo"]))
    if p.get("lastlogoff"):
        ts = datetime.datetime.fromtimestamp(p["lastlogoff"]).strftime("%Y-%m-%d %H:%M")
        rows.append(("Last online", ts))
    if p.get("timecreated"):
        ts = datetime.datetime.fromtimestamp(p["timecreated"]).strftime("%Y-%m-%d")
        rows.append(("Account created", ts))

    return {"player": p.get("personaname", identifier), "rows": rows}


# ---------------------------------------------------------------------------
# Supercell providers (Clash of Clans, Clash Royale, Brawl Stars)
#
# All three use the same shape: Bearer token, GET /v1/players/{tag}, tag
# starts with "#" (which must be percent-encoded to %23 in the URL path).
#
# NOTE: Supercell API keys are locked to the IP address that was current
# when the key was created. If the machine's public IP changes later,
# calls start failing with 401/403 until a new key is generated for the
# new IP — that's expected and not a bug here.
# ---------------------------------------------------------------------------

def _supercell_tag(identifier):
    tag = identifier.strip().upper()
    if not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


def fetch_clash_of_clans_stats(identifier, api_key, extra=None):
    tag = _supercell_tag(identifier)
    data = _get(
        f"https://api.clashofclans.com/v1/players/{urllib.parse.quote(tag)}",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    clan = data.get("clan") or {}
    league = data.get("league") or {}
    rows = [
        ("Town Hall level", data.get("townHallLevel", "—")),
        ("Experience level", data.get("expLevel", "—")),
        ("Trophies", data.get("trophies", 0)),
        ("Best trophies", data.get("bestTrophies", 0)),
        ("League", league.get("name", "Unranked")),
        ("War stars", data.get("warStars", "—")),
        ("Attack wins", data.get("attackWins", "—")),
        ("Defense wins", data.get("defenseWins", "—")),
        ("Donations", data.get("donations", "—")),
        ("Donations received", data.get("donationsReceived", "—")),
    ]
    if data.get("builderHallLevel") is not None:
        rows.append(("Builder Hall level", data.get("builderHallLevel")))
        rows.append(("Builder Base trophies", data.get("builderBaseTrophies", 0)))
        rows.append(("Best Builder Base trophies", data.get("bestBuilderBaseTrophies", 0)))
    if clan:
        rows.append(("Clan", clan.get("name", "—")))
        rows.append(("Clan role", data.get("role", "—")))

    return {"player": data.get("name", identifier), "rows": rows}


def fetch_clash_royale_stats(identifier, api_key, extra=None):
    tag = _supercell_tag(identifier)
    data = _get(
        f"https://api.clashroyale.com/v1/players/{urllib.parse.quote(tag)}",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    clan = data.get("clan") or {}
    arena = data.get("arena") or {}
    rows = [
        ("Trophies", data.get("trophies", 0)),
        ("Best trophies", data.get("bestTrophies", 0)),
        ("Arena", arena.get("name", "—")),
        ("Experience level", data.get("expLevel", "—")),
        ("Wins", data.get("wins", 0)),
        ("Losses", data.get("losses", 0)),
        ("Battle count", data.get("battleCount", 0)),
        ("Three-crown wins", data.get("threeCrownWins", "—")),
        ("Donations", data.get("donations", "—")),
        ("Total donations", data.get("totalDonations", "—")),
    ]
    if clan:
        rows.append(("Clan", clan.get("name", "—")))
        rows.append(("Clan role", data.get("role", "—")))

    return {"player": data.get("name", identifier), "rows": rows}


def fetch_brawl_stars_stats(identifier, api_key, extra=None):
    tag = _supercell_tag(identifier)
    data = _get(
        f"https://api.brawlstars.com/v1/players/{urllib.parse.quote(tag)}",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    club = data.get("club") or {}
    rows = [
        ("Trophies", data.get("trophies", 0)),
        ("Highest trophies", data.get("highestTrophies", 0)),
        ("Experience level", data.get("expLevel", "—")),
        ("3v3 victories", data.get("3vs3Victories", 0)),
        ("Solo victories", data.get("soloVictories", 0)),
        ("Duo victories", data.get("duoVictories", 0)),
        ("Brawlers unlocked", len(data.get("brawlers") or [])),
    ]
    if club:
        rows.append(("Club", club.get("name", "—")))
        rows.append(("Club role", club.get("role", "—")))

    return {"player": data.get("name", identifier), "rows": rows}


def fetch_custom_stats(identifier, api_key, extra=None):
    """Generic path: any REST API taking a key + a player identifier.

    extra:
        base_url      - may contain "{id}" to interpolate the identifier
                         directly into the URL; otherwise the identifier
                         is sent as a query param named id_param
        header_name    - e.g. "Authorization", "x-api-key" (blank = no auth header)
        header_prefix  - e.g. "Bearer " (optional, prepended to the key)
        id_param       - query param name when "{id}" isn't in base_url (default "name")
    """
    extra = extra or {}
    base_url = extra.get("base_url", "").strip()
    if not base_url:
        raise GameStatsError("This custom key has no base URL configured — edit it in API Keys.")

    headers = {}
    header_name = extra.get("header_name", "").strip()
    if header_name:
        prefix = extra.get("header_prefix", "")
        headers[header_name] = f"{prefix}{api_key}"

    if "{id}" in base_url:
        url = base_url.replace("{id}", identifier)
        params = None
    else:
        url = base_url
        params = {extra.get("id_param") or "name": identifier}

    data = _get(url, headers=headers, params=params)

    # We don't know this API's response shape, so just show it flattened —
    # one row per top-level field, nested structures shown as compact JSON.
    rows = []
    if isinstance(data, dict):
        for k, v in data.items():
            rows.append((str(k), v if isinstance(v, (str, int, float, bool)) or v is None else str(v)))
    else:
        rows.append(("Response", str(data)))

    return {"player": identifier, "rows": rows or [("Response", "(empty)")]}


PROVIDERS = {
    "fortnite": {
        "name": "Fortnite",
        "icon": "🏆",
        "id_label": "Epic display name",
        "key_help": "Free — generate one on the Fortnite-API dashboard (login with Discord).",
        "key_url": "https://dash.fortnite-api.com/account",
        "fetch": fetch_fortnite_stats,
        "needs_extra": False,
    },
    "steam": {
        "name": "Steam",
        "icon": "🎮",
        "id_label": "SteamID64",
        "key_help": "Free — from your Steam Web API key page (needs a phone number on the account).",
        "key_url": "https://steamcommunity.com/dev/apikey",
        "fetch": fetch_steam_stats,
        "needs_extra": False,
    },
    "clash_of_clans": {
        "name": "Clash of Clans",
        "icon": "⚔️",
        "id_label": "Player tag (e.g. #2PP0JJVU)",
        "key_help": "Free — create a key on the Clash of Clans developer site. The key is locked to your "
                     "current public IP; if your IP changes later, generate a new key for it.",
        "key_url": "https://developer.clashofclans.com/#/account",
        "fetch": fetch_clash_of_clans_stats,
        "needs_extra": False,
    },
    "clash_royale": {
        "name": "Clash Royale",
        "icon": "👑",
        "id_label": "Player tag (e.g. #2PP0JJVU)",
        "key_help": "Free — create a key on the Clash Royale developer site. The key is locked to your "
                     "current public IP; if your IP changes later, generate a new key for it.",
        "key_url": "https://developer.clashroyale.com/#/account",
        "fetch": fetch_clash_royale_stats,
        "needs_extra": False,
    },
    "brawl_stars": {
        "name": "Brawl Stars",
        "icon": "🌟",
        "id_label": "Player tag (e.g. #2PP0JJVU)",
        "key_help": "Free — create a key on the Brawl Stars developer site. The key is locked to your "
                     "current public IP; if your IP changes later, generate a new key for it.",
        "key_url": "https://developer.brawlstars.com/#/account",
        "fetch": fetch_brawl_stars_stats,
        "needs_extra": False,
    },
    "custom": {
        "name": "Custom API",
        "icon": "🔧",
        "id_label": "Player identifier",
        "key_help": "Point this at any game's REST stats API — you fill in the URL and auth header.",
        "key_url": "",
        "fetch": fetch_custom_stats,
        "needs_extra": True,
    },
}


def fetch_stats(provider, identifier, api_key, extra=None):
    entry = PROVIDERS.get(provider)
    if not entry:
        raise GameStatsError(f"Unknown provider: {provider}")
    identifier = (identifier or "").strip()
    if not identifier:
        raise GameStatsError(f"Enter a {entry['id_label'].lower()}.")
    return entry["fetch"](identifier, api_key, extra)
