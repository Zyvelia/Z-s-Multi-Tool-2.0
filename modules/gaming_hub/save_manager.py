import json
import os
import shutil
import datetime
import stat
import subprocess
import getpass

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

    SETTINGS_FILE = paths.data_path("gaming_hub", "save_manager_settings.json")

    # Current user, used as the target for the ACL deny rules in
    # lock_path()/unlock_path(). This is who most games will be running
    # as, so denying THIS account write access at the ACL level blocks
    # writes even if the game resets the read-only attribute.
    #
    # Qualified as "COMPUTERNAME\username" rather than a bare username -
    # icacls needs this to resolve to the exact local account. A bare
    # name is ambiguous (domain-joined machines, synced Microsoft-account
    # profiles, etc.) and when icacls can't resolve it cleanly it ends up
    # writing the DENY rule against an unresolved/orphaned SID instead of
    # your actual account - which shows up as a garbled ID in icacls
    # output and does nothing, since the account really doing the
    # writing was never actually denied.
    _RAW_USER = os.environ.get("USERNAME") or getpass.getuser()
    _COMPUTERNAME = os.environ.get("COMPUTERNAME", "")
    ACL_USER = f"{_COMPUTERNAME}\\{_RAW_USER}" if _COMPUTERNAME else _RAW_USER

    def __init__(self):

        self.paths = self.load_paths()
        self.blocked_games = self.load_blocked()
        self.settings = self.load_settings()

    # ── save manager settings (backup output folder, etc.) ──

    def load_settings(self):

        if not os.path.exists(self.SETTINGS_FILE):
            return {"backup_folder": ""}

        try:
            with open(self.SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"backup_folder": data.get("backup_folder", "")}
        except Exception:
            return {"backup_folder": ""}

    def save_settings(self):

        with open(self.SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4)

    def get_backup_folder(self):
        """Returns the active backup destination root - the user's
        custom folder if one is set, otherwise the default AppData
        location."""
        custom = (self.settings.get("backup_folder") or "").strip()
        return custom if custom else self.BACKUP_FOLDER

    def set_backup_folder(self, folder_path):
        self.settings["backup_folder"] = (folder_path or "").strip()
        self.save_settings()

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

    @staticmethod
    def _clean_path(path):
        """Strips whitespace and wrapping quote characters from a path.

        Windows Explorer's "Copy as path" wraps paths in double quotes
        (it does this specifically when the path contains spaces, which
        save folders almost always do - "My Games", "Save Games", etc.).
        If a user pastes that directly into the save-path field, the
        literal quote characters end up saved into save_paths.json.
        The field still LOOKS right, but os.path.exists() on a string
        like '"C:\\...\\SaveGames"' returns False, so the save tree
        silently comes back empty. Cleaning here (both when saving AND
        when reading) fixes new entries and self-heals anything already
        saved with quotes baked in, without needing the user to retype it.
        """
        if not path:
            return path

        path = path.strip()

        for quote_char in ('"', "'", "\u201c", "\u201d"):
            if len(path) >= 2 and path[0] == quote_char and path[-1] in ('"', "'", "\u201c", "\u201d"):
                path = path[1:-1].strip()

        return path

    def set_path(
        self,
        game_name,
        path
    ):

        self.paths[game_name] = self._clean_path(path)

        self.save_paths()

    def get_path(
        self,
        game_name
    ):

        return self._clean_path(
            self.paths.get(
                game_name,
                ""
            )
        )

    def delete_path(self, game_name):
        """Removes a game's saved-path entry entirely. Only ever called
        from an explicit, user-reviewed cleanup action (see
        get_orphaned_games) - never automatically off a scan result,
        since a game missing from one scan doesn't mean it's actually
        uninstalled or that the save path config should be lost."""
        if game_name in self.paths:
            del self.paths[game_name]
            self.save_paths()

    def get_orphaned_games(self, known_game_names):
        """Returns the saved-path entries whose game name doesn't match
        any name in known_game_names (the most recent scan results),
        sorted A-Z, for a manual review-and-remove UI. Case-insensitive
        match, so stray case drift between the scanner and a
        hand-entered name doesn't flag something that's really still
        valid."""
        known_lower = {name.lower() for name in known_game_names}
        return sorted(
            (name for name in self.paths if name.lower() not in known_lower),
            key=str.lower
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

    def unblock_game(self, game):
        """Removes a game from the Save Manager hidden list, making it
        show up in the game dropdown again."""
        self.blocked_games.discard(game)
        self.save_blocked()

    def get_blocked_games(self):
        """Returns the currently hidden (Save Manager only) games,
        sorted A-Z, for populating an 'unhide' list in the UI."""
        return sorted(self.blocked_games, key=str.lower)

    def is_blocked(self, game):

        return game in self.blocked_games

    def backup_game(
        self,
        game_name,
        source_path=None
    ):
        """Backs up either the whole configured save folder for
        game_name (default) or a single file/subfolder within it
        (pass source_path, e.g. the item currently selected in the
        Save Explorer tree). Always writes into get_backup_folder(),
        which is the user's custom output folder if one is set."""

        save_path = source_path or self.get_path(
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
            self.get_backup_folder(),
            game_name
        )

        os.makedirs(
            game_folder,
            exist_ok=True
        )

        timestamp = datetime.datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        item_name = os.path.basename(
            save_path.rstrip("\\/")
        ) or game_name

        backup_folder = os.path.join(
            game_folder,
            f"{timestamp}_{item_name}" if source_path else timestamp
        )

        if os.path.isfile(save_path):
            os.makedirs(backup_folder, exist_ok=True)
            shutil.copy2(save_path, os.path.join(backup_folder, item_name))
        else:
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

        # A single-file backup contains just one file - copy it back
        # over the matching file in the save folder rather than
        # replacing the whole save folder.
        contents = os.listdir(backup_folder)
        if len(contents) == 1 and os.path.isfile(
            os.path.join(backup_folder, contents[0])
        ):
            target_file = os.path.join(save_path, contents[0])
            os.makedirs(save_path, exist_ok=True)
            shutil.copy2(
                os.path.join(backup_folder, contents[0]),
                target_file
            )
            return

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
            self.get_backup_folder(),
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

    # subprocess.CREATE_NO_WINDOW is only defined on Windows. Every icacls
    # call below passes this via creationflags, since without it a windowed
    # (--windowed PyInstaller build has no console of its own) app will
    # briefly flash a real console window every time icacls runs - which
    # is what "random terminals popping up" while locking/unlocking a
    # save was.
    _NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _acl_deny_write(self, path, recursive=False):
        """
        Adds an explicit Windows ACL deny-write rule for the current
        user on top of the read-only attribute set in lock_path().

        The read-only attribute alone is easy to bypass - some games
        just clear it (SetFileAttributes) before writing their save,
        ignoring it entirely. A DENY ACE is enforced by the OS at the
        permissions level instead, so a normal (non-elevated) process
        can't just flip it back and write anyway.

        No-op on non-Windows platforms, where icacls doesn't exist.
        """
        if os.name != "nt":
            return

        flags = "(OI)(CI)W" if recursive else "(W)"
        cmd = ["icacls", path, "/deny", f"{self.ACL_USER}:{flags}"]
        if recursive:
            cmd.append("/T")

        try:
            subprocess.run(
                cmd, capture_output=True, check=False,
                creationflags=self._NO_WINDOW_FLAGS
            )
        except Exception as e:
            print(f"[SaveManager] ACL deny failed for {path}: {e}")

    def _acl_allow_write(self, path, recursive=False):
        """Removes the deny-write ACE added by _acl_deny_write(), restoring
        normal write access at the permissions level."""
        if os.name != "nt":
            return

        cmd = ["icacls", path, "/remove:d", self.ACL_USER]
        if recursive:
            cmd.append("/T")

        try:
            subprocess.run(
                cmd, capture_output=True, check=False,
                creationflags=self._NO_WINDOW_FLAGS
            )
        except Exception as e:
            print(f"[SaveManager] ACL allow failed for {path}: {e}")

    def lock_path(self, path):
        """Marks a single file, or every file under a folder, read-only
        (denies write access)."""
        if not path or not os.path.exists(path):
            return

        if os.path.isfile(path):
            try:
                os.chmod(path, stat.S_IREAD)
            except Exception as e:
                print(f"Failed to lock {path}: {e}")
            self._acl_deny_write(path)
            return

        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.chmod(
                        file_path,
                        stat.S_IREAD
                    )
                except Exception as e:
                    print(f"Failed to lock {file_path}: {e}")

        # One recursive ACL call on the folder (inherits to everything
        # underneath) instead of one call per file - much faster and
        # covers files/subfolders added later too.
        self._acl_deny_write(path, recursive=True)

    def unlock_path(self, path):
        """Restores write access to a single file, or every file under
        a folder.

        Order matters here: the ACL deny rule (if present) blocks
        FILE_WRITE_ATTRIBUTES too, not just data writes - so if chmod
        runs first while the deny rule is still active, it fails with
        WinError 5 even though the overall unlock still succeeds once
        the ACL rule is removed. Removing the ACL rule first means
        chmod runs against a path that's actually writable again.
        """
        if not path or not os.path.exists(path):
            return

        if os.path.isfile(path):
            self._acl_allow_write(path)
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except Exception as e:
                print(f"Failed to unlock {path}: {e}")
            return

        self._acl_allow_write(path, recursive=True)

        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.chmod(
                        file_path,
                        stat.S_IWRITE | stat.S_IREAD
                    )
                except Exception as e:
                    print(f"Failed to unlock {file_path}: {e}")

    def _acl_has_deny(self, path):
        """Checks whether the current user already has a DENY write ACE
        on this path (via icacls). Used so is_locked() stays accurate
        even if a game clears the read-only attribute but the ACL deny
        rule set by _acl_deny_write() is still in effect."""
        if os.name != "nt":
            return False

        try:
            result = subprocess.run(
                ["icacls", path],
                capture_output=True, text=True, check=False,
                creationflags=self._NO_WINDOW_FLAGS
            )
            for line in (result.stdout or "").splitlines():
                if self.ACL_USER in line and "(DENY)" in line:
                    return True
        except Exception:
            pass
        return False

    def is_locked(self, path):
        """Ground-truth protection check straight from the filesystem
        (not a flag that can go stale) - a file is 'locked' if it
        isn't writable, OR if it's still covered by an ACL deny rule
        even after the read-only attribute got reset (some games clear
        the attribute directly but can't remove a DENY ACE they don't
        have permission to touch). A folder is reported locked if ANY
        file inside it is read-only, or the folder itself has a deny
        rule applied."""
        if not path or not os.path.exists(path):
            return False

        if os.path.isfile(path):
            return not os.access(path, os.W_OK) or self._acl_has_deny(path)

        for root, dirs, files in os.walk(path):
            for file in files:
                if not os.access(os.path.join(root, file), os.W_OK):
                    return True

        return self._acl_has_deny(path)

    def lock_saves(self, game_name):
        self.lock_path(self.get_path(game_name))

    def unlock_saves(self, game_name):
        self.unlock_path(self.get_path(game_name))

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