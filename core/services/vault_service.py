import json
import os
import uuid
from datetime import datetime

from core import paths


class VaultService:

    FILE = paths.migrate_legacy_file(
        paths.data_path("vault.json"),
        "data", "vault.json"
    )

    def __init__(self, crypto):

        self.crypto = crypto

        if not os.path.exists(self.FILE):

            with open(self.FILE, "w") as f:
                json.dump([], f)

    # =====================================================
    # FILE IO
    # =====================================================

    def load(self):

        try:
            with open(self.FILE, "r") as f:
                return json.load(f)

        except Exception:
            return []

    def save(self, data):

        with open(self.FILE, "w") as f:
            json.dump(data, f, indent=4)

    # =====================================================
    # CREATE
    # =====================================================

    def add_entry(
        self,
        site,
        username,
        password,
        category="General"
    ):

        data = self.load()

        now = datetime.now().isoformat()

        data.append({
            "id": str(uuid.uuid4()),
            "site": site,
            "username": username,
            "password": self.crypto.encrypt(password),
            "category": category,
            "favorite": False,
            "created": now,
            "updated": now,
            "history": []
        })

        self.save(data)

    # =====================================================
    # DELETE
    # =====================================================

    def delete_entry(self, entry_id):

        data = self.load()

        data = [
            item
            for item in data
            if item.get("id") != entry_id
        ]

        self.save(data)

    # =====================================================
    # UPDATE
    # =====================================================

    def update_entry(
        self,
        entry_id,
        site,
        username,
        password,
        category="General"
    ):

        data = self.load()

        for item in data:

            if item.get("id") == entry_id:
                if item["password"] != self.crypto.encrypt(password):
                    item.setdefault("history", []).append({
                        "password": item["password"],
                        "date": item["updated"]
                    })

                item["site"] = site
                item["username"] = username
                item["password"] = self.crypto.encrypt(password)
                item["category"] = category
                item["updated"] = datetime.now().isoformat()

                break

        self.save(data)

    # =====================================================
    # FAVORITES
    # =====================================================

    def toggle_favorite(self, entry_id):

        data = self.load()

        for item in data:

            if item.get("id") == entry_id:

                item["favorite"] = not item.get(
                    "favorite",
                    False
                )
                item["updated"] = datetime.now().isoformat()
                break

        self.save(data)

    # =====================================================
    # READ
    # =====================================================

    def get_entries(self):

        data = self.load()

        results = []

        for item in data:

            try:
                decrypted_password = self.crypto.decrypt(
                    item["password"]
                )

                history_decrypted = []
                for hist_item in item.get("history", []):
                    history_decrypted.append({
                        "password": self.crypto.decrypt(hist_item["password"]),
                        "date": hist_item["date"]
                    })

                results.append({
                    "id": item.get("id"),
                    "site": item.get("site", ""),
                    "username": item.get("username", ""),
                    "password": decrypted_password,
                    "category": item.get(
                        "category",
                        "General"
                    ),
                    "favorite": item.get(
                        "favorite",
                        False
                    ),
                    "created": item.get(
                        "created",
                        ""
                    ),
                    "updated": item.get(
                        "updated",
                        ""
                    ),
                    "history": history_decrypted
                })

            except Exception:
                pass

        return results

    def get_entry(self, entry_id):

        for entry in self.get_entries():

            if entry["id"] == entry_id:
                return entry

        return None

    def get_history(self, entry_id):
        """
        Retrieves the password history for a specific entry.
        """
        entry = self.get_entry(entry_id)
        if entry:
            return entry.get("history", [])
        return []

    # =====================================================
    # SEARCH
    # =====================================================

    def search(self, query):

        query = query.lower().strip()

        return [
            e
            for e in self.get_entries()
            if (
                query in e["site"].lower()
                or query in e["username"].lower()
                or query in e["category"].lower()
            )
        ]

    # =====================================================
    # FILTERS
    # =====================================================

    def get_favorites(self):

        return [
            e
            for e in self.get_entries()
            if e["favorite"]
        ]

    def get_by_category(self, category):

        return [
            e
            for e in self.get_entries()
            if e["category"] == category
        ]

    def get_recent(self, limit=10):
        """
        Returns a list of the most recently updated entries.
        """
        entries = self.get_entries()

        entries.sort(
            key=lambda x: x.get(
                "updated",
                ""
            ),
            reverse=True
        )

        return entries[:limit]

    def get_categories(self):
        """
        Returns a sorted list of all unique categories present in the vault.
        """
        categories = set()

        for entry in self.get_entries():
            categories.add(
                entry["category"]
            )

        return sorted(list(categories))

    # =====================================================
    # STATS & SECURITY
    # =====================================================

    def count(self):

        return len(self.load())

    def stats(self): # <--- ADDED THIS METHOD

        entries = self.get_entries()

        favorites = len(
            [e for e in entries if e.get("favorite", False)]
        )

        categories = len({
            e.get("category", "General")
            for e in entries
        })

        sites = len({
            e.get("site", "").lower()
            for e in entries
        })

        return {
            "total": len(entries),
            "favorites": favorites,
            "categories": categories,
            "sites": sites
        }

    def get_weak_passwords(self):
        """
        Identifies and returns entries with weak passwords (length < 10 characters).
        """
        weak = []
        for entry in self.get_entries():
            if len(entry["password"]) < 10:
                weak.append(entry)
        return weak

    def find_duplicates(self):
        """
        Identifies and returns entries that share duplicate passwords.
        """
        seen_passwords = {}
        duplicates = []

        for entry in self.get_entries():
            pwd = entry["password"]

            if pwd in seen_passwords:
                if seen_passwords[pwd] not in duplicates:
                    duplicates.append(seen_passwords[pwd])
                if entry not in duplicates:
                    duplicates.append(entry)
            else:
                seen_passwords[pwd] = entry
        
        duplicates.sort(key=lambda x: x["id"]) 
        return duplicates


    def security_score(self):
        """
        Calculates a security score based on weak and duplicate passwords.
        """
        score = 100
        weak_passwords = self.get_weak_passwords()
        duplicate_passwords = self.find_duplicates()

        weak_count = len(weak_passwords)
        
        # Count unique passwords that are duplicated
        unique_duplicated_passwords = set(e["password"] for e in duplicate_passwords)
        duplicate_count = len(unique_duplicated_passwords)


        score -= (weak_count * 10)
        score -= (duplicate_count * 15)

        score = max(0, score)

        return {
            "score": score,
            "weak": weak_count,
            "duplicates": duplicate_count
        }

    # =====================================================
    # IMPORT / EXPORT
    # =====================================================

    def export_json(self, filepath):

        with open(filepath, "w") as f:
            json.dump(
                self.load(),
                f,
                indent=4
            )

    def import_json(self, filepath):
        """
        Imports entries from a JSON file, preventing duplicates based on entry 'id'.
        """
        with open(filepath, "r") as f:
            imported = json.load(f)

        current = self.load()

        existing_ids = {
            item.get("id")
            for item in current
            if item.get("id") is not None
        }

        for item in imported:
            if item.get("id") is not None and item.get("id") not in existing_ids:
                current.append(item)
            elif item.get("id") is None:
                item["id"] = str(uuid.uuid4())
                current.append(item)

        self.save(current)

    def export_plaintext(self, filepath):
        """
        Exports all decrypted vault entries to a JSON file.
        Useful for backups in a readable format.
        """
        with open(filepath, "w") as f:
            json.dump(
                self.get_entries(),
                f,
                indent=4
            )
            
    def export_encrypted(self, filepath):
        """
        Exports the entire vault data as a single encrypted file.
        """
        data = self.load()
        encrypted_content = self.crypto.encrypt(json.dumps(data))

        with open(filepath, "w") as f:
            f.write(encrypted_content)

    def import_encrypted(self, filepath):
        """
        Imports encrypted vault data from a file and merges it into the current vault.
        """
        try:
            with open(filepath, "r") as f:
                encrypted_content = f.read()

            decrypted_json_str = self.crypto.decrypt(encrypted_content)
            imported_data = json.loads(decrypted_json_str)

            current = self.load()
            existing_ids = {item.get("id") for item in current if item.get("id") is not None}

            for item in imported_data:
                if item.get("id") is not None and item.get("id") not in existing_ids:
                    current.append(item)
                elif item.get("id") is None:
                    item["id"] = str(uuid.uuid4())
                    current.append(item)

            self.save(current)

        except Exception as e:
            print(f"Error importing encrypted vault: {e}")

    # =====================================================
    # CLEAR
    # =====================================================

    def clear_vault(self):
        """
        Clears all entries from the vault.
        """
        self.save([])