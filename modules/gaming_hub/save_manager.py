import json
import os
import shutil
import datetime
import stat

from core import paths


class SaveManager:

    CONFIG_FILE = paths.migrate_legacy_file(
        paths.data_path("gaming_hub", "save_paths.json"),
        "modules", "gaming_hub", "save_paths.json"
    )

    BLOCK_FILE = paths.migrate_legacy_file(
        paths.data_path("gaming_hub", "blocked_saves.json"),
        "modules", "gaming_hub", "blocked_saves.json"
    )

    BACKUP_FOLDER = paths.data_path("gaming_hub", "backups")

    def __init__(self):

        self.paths = self.load_paths()
        self.blocked_games = self.load_blocked()

    def load_paths(self):

        if not os.path.exists(
            self.CONFIG_FILE
        ):
            return {}

        try:

            with open(
                self.CONFIG_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

        except Exception:

            return {}

    def save_paths(self):

        with open(
            self.CONFIG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                self.paths,
                f,
                indent=4
            )

    def set_path(
        self,
        game_name,
        path
    ):

        self.paths[game_name] = path

        self.save_paths()

    def get_path(
        self,
        game_name
    ):

        return self.paths.get(
            game_name,
            ""
        )

    def load_blocked(self):

        try:

            with open(
                self.BLOCK_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            return set(
                data.get(
                    "blocked",
                    []
                )
            )

        except Exception:

            return set()

    def save_blocked(self):

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

    def block_game(self, game):

        self.blocked_games.add(game)

        self.save_blocked()

    def is_blocked(self, game):

        return game in self.blocked_games

    def backup_game(
        self,
        game_name
    ):

        save_path = self.get_path(
            game_name
        )

        if not save_path:

            raise ValueError(
                "No save path configured."
            )

        if not os.path.exists(
            save_path
        ):

            raise ValueError(
                "Save folder not found."
            )

        game_folder = os.path.join(
            self.BACKUP_FOLDER,
            game_name
        )

        os.makedirs(
            game_folder,
            exist_ok=True
        )

        timestamp = datetime.datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        backup_folder = os.path.join(
            game_folder,
            timestamp
        )

        shutil.copytree(
            save_path,
            backup_folder
        )

        return backup_folder

    def restore_backup(
        self,
        game_name,
        backup_folder
    ):

        save_path = self.get_path(
            game_name
        )

        if not save_path:

            raise ValueError(
                "No save path configured."
            )

        if os.path.exists(
            save_path
        ):

            shutil.rmtree(
                save_path
            )

        shutil.copytree(
            backup_folder,
            save_path
        )

    def get_backups(
        self,
        game_name
    ):

        folder = os.path.join(
            self.BACKUP_FOLDER,
            game_name
        )

        if not os.path.exists(
            folder
        ):

            return []

        return sorted(
            os.listdir(folder),
            reverse=True
        )

    def lock_saves(self, game_name):
        path = self.get_path(game_name)
        if not path:
            return

        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(
                    root,
                    file
                )
                try:
                    os.chmod(
                        file_path,
                        stat.S_IREAD
                    )
                except Exception as e:
                    print(f"Failed to lock {file_path}: {e}")

    def unlock_saves(self, game_name):
        path = self.get_path(game_name)
        if not path:
            return

        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(
                    root,
                    file
                )
                try:
                    os.chmod(
                        file_path,
                        stat.S_IWRITE | stat.S_IREAD
                    )
                except Exception as e:
                    print(f"Failed to unlock {file_path}: {e}")

    # STEP 6: Add get_save_tree method
    def get_save_tree(self, game_name):
        path = self.get_path(game_name)

        if not path:
            return []

        if not os.path.exists(path):
            return []

        results = []

        for root, dirs, files in os.walk(path):
            # Sort files and directories for consistent display
            files.sort()
            dirs.sort() # os.walk yields dirs in arbitrary order, but we want to process sorted

            # Calculate relative path
            relative_path = os.path.relpath(
                root,
                path
            )
            
            # Store (relative_path, files_in_this_path)
            # We explicitly want to collect files for the current 'root' folder
            # The Treeview will handle nested structure, we just need to know
            # which files belong to which relative path.
            results.append(
                (
                    relative_path,
                    files # List of filenames in the current 'root' directory
                )
            )

        return results