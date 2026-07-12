import os
import re
import json
import string

from .models import Game
from core import paths


class GameScanner:

    # Class variable for the blocked games file path
    BLOCK_FILE = paths.migrate_legacy_file(
        paths.data_path("gaming_hub", "blocked_games.json"),
        "modules", "gaming_hub", "blocked_games.json"
    )

    # Common Steam install folder names to check on every drive
    STEAM_SUBPATHS = [
        r"Program Files (x86)\Steam\steamapps",
        r"Program Files\Steam\steamapps",
        r"SteamLibrary\steamapps",
        r"Steam\steamapps",
    ]

    def __init__(self):
        # 1. Inside __init__: This line is already present as requested.
        self.blocked_games = self.load_blocked()

    @staticmethod
    def detect_drives():
        """
        Returns every drive letter that currently exists on this machine,
        e.g. ["C:", "D:", "E:"]. Used both to populate the drive checklist
        in Settings and as the default scan set when the user hasn't
        picked specific drives.
        """
        drives = []
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(f"{letter}:")
        return drives

    def steam_candidates_for_drives(self, drives):
        """
        Builds the list of steamapps paths to check across the given
        drives (e.g. ["C:", "D:"]), using the common Steam install
        locations under each one.
        """
        candidates = []
        for drive in drives:
            for sub in self.STEAM_SUBPATHS:
                candidates.append(os.path.join(f"{drive}\\", sub))
        return candidates

    # Re-added find_exe method as it's used by scan_steam_library
    def find_exe(
        self,
        folder
    ):
        """
        Searches for the first .exe file in the given folder and its subdirectories.
        """
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(".exe"):
                    return os.path.join(
                        root,
                        file
                    )
        return ""

    def scan_steam_library(
        self,
        steamapps_path
    ):
        """
        Scans a specific Steam 'steamapps' directory for installed games.
        """
        games = []

        if not os.path.exists(steamapps_path):
            return games

        common_path = os.path.join(
            steamapps_path,
            "common"
        )

        if not os.path.exists(common_path):
            return games


        for file in os.listdir(steamapps_path):

            if not file.startswith(
                "appmanifest_"
            ):
                continue

            if not file.endswith(".acf"):
                continue

            manifest = os.path.join(
                steamapps_path,
                file
            )

            try:

                with open(
                    manifest,
                    "r",
                    encoding="utf-8",
                    errors="ignore"
                ) as f:

                    content = f.read()

                name_match = re.search(
                    r'"name"\s+"([^"]+)"',
                    content
                )

                dir_match = re.search(
                    r'"installdir"\s+"([^"]+)"',
                    content
                )

                if not name_match:
                    continue

                game_name = name_match.group(1)

                # 3. Add game_name.lower() check after getting the game name
                if game_name.lower() in self.blocked_games:
                    continue

                install_dir = (
                    dir_match.group(1)
                    if dir_match
                    else game_name
                )

                game_path = os.path.join(
                    common_path,
                    install_dir
                )

                exe = self.find_exe(
                    game_path
                )
                
                # Only append if an executable was found
                if exe:
                    games.append(
                        Game(
                            name=game_name,
                            path=game_path,
                            launcher="Steam",
                            exe_path=exe
                        )
                    )

            except Exception as e:

                print(
                    f"Steam manifest error: {e}"
                )

        return games

    def scan_epic_library(
        self,
        manifests_path=r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
    ):
        """
        Scans the Epic Games Launcher's manifest folder for installed games.
        Epic writes one .item file (plain JSON, despite the extension) per
        installed game to this folder — no per-drive library scanning
        needed like Steam, Epic tracks everything centrally here regardless
        of which drive a game was actually installed to.
        """
        games = []

        if not os.path.exists(manifests_path):
            return games

        for file in os.listdir(manifests_path):

            if not file.lower().endswith(".item"):
                continue

            manifest = os.path.join(manifests_path, file)

            try:

                with open(
                    manifest,
                    "r",
                    encoding="utf-8",
                    errors="ignore"
                ) as f:
                    data = json.load(f)

                game_name = data.get("DisplayName")

                if not game_name:
                    continue

                if game_name.lower() in self.blocked_games:
                    continue

                install_location = data.get("InstallLocation", "")
                launch_exe = data.get("LaunchExecutable", "")

                exe = ""

                if install_location and launch_exe:
                    candidate = os.path.join(install_location, launch_exe)
                    if os.path.exists(candidate):
                        exe = candidate

                if not exe and install_location:
                    exe = self.find_exe(install_location)

                if exe:
                    games.append(
                        Game(
                            name=game_name,
                            path=install_location,
                            launcher="Epic",
                            exe_path=exe
                        )
                    )

            except Exception as e:

                print(
                    f"Epic manifest error: {e}"
                )

        return games

    def scan(self, drives=None):
        """
        Scans Steam library paths across the given drives (or every
        detected drive, if none given) plus the Epic Games Launcher's
        manifest folder for installed games.

        drives: optional list like ["C:", "D:"] — pass this to limit
        scanning to specific drives (from the Settings tab). Leave as
        None to auto-detect and scan every drive on the machine.
        """
        # 2. At the very top of scan(): Add this line
        self.blocked_games = self.load_blocked()

        games = []

        scan_drives = drives if drives is not None else self.detect_drives()

        for library in self.steam_candidates_for_drives(scan_drives):

            games.extend(
                self.scan_steam_library(
                    library
                )
            )

        games.extend(
            self.scan_epic_library()
        )

        return games

    def load_blocked(self):
        """
        Loads a set of blocked game names from a JSON file.
        """
        try:
            with open(
                self.BLOCK_FILE,
                "r",
                encoding="utf-8"
            ) as f:
                data = json.load(f)
            # 4. In load_blocked(): Change return to use set comprehension with lower()
            return {
                game.lower()
                for game in data.get(
                    "blocked",
                    []
                )
            }
        except Exception:
            return set()

    def save_blocked(self):
        """
        Saves the current set of blocked game names to a JSON file.
        """
        with open(
            self.BLOCK_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "blocked": list(
                        self.blocked_games
                    )
                },
                f,
                indent=4
            )

    def block_game(
        self,
        game_name
    ):
        """
        Blocks a game by adding its name to the blocked list and saving it.
        """
        # 5. In block_game(): Add game_name.lower()
        self.blocked_games.add(
            game_name.lower()
        )
        self.save_blocked()