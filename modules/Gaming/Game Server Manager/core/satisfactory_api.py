"""Minimal Satisfactory dedicated server HTTPS API client."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests

SATISFACTORY_API_TIMEOUT = 12.0


class SatisfactoryApiError(Exception):
    pass


class SatisfactoryApiClient:
    """Talks to the local HTTPS API (self-signed TLS on the game port)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7777,
        *,
        api_token: str = "",
        admin_password: str = "",
        timeout: float = SATISFACTORY_API_TIMEOUT,
    ):
        self.host = host
        self.port = int(port)
        self.api_token = api_token.strip()
        self.admin_password = admin_password.strip()
        self.timeout = timeout
        self._session_token = ""

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}/api/v1/"

    def _post(
        self,
        function: str,
        data: dict[str, Any] | None = None,
        *,
        token: str | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"function": function}
        if data is not None:
            payload["data"] = data

        headers = {"Content-Type": "application/json"}
        auth = token or self._auth_token()
        if auth:
            headers["Authorization"] = f"Bearer {auth}"

        url = f"{self.base_url}?function={quote(function)}"
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=False,
            )
        except requests.RequestException as e:
            raise SatisfactoryApiError(f"HTTPS API unreachable at {self.host}:{self.port}: {e}") from e

        if resp.status_code == 204:
            return None

        body: dict[str, Any] | None = None
        if resp.content:
            try:
                body = resp.json()
            except json.JSONDecodeError as e:
                raise SatisfactoryApiError(
                    f"HTTPS API returned non-JSON ({resp.status_code}): {resp.text[:200]}"
                ) from e

        if resp.status_code >= 400:
            err = (body or {}).get("errorMessage") or (body or {}).get("errorCode") or resp.text[:200]
            raise SatisfactoryApiError(f"HTTPS API error ({resp.status_code}): {err}")

        if body and "errorCode" in body:
            err = body.get("errorMessage") or body.get("errorCode")
            raise SatisfactoryApiError(str(err))

        return body

    def _auth_token(self) -> str:
        if self.api_token:
            return self.api_token
        return self._session_token

    def ensure_authenticated(self) -> None:
        if self.api_token or self._session_token:
            return

        if self.admin_password:
            body = self._post(
                "PasswordLogin",
                {
                    "minimumPrivilegeLevel": "Administrator",
                    "password": self.admin_password,
                },
                token="",
            )
        else:
            body = self._post(
                "PasswordlessLogin",
                {"minimumPrivilegeLevel": "Administrator"},
                token="",
            )

        if not body or "data" not in body:
            raise SatisfactoryApiError(
                "HTTPS API login failed — set Admin password or API token in Config, "
                "or claim the server in-game and enable local API access."
            )
        token = str(body["data"].get("authenticationToken", "")).strip()
        if not token:
            raise SatisfactoryApiError("HTTPS API login returned no token.")
        self._session_token = token

    def run_command(self, command: str) -> str:
        self.ensure_authenticated()
        body = self._post("RunCommand", {"command": command})
        if not body:
            return ""
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("commandResult", "result", "output"):
                if key in data and data[key]:
                    return str(data[key])
        if isinstance(data, str):
            return data
        return ""

    def shutdown(self) -> None:
        self.ensure_authenticated()
        self._post("Shutdown")

    def save_game(self, save_name: str) -> None:
        self.ensure_authenticated()
        self._post("SaveGame", {"saveName": save_name})

    def query_server_state(self) -> dict[str, Any]:
        self.ensure_authenticated()
        body = self._post("QueryServerState")
        if not body:
            return {}
        data = body.get("data")
        return data if isinstance(data, dict) else {}


def satisfactory_api_client(config: dict) -> SatisfactoryApiClient:
    try:
        port = int(str(config.get("port", "7777")).strip() or "7777")
    except ValueError:
        port = 7777
    return SatisfactoryApiClient(
        port=port,
        api_token=str(config.get("api_token", "")).strip(),
        admin_password=str(config.get("admin_password", "")).strip(),
    )
