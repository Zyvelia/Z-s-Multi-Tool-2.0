import os
import re
import json
import string
import datetime
from dataclasses import asdict

try:
    import winreg
except ImportError:
    # Registry access is Windows-only. On any other platform the
    # registry-based scanners below just return an empty list instead
    # of failing at import time.
    winreg = None

from .models import Game
from core import paths


class GameScanner:

    # Class variable for the blocked games file path
    BLOCK_FILE = paths.migrate_legacy_file(
        paths.data_path("gaming_hub", "blocked_games.json"),
        "modules", "gaming_hub", "blocked_games.json"
    )

    # Where the results of the most recent scan get cached, so other
    # code (or a future run) can see what was found without rescanning.
    CACHE_FILE = paths.data_path("gaming_hub", "games_cache.json")

    # Common Steam install folder names to check on every drive
    STEAM_SUBPATHS = [
        r"Program Files (x86)\Steam\steamapps",
        r"Program Files\Steam\steamapps",
        r"SteamLibrary\steamapps",
        r"Steam\steamapps",
    ]

    # Default GOG Galaxy install root on a given drive. Galaxy only lets
    # you set one library root at a time, but people commonly end up with
    # a "GOG Games" folder on more than one drive over time (reinstalls,
    # moving to a bigger drive, etc.) — so, like Steam, every drive gets
    # checked rather than assuming everything is on C:.
    GOG_SUBPATHS = [
        r"GOG Games",
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

    def gog_candidates_for_drives(self, drives):
        """
        Builds the list of "GOG Games" folder paths to check across the
        given drives, same idea as steam_candidates_for_drives.
        """
        candidates = []
        for drive in drives:
            for sub in self.GOG_SUBPATHS:
                candidates.append(os.path.join(f"{drive}\\", sub))
        return candidates

    # Folder names that are almost never where a game's real .exe lives —
    # redistributable installers, engine internals, DLC blobs, etc. Skipping
    # these keeps find_exe() from wasting time digging through them on
    # large/cluttered game folders.
    SKIP_DIRS = {
        "_commonredist", "redist", "redistributables",
        "directx", "dotnet", "vcredist",
        "engine", "binaries", "intermediate",
        "dlc", "soundtrack", "extras", "artbook",
        "__pycache__", ".git",
    }

    # Re-added find_exe method as it's used by scan_steam_library
    def find_exe(
        self,
        folder,
        max_depth=4
    ):
        """
        Searches for the first .exe file in the given folder and its
        subdirectories, breadth-first-ish via os.walk.

        max_depth caps how many levels below `folder` it will descend
        (0 = only the top-level folder itself). Most games put their
        main .exe at or near the top, so this avoids arbitrarily deep
        walks through huge, deeply-nested install trees. Known junk
        folders (see SKIP_DIRS) are pruned outright regardless of depth.
        """
        base_depth = folder.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(folder):
            depth = root.rstrip(os.sep).count(os.sep) - base_depth

            if depth >= max_depth:
                dirs[:] = []  # don't descend any further from here
            else:
                dirs[:] = [
                    d for d in dirs
                    if d.lower() not in self.SKIP_DIRS
                ]

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

    @staticmethod
    def _reg_value(key, name):
        """Reads a single registry value, returning None if it's missing
        instead of raising — every registry-based scanner below leans on
        this since not every game's entry has every field populated."""
        try:
            value, _ = winreg.QueryValueEx(key, name)
            return value
        except FileNotFoundError:
            return None

    def _iter_subkeys(self, hive, key_path):
        """Yields (name, opened key) for every subkey under key_path, or
        nothing at all if the key doesn't exist (launcher not installed)
        or winreg isn't available (non-Windows)."""
        if winreg is None:
            return

        try:
            root_key = winreg.OpenKey(hive, key_path)
        except FileNotFoundError:
            return
        except Exception as e:
            print(f"Registry open error ({key_path}): {e}")
            return

        with root_key:
            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(root_key, index)
                except OSError:
                    break
                index += 1

                try:
                    with winreg.OpenKey(root_key, subkey_name) as subkey:
                        yield subkey_name, subkey
                except Exception as e:
                    print(f"Registry subkey error ({key_path}\\{subkey_name}): {e}")

    def _scan_gog_registry(self):
        """
        Scans GOG Galaxy's registry entries for installed games. GOG
        writes one subkey per installed game under Games, holding the
        display name, install path, and launch exe — checks both the
        64-bit (WOW6432Node) and 32-bit registry locations since which
        one GOG uses depends on the installed Python/OS bitness.

        Covers every drive automatically (each entry's "path" is already
        the full install location), but only catches games GOG actually
        wrote a registry entry for — see scan_gog_folder() for the
        drive-scan fallback that catches everything else.
        """
        games = []
        seen_ids = set()

        key_paths = [
            r"SOFTWARE\WOW6432Node\GOG.com\Games",
            r"SOFTWARE\GOG.com\Games",
        ]

        for key_path in key_paths:
            for game_id, game_key in self._iter_subkeys(winreg.HKEY_LOCAL_MACHINE if winreg else None, key_path):
                if game_id in seen_ids:
                    continue
                seen_ids.add(game_id)

                game_name = self._reg_value(game_key, "gameName")
                install_path = self._reg_value(game_key, "path")
                exe_name = self._reg_value(game_key, "exe")

                if not game_name or not install_path:
                    continue

                if game_name.lower() in self.blocked_games:
                    continue

                exe = ""
                if exe_name:
                    candidate = exe_name if os.path.isabs(exe_name) else os.path.join(install_path, exe_name)
                    if os.path.exists(candidate):
                        exe = candidate
                if not exe:
                    exe = self.find_exe(install_path)

                if exe:
                    games.append(
                        Game(
                            name=game_name,
                            path=install_path,
                            launcher="GOG",
                            exe_path=exe
                        )
                    )

        return games

    def scan_gog_folder(self, root_path):
        """
        Scans a "GOG Games" style folder for installed games, reading the
        goggame-<id>.info manifest Galaxy drops inside each game's own
        folder (same idea as Steam's appmanifest_*.acf files). Falls back
        to the folder name itself if a game's .info file is missing or
        unreadable, so a game still shows up even without a clean name.

        This exists as a companion to _scan_gog_registry() — it catches
        games on a drive that never got (or lost) a registry entry, e.g.
        an offline/standalone installer, a moved install, or a restored
        backup.
        """
        games = []

        if not os.path.exists(root_path):
            return games

        for entry in os.listdir(root_path):
            game_dir = os.path.join(root_path, entry)

            if not os.path.isdir(game_dir):
                continue

            game_name = None
            try:
                for fname in os.listdir(game_dir):
                    if fname.lower().startswith("goggame-") and fname.lower().endswith(".info"):
                        try:
                            with open(
                                os.path.join(game_dir, fname),
                                "r", encoding="utf-8", errors="ignore"
                            ) as f:
                                info = json.load(f)
                            game_name = info.get("name")
                        except Exception as e:
                            print(f"GOG info file error ({fname}): {e}")
                        break
            except Exception as e:
                print(f"GOG folder read error ({game_dir}): {e}")

            if not game_name:
                game_name = entry  # no/unreadable manifest — folder name is the best we've got

            if game_name.lower() in self.blocked_games:
                continue

            exe = self.find_exe(game_dir)

            if exe:
                games.append(
                    Game(
                        name=game_name,
                        path=game_dir,
                        launcher="GOG",
                        exe_path=exe
                    )
                )

        return games

    def scan_gog_library(self, drives=None):
        """
        Combines both GOG detection methods and de-duplicates the result
        by resolved exe path:
          1. Registry entries — covers every Galaxy-installed game
             regardless of drive, as long as GOG actually wrote one.
          2. A "GOG Games" folder scan across the given drives (or every
             detected drive if none given) — catches installs that don't
             have a registry entry for whatever reason.
        """
        games = {}

        for g in self._scan_gog_registry():
            games[os.path.normcase(g.exe_path)] = g

        scan_drives = drives if drives is not None else self.detect_drives()
        for folder in self.gog_candidates_for_drives(scan_drives):
            for g in self.scan_gog_folder(folder):
                key = os.path.normcase(g.exe_path)
                if key not in games:
                    games[key] = g

        return list(games.values())

    def scan_ubisoft_library(self):
        """
        Scans Ubisoft Connect's registry entries for installed games.
        Unlike GOG/Epic, Ubisoft's registry only stores an install
        directory per game ID — no display name — so the folder name is
        used as the game's name instead, the same fallback pattern
        already used above for a Steam manifest missing its own name.
        """
        games = []
        key_path = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"

        for game_id, game_key in self._iter_subkeys(winreg.HKEY_LOCAL_MACHINE if winreg else None, key_path):
            install_dir = self._reg_value(game_key, "InstallDir")

            if not install_dir or not os.path.exists(install_dir):
                continue

            game_name = os.path.basename(os.path.normpath(install_dir))

            if game_name.lower() in self.blocked_games:
                continue

            exe = self.find_exe(install_dir)

            if exe:
                games.append(
                    Game(
                        name=game_name,
                        path=install_dir,
                        launcher="Ubisoft Connect",
                        exe_path=exe
                    )
                )

        return games

    def scan_ea_library(self):
        """
        Scans EA/Origin's registry entries for installed games. Both the
        legacy Origin client and the current EA App still register
        installed titles the same way, under 'Origin Games' — each
        subkey has a DisplayName and Install Dir.
        """
        games = []
        key_path = r"SOFTWARE\WOW6432Node\Origin Games"

        for game_id, game_key in self._iter_subkeys(winreg.HKEY_LOCAL_MACHINE if winreg else None, key_path):
            install_dir = self._reg_value(game_key, "Install Dir")

            if not install_dir or not os.path.exists(install_dir):
                continue

            game_name = self._reg_value(game_key, "DisplayName") or \
                os.path.basename(os.path.normpath(install_dir))

            if game_name.lower() in self.blocked_games:
                continue

            exe = self.find_exe(install_dir)

            if exe:
                games.append(
                    Game(
                        name=game_name,
                        path=install_dir,
                        launcher="EA / Origin",
                        exe_path=exe
                    )
                )

        return games

    def scan(self, drives=None):
        """
        Scans Steam library paths across the given drives (or every
        detected drive, if none given), plus the Epic Games Launcher's
        manifest folder, and GOG Galaxy / Ubisoft Connect / EA App
        (Origin)'s registry entries for installed games.

        drives: optional list like ["C:", "D:"] — pass this to limit
        scanning to specific drives (from the Settings tab). Leave as
        None to auto-detect and scan every drive on the machine. Only
        Steam is drive-scanned this way; the other launchers track
        install locations centrally (a manifest folder or the registry)
        regardless of which drive games actually live on.
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

        games.extend(self.scan_gog_library(drives=scan_drives))
        games.extend(self.scan_ubisoft_library())
        games.extend(self.scan_ea_library())

        self.save_cache(games)

        return games

    def save_cache(self, games):
        """
        Writes the results of the most recent scan to CACHE_FILE
        (games_cache.json) so they can be inspected or reloaded without
        re-scanning the whole machine.
        """
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "scanned_at": datetime.datetime.now().isoformat(),
                        "count": len(games),
                        "games": [asdict(g) for g in games],
                    },
                    f,
                    indent=4,
                )
        except Exception as e:
            print(f"[GameScanner] Failed saving cache: {e}")

    def load_cache(self):
        """
        Loads the last cached scan results from CACHE_FILE, if present.
        Returns a list of Game objects, or an empty list if there's no
        cache yet or it can't be read.
        """
        if not os.path.exists(self.CACHE_FILE):
            return []

        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [Game(**g) for g in data.get("games", [])]
        except Exception as e:
            print(f"[GameScanner] Failed loading cache: {e}")
            return []

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