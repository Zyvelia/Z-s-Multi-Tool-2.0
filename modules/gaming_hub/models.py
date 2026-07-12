from dataclasses import dataclass


@dataclass
class Game:

    name: str

    path: str

    launcher: str = "Unknown"

    exe_path: str = ""

    save_path: str = ""