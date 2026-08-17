"""
hibp_api.py
Thin client for the "Have I Been Pwned" (HIBP) services.

Two completely separate APIs are used here:

1. Pwned Passwords (k-anonymity range search) - FREE, no API key
   required. Only the first 5 hex characters of a SHA-1 hash of the
   password are ever sent over the network; the full password (and
   even the full hash) never leaves this machine.
   https://haveibeenpwned.com/API/v3#PwnedPasswords

2. Breached Account lookup - requires a personal HIBP API key (paid
   subscription). The key is supplied by the user at runtime and is
   only ever held in memory for the session (see security.py) - this
   module never writes it to disk, logs, or settings.
   https://haveibeenpwned.com/API/Key
"""

import hashlib
import requests

PWNED_PASSWORDS_URL = "https://api.pwnedpasswords.com/range/{prefix}"
BREACHED_ACCOUNT_URL = "https://haveibeenpwned.com/api/v3/breachedaccount/{account}"
ALL_BREACHES_URL = "https://haveibeenpwned.com/api/v3/breaches"

USER_AGENT = "Zs-Multi-Tool-Breach-Checker"

TIMEOUT = 15


class HIBPError(Exception):
    """Raised for any HIBP request failure (network, auth, rate-limit, etc)."""


# ---------------------------------------------------------------------------
# Pwned Passwords (free, no key)
# ---------------------------------------------------------------------------

def check_password(password: str) -> int:
    """
    Returns how many times this password has appeared in known breach
    dumps, using the k-anonymity range API. Returns 0 if never seen.
    Raises HIBPError on network/API failure.
    """
    if not password:
        raise HIBPError("No password provided.")

    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    try:
        resp = requests.get(
            PWNED_PASSWORDS_URL.format(prefix=prefix),
            headers={"User-Agent": USER_AGENT, "Add-Padding": "true"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise HIBPError(f"Network error: {e}") from e

    if resp.status_code != 200:
        raise HIBPError(f"Pwned Passwords API returned status {resp.status_code}")

    for line in resp.text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        line_suffix, _, count = line.partition(":")
        if line_suffix.strip().upper() == suffix:
            try:
                return int(count.strip())
            except ValueError:
                return 0

    return 0


# ---------------------------------------------------------------------------
# Breached Account lookup (requires the user's own HIBP API key)
# ---------------------------------------------------------------------------

def check_account(account: str, api_key: str, truncate: bool = False):
    """
    Looks up an email/username against HIBP's breach database.
    Returns a list of breach dicts (empty list = no known breaches).
    Raises HIBPError on missing key, auth failure, rate limiting, or
    network errors.
    """
    if not account or not account.strip():
        raise HIBPError("No account/email provided.")
    if not api_key or not api_key.strip():
        raise HIBPError(
            "An HIBP API key is required for account lookups. "
            "Get one at haveibeenpwned.com/API/Key."
        )

    url = BREACHED_ACCOUNT_URL.format(account=requests.utils.quote(account.strip(), safe=""))
    params = {"truncateResponse": "true" if truncate else "false"}
    headers = {
        "hibp-api-key": api_key.strip(),
        "User-Agent": USER_AGENT,
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise HIBPError(f"Network error: {e}") from e

    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError:
            raise HIBPError("Unexpected (non-JSON) response from HIBP.")
    if resp.status_code == 404:
        return []
    if resp.status_code == 401:
        raise HIBPError("Invalid or missing HIBP API key.")
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "a few")
        raise HIBPError(f"Rate limited by HIBP - try again in {retry_after} seconds.")
    if resp.status_code == 400:
        raise HIBPError("Bad request - is the email address valid?")
    raise HIBPError(f"HIBP API returned status {resp.status_code}")


def get_all_breaches():
    """
    Fetches the full public list of breach metadata (name, domain,
    date, description, data classes, etc). No API key required. Used
    to resolve a truncated breach name into full details if ever
    needed, or to browse the breach corpus.
    """
    try:
        resp = requests.get(
            ALL_BREACHES_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HIBPError(f"Network error: {e}") from e
