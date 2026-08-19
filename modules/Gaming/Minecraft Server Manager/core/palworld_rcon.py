"""Palworld RCON helpers — wraps generic Source RCON client."""

from __future__ import annotations

from dataclasses import dataclass

from .source_rcon import SourceRconClient, SourceRconError

PalworldRconError = SourceRconError


@dataclass
class PalPlayer:
    name: str
    player_uid: str
    steam_id: str


class PalworldRconClient(SourceRconClient):
    def show_players(self) -> list[PalPlayer]:
        text = self.execute("ShowPlayers", max_attempts=10)
        if not text.endswith("\n"):
            text += "\n"
        return parse_show_players(text)

    def kick_player(self, steam_id: str) -> str:
        return self.execute(f"KickPlayer {steam_id}")

    def broadcast(self, message: str) -> str:
        return self.execute(f"Broadcast {message}")


def parse_show_players(text: str) -> list[PalPlayer]:
    players: list[PalPlayer] = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("name,"):
            continue
        parts = line.rsplit(",", 2)
        if len(parts) != 3:
            continue
        name, uid, steam_id = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not steam_id.isdigit():
            continue
        players.append(PalPlayer(name=name, player_uid=uid, steam_id=steam_id))
    return players
