"""Qt Save Editor — open, browse, and edit game save files of (almost) any format."""

from __future__ import annotations

import importlib
import struct
import json
import fnmatch
import copy
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

_core = importlib.import_module("modules.Files.Save Editor.core")
_module = importlib.import_module("modules.Files.Save Editor.module")
_crypto = importlib.import_module("modules.Files.Save Editor.crypto_formats")
_layouts = importlib.import_module("modules.Files.Save Editor.layouts")
_formats = importlib.import_module("modules.Files.Save Editor.formats")
_binary_scan = importlib.import_module("modules.Files.Save Editor.binary_scan")
_binary_template = importlib.import_module("modules.Files.Save Editor.binary_template")
_bl4_tools = importlib.import_module("modules.Files.Save Editor.games.Borderlands4.tools")

SaveFile = _core.SaveFile
PathError = _core.PathError
STRUCTURED_FORMATS = _module.STRUCTURED_FORMATS
HEX_BYTES_PER_LINE = _module.HEX_BYTES_PER_LINE
HEX_SIZE_WARN_BYTES = _module.HEX_SIZE_WARN_BYTES
SaveProfile = _crypto.SaveProfile
GameLayout = _layouts.GameLayout
FieldSpec = _layouts.FieldSpec
TaggedValue = getattr(_formats, "TaggedValue", None)  # only defined if PyYAML is installed

# Loaded once per process: every registered profile becomes a format that
# decode() tries automatically, same as gzip/zlib/base64.
def _bundled_config_path(filename: str) -> Path:
    return Path(__file__).with_name(filename)

def _load_active_profiles() -> list:
    """Load bundled defaults and AppData overrides, merged by profile name."""
    merged = {}
    bundled = _bundled_config_path(_module.PROFILES_FILENAME)
    for p in _crypto.load_profiles(str(bundled)):
        merged[p.name] = p
    for p in _crypto.load_profiles(_module.profiles_path()):
        merged[p.name] = p
    return list(merged.values())


_crypto.register_all(_load_active_profiles())


# ---------------------------------------------------------------------------
# Borderlands 4 friendly naming / filtering
# ---------------------------------------------------------------------------

_BL4_EXACT_NAMES = {
    "state.char_name": "Character Name",
    "state.class": "Vault Hunter Class",
    "state.player_difficulty": "Game Difficulty",
    "state.true_mode": "True Vault Hunter Mode",
    "state.highest_unlocked_mayhem_level": "Highest Mayhem Level Unlocked",
    "state.total_playtime": "Total Playtime",
    "state.last_played_timestamp": "Last Played Timestamp",
    "state.personal_vehicle": "Personal Vehicle",
    "state.hover_drive": "Vehicle Hover Drive",
    "state.vehicle_weapon_slot": "Vehicle Weapon Slot",
    "state.inventory.items.backpack": "Backpack Inventory",
    "state.checkpoint_name": "Current Checkpoint",
    "state.world_region_name": "Current World Region",
    "state.currencies.cash": "Cash",
    "state.currencies.eridium": "Eridium",
    "state.ammo.assaultrifle": "Assault Rifle Ammo",
    "state.ammo.pistol": "Pistol Ammo",
    "state.ammo.shotgun": "Shotgun Ammo",
    "state.ammo.smg": "SMG Ammo",
    "state.ammo.sniper": "Sniper Ammo",
    "state.ammo.repairkit": "Repair Kits",
    "state.experience[0].level": "Character Level",
    "state.experience[0].points": "Character XP",
    "state.experience[1].level": "Specialization Level",
    "state.experience[1].points": "Specialization XP",
    "progression.point_pools.characterprogresspoints": "Character Progress Points",
    "progression.point_pools.specializationtokenpool": "Specialization Tokens",
    "globals.highest_unlocked_vault_hunter_level": "Highest Vault Hunter Level Unlocked",
    "globals.vault_hunter_level": "Current Vault Hunter Level",
    "globals.highest_unlocked_mayhem_level": "Highest Mayhem Level Unlocked",
    "globals.mayhem_level": "Current Mayhem Level",
    "globals.mainmissioncomplete": "Main Campaign Complete",
    "globals.prologue_completed": "Prologue Complete",
    "globals.repkit_unlocked": "Repkits Unlocked",
    "globals.movegrant_glide": "Glide Unlocked",
    "globals.movegrant_grapplegrabber": "Grapple Grabber Unlocked",
    "globals.movegrant_ordonitegloves": "Ordonite Gloves Unlocked",
    "globals.movegrant_echolocation": "Echolocation Unlocked",
    "globals.lockdownlifted": "World Lockdown Lifted",
    "globals.true_mode": "True Vault Hunter Mode",
    "globals.true_mode_override": "True Mode Override",
    "globals.time_of_day": "World Time of Day",
}

_BL4_SECTION_PREFIXES = [
    ("Character", ("state.char_name", "state.class", "state.player_difficulty", "state.true_mode", "state.experience", "state.total_playtime", "state.checkpoint_name", "state.world_region_name")),
    ("Currency & Ammo", ("state.currencies", "state.ammo")),
    ("Inventory & Gear", ("state.inventory", "state.gbxactorparts")),
    ("Progression & Skills", ("progression", "state.unique_rewards")),
    ("Missions", ("missions",)),
    ("Challenges & Achievements", ("stats.challenge", "stats.achievements", "stats.dlc_challenge", "challenge")),
    ("World & Unlocks", ("unlockables", "world_state", "globals.movegrant", "globals.lockdownlifted", "globals.prologue_completed", "globals.mainmissioncomplete", "globals.repkit_unlocked")),
    ("Statistics", ("stats",)),
    ("Discovery & Collection", ("gbx_discovery_pc", "gbx_discovery_pg", "pips")),
    ("Online / UI Data", ("onlinecharacterprefs", "oak.ui.progression_data")),
    ("Save Metadata", ("save_game_header", "timed_facts", "activities")),
]

_BL4_ESSENTIAL_PREFIXES = (
    "state.char_name", "state.class", "state.player_difficulty",
    "state.true_mode", "state.highest_unlocked_mayhem_level",
    "state.experience", "state.currencies", "state.ammo",
    "state.personal_vehicle", "state.hover_drive",
    "state.checkpoint_name", "state.world_region_name",
    "state.inventory.items.backpack", "progression.point_pools",
    "globals.", "unlockables",
)

_BL4_NOISY_PREFIXES = (
    "stats.challenge.", "stats.openworld.", "stats.hud.", "stats.tutorial.",
    "stats.regions.", "pips.", "gbx_discovery_pc.", "gbx_discovery_pg.",
    "onlinecharacterprefs.", "oak.ui.progression_data.", "save_game_header.",
)


def _bl4_humanize_token(token: str) -> str:
    token = token.strip("_")
    token = token.replace("__", "_")
    replacements = {
        "assaultrifle": "Assault Rifle", "repairkit": "Repair Kit",
        "smg": "SMG", "xp": "XP", "ui": "UI", "vh": "Vault Hunter",
        "dlc": "DLC", "npc": "NPC", "id": "ID", "guid": "GUID",
        "endstate": "Completion State", "ui_flags": "UI Flags",
        "cursorposition": "Cursor Position", "char": "Character",
        "blackmarket": "Black Market", "mainmissioncomplete": "Main Campaign Complete",
        "prologue": "Prologue", "true_mode": "True Vault Hunter Mode",
    }
    # Preserve a few well-known game vocabulary terms instead of title-casing
    # them into awkward labels.
    low = token.lower()
    if low in replacements:
        return replacements[low]
    token = token.replace("-", " ").replace("_", " ")
    return token.title()


def _bl4_mission_context(path: str) -> str:
    """Turn internal mission IDs into useful labels while retaining the raw path elsewhere."""
    bits = [b for b in path.split(".") if b]
    if not bits:
        return "Mission"
    # Prefer the mission ID immediately before status/final/exit/ui_flags.
    meaningful = [b for b in bits if b not in {"missions", "local_sets", "missionset"}]
    marker = None
    for candidate in ("status", "final", "exit", "ui_flags"):
        if candidate in meaningful:
            marker = meaningful.index(candidate)
            break
    if marker is not None:
        before = meaningful[:marker]
        if before:
            ident = before[-1]
            return _bl4_humanize_token(ident)
    # For an objective leaf, use the final internal identifier.
    return _bl4_humanize_token(meaningful[-1]) if meaningful else "Mission"


def _bl4_friendly_name(path: str) -> str:
    if path in _BL4_EXACT_NAMES:
        return _BL4_EXACT_NAMES[path]
    if path.endswith(".experience[0]"):
        return "Character Experience"
    if path.endswith(".experience[1]"):
        return "Specialization Experience"

    if path.startswith("missions."):
        leaf = path.rsplit(".", 1)[-1]
        context = _bl4_mission_context(path)
        if leaf == "status":
            return f"{context} — Status"
        if leaf == "ui_flags":
            return f"{context} — UI Flags (Internal)"
        if leaf == "exit":
            return f"{context} — Exit Marker (Internal)"
        if leaf == "final":
            return f"{context} — Objective Data"
        if leaf.endswith("_endstate"):
            return f"{context} — {_bl4_humanize_token(leaf[:-9])} — Completion State"
        return f"{context} — {_bl4_humanize_token(leaf)}"

    leaf = path.rsplit(".", 1)[-1]
    if leaf == "state_flags":
        return "Inventory State Flags"
    if leaf == "serial":
        return "Item Serial"
    if leaf == "type":
        return "Data Type / Item Type"
    if leaf == "points":
        return "Points"
    if leaf == "level":
        # Make the common experience entries explicit.
        if "experience[0]" in path:
            return "Character Level"
        if "experience[1]" in path:
            return "Specialization Level"
        return "Level"
    if leaf == "status":
        return "Status"
    return _bl4_humanize_token(leaf)

def _bl4_section(path: str) -> str:
    for name, prefixes in _BL4_SECTION_PREFIXES:
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
                return name
    return "Other Data"


def _bl4_is_essential(path: str) -> bool:
    for prefix in _BL4_ESSENTIAL_PREFIXES:
        if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return True
    # Mission set/mission status is useful; individual objective internals are
    # intentionally moved to All Values so the default list stays manageable.
    if path.startswith("missions.") and (path.endswith(".status") or path.endswith(".exit")):
        return True
    return False


class _ProfileDialog(QDialog):
    """Add/edit a single decryption profile (game name + algo + key)."""

    ALGOS = ["xor", "aes-cbc", "aes-ecb", "aes-gcm", "bl4-steamid"]

    def __init__(self, parent, profile: SaveProfile | None = None):
        super().__init__(parent)
        self.setWindowTitle("Save Decryption Profile")
        form = QFormLayout(self)

        self.name_edit = QLineEdit(profile.name if profile else "")
        self.algo_box = QComboBox()
        self.algo_box.addItems(self.ALGOS)
        if profile:
            self.algo_box.setCurrentText(profile.algo)
        self.key_edit = QLineEdit(profile.key.hex() if profile else "")
        self.key_edit.setPlaceholderText("hex, e.g. 2b7e151628aed2a6abf7158809cf4f3c")
        self.iv_box = QComboBox()
        self.iv_box.addItems(["none", "prefix16", "fixed"])
        if profile:
            self.iv_box.setCurrentText(profile.iv_mode)
        self.fixed_iv_edit = QLineEdit(profile.fixed_iv.hex() if profile else "")
        self.fixed_iv_edit.setPlaceholderText("hex IV, only used when IV mode = fixed")
        self.steam_id_edit = QLineEdit(profile.steam_id if profile else "")
        self.steam_id_edit.setPlaceholderText("e.g. 76561198667243843 (bl4-steamid only)")

        form.addRow("Game / profile name:", self.name_edit)
        form.addRow("Algorithm:", self.algo_box)
        self._key_row = self._add_labeled_row(form, "Key (hex):", self.key_edit)
        self._iv_mode_row = self._add_labeled_row(form, "IV mode (aes-cbc only):", self.iv_box)
        self._fixed_iv_row = self._add_labeled_row(form, "Fixed IV (hex):", self.fixed_iv_edit)
        self._steam_id_row = self._add_labeled_row(form, "Steam/Epic ID:", self.steam_id_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.algo_box.currentTextChanged.connect(self._update_field_visibility)
        self._update_field_visibility(self.algo_box.currentText())

    @staticmethod
    def _add_labeled_row(form: QFormLayout, label: str, widget) -> QLabel:
        """addRow but keep a handle on the label so the row can be hidden."""
        label_widget = QLabel(label)
        form.addRow(label_widget, widget)
        return label_widget

    def _update_field_visibility(self, algo: str) -> None:
        # bl4-steamid derives its key from the Steam/Epic ID, so the raw
        # key/IV fields are irrelevant (and vice versa) for that algo.
        is_bl4 = algo == "bl4-steamid"
        for label, widget in (
            (self._key_row, self.key_edit),
            (self._iv_mode_row, self.iv_box),
            (self._fixed_iv_row, self.fixed_iv_edit),
        ):
            label.setVisible(not is_bl4)
            widget.setVisible(not is_bl4)
        self._steam_id_row.setVisible(is_bl4)
        self.steam_id_edit.setVisible(is_bl4)

    def profile(self) -> SaveProfile:
        return SaveProfile(
            name=self.name_edit.text().strip(),
            algo=self.algo_box.currentText(),
            key=bytes.fromhex(self.key_edit.text().strip()) if self.key_edit.text().strip() else b"",
            iv_mode=self.iv_box.currentText(),
            fixed_iv=bytes.fromhex(self.fixed_iv_edit.text().strip()) if self.fixed_iv_edit.text().strip() else b"",
            steam_id=self.steam_id_edit.text().strip(),
        )

class _AddFieldDialog(QDialog):
    """Quick 'add this to a custom layout' popup.

    Used two ways: from the tree/Find-Results right-click menu on a
    structured save (path already known, offset fields hidden), or from
    the Readable Text / hex view on a raw-binary save (offset/size/type
    already known, path hidden). Whichever one is passed in decides
    which half of the form is editable.
    """

    PATH_TYPES = ["auto", "int", "float", "string", "bool"]

    def __init__(self, parent, path: str = None, default_label: str = "",
                 offset: int = None, binary_type: str = "int32", size: int = None):
        super().__init__(parent)
        self.setWindowTitle("Add Field to Layout")
        form = QFormLayout(self)
        self._is_binary = offset is not None
        self._path = path or ""

        self.label_edit = QLineEdit(default_label)
        self.section_edit = QLineEdit("General")
        form.addRow("Display label:", self.label_edit)

        if self._is_binary:
            form.addRow("Offset (bytes):", QLabel(f"0x{offset:X} ({offset})"))
            self.type_box = QComboBox()
            self.type_box.addItems(_layouts.BINARY_TYPES)
            self.type_box.setCurrentText(binary_type)
            self.size_spin = QSpinBox()
            self.size_spin.setRange(1, 1_000_000)
            self.size_spin.setValue(size or 16)
            self.endian_box = QComboBox()
            self.endian_box.addItems(["little-endian", "big-endian"])
            form.addRow("Type:", self.type_box)
            self.size_row = self._add_row_ref(form, "Size (bytes, for text/bytes types):", self.size_spin)
            form.addRow("Byte order:", self.endian_box)
            self.type_box.currentTextChanged.connect(self._update_size_visibility)
            self._update_size_visibility(self.type_box.currentText())
        else:
            form.addRow("Path:", QLabel(self._path))
            self.type_box = QComboBox()
            self.type_box.addItems(self.PATH_TYPES)

        self._offset = offset
        form.addRow("Section:", self.section_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _add_row_ref(form, label, widget):
        form.addRow(label, widget)
        return widget

    def _update_size_visibility(self, type_: str):
        needs_size = type_ in ("cstr", "utf16str", "bytes")
        self.size_spin.setEnabled(needs_size)

    def field_spec(self) -> FieldSpec:
        label = self.label_edit.text().strip() or self._path or f"field_{self._offset}"
        section = self.section_edit.text().strip() or "General"
        if self._is_binary:
            needs_size = self.type_box.currentText() in ("cstr", "utf16str", "bytes")
            return FieldSpec(
                label=label, section=section,
                type=self.type_box.currentText(),
                offset=self._offset,
                size=self.size_spin.value() if needs_size else None,
                endian="<" if self.endian_box.currentText() == "little-endian" else ">",
            )
        return FieldSpec(
            label=label, path=self._path,
            type=self.type_box.currentText(), section=section,
        )


class _LayoutDesignerDialog(QDialog):
    """Full editor for one GameLayout: its fields (label / path-or-offset /
    type / section / size / endian) plus the match_paths and match_bytes
    used to auto-select it when a save is opened.

    One layout can freely mix structured-path fields and raw-binary
    offset fields in the same table — that's what makes a single layout
    system work whether the save underneath is JSON or an unrecognized
    binary blob. In the "Path / Offset" column, type a normal path
    (player.stats.gold) for a structured field, or `@` followed by a
    byte offset (@0x10 or @16) for a binary field.
    """

    TYPES = ["auto", "int", "float", "string", "bool"] + [
        t for t in _layouts.BINARY_TYPES if t not in ("cstr",)
    ] + ["cstr"]

    def __init__(self, parent, layout: GameLayout):
        super().__init__(parent)
        self.setWindowTitle(f"Layout Designer \u2014 {layout.name}")
        self.resize(760, 460)
        self._layout_obj = layout
        root = QVBoxLayout(self)

        self.name_edit = QLineEdit(layout.name)
        root.addWidget(QLabel("Layout name:"))
        root.addWidget(self.name_edit)

        root.addWidget(QLabel(
            "Match paths (comma-separated). If every one of these paths exists in an "
            "opened save, this layout is selected automatically:"
        ))
        self.match_edit = QLineEdit(", ".join(layout.match_paths))
        root.addWidget(self.match_edit)

        root.addWidget(QLabel(
            "Match byte signatures, for raw-binary saves (comma-separated offset:hex pairs, "
            "e.g. \"0:cafebabe, 10:01\"). If every byte sequence matches at its offset, this "
            "layout is selected automatically:"
        ))
        self.match_bytes_edit = QLineEdit(
            ", ".join(f"{m['offset']}:{m['hex']}" for m in layout.match_bytes)
        )
        root.addWidget(self.match_bytes_edit)

        root.addWidget(QLabel(
            "Fields \u2014 use a normal path for structured saves, or \"@offset\" "
            "(e.g. @0x14 or @20) for a raw-binary field:"
        ))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Label", "Path / @Offset", "Type", "Section", "Size (bin text/bytes)", "Endian (bin)"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for f in layout.fields:
            self._add_row(f.label, self._path_cell(f), f.type, f.section,
                          str(f.size) if f.size is not None else "", f.endian)
        root.addWidget(self.table, 1)

        row_btns = QHBoxLayout()
        add_btn = QPushButton("Add Row")
        add_btn.clicked.connect(lambda: self._add_row("", "", "auto", "General", "", "<"))
        remove_btn = QPushButton("Remove Selected Row")
        remove_btn.clicked.connect(self._remove_selected)
        row_btns.addWidget(add_btn)
        row_btns.addWidget(remove_btn)
        row_btns.addStretch(1)
        root.addLayout(row_btns)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _path_cell(f: FieldSpec) -> str:
        return f"@{f.offset}" if f.is_binary else f.path

    def _add_row(self, label, path_cell, type_, section, size, endian):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(label))
        self.table.setItem(r, 1, QTableWidgetItem(path_cell))
        combo = QComboBox()
        combo.addItems(self.TYPES)
        combo.setCurrentText(type_)
        self.table.setCellWidget(r, 2, combo)
        self.table.setItem(r, 3, QTableWidgetItem(section))
        self.table.setItem(r, 4, QTableWidgetItem(size))
        endian_combo = QComboBox()
        endian_combo.addItems(["<", ">"])
        endian_combo.setCurrentText(endian or "<")
        self.table.setCellWidget(r, 5, endian_combo)

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def result_layout(self) -> GameLayout:
        fields = []
        for r in range(self.table.rowCount()):
            label = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ""
            cell = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            if not cell:
                continue
            type_ = self.table.cellWidget(r, 2).currentText()
            section = self.table.item(r, 3).text().strip() if self.table.item(r, 3) else "General"
            size_text = self.table.item(r, 4).text().strip() if self.table.item(r, 4) else ""
            endian = self.table.cellWidget(r, 5).currentText()

            if cell.startswith("@"):
                try:
                    offset = int(cell[1:], 0)  # base 0 -> accepts "0x14" or "20"
                except ValueError:
                    continue  # malformed offset, skip rather than crash the dialog
                size = int(size_text) if size_text else None
                fields.append(FieldSpec(label=label or cell, type=type_, section=section,
                                         offset=offset, size=size, endian=endian))
            else:
                fields.append(FieldSpec(label=label or cell, path=cell, type=type_, section=section))

        match_paths = [p.strip() for p in self.match_edit.text().split(",") if p.strip()]
        match_bytes = []
        for chunk in self.match_bytes_edit.text().split(","):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            off_text, hex_text = chunk.split(":", 1)
            try:
                match_bytes.append({"offset": int(off_text.strip(), 0), "hex": hex_text.strip()})
            except ValueError:
                continue
        return GameLayout(name=self.name_edit.text().strip() or self._layout_obj.name,
                           match_paths=match_paths, match_bytes=match_bytes, fields=fields)


_PATH_ROLE = Qt.UserRole
_TYPE_ROLE = Qt.UserRole + 1


def _format_chain(sf) -> str:
    """Human-readable format description, e.g. 'gzip -> json' for wrapped saves."""
    chain = [sf.fmt.name]
    meta = sf.meta
    while "_inner_fmt" in meta:
        inner = meta["_inner_fmt"]
        chain.append(inner.name)
        meta = {}  # inner formats don't nest meta further in this design
        break
    if "_wrapper" in sf.meta:
        return f"{sf.meta['_wrapper']} \u2192 {sf.meta['_inner_fmt'].name}"
    return sf.fmt.name


def _coerce_like(old_value, new_text: str):
    """Coerce text back to the original scalar type, including tagged values."""
    if TaggedValue is not None and isinstance(old_value, TaggedValue):
        old_value = old_value.value
    text = new_text.strip()
    if old_value is None:
        if text.lower() in ("null", "none", "~", ""):
            return None
        return new_text
    if isinstance(old_value, bool):
        lowered = text.lower()
        if lowered in ("true", "1", "yes", "on"): return True
        if lowered in ("false", "0", "no", "off"): return False
        raise ValueError("boolean must be true/false")
    if isinstance(old_value, int) and not isinstance(old_value, bool):
        return int(text, 0)
    if isinstance(old_value, float):
        return float(text)
    return new_text


def _hex_dump(raw: bytes) -> str:
    lines = []
    for offset in range(0, len(raw), HEX_BYTES_PER_LINE):
        chunk = raw[offset: offset + HEX_BYTES_PER_LINE]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_part:<{HEX_BYTES_PER_LINE * 3}}  {ascii_part}")
    return "\n".join(lines)


def _parse_hex_dump(text: str) -> bytes:
    """Reverse of _hex_dump: pull the hex bytes back out, ignore offset/ascii columns."""
    out = bytearray()
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        rest = parts[1] if len(parts) > 1 else line
        hex_field = rest[: HEX_BYTES_PER_LINE * 3].strip()
        for token in hex_field.split():
            out.append(int(token, 16))
    return bytes(out)


class _ValueEditorDialog(QDialog):
    """Type-aware editor for any scalar save value.

    The generic table deliberately uses a text cell for fast scanning, but
    this dialog removes the ambiguity around booleans, nulls, numbers, and
    tagged values. It is also used by the tree and custom layout views.
    """

    TYPES = ["auto", "string", "integer", "float", "boolean", "null"]

    def __init__(self, parent, value, tag: str = "", path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Edit Save Value")
        self.resize(560, 260)
        self._original = value
        self._tag = tag or ""

        # TaggedValue is a wrapper; edit its payload, not the wrapper itself.
        if TaggedValue is not None and isinstance(value, TaggedValue):
            self._tag = value.tag
            value = value.value
        self._value = value

        root = QVBoxLayout(self)
        if path:
            path_label = QLabel(path)
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(path_label)

        form = QFormLayout()
        self.type_box = QComboBox()
        self.type_box.addItems(self.TYPES)
        self.type_box.setCurrentText(self._type_name(value))
        form.addRow("Type:", self.type_box)

        self.value_edit = QLineEdit()
        self.value_edit.setText(self._display(value))
        form.addRow("Value:", self.value_edit)

        self.bool_box = QCheckBox("true")
        self.bool_box.setChecked(bool(value))
        form.addRow("Boolean:", self.bool_box)

        tag_label = QLabel(self._tag or "(none)")
        tag_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("YAML tag:", tag_label)
        root.addLayout(form)

        self.type_box.currentTextChanged.connect(self._type_changed)
        self._type_changed(self.type_box.currentText())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _type_name(value):
        if value is None: return "null"
        if isinstance(value, bool): return "boolean"
        if isinstance(value, int) and not isinstance(value, bool): return "integer"
        if isinstance(value, float): return "float"
        return "string"

    @staticmethod
    def _display(value):
        if value is None: return "null"
        if isinstance(value, bool): return "true" if value else "false"
        return str(value)

    def _type_changed(self, type_name):
        is_bool = type_name == "boolean"
        self.bool_box.setVisible(is_bool)
        self.value_edit.setVisible(not is_bool and type_name != "null")

    def value(self):
        t = self.type_box.currentText()
        if t == "null":
            return None
        if t == "boolean":
            return self.bool_box.isChecked()
        text = self.value_edit.text()
        if t == "integer":
            return int(text.strip())
        if t == "float":
            return float(text.strip())
        if t == "auto":
            return _coerce_like(self._value, text)
        return text


class SaveEditorModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.sf = None
        self.current_path: Path | None = None
        self._path_to_item: dict = {}
        self._loading = False  # guards itemChanged while we populate the tree
        self._layouts: list = []          # every saved GameLayout
        self.current_layout: GameLayout | None = None
        self._custom_widgets: dict = {}   # path -> the input widget in the custom view
        self._binary_view_mode = "hex"    # "hex" | "strings" — for raw/unrecognized binary saves
        self._string_hits: list = []      # last extract_strings() result, row index -> StringHit
        self._loading_strings = False     # guards itemChanged while we populate the strings table
        self._undo_stack = []
        self._redo_stack = []
        self._history_limit = 100
        self._saved_snapshot = None

        root = QVBoxLayout(self)

        title = QLabel("Save Editor")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "Works with any game's save: auto-detects JSON, XML, YAML, INI, gzip/zlib/base64-"
            "wrapped, and (via a saved decryption profile) encrypted saves. Build a custom "
            "layout to edit named fields like Gold or Coins directly. Unrecognized binary "
            "saves get a Readable Text view and a value search on top of raw hex, so you can "
            "find and name fields yourself \u2014 the same layout system then works for that "
            "game too."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # --- top toolbar ---------------------------------------------------
        bar = QHBoxLayout()
        open_btn = QPushButton("Open Save File")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open_file)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self._reload_file)
        self.reload_btn.setEnabled(False)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save_file)
        self.save_btn.setEnabled(False)
        self.save_as_btn = QPushButton("Save As\u2026")
        self.save_as_btn.clicked.connect(self._save_file_as)
        self.save_as_btn.setEnabled(False)
        self.diff_btn = QPushButton("Compare With\u2026")
        self.diff_btn.clicked.connect(self._compare_with)
        self.diff_btn.setEnabled(False)
        profiles_btn = QPushButton("Decryption Profiles…")
        profiles_btn.clicked.connect(self._manage_profiles)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn = QPushButton("Redo")
        self.redo_btn.setEnabled(False)
        self.redo_btn.clicked.connect(self._redo)
        backup_btn = QPushButton("Backup")
        backup_btn.clicked.connect(self._backup_file)
        export_btn = QPushButton("Export Data…")
        export_btn.clicked.connect(self._export_data)
        self.bl4_workspace_btn = QPushButton("BL4 Workspace…")
        self.bl4_workspace_btn.clicked.connect(self._open_bl4_workspace)
        self.bl4_workspace_btn.setEnabled(False)
        self.bl4_validate_btn = QPushButton("Validate BL4")
        self.bl4_validate_btn.clicked.connect(self._validate_bl4)
        self.bl4_validate_btn.setEnabled(False)
        for b in (open_btn, self.reload_btn, self.save_btn, self.save_as_btn, self.diff_btn, profiles_btn, self.undo_btn, self.redo_btn, backup_btn, export_btn, self.bl4_workspace_btn, self.bl4_validate_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.format_label = QLabel("No file loaded.")
        self.format_label.setObjectName("Muted")
        root.addWidget(self.format_label)

        # --- search row ------------------------------------------------------
        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Find a key anywhere in the save (e.g. gold)\u2026")
        self.search_box.returnPressed.connect(self._run_find)
        find_btn = QPushButton("Find")
        find_btn.clicked.connect(self._run_find)
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(find_btn)
        root.addLayout(search_row)

        # --- custom layout controls ------------------------------------------
        layout_row = QHBoxLayout()
        layout_row.addWidget(QLabel("Custom layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("(none \u2014 show tree)")
        self.layout_combo.currentIndexChanged.connect(self._on_layout_selected)
        layout_row.addWidget(self.layout_combo, 1)
        new_layout_btn = QPushButton("New Layout\u2026")
        new_layout_btn.clicked.connect(self._new_layout)
        edit_layout_btn = QPushButton("Edit Layout\u2026")
        edit_layout_btn.clicked.connect(self._edit_current_layout)
        layout_row.addWidget(new_layout_btn)
        layout_row.addWidget(edit_layout_btn)
        root.addLayout(layout_row)

        # --- main split: tree editor (or hex view) | find results / log ------
        splitter = QSplitter()

        editor_panel = QFrame()
        editor_panel.setObjectName("Panel")
        editor_layout = QVBoxLayout(editor_panel)
        tree_title = QLabel("Save Contents")
        tree_title.setObjectName("CardTitle")
        editor_layout.addWidget(tree_title)

        # --- binary view mode toggle + value search — shown only for raw/
        # unrecognized binary saves with no custom layout selected. "Hex"
        # is always available; "Readable Text" turns the same bytes into
        # the printable strings buried in them (see binary_scan.py), and
        # the search box finds a known number anywhere in the file so you
        # don't need to know the offset already.
        self.binary_tools_bar = QWidget()
        binary_tools_layout = QHBoxLayout(self.binary_tools_bar)
        binary_tools_layout.setContentsMargins(0, 0, 0, 0)
        self.hex_mode_btn = QPushButton("Hex")
        self.hex_mode_btn.setCheckable(True)
        self.hex_mode_btn.setChecked(True)
        self.hex_mode_btn.clicked.connect(lambda: self._set_binary_mode("hex"))
        self.text_mode_btn = QPushButton("Readable Text")
        self.text_mode_btn.setCheckable(True)
        self.text_mode_btn.clicked.connect(lambda: self._set_binary_mode("strings"))
        binary_tools_layout.addWidget(self.hex_mode_btn)
        binary_tools_layout.addWidget(self.text_mode_btn)
        binary_tools_layout.addSpacing(16)
        binary_tools_layout.addWidget(QLabel("Find value:"))
        self.value_search_box = QLineEdit()
        self.value_search_box.setPlaceholderText("e.g. 500 or 12.5")
        self.value_search_box.setMaximumWidth(120)
        self.value_search_box.returnPressed.connect(self._run_binary_search)
        binary_tools_layout.addWidget(self.value_search_box)
        self.value_type_box = QComboBox()
        self.value_type_box.addItems(["any numeric type"] + list(_binary_scan.NUMERIC_TYPES))
        binary_tools_layout.addWidget(self.value_type_box)
        value_search_btn = QPushButton("Search")
        value_search_btn.clicked.connect(self._run_binary_search)
        binary_tools_layout.addWidget(value_search_btn)
        binary_tools_layout.addStretch(1)
        self.binary_tools_bar.setVisible(False)
        editor_layout.addWidget(self.binary_tools_bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Key", "Value", "Type"])
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        editor_layout.addWidget(self.tree, 1)

        # custom, per-game form view — built from the selected GameLayout
        self.custom_scroll = QScrollArea()
        self.custom_scroll.setWidgetResizable(True)
        self.custom_scroll.setVisible(False)
        self.custom_content = QWidget()
        self.custom_content_layout = QVBoxLayout(self.custom_content)
        self.custom_content_layout.addStretch(1)
        self.custom_scroll.setWidget(self.custom_content)
        editor_layout.addWidget(self.custom_scroll, 1)

        self.hex_edit = QPlainTextEdit()
        self.hex_edit.setVisible(False)
        self.hex_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.hex_edit.setStyleSheet("font-family: monospace;")
        editor_layout.addWidget(self.hex_edit, 1)

        # "Readable Text" view — every printable string binary_scan found,
        # with its offset, so you can see what "4f 00 6c 00 64 00" *means*
        # without reading hex. Double-click Text to rename it in place
        # (only shortening/same-length edits are allowed, so nothing after
        # it in the file shifts); right-click to turn it into a named,
        # reusable field in a custom layout.
        self.strings_table = QTableWidget(0, 4)
        self.strings_table.setHorizontalHeaderLabels(["Offset", "Length", "Encoding", "Text"])
        self.strings_table.horizontalHeader().setStretchLastSection(True)
        self.strings_table.setVisible(False)
        self.strings_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.strings_table.customContextMenuRequested.connect(self._strings_context_menu)
        self.strings_table.itemChanged.connect(self._on_string_edited)
        editor_layout.addWidget(self.strings_table, 1)

        # Borderlands 4 readable stats view. BL4 saves decrypt to a large
        # tagged YAML tree; the normal tree is useful for structure but is
        # cumbersome when you want to scan every scalar stat at once.
        self.bl4_stats_bar = QWidget()
        bl4_stats_layout = QHBoxLayout(self.bl4_stats_bar)
        bl4_stats_layout.setContentsMargins(0, 0, 0, 0)
        bl4_stats_layout.addWidget(QLabel("Find:"))
        self.bl4_stats_filter = QLineEdit()
        self.bl4_stats_filter.setPlaceholderText("Try: cash, eridium, level, mayhem, ammo, grapple, mission…")
        self.bl4_stats_filter.setClearButtonEnabled(True)
        self.bl4_stats_filter.textChanged.connect(self._filter_bl4_stats)
        bl4_stats_layout.addWidget(self.bl4_stats_filter, 2)
        bl4_stats_layout.addWidget(QLabel("Category:"))
        self.bl4_category_filter = QComboBox()
        self.bl4_category_filter.currentTextChanged.connect(self._filter_bl4_stats)
        bl4_stats_layout.addWidget(self.bl4_category_filter, 1)
        bl4_stats_layout.addWidget(QLabel("View:"))
        self.bl4_view_filter = QComboBox()
        self.bl4_view_filter.addItems(["Essentials", "All Values", "Technical"])
        self.bl4_view_filter.currentTextChanged.connect(self._filter_bl4_stats)
        bl4_stats_layout.addWidget(self.bl4_view_filter)
        self.bl4_stats_count = QLabel("")
        self.bl4_stats_count.setObjectName("Muted")
        bl4_stats_layout.addWidget(self.bl4_stats_count)
        self.bl4_edit_btn = QPushButton("Edit Selected…")
        self.bl4_edit_btn.clicked.connect(self._edit_selected_bl4_stat)
        bl4_stats_layout.addWidget(self.bl4_edit_btn)
        self.bl4_stats_bar.setVisible(False)
        editor_layout.addWidget(self.bl4_stats_bar)

        self.bl4_stats_table = QTableWidget(0, 6)
        self.bl4_stats_table.setHorizontalHeaderLabels(["Category", "Name", "Value", "Type", "Technical Path", "Tag"])
        self.bl4_stats_table.setAlternatingRowColors(True)
        self.bl4_stats_table.setSortingEnabled(True)
        self.bl4_stats_table.setSelectionBehavior(QTableWidget.SelectRows)
        # BL4 values use the type-aware Edit Selected / double-click dialog.
        # Do not allow QTableWidget inline editing here: it emits itemChanged
        # while the dialog path is also active, which can apply/log the same
        # edit multiple times.
        self.bl4_stats_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.bl4_stats_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.bl4_stats_table.setColumnHidden(4, True)
        self.bl4_stats_table.setColumnHidden(5, True)
        self.bl4_stats_table.setVisible(False)
        self.bl4_stats_table.cellDoubleClicked.connect(self._on_bl4_stat_double_clicked)
        self.bl4_stats_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bl4_stats_table.customContextMenuRequested.connect(self._bl4_stats_context_menu)
        editor_layout.addWidget(self.bl4_stats_table, 1)

        self.apply_hex_btn = QPushButton("Apply Hex Changes")
        self.apply_hex_btn.setVisible(False)
        self.apply_hex_btn.clicked.connect(self._apply_hex_changes)
        editor_layout.addWidget(self.apply_hex_btn)

        splitter.addWidget(editor_panel)

        side_panel = QFrame()
        side_panel.setObjectName("Panel")
        side_layout = QVBoxLayout(side_panel)
        results_title = QLabel("Find Results")
        results_title.setObjectName("CardTitle")
        side_layout.addWidget(results_title)
        self.results_list = QListWidget()
        self.results_list.itemActivated.connect(self._jump_to_result)
        self.results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._results_context_menu)
        side_layout.addWidget(self.results_list, 1)

        log_title = QLabel("Log")
        log_title.setObjectName("CardTitle")
        side_layout.addWidget(log_title)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        side_layout.addWidget(self.log_box)

        splitter.addWidget(side_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

    # ------------------------------------------------------------------
    # file operations
    # ------------------------------------------------------------------

    def _record_edit(self, description: str = "Edit"):
        if self.sf is None: return
        self._undo_stack.append((copy.deepcopy(self.sf.data), description))
        if len(self._undo_stack) > self._history_limit: self._undo_stack.pop(0)
        self._redo_stack.clear(); self._update_history_buttons()

    def _update_history_buttons(self):
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(bool(self._undo_stack)); self.redo_btn.setEnabled(bool(self._redo_stack))

    def _undo(self):
        if self.sf is None or not self._undo_stack: return
        current=copy.deepcopy(self.sf.data); snapshot,desc=self._undo_stack.pop(); self._redo_stack.append((current,desc))
        self.sf.data=copy.deepcopy(snapshot); self._refresh_view(); self._update_history_buttons(); self.status.setText(f"Undid: {desc}")

    def _redo(self):
        if self.sf is None or not self._redo_stack: return
        current=copy.deepcopy(self.sf.data); snapshot,desc=self._redo_stack.pop(); self._undo_stack.append((current,desc))
        self.sf.data=copy.deepcopy(snapshot); self._refresh_view(); self._update_history_buttons(); self.status.setText(f"Redid: {desc}")

    def _backup_file(self):
        if self.current_path is None or not self.current_path.exists(): self._fail("Open a save file first."); return
        try:
            stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
            dest=self.current_path.with_name(f"{self.current_path.stem}.backup_{stamp}{self.current_path.suffix}")
            shutil.copy2(self.current_path,dest); self._log(f"Backup created: {dest}"); self.status.setText(f"Backup created: {dest.name}")
        except Exception as exc: self._fail(f"Could not create backup: {exc}")

    def _json_safe(self,value):
        if TaggedValue is not None and isinstance(value,TaggedValue): return self._json_safe(value.value)
        if value is None or isinstance(value,(str,int,float,bool)): return value
        if isinstance(value,(bytes,bytearray)): return {"__bytes__":bytes(value).hex()}
        if isinstance(value,dict): return {str(k):self._json_safe(v) for k,v in value.items()}
        if isinstance(value,list): return [self._json_safe(v) for v in value]
        return repr(value)

    def _collect_generic_scalars(self):
        rows=[]
        def walk(node,path=""):
            if TaggedValue is not None and isinstance(node,TaggedValue): walk(node.value,path); return
            if isinstance(node,dict):
                for k,v in node.items(): walk(v,f"{path}.{k}" if path else str(k))
            elif isinstance(node,list):
                for i,v in enumerate(node): walk(v,f"{path}[{i}]")
            else: rows.append((path,node,""))
        walk(self.sf.data); return rows

    def _export_data(self):
        if self.sf is None: return
        path,_=QFileDialog.getSaveFileName(self,"Export readable data","save_export.json","JSON (*.json);;Text (*.txt)")
        if not path: return
        rows=self._collect_bl4_scalars() if self._is_bl4_save() else self._collect_generic_scalars()
        try:
            payload=[{"path":p,"value":self._json_safe(v),"tag":t} for p,v,t in rows]
            if path.lower().endswith('.txt'): Path(path).write_text("\n".join(f"{r['path']} = {r['value']!r}" for r in payload),encoding='utf-8')
            else: Path(path).write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
            self._log(f"Exported {len(payload):,} values to {path}"); self.status.setText(f"Exported {len(payload):,} values.")
        except Exception as exc: self._fail(f"Could not export data: {exc}")

    def _log(self, text: str):
        self.log_box.appendPlainText(text)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open save file")
        if not path:
            return
        self._load_path(Path(path))

    def _reload_file(self):
        if self.current_path is not None:
            self._load_path(self.current_path)

    def _load_path(self, path: Path):
        try:
            sf = SaveFile.load(str(path))
        except Exception as exc:
            self._fail(f"Could not load {path.name}: {exc}")
            return
        self.sf = sf
        self.current_path = path
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._saved_snapshot = copy.deepcopy(sf.data)
        self._update_history_buttons()
        self.reload_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.save_as_btn.setEnabled(True)
        self.diff_btn.setEnabled(True)
        self.bl4_workspace_btn.setEnabled(self._is_bl4_save())
        if hasattr(self, "bl4_validate_btn"):
            self.bl4_validate_btn.setEnabled(self._is_bl4_save())
        self.format_label.setObjectName("Muted")
        self.format_label.setText(f"{path.name}  \u2014  format: {_format_chain(sf)}")
        self._log(f"Opened {path} (format: {_format_chain(sf)})")
        self.results_list.clear()
        self._reload_layouts_and_autoselect()
        self._refresh_view()
        self.status.setText("Loaded.")

    def _validate_bl4(self):
        if self.sf is None or not self._is_bl4_save():
            self.status.setText("Open a Borderlands 4 save first.")
            return
        problems = _bl4_tools.validate_bl4_save(self.sf)
        if problems:
            text = "BL4 validation found issues:\n\n" + "\n".join("• " + p for p in problems[:50])
            if len(problems) > 50:
                text += f"\n\n…and {len(problems) - 50} more."
            QMessageBox.warning(self, "BL4 Save Validation", text)
            self._log(f"BL4 validation: {len(problems)} issue(s).")
        else:
            QMessageBox.information(self, "BL4 Save Validation", "No problems were found in the known BL4 structures. Unknown game fields are not treated as errors.")
            self._log("BL4 validation passed.")

    def _open_bl4_workspace(self):
        if self.sf is None or not self._is_bl4_save():
            self.status.setText("Open a Borderlands 4 save first.")
            return
        try:
            dlg = _bl4_tools.BL4Workspace(
                self,
                self.sf,
                self._edit_path_from_bl4_workspace,
                lambda desc: self._record_edit(desc),
            )
            dlg.exec()
            self._refresh_view()
        except Exception as exc:
            self._fail(f"Could not open BL4 workspace: {exc}")

    def _edit_path_from_bl4_workspace(self, path: str):
        if self.sf is None:
            return
        try:
            old = self.sf.get(path)
        except Exception:
            self._fail(f"Path not found: {path}")
            return
        dlg = _ValueEditorDialog(self, old, getattr(old, "tag", ""), path)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            value = dlg.value()
            self._record_edit(f"Edit {path}")
            self.sf.set(path, value)
            self._log(f"{path}: {old!r} → {self.sf.get(path)!r}")
            self.status.setText(f"Updated {path} — remember to Save.")
        except Exception as exc:
            self._fail(f"Could not edit {path}: {exc}")

    def _reload_layouts_and_autoselect(self):
        self._layouts = _layouts.load_layouts(_module.layouts_path())
        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        self.layout_combo.addItem("(none \u2014 show tree)")
        for l in self._layouts:
            self.layout_combo.addItem(l.name)
        match = _layouts.find_layout_for(self.sf, self._layouts) if self._layouts else None
        self.current_layout = match
        self.layout_combo.setCurrentIndex(
            self._layouts.index(match) + 1 if match else 0
        )
        self.layout_combo.blockSignals(False)
        if match:
            self._log(f"Auto-selected layout '{match.name}' for this save.")

    def _refresh_view(self):
        top_fmt = self.sf.fmt.name
        is_structured_top = top_fmt in STRUCTURED_FORMATS or "_inner_fmt" in self.sf.meta
        is_structured = is_structured_top and isinstance(self.sf.data, (dict, list))
        is_raw = isinstance(self.sf.data, dict) and "_raw" in self.sf.data and not is_structured

        # hide everything, then show only what this save/mode needs
        self.tree.setVisible(False)
        self.custom_scroll.setVisible(False)
        self.hex_edit.setVisible(False)
        self.strings_table.setVisible(False)
        self.bl4_stats_bar.setVisible(False)
        self.bl4_stats_table.setVisible(False)
        self.apply_hex_btn.setVisible(False)
        self.binary_tools_bar.setVisible(False)

        # BL4 is encrypted -> zlib -> tagged YAML. Show a flat, searchable
        # scalar-stat table alongside the normal tree so the save is readable
        # without manually opening every nested object.
        if self._is_bl4_save() and is_structured:
            self.bl4_stats_bar.setVisible(True)
            self.bl4_stats_table.setVisible(True)
            self._populate_bl4_stats()
            self.status.setText("Borderlands 4 — readable stats view. Double-click a value to edit it.")
            return

        if self.current_layout and (is_structured or is_raw):
            # a custom layout applies to both structured saves (path
            # fields) and raw binary saves (offset fields) the same way
            self.custom_scroll.setVisible(True)
            self._build_custom_editor()
            return

        if is_structured:
            self.tree.setVisible(True)
            self._populate_tree()
            return

        # raw / unrecognized binary, no layout selected yet — hex is
        # always available; Readable Text decodes the printable strings
        # in it so you don't have to eyeball hex to find "PlayerName".
        self.binary_tools_bar.setVisible(True)
        raw = self.sf.data.get("_raw", b"") if isinstance(self.sf.data, dict) else b""
        if len(raw) > HEX_SIZE_WARN_BYTES:
            self._log(
                f"Warning: {len(raw):,} bytes is large for this view; "
                "editing may be slow. Consider building a Custom Layout for known fields."
            )
        if self._binary_view_mode == "strings":
            self.strings_table.setVisible(True)
            self._populate_strings(raw)
            self.status.setText(
                "Unrecognized binary format \u2014 showing readable text found in the file. "
                "Right-click a row to save it as a named field, or switch to Hex."
            )
        else:
            self.hex_edit.setVisible(True)
            self.apply_hex_btn.setVisible(True)
            self.hex_edit.setPlainText(_hex_dump(raw))
            self.status.setText(
                "Unrecognized binary format \u2014 showing raw hex. Try \"Readable Text\" above, "
                "or search for a known value, to find fields without a hex editor."
            )

    def _is_bl4_save(self) -> bool:
        """Return True when the current save was decoded by the BL4 profile."""
        if self.sf is None:
            return False
        profile = self.sf.meta.get("_profile")
        if profile is not None and getattr(profile, "algo", "") == "bl4-steamid":
            return True
        return "borderlands 4" in _format_chain(self.sf).lower()

    def _collect_bl4_scalars(self):
        rows = []

        def walk(node, path=""):
            tag = ""
            value = node
            if TaggedValue is not None and isinstance(node, TaggedValue):
                tag = node.tag
                value = node.value

            if isinstance(value, dict):
                for key, child in value.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    walk(child, child_path)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    walk(child, f"{path}[{i}]")
            else:
                rows.append((path, value, tag))

        walk(self.sf.data)
        return rows


    def _load_readable_schema(self):
        """Load editable category rules. Users can add their own rules without changing Python."""
        schema_path = Path(__file__).with_name("readable_schemas.json")
        try:
            raw = json.loads(schema_path.read_text(encoding="utf-8"))
            return raw.get("borderlands4", {}).get("categories", [])
        except Exception as exc:
            self._log(f"Readable schema unavailable: {exc}")
            return []

    def _category_for_bl4_path(self, path):
        for rule in getattr(self, "_bl4_schema", []):
            prefixes = rule.get("prefixes", [])
            if any(path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[") for prefix in prefixes):
                return rule.get("name", "General")
        return path.split(".", 1)[0].replace("_", " ").title() if path else "General"

    def _load_view_profile(self):
        """Load bundled game view profiles, then apply user overrides by id."""
        cfg = {}
        try:
            cfg = json.loads(_bundled_config_path(_module.VIEW_PROFILES_FILENAME).read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        try:
            user_path = Path(_module.view_profiles_path())
            if user_path.exists():
                user_cfg = json.loads(user_path.read_text(encoding="utf-8"))
                profiles = {p.get("id"): p for p in cfg.get("profiles", []) if p.get("id")}
                for p in user_cfg.get("profiles", []):
                    if p.get("id"):
                        profiles[p["id"]] = p
                cfg["profiles"] = list(profiles.values())
                if "default" in user_cfg:
                    cfg["default"] = user_cfg["default"]
        except Exception as exc:
            self._log(f"Custom view profiles unavailable: {exc}")
        profile = self.sf.meta.get("_profile") if self.sf else None
        algo = getattr(profile, "algo", "") if profile else ""
        for item in cfg.get("profiles", []):
            if item.get("match", {}).get("profile_algo") == algo:
                return item
        return cfg.get("default", {"sections": [], "fallback": "Other"})

    def _section_for_path(self, path, view_profile):
        for section in view_profile.get("sections", []):
            for pattern in section.get("match", []):
                if fnmatch.fnmatchcase(path.lower(), pattern.lower()):
                    return section.get("name", "Other")
        return view_profile.get("fallback", "Other")

    def _populate_bl4_stats(self):
        self._loading_bl4_stats = True
        self.bl4_stats_table.blockSignals(True)
        self.bl4_stats_table.setSortingEnabled(False)
        self.bl4_stats_table.setRowCount(0)
        self._bl4_schema = self._load_readable_schema()
        self._bl4_stat_rows = self._collect_bl4_scalars()

        self.bl4_category_filter.blockSignals(True)
        self.bl4_category_filter.clear()
        self.bl4_category_filter.addItem("All Categories")
        categories = sorted({_bl4_section(path) for path, _, _ in self._bl4_stat_rows})
        self.bl4_category_filter.addItems(categories)
        self.bl4_category_filter.blockSignals(False)

        for path, value, tag in self._bl4_stat_rows:
            r = self.bl4_stats_table.rowCount()
            self.bl4_stats_table.insertRow(r)
            category = _bl4_section(path)
            name = _bl4_friendly_name(path)
            display_value = "null" if value is None else ("true" if value is True else "false" if value is False else str(value))

            items = [
                QTableWidgetItem(category),
                QTableWidgetItem(name),
                QTableWidgetItem(display_value),
                QTableWidgetItem(type(value).__name__),
                QTableWidgetItem(path),
                QTableWidgetItem(tag),
            ]
            for c, item in enumerate(items):
                if c != 2:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            items[1].setToolTip(path)
            items[2].setToolTip(f"{name}\n\n{path}")
            value_item = items[2]
            value_item.setData(Qt.UserRole, path)
            value_item.setData(Qt.UserRole + 1, value)
            value_item.setData(Qt.UserRole + 2, tag)
            self.bl4_stats_table.setItem(r, 0, items[0])
            self.bl4_stats_table.setItem(r, 1, items[1])
            self.bl4_stats_table.setItem(r, 2, items[2])
            self.bl4_stats_table.setItem(r, 3, items[3])
            self.bl4_stats_table.setItem(r, 4, items[4])
            self.bl4_stats_table.setItem(r, 5, items[5])

        self.bl4_stats_table.setSortingEnabled(True)
        self.bl4_stats_table.blockSignals(False)
        self._loading_bl4_stats = False
        self._filter_bl4_stats()
        self.status.setText(
            f"Borderlands 4 — {len(self._bl4_stat_rows):,} editable values. "
            "Essentials hides internal/noisy data; All Values shows everything."
        )

    def _filter_bl4_stats(self, text=None):
        if not hasattr(self, "bl4_stats_table"):
            return
        needle = self.bl4_stats_filter.text().strip().lower()
        selected_category = self.bl4_category_filter.currentText() if hasattr(self, "bl4_category_filter") else "All Categories"
        view = self.bl4_view_filter.currentText() if hasattr(self, "bl4_view_filter") else "Essentials"
        visible = 0
        total = self.bl4_stats_table.rowCount()
        for row in range(total):
            category_item = self.bl4_stats_table.item(row, 0)
            name_item = self.bl4_stats_table.item(row, 1)
            value_item = self.bl4_stats_table.item(row, 2)
            path_item = self.bl4_stats_table.item(row, 4)
            if not (name_item and value_item and path_item):
                continue
            path = path_item.text()
            haystack = " ".join((name_item.text(), value_item.text(), path)).lower()
            category_match = selected_category in ("", "All Categories") or (category_item and category_item.text() == selected_category)
            search_match = not needle or needle in haystack
            if view == "Essentials":
                view_match = _bl4_is_essential(path)
            elif view == "Technical":
                view_match = not _bl4_is_essential(path)
            else:
                view_match = True
            hidden = not (category_match and search_match and view_match)
            self.bl4_stats_table.setRowHidden(row, hidden)
            if not hidden:
                visible += 1
        self.bl4_stats_count.setText(f"{visible:,} shown / {total:,} editable")

    def _edit_bl4_row(self, row: int):
        item = self.bl4_stats_table.item(row, 2)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        old_value = item.data(Qt.UserRole + 1)
        if not path:
            return
        dlg = _ValueEditorDialog(self, old_value, item.data(Qt.UserRole + 2) or "", path)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            value = dlg.value()
            if value == old_value:
                self.status.setText(f"No change to {path}.")
                return
            self._record_edit(f"Edit {path}")
            self.sf.set(path, value)
            actual = self.sf.get(path)
            # Updating the table is display-only and must not generate another
            # edit event. Inline editing is disabled above, but keep this
            # update signal-safe in case the table configuration changes later.
            self.bl4_stats_table.blockSignals(True)
            try:
                item.setData(Qt.UserRole + 1, actual)
                item.setText("null" if actual is None else ("true" if actual is True else "false" if actual is False else str(actual)))
            finally:
                self.bl4_stats_table.blockSignals(False)
            self._log(f"{path}: {old_value!r} → {actual!r}")
            self.status.setText(f"Updated {path} — remember to Save.")
        except Exception as exc:
            self._fail(f"Could not set {path}: {exc}")

    def _on_bl4_stat_double_clicked(self, row, column):
        if column == 2:
            self._edit_bl4_row(row)

    def _on_bl4_stat_edited(self, item: QTableWidgetItem):
        if getattr(self, "_loading_bl4_stats", False) or item.column() != 2:
            return
        path = item.data(Qt.UserRole)
        old_value = item.data(Qt.UserRole + 1)
        if not path:
            return
        try:
            coerced = _coerce_like(old_value, item.text())
            self._record_edit(f"Edit {path}")
            self.sf.set(path, coerced)
            actual = self.sf.get(path)
            item.setData(Qt.UserRole + 1, actual)
            if actual is None: item.setText("null")
            self._log(f"{path}: {old_value!r} → {actual!r}")
            self.status.setText(f"Updated {path} — remember to Save.")
        except Exception as exc:
            self._fail(f"Could not set {path} to {item.text()!r}: {exc}")
            self.bl4_stats_table.blockSignals(True)
            item.setText("null" if old_value is None else str(old_value))
            self.bl4_stats_table.blockSignals(False)

    def _edit_selected_bl4_stat(self):
        rows = self.bl4_stats_table.selectionModel().selectedRows()
        if rows:
            self._edit_bl4_row(rows[0].row())
        else:
            self.status.setText("Select a stat first.")

    def _bl4_stats_context_menu(self, pos):
        item = self.bl4_stats_table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        path_item = self.bl4_stats_table.item(row, 4)
        value_item = self.bl4_stats_table.item(row, 2)
        if value_item is None or path_item is None:
            return
        menu = QMenu(self)
        edit = QAction("Edit Value…", self)
        edit.triggered.connect(lambda: self._edit_bl4_row(row))
        menu.addAction(edit)
        copy_path = QAction("Copy Path", self)
        copy_path.triggered.connect(lambda: self._copy_text(path_item.text()))
        menu.addAction(copy_path)
        menu.exec(self.bl4_stats_table.viewport().mapToGlobal(pos))

    def _copy_text(self, text):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.status.setText("Copied to clipboard.")

    def _set_binary_mode(self, mode: str):
        self._binary_view_mode = mode
        self.hex_mode_btn.setChecked(mode == "hex")
        self.text_mode_btn.setChecked(mode == "strings")
        if self.sf is not None:
            self._refresh_view()

    def _populate_tree(self):
        self._loading = True
        self.tree.blockSignals(True)
        self.tree.clear()
        self._path_to_item.clear()
        root_item = self.tree.invisibleRootItem()
        data = self.sf.data
        if isinstance(data, dict):
            for k, v in data.items():
                self._add_node(root_item, str(k), v, k)
        elif isinstance(data, list):
            for i, v in enumerate(data):
                self._add_node(root_item, f"[{i}]", v, f"[{i}]")
        self.tree.expandToDepth(1)
        self.tree.blockSignals(False)
        self._loading = False

    def _add_node(self, parent_item, label: str, value, path: str):
        tag_suffix = ""
        display = value
        if TaggedValue is not None and isinstance(value, TaggedValue):
            # Show the custom tag alongside the type instead of dumping
            # a raw TaggedValue(...) repr; iterate the wrapped value so
            # tagged dicts/lists are still browsable. Path traversal
            # keeps working untouched because TaggedValue delegates
            # __getitem__/__setitem__ to what it wraps.
            tag_suffix = f"  {value.tag}"
            display = value.value
        if isinstance(display, dict):
            item = QTreeWidgetItem([label, "", f"object{tag_suffix}"])
            parent_item.addChild(item)
            for k, v in display.items():
                self._add_node(item, str(k), v, f"{path}.{k}")
        elif isinstance(display, list):
            item = QTreeWidgetItem([label, f"[{len(display)} items]", f"array{tag_suffix}"])
            parent_item.addChild(item)
            for i, v in enumerate(display):
                self._add_node(item, f"[{i}]", v, f"{path}[{i}]")
        elif tag_suffix:
            # tagged scalar, e.g. `!SomeTag 5` — editable like a normal
            # leaf; _coerce_like falls back to plain text for unknown
            # types, which drops the tag only if this exact leaf is
            # the one edited (everything else round-trips untouched).
            item = QTreeWidgetItem([label, "" if display is None else str(display), f"tagged{tag_suffix}"])
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setData(0, _PATH_ROLE, path)
            item.setData(0, _TYPE_ROLE, type(display))
            parent_item.addChild(item)
            self._path_to_item[path] = item
        else:
            item = QTreeWidgetItem([label, "" if value is None else str(value), type(value).__name__])
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setData(0, _PATH_ROLE, path)
            item.setData(0, _TYPE_ROLE, type(value))
            parent_item.addChild(item)
            self._path_to_item[path] = item

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._loading or column != 1:
            return
        path = item.data(0, _PATH_ROLE)
        if path is None:
            return  # an object/array row, not an editable leaf
        old_value = self.sf.get(path)
        new_text = item.text(1)
        try:
            coerced = _coerce_like(old_value, new_text)
            self._record_edit(f"Edit {path}")
            self.sf.set(path, coerced)
            self._log(f"{path}: {old_value!r} \u2192 {coerced!r}")
            self.status.setText(f"Updated {path}")
        except (ValueError, PathError) as exc:
            self._log(f"Could not set {path} to {new_text!r}: {exc}")
            self.tree.blockSignals(True)
            item.setText(1, "" if old_value is None else str(old_value))
            self.tree.blockSignals(False)
            self.status.setObjectName("Danger")
            self.status.setText(f"Invalid value for {path} \u2014 reverted.")

    # ------------------------------------------------------------------
    # custom per-game layout view
    # ------------------------------------------------------------------

    def _build_custom_editor(self):
        # clear previous contents
        while self.custom_content_layout.count():
            item = self.custom_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._custom_widgets.clear()

        sections: dict = {}
        for f in self.current_layout.fields:
            sections.setdefault(f.section, []).append(f)

        for section_name, fields in sections.items():
            box = QGroupBox(section_name)
            form = QFormLayout(box)
            for f in fields:
                try:
                    current = self._get_field_value(f)
                except Exception:
                    where = f"offset {f.offset}" if f.is_binary else f"path {f.path!r}"
                    form.addRow(f.label, QLabel(f"(not found in this save \u2014 {where})"))
                    continue
                if TaggedValue is not None and isinstance(current, TaggedValue):
                    current = current.value
                widget = self._make_field_widget(f, current)
                form.addRow(f.label, widget)
                self._custom_widgets[id(f)] = (widget, f)
            self.custom_content_layout.addWidget(box)
        self.custom_content_layout.addStretch(1)

    def _get_field_value(self, f: FieldSpec):
        if f.is_binary:
            return self.sf.get_binary_field(f.offset, f.type, f.size, f.endian)
        return self.sf.get(f.path)

    def _make_field_widget(self, f: FieldSpec, current):
        if f.is_binary:
            resolved_type = f.type
        else:
            resolved_type = f.type
            if resolved_type == "auto":
                resolved_type = {bool: "bool", int: "int", float: "float"}.get(type(current), "string")

        if resolved_type == "bool":
            w = QCheckBox()
            w.setChecked(bool(current))
            w.stateChanged.connect(lambda _st, fs=f, box=w: self._commit_field(fs, box.isChecked()))
            return w

        if resolved_type in ("int", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64"):
            w = QSpinBox()
            w.setRange(int(f.min) if f.min is not None else -2_147_483_648,
                       int(f.max) if f.max is not None else 2_147_483_647)
            w.setSingleStep(int(f.step) or 1)
            w.setValue(int(current))
            w.editingFinished.connect(lambda fs=f, box=w: self._commit_field(fs, box.value()))
            return w

        if resolved_type in ("float", "float32", "float64"):
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(f.min if f.min is not None else -1e12, f.max if f.max is not None else 1e12)
            w.setSingleStep(f.step or 1.0)
            w.setValue(float(current))
            w.editingFinished.connect(lambda fs=f, box=w: self._commit_field(fs, box.value()))
            return w

        if resolved_type == "bytes":
            w = QLineEdit("" if current is None else current.hex())
            w.setPlaceholderText(f"{f.size} bytes, as hex")
            w.editingFinished.connect(lambda fs=f, box=w: self._commit_field(fs, bytes.fromhex(box.text().strip())))
            return w

        # string / cstr / utf16str / anything else
        w = QLineEdit("" if current is None else str(current))
        if f.is_binary and f.size:
            max_chars = f.size - 1 if f.type == "cstr" else f.size // 2 - 1
            w.setMaxLength(max(max_chars, 0))
        w.editingFinished.connect(lambda fs=f, box=w: self._commit_field(fs, box.text()))
        return w

    def _commit_field(self, f: FieldSpec, value):
        label = f.label
        try:
            self._record_edit(f"Edit {label}")
            if f.is_binary:
                self.sf.set_binary_field(f.offset, f.type, value, f.size, f.endian)
            else:
                self.sf.set(f.path, value)
            self._log(f"{label}: \u2192 {value!r}")
            self.status.setText(f"Updated {label}")
        except (ValueError, PathError, struct.error) as exc:
            self._fail(f"Could not set {label} to {value!r}: {exc}")

    def _on_layout_selected(self, index: int):
        self.current_layout = self._layouts[index - 1] if index > 0 else None
        if self.sf is not None:
            self._refresh_view()

    def _new_layout(self):
        blank = GameLayout(name="New Layout")
        dlg = _LayoutDesignerDialog(self, blank)
        if dlg.exec() != QDialog.Accepted:
            return
        new_layout = dlg.result_layout()
        self._layouts.append(new_layout)
        _layouts.save_layouts(_module.layouts_path(), self._layouts)
        self._reload_layouts_and_autoselect()
        # select the one just created
        idx = next((i for i, l in enumerate(self._layouts) if l.name == new_layout.name), None)
        if idx is not None:
            self.layout_combo.setCurrentIndex(idx + 1)

    def _edit_current_layout(self):
        if self.current_layout is None:
            self._fail("Select a layout first (or create one with 'New Layout\u2026').")
            return
        old_name = self.current_layout.name
        dlg = _LayoutDesignerDialog(self, self.current_layout)
        if dlg.exec() != QDialog.Accepted:
            return
        updated = dlg.result_layout()
        self._layouts = [updated if l.name == old_name else l for l in self._layouts]
        _layouts.save_layouts(_module.layouts_path(), self._layouts)
        self._reload_layouts_and_autoselect()
        idx = next((i for i, l in enumerate(self._layouts) if l.name == updated.name), None)
        if idx is not None:
            self.layout_combo.setCurrentIndex(idx + 1)
        self._log(f"Layout '{updated.name}' saved.")

    def _tree_context_menu(self, pos):
        item=self.tree.itemAt(pos)
        if item is None: return
        path=item.data(0,_PATH_ROLE); menu=QMenu(self)
        if path is not None:
            act=QAction("Edit Value…",self); act.triggered.connect(lambda:self._edit_tree_value(path)); menu.addAction(act)
            cp=QAction("Copy Path",self); cp.triggered.connect(lambda:self._copy_text(path)); menu.addAction(cp)
            try: node=self.sf.get(path)
            except Exception: node=None
            menu.addSeparator()
            if isinstance(node,dict):
                a=QAction("Add Property…",self); a.triggered.connect(lambda:self._add_dict_property(path)); menu.addAction(a)
            elif isinstance(node,list):
                a=QAction("Append Array Item…",self); a.triggered.connect(lambda:self._append_list_item(path)); menu.addAction(a)
                if node:
                    a=QAction("Duplicate Last Item",self); a.triggered.connect(lambda:self._duplicate_list_item(path)); menu.addAction(a)
            d=QAction("Delete…",self); d.triggered.connect(lambda:self._delete_path(path)); menu.addAction(d)
        if menu.actions(): menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _edit_tree_value(self,path):
        try: value=self.sf.get(path)
        except Exception as exc: self._fail(str(exc)); return
        if isinstance(value,(dict,list)) or (TaggedValue is not None and isinstance(value,TaggedValue) and isinstance(value.value,(dict,list))):
            self._show_container_json(path,value); return
        tag=value.tag if TaggedValue is not None and isinstance(value,TaggedValue) else ""
        dlg=_ValueEditorDialog(self,value,tag,path)
        if dlg.exec()!=QDialog.Accepted: return
        try:
            self._record_edit(f"Edit {path}"); self.sf.set(path,dlg.value()); self._refresh_view()
        except Exception as exc: self._fail(f"Could not set {path}: {exc}")

    def _copy_text(self,text):
        self.window().clipboard().setText(str(text)); self.status.setText("Copied to clipboard.")

    def _add_dict_property(self,path):
        key,ok=QInputDialog.getText(self,"Add Property","Property name:")
        if not ok or not key.strip(): return
        try:
            node=self.sf.get(path)
            if key in node: self._fail(f"Property already exists: {key}"); return
            dlg=_ValueEditorDialog(self,None,"",f"{path}.{key}")
            if dlg.exec()!=QDialog.Accepted: return
            self._record_edit(f"Add {path}.{key}"); node[key]=dlg.value(); self._refresh_view()
        except Exception as exc: self._fail(f"Could not add property: {exc}")

    def _append_list_item(self,path):
        try:
            node=self.sf.get(path); dlg=_ValueEditorDialog(self,None,"",f"{path}[{len(node)}]")
            if dlg.exec()!=QDialog.Accepted: return
            self._record_edit(f"Append {path}[{len(node)}]"); node.append(dlg.value()); self._refresh_view()
        except Exception as exc: self._fail(f"Could not append item: {exc}")

    def _duplicate_list_item(self,path):
        try:
            node=self.sf.get(path)
            if not node: return
            self._record_edit(f"Duplicate {path}[-1]"); node.append(copy.deepcopy(node[-1])); self._refresh_view()
        except Exception as exc: self._fail(f"Could not duplicate item: {exc}")

    def _delete_path(self,path):
        if not path: return
        if QMessageBox.question(self,"Delete value",f"Delete this path?\n\n{path}",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes: return
        try:
            self._record_edit(f"Delete {path}"); self.sf.delete(path); self._refresh_view()
        except Exception as exc: self._fail(f"Could not delete {path}: {exc}")

    def _show_container_json(self,path,value):
        raw=value.value if TaggedValue is not None and isinstance(value,TaggedValue) else value
        dlg=QDialog(self); dlg.setWindowTitle(f"Edit Structure — {path}"); dlg.resize(760,560); lay=QVBoxLayout(dlg)
        warn=QLabel("Replace this object/array as JSON. Existing custom tags inside the replaced structure may be lost. Use Add/Delete for safer tag-preserving edits."); warn.setWordWrap(True); lay.addWidget(warn)
        edit=QPlainTextEdit(); edit.setPlainText(json.dumps(self._json_safe(raw),indent=2,ensure_ascii=False)); lay.addWidget(edit,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject); lay.addWidget(buttons)
        if dlg.exec()!=QDialog.Accepted:return
        try:
            parsed=json.loads(edit.toPlainText())
            if not isinstance(parsed,type(raw)): raise ValueError(f"Root type must remain {type(raw).__name__}")
            self._record_edit(f"Replace structure {path}")
            if TaggedValue is not None and isinstance(value,TaggedValue): value.value=parsed
            else: self.sf.set(path,parsed)
            self._refresh_view()
        except Exception as exc:self._fail(f"Could not replace structure: {exc}")

    def _results_context_menu(self, pos):
        item = self.results_list.itemAt(pos)
        if item is None:
            return
        data = item.data(_PATH_ROLE)
        if not data:
            return
        menu = QMenu(self)
        if isinstance(data, tuple) and data[0] == "binary":
            _, offset, type_name = data
            action = QAction("Add to Custom Layout\u2026", self)
            action.triggered.connect(
                lambda: self._add_binary_field(offset, f"field_0x{offset:X}", binary_type=type_name)
            )
        else:
            path = data
            action = QAction("Add to Custom Layout\u2026", self)
            action.triggered.connect(lambda: self._add_field_from_path(path, path.split(".")[-1]))
        menu.addAction(action)
        menu.exec(self.results_list.viewport().mapToGlobal(pos))

    def _add_field_from_path(self, path: str, default_label: str):
        dlg = _AddFieldDialog(self, path=path, default_label=default_label)
        if dlg.exec() != QDialog.Accepted:
            return
        self._append_field_to_layout(dlg.field_spec(), path)

    def _add_binary_field(self, offset: int, default_label: str, binary_type: str = "int32", size: int = None):
        dlg = _AddFieldDialog(self, default_label=default_label, offset=offset,
                              binary_type=binary_type, size=size)
        if dlg.exec() != QDialog.Accepted:
            return
        self._append_field_to_layout(dlg.field_spec(), f"offset {offset}")

    def _append_field_to_layout(self, spec: FieldSpec, source_desc: str):
        if self.current_layout is None:
            name, ok = QInputDialog.getText(self, "New Layout", "Name this layout (e.g. the game's name):")
            if not ok or not name.strip():
                return
            self.current_layout = GameLayout(name=name.strip())
            self._layouts.append(self.current_layout)

        self.current_layout.fields.append(spec)
        _layouts.save_layouts(_module.layouts_path(), self._layouts)
        self._reload_layouts_and_autoselect()
        idx = next((i for i, l in enumerate(self._layouts) if l.name == self.current_layout.name), None)
        if idx is not None:
            self.layout_combo.setCurrentIndex(idx + 1)
        self._log(f"Added '{spec.label}' ({source_desc}) to layout '{self.current_layout.name}'.")

    # ------------------------------------------------------------------
    # raw-binary "Readable Text" view + value search
    # ------------------------------------------------------------------

    def _populate_strings(self, raw: bytes):
        self._loading_strings = True
        self.strings_table.blockSignals(True)
        self.strings_table.setRowCount(0)
        self._string_hits = _binary_scan.extract_strings(bytes(raw), min_length=4)
        for hit in self._string_hits:
            r = self.strings_table.rowCount()
            self.strings_table.insertRow(r)
            offset_item = QTableWidgetItem(f"0x{hit.offset:X}")
            offset_item.setFlags(offset_item.flags() & ~Qt.ItemIsEditable)
            length_item = QTableWidgetItem(str(hit.length))
            length_item.setFlags(length_item.flags() & ~Qt.ItemIsEditable)
            enc_item = QTableWidgetItem(hit.encoding)
            enc_item.setFlags(enc_item.flags() & ~Qt.ItemIsEditable)
            text_item = QTableWidgetItem(hit.text)
            text_item.setFlags(text_item.flags() | Qt.ItemIsEditable)
            self.strings_table.setItem(r, 0, offset_item)
            self.strings_table.setItem(r, 1, length_item)
            self.strings_table.setItem(r, 2, enc_item)
            self.strings_table.setItem(r, 3, text_item)
        if not self._string_hits:
            self._log("No printable text (4+ chars) found in this file.")
        self.strings_table.blockSignals(False)
        self._loading_strings = False

    def _on_string_edited(self, item: QTableWidgetItem):
        if self._loading_strings or item.column() != 3:
            return
        row = item.row()
        hit = self._string_hits[row]
        new_text = item.text()
        try:
            self._record_edit(f"Edit text at 0x{hit.offset:X}")
            if hit.encoding == "ascii":
                encoded = new_text.encode("ascii")
                pad_byte, pad_unit = b" ", 1
            else:
                encoded = new_text.encode("utf-16-le")
                pad_byte, pad_unit = b"\x00\x00", 2
            if len(encoded) > hit.length:
                raise ValueError(
                    f"Too long \u2014 the original text used exactly {hit.length} bytes "
                    f"and this would take {len(encoded)}. Shorten it or pad with spaces yourself."
                )
            padding = pad_byte * ((hit.length - len(encoded)) // pad_unit)
            raw = self.sf.raw_bytes()
            raw[hit.offset: hit.offset + hit.length] = encoded + padding
            self._log(f"Text at offset 0x{hit.offset:X}: {hit.text!r} \u2192 {new_text!r}")
            self.status.setText(f"Updated text at offset 0x{hit.offset:X} \u2014 remember to Save.")
            self._string_hits[row] = _binary_scan.StringHit(hit.offset, hit.length, hit.encoding, new_text)
        except Exception as exc:
            self._fail(f"Could not update text: {exc}")
            self.strings_table.blockSignals(True)
            item.setText(hit.text)
            self.strings_table.blockSignals(False)

    def _strings_context_menu(self, pos):
        item = self.strings_table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        hit = self._string_hits[row]
        menu = QMenu(self)
        action = QAction("Save as Named Field in Layout\u2026", self)
        default_type = "utf16str" if hit.encoding == "utf16le" else "cstr"
        action.triggered.connect(
            lambda: self._add_binary_field(hit.offset, hit.text[:24] or "text_field",
                                           binary_type=default_type, size=hit.length)
        )
        menu.addAction(action)
        menu.exec(self.strings_table.viewport().mapToGlobal(pos))

    def _run_binary_search(self):
        if self.sf is None:
            return
        text = self.value_search_box.text().strip()
        if not text:
            return
        chosen = self.value_type_box.currentText()
        types = None if chosen == "any numeric type" else [chosen]
        try:
            value = float(text) if "." in text else int(text)
        except ValueError:
            self._fail(f"Not a number: {text!r}")
            return
        raw = bytes(self.sf.raw_bytes())
        hits = _binary_scan.search_numeric(raw, value, types=types)
        self.results_list.clear()
        if not hits:
            self.results_list.addItem("(no matches)")
            self._log(f"No offsets contain {value!r} in any numeric type tried.")
            return
        for offset, type_name in hits:
            list_item = QListWidgetItem(f"0x{offset:X}  ({type_name})")
            list_item.setData(_PATH_ROLE, ("binary", offset, type_name))
            self.results_list.addItem(list_item)
        self._log(
            f"Found {value!r} at {len(hits)} offset(s). Change the value in-game, save again, "
            "and re-search \u2014 the offset that shows up both times is your field."
        )

    def _apply_hex_changes(self):
        if self.sf is None:
            return
        try:
            new_raw = _parse_hex_dump(self.hex_edit.toPlainText())
        except ValueError as exc:
            self._fail(f"Could not parse hex: {exc}")
            return
        self._record_edit("Apply hex changes")
        self.sf.data["_raw"] = bytearray(new_raw)
        self._log(f"Applied hex edits ({len(new_raw):,} bytes).")
        self.status.setText("Hex changes applied \u2014 remember to Save.")

    def _save_file(self):
        if self.sf is None or self.current_path is None:
            return
        self._write_to(self.current_path)

    def _save_file_as(self):
        if self.sf is None:
            return
        start = str(self.current_path) if self.current_path else ""
        path, _ = QFileDialog.getSaveFileName(self, "Save save file as", start)
        if not path:
            return
        self._write_to(Path(path))

    def _write_to(self, path: Path):
        # BL4 saves get an automatic pre-save backup and a validation pass. The
        # validator only checks structures we understand and never blocks unknown data.
        if self._is_bl4_save():
            problems = _bl4_tools.validate_bl4_save(self.sf)
            if problems:
                text = "Known BL4 structures have validation warnings:\n\n" + "\n".join("• " + p for p in problems[:25])
                if len(problems) > 25:
                    text += f"\n\n…and {len(problems) - 25} more."
                text += "\n\nSave anyway?"
                answer = QMessageBox.warning(self, "BL4 Validation Warning", text, QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Save)
                if answer != QMessageBox.Save:
                    return
        if path.exists():
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = path.with_name(f"{path.stem}.before_save_{stamp}{path.suffix}")
                shutil.copy2(path, backup)
                self._log(f"Automatic pre-save backup: {backup}")
            except Exception as exc:
                answer = QMessageBox.warning(self, "Backup Failed", f"Could not create the automatic backup:\n{exc}\n\nSave anyway?", QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer != QMessageBox.Save:
                    return
        try:
            self.sf.save(str(path))
        except Exception as exc:
            self._fail(f"Could not save {path.name}: {exc}")
            return
        self.current_path = path
        self.format_label.setText(f"{path.name}  \u2014  format: {_format_chain(self.sf)}")
        self._log(f"Saved to {path}")
        self.status.setObjectName("Success")
        self.status.setText(f"Saved to {path.name}")

    # ------------------------------------------------------------------
    # find / diff
    # ------------------------------------------------------------------

    def _run_find(self):
        if self.sf is None:
            return
        key = self.search_box.text().strip()
        if not key:
            return
        self.results_list.clear()
        try:
            hits = self.sf.find(key)
        except Exception as exc:
            self._fail(f"Search failed: {exc}")
            return
        if not hits:
            self.results_list.addItem("(no matches)")
            return
        for path, value in hits:
            list_item = QListWidgetItem(f"{path} = {value!r}")
            list_item.setData(_PATH_ROLE, path)
            self.results_list.addItem(list_item)

    def _jump_to_result(self, list_item: QListWidgetItem):
        data = list_item.data(_PATH_ROLE)
        if isinstance(data, tuple) and data[0] == "binary":
            self._jump_to_binary_offset(data[1])
            return
        path = data
        target = self._path_to_item.get(path)
        if target is None:
            return
        self.tree.setCurrentItem(target)
        self.tree.scrollToItem(target)
        ancestor = target.parent()
        while ancestor is not None:
            ancestor.setExpanded(True)
            ancestor = ancestor.parent()

    def _jump_to_binary_offset(self, offset: int):
        """Switch to the hex view and highlight the line holding `offset`
        — used when activating a "Find value" search hit."""
        if self.current_layout is not None:
            self._fail("Clear the custom layout (select \"(none \u2014 show tree)\") to jump into hex.")
            return
        self._set_binary_mode("hex")
        line_no = offset // HEX_BYTES_PER_LINE
        block = self.hex_edit.document().findBlockByNumber(line_no)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.LineUnderCursor)
        self.hex_edit.setTextCursor(cursor)
        self.hex_edit.centerCursor()

    def _compare_with(self):
        if self.sf is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Compare with\u2026")
        if not path:
            return
        try:
            other = SaveFile.load(path)
            diffs = self.sf.diff(other)
        except Exception as exc:
            self._fail(f"Compare failed: {exc}")
            return
        self._log(f"--- diff vs {Path(path).name} ({len(diffs)} difference(s)) ---")
        if not diffs:
            self._log("(no differences)")
        for p, old, new in diffs:
            self._log(f"{p}: {old!r} \u2192 {new!r}")

    def _manage_profiles(self):
        path = _module.profiles_path()
        # Include bundled defaults so built-in game profiles can be edited and
        # the resulting merged set is persisted to AppData.
        profiles = _load_active_profiles()
        names = [p.name for p in profiles] + ["+ Add new\u2026"]
        choice, ok = QInputDialog.getItem(self, "Decryption Profiles", "Profile:", names, editable=False)
        if not ok:
            return
        if choice == "+ Add new\u2026":
            dlg = _ProfileDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return
            try:
                profiles.append(dlg.profile())
            except ValueError as exc:
                self._fail(f"Invalid key/IV hex: {exc}")
                return
        else:
            existing = next(p for p in profiles if p.name == choice)
            dlg = _ProfileDialog(self, existing)
            if dlg.exec() != QDialog.Accepted:
                return
            try:
                new_profile = dlg.profile()
            except ValueError as exc:
                self._fail(f"Invalid key/IV hex: {exc}")
                return
            profiles = [new_profile if p.name == choice else p for p in profiles]

        _crypto.save_profiles(path, profiles)
        _crypto.register_all(profiles)  # re-register so it applies immediately
        self._log(f"Saved decryption profile. {len(profiles)} profile(s) active — reopen a save to apply.")

    # ------------------------------------------------------------------

    def _fail(self, message: str):
        self._log(f"ERROR: {message}")
        self.status.setObjectName("Danger")
        self.status.setText(message)
        QMessageBox.warning(self, "Save Editor", message)
