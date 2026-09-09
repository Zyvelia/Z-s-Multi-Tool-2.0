"""Borderlands 4-specific save editing tools.

The generic save editor stays generic; this module provides a BL4-facing layer
that understands item serials instead of making users hunt through raw YAML.

Serial decoding/encoding follows the public BL4 serial format documented by
community reverse-engineering projects. The implementation here is deliberately
self-contained so the Save Editor does not depend on another application.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QInputDialog,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

# ---------------------------------------------------------------------------
# BL4 Base85 serial codec
# ---------------------------------------------------------------------------

B85_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{/}~"
B85_REVERSE = {c: i for i, c in enumerate(B85_CHARSET)}
B85_MIRROR = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
UINT4_MIRROR = tuple(int(f"{i:04b}"[::-1], 2) for i in range(16))
UINT5_MIRROR = tuple(int(f"{i:05b}"[::-1], 2) for i in range(32))
UINT7_MIRROR = tuple(int(f"{i:07b}"[::-1], 2) for i in range(128))


def decode_item_serial(serial: str) -> bytes:
    if not isinstance(serial, str) or not serial.startswith("@U"):
        raise ValueError("Not a BL4 item serial")
    payload = serial[2:]
    result = bytearray()
    idx = 0
    while idx < len(payload):
        value = 0
        count = 0
        j = idx
        for _ in range(5):
            if j >= len(payload) or payload[j] not in B85_REVERSE:
                break
            value = value * 85 + B85_REVERSE[payload[j]]
            count += 1
            j += 1
        idx = j
        if count == 0:
            break
        if count < 5:
            for _ in range(5 - count):
                value = value * 85 + 84
        byte_count = 4 if count == 5 else count - 1
        for shift in (24, 16, 8, 0)[:byte_count]:
            result.append((value >> shift) & 0xFF)
    return bytes(B85_MIRROR[b] for b in result)


def encode_item_serial(data: bytes) -> str:
    mirrored = bytes(B85_MIRROR[b] for b in data)
    out: list[str] = []
    full = len(mirrored) // 4
    extra = len(mirrored) % 4
    pos = 0
    pows = (85**4, 85**3, 85**2, 85)
    for _ in range(full):
        value = int.from_bytes(mirrored[pos:pos + 4], "big")
        pos += 4
        for div in pows:
            out.append(B85_CHARSET[value // div])
            value %= div
        out.append(B85_CHARSET[value])
    if extra:
        value = int.from_bytes(mirrored[pos:], "big") << (8 * (4 - extra))
        out.append(B85_CHARSET[value // (85**4)])
        value %= 85**4
        out.append(B85_CHARSET[value // (85**3)])
        if extra >= 2:
            value %= 85**3
            out.append(B85_CHARSET[value // (85**2)])
        if extra == 3:
            value %= 85**2
            out.append(B85_CHARSET[value // 85])
    return "@U" + "".join(out)


# ---------------------------------------------------------------------------
# BL4 serial bitstream parser/serializer
# ---------------------------------------------------------------------------

class _BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self) -> int:
        if self.pos >= len(self.data) * 8:
            raise EOFError
        bit = (self.data[self.pos // 8] >> (7 - self.pos % 8)) & 1
        self.pos += 1
        return bit

    def read_n(self, n: int) -> int:
        value = 0
        for _ in range(n):
            value = (value << 1) | self.read()
        return value

    @property
    def remaining(self) -> int:
        return len(self.data) * 8 - self.pos


class _BitWriter:
    def __init__(self):
        self.bits: list[int] = []

    def bit(self, value: int):
        self.bits.append(value & 1)

    def bits_(self, *values: int):
        self.bits.extend(v & 1 for v in values)

    def write_n(self, value: int, n: int):
        for i in range(n - 1, -1, -1):
            self.bit((value >> i) & 1)

    def data(self) -> bytes:
        out = bytearray((len(self.bits) + 7) // 8)
        for i, bit in enumerate(self.bits):
            if bit:
                out[i // 8] |= 1 << (7 - i % 8)
        return bytes(out)


def _read_varint(br: _BitReader) -> int:
    output = 0
    shift = 0
    for _ in range(4):
        block = br.read_n(4)
        output |= UINT4_MIRROR[block] << shift
        shift += 4
        if br.read() == 0:
            return output
    raise ValueError("BL4 VarInt exceeds 16 bits")


def _write_varint(bw: _BitWriter, value: int):
    if value < 0:
        raise ValueError("BL4 VarInt cannot be negative")
    value = min(int(value), 0xFFFF)
    n_bits = value.bit_length() if value else 1
    n_bits = min(n_bits, 16)
    while n_bits > 4:
        for _ in range(4):
            bw.bit(value & 1)
            value >>= 1
            n_bits -= 1
        bw.bit(1)
    for _ in range(4):
        if n_bits:
            bw.bit(value & 1)
            value >>= 1
            n_bits -= 1
        else:
            bw.bit(0)
    bw.bit(0)


def _read_varbit(br: _BitReader) -> int:
    length = UINT5_MIRROR[br.read_n(5)]
    value = 0
    for i in range(length):
        value |= br.read() << i
    return value


def _write_varbit(bw: _BitWriter, value: int):
    value = max(0, int(value))
    length = max(1, value.bit_length())
    length = min(length, 31)
    for i in range(5):
        bw.bit((length >> i) & 1)
    for i in range(length):
        bw.bit((value >> i) & 1)


def _read_b4string(br: _BitReader) -> str:
    length = _read_varint(br)
    data = bytearray()
    for _ in range(length):
        data.append(UINT7_MIRROR[br.read_n(7)])
    return data.decode("utf-8")


def _write_b4string(bw: _BitWriter, text: str):
    data = text.encode("utf-8")
    _write_varint(bw, len(data))
    for byte in data:
        bw.write_n(UINT7_MIRROR[byte], 7)


@dataclass
class BL4Part:
    index: int
    subtype: str = "none"
    value: int = 0
    values: list[int] | None = None

    def display(self) -> str:
        if self.subtype == "int":
            return f"{{{self.index}:{self.value}}}"
        if self.subtype == "list":
            return f"{{{self.index}:[{' '.join(map(str, self.values or []))}]}}"
        return f"{{{self.index}}}"


@dataclass
class BL4Block:
    token: str
    value: int = 0
    text: str = ""
    part: BL4Part | None = None

    def display(self) -> str:
        if self.token == "varint":
            return str(self.value)
        if self.token == "varbit":
            return f"{self.value} (VarBit)"
        if self.token == "string":
            return repr(self.text)
        if self.token == "part" and self.part:
            return self.part.display()
        return "|" if self.token == "sep2" else "||"


def _read_part(t: _BitReader) -> BL4Part:
    index = _read_varint(t)
    flag = t.read()
    if flag:
        value = _read_varint(t)
        if t.read_n(3) != 0:
            raise ValueError("Invalid BL4 part terminator")
        return BL4Part(index, "int", value)
    flag2 = t.read_n(2)
    if flag2 == 0b10:
        return BL4Part(index)
    if flag2 != 0b01:
        raise ValueError("Unknown BL4 part subtype")
    if t.read_n(2) != 0b01:
        raise ValueError("Invalid BL4 part list prefix")
    values: list[int] = []
    while True:
        first = t.read_n(2)
        if first == 0:
            return BL4Part(index, "list", values=values)
        third = t.read()
        token = (first << 1) | third
        if token == 0b100:
            values.append(_read_varint(t))
        elif token == 0b110:
            values.append(_read_varbit(t))
        else:
            raise ValueError("Invalid token inside BL4 part list")


def _write_part(bw: _BitWriter, part: BL4Part):
    _write_varint(bw, part.index)
    if part.subtype == "int":
        bw.bit(1)
        _write_varint(bw, part.value)
        bw.bits_(0, 0, 0)
    elif part.subtype == "list":
        bw.bits_(0, 0, 1)
        bw.bits_(0, 1)
        for value in part.values or []:
            v1 = _BitWriter(); _write_varint(v1, value)
            v2 = _BitWriter(); _write_varbit(v2, value)
            if len(v1.bits) <= len(v2.bits):
                bw.bits_(1, 0, 0); bw.bits.extend(v1.bits)
            else:
                bw.bits_(1, 1, 0); bw.bits.extend(v2.bits)
        bw.bits_(0, 0)
    else:
        bw.bits_(0, 1, 0)


def decode_item_blocks(serial: str) -> list[BL4Block]:
    br = _BitReader(decode_item_serial(serial))
    magic = tuple(br.read() for _ in range(7))
    if magic != (0, 0, 1, 0, 0, 0, 0):
        raise ValueError("Invalid BL4 item serial magic header")
    blocks: list[BL4Block] = []
    trailing_separators = 0
    while br.remaining >= 2:
        first = br.read_n(2)
        if first == 0:
            blocks.append(BL4Block("sep1")); trailing_separators += 1; continue
        if first == 1:
            blocks.append(BL4Block("sep2")); trailing_separators = 0; continue
        token = (first << 1) | br.read()
        trailing_separators = 0
        if token == 0b100:
            blocks.append(BL4Block("varint", value=_read_varint(br)))
        elif token == 0b110:
            blocks.append(BL4Block("varbit", value=_read_varbit(br)))
        elif token == 0b101:
            blocks.append(BL4Block("part", part=_read_part(br)))
        elif token == 0b111:
            blocks.append(BL4Block("string", text=_read_b4string(br)))
        else:
            raise ValueError(f"Invalid BL4 serial token {token:03b}")
    if trailing_separators > 1:
        del blocks[-(trailing_separators - 1):]
    return blocks


def encode_item_blocks(blocks: list[BL4Block]) -> str:
    bw = _BitWriter()
    bw.bits_(0, 0, 1, 0, 0, 0, 0)
    for block in blocks:
        if block.token == "sep1":
            bw.bits_(0, 0)
        elif block.token == "sep2":
            bw.bits_(0, 1)
        elif block.token == "varint":
            bw.bits_(1, 0, 0); _write_varint(bw, block.value)
        elif block.token == "varbit":
            bw.bits_(1, 1, 0); _write_varbit(bw, block.value)
        elif block.token == "part":
            bw.bits_(1, 0, 1); _write_part(bw, block.part or BL4Part(0))
        elif block.token == "string":
            bw.bits_(1, 1, 1); _write_b4string(bw, block.text)
        else:
            raise ValueError(f"Unknown BL4 block token: {block.token}")
    return encode_item_serial(bw.data())


# ---------------------------------------------------------------------------
# BL4 item identity / friendly names
# ---------------------------------------------------------------------------

WEAPON_FAMILIES = {
    2: ("Daedalus", "Pistol"), 3: ("Jakobs", "Pistol"), 4: ("Order", "Pistol"),
    5: ("Tediore", "Pistol"), 6: ("Torgue", "Pistol"),
    7: ("Ripper", "Shotgun"), 8: ("Daedalus", "Shotgun"), 9: ("Jakobs", "Shotgun"),
    10: ("Maliwan", "Shotgun"), 11: ("Tediore", "Shotgun"), 12: ("Torgue", "Shotgun"),
    13: ("Daedalus", "Assault Rifle"), 14: ("Tediore", "Assault Rifle"),
    15: ("Order", "Assault Rifle"), 16: ("Vladof", "Sniper"), 17: ("Torgue", "Assault Rifle"),
    18: ("Vladof", "Assault Rifle"), 19: ("Ripper", "SMG"), 20: ("Daedalus", "SMG"),
    21: ("Maliwan", "SMG"), 22: ("Vladof", "SMG"), 23: ("Ripper", "Sniper"),
    24: ("Jakobs", "Sniper"), 25: ("Maliwan", "Sniper"), 26: ("Order", "Sniper"),
    27: ("Jakobs", "Assault Rifle"),
}

EQUIPMENT_FAMILIES = {
    234: ("Universal", "Class Mod"), 237: ("Universal", "Armor Shield"), 243: ("Universal", "Repkit"),
    244: ("Universal", "Heavy Weapon Gadget"), 245: ("Universal", "Grenade Gadget"),
    246: ("Universal", "Shield"), 247: ("Universal", "Enhancement"), 248: ("Universal", "Energy Shield"),
    254: ("Siren", "Class Mod"), 255: ("Forgeknight", "Class Mod"), 256: ("Exo", "Class Mod"),
    259: ("Gravitar", "Class Mod"), 261: ("Torgue", "Repkit"), 263: ("Maliwan", "Grenade"),
    264: ("Hyperion", "Enhancement"), 265: ("Jakobs", "Repkit"), 266: ("Maliwan", "Repkit"),
    267: ("Jakobs", "Grenade"), 268: ("Jakobs", "Enhancement"), 269: ("Vladof", "Repkit"),
    270: ("Daedalus", "Grenade"), 271: ("Maliwan", "Enhancement"), 272: ("Order", "Grenade"),
    273: ("Torgue", "Heavy Gun"), 274: ("Ripper", "Repkit"), 275: ("Ripper", "Heavy Gun"),
    277: ("Daedalus", "Repkit"), 278: ("Ripper", "Grenade"), 279: ("Maliwan", "Shield"),
    281: ("Order", "Enhancement"), 282: ("Vladof", "Heavy Gun"), 283: ("Vladof", "Shield"),
    284: ("Atlas", "Enhancement"), 285: ("Order", "Repair Kit"), 286: ("CoV", "Enhancement"),
    287: ("Tediore", "Shield"), 289: ("Maliwan", "Heavy Gun"), 290: ("Tediore", "Repkit"),
    291: ("Vladof", "Grenade"), 292: ("Tediore", "Enhancement"), 293: ("Order", "Shield"),
    296: ("Ripper", "Enhancement"), 298: ("Torgue", "Grenade"), 299: ("Daedalus", "Enhancement"),
    300: ("Ripper", "Shield"), 303: ("Torgue", "Enhancement"), 306: ("Jakobs", "Shield"),
    310: ("Vladof", "Enhancement"), 311: ("Tediore", "Grenade"), 312: ("Daedalus", "Shield"),
    321: ("Torgue", "Shield"), 404: ("Rogue", "Class Mod"),
}


def family_info(category_id: int, first_token: str) -> tuple[str, str, str]:
    if first_token == "varint" and category_id in WEAPON_FAMILIES:
        manufacturer, kind = WEAPON_FAMILIES[category_id]
        return manufacturer, kind, f"{manufacturer} {kind}"
    if category_id in EQUIPMENT_FAMILIES:
        manufacturer, kind = EQUIPMENT_FAMILIES[category_id]
        if manufacturer == "Universal":
            return manufacturer, kind, kind
        return manufacturer, kind, f"{manufacturer} {kind}"
    return "Unknown", "Unknown", f"Unknown Item (Family {category_id})"


def extract_level(blocks: list[BL4Block]) -> int | None:
    if len(blocks) > 6 and blocks[6].token == "varint":
        return blocks[6].value
    return None


def extract_seed(blocks: list[BL4Block]) -> int | None:
    # Standard BL4 serials put seed at block 10; keep a fallback for unusual
    # equipment layouts where the nearby field can be VarBit.
    for index in (10, 8, 9):
        if len(blocks) > index and blocks[index].token in {"varint", "varbit"}:
            return blocks[index].value
    return None


def item_flags(state_flags: int) -> str:
    flags = int(state_flags or 0)
    labels = []
    if flags & 2: labels.append("Favorite")
    if flags & 4: labels.append("Junk")
    for bit, name in ((16, "Label 1"), (32, "Label 2"), (64, "Label 3"), (128, "Label 4")):
        if flags & bit: labels.append(name)
    if flags & 512:
        labels.append("Backpack")
    else:
        labels.append("Equipped")
    return " • ".join(labels) if labels else "Normal"


@dataclass
class BL4Item:
    slot: str
    serial: str
    state_flags: int
    blocks: list[BL4Block]
    category_id: int
    first_token: str
    manufacturer: str
    item_type: str
    display_name: str
    level: int | None
    seed: int | None

    @classmethod
    def from_inventory(cls, slot: str, item: dict[str, Any]) -> "BL4Item":
        serial = item.get("serial", "")
        blocks = decode_item_blocks(serial)
        first = blocks[0]
        category = first.value if first.token in {"varint", "varbit"} else -1
        manufacturer, item_type, display = family_info(category, first.token)
        return cls(
            slot=slot, serial=serial, state_flags=int(item.get("state_flags", 0) or 0),
            blocks=blocks, category_id=category, first_token=first.token,
            manufacturer=manufacturer, item_type=item_type, display_name=display,
            level=extract_level(blocks), seed=extract_seed(blocks),
        )

    @property
    def rarity(self) -> str:
        # Rarity is part/manifest-derived; do not guess from an opaque flag.
        return "Unresolved"

    @property
    def parts(self) -> list[BL4Part]:
        return [b.part for b in self.blocks if b.token == "part" and b.part is not None]

    def set_level(self, level: int):
        if len(self.blocks) <= 6 or self.blocks[6].token != "varint":
            raise ValueError("This serial does not have the standard BL4 level field")
        self.blocks[6].value = int(level)
        self.serial = encode_item_blocks(self.blocks)
        self.level = int(level)

    def set_seed(self, seed: int):
        target = 10 if len(self.blocks) > 10 and self.blocks[10].token in {"varint", "varbit"} else 8
        if len(self.blocks) <= target or self.blocks[target].token not in {"varint", "varbit"}:
            raise ValueError("This serial does not expose a writable seed field")
        self.blocks[target].value = int(seed)
        self.serial = encode_item_blocks(self.blocks)
        self.seed = int(seed)

    def set_part_index(self, part_number: int, new_index: int):
        parts = [b for b in self.blocks if b.token == "part" and b.part is not None]
        if not 0 <= part_number < len(parts):
            raise IndexError("Part number out of range")
        parts[part_number].part.index = int(new_index)
        self.serial = encode_item_blocks(self.blocks)

    def set_part_value(self, part_number: int, new_value: int):
        parts = [b for b in self.blocks if b.token == "part" and b.part is not None]
        if not 0 <= part_number < len(parts):
            raise IndexError("Part number out of range")
        part = parts[part_number].part
        if part.subtype == "none":
            raise ValueError("This part has no attached value")
        if part.subtype == "int":
            part.value = int(new_value)
        else:
            if not part.values:
                raise ValueError("This part has no list values")
            part.values[0] = int(new_value)
        self.serial = encode_item_blocks(self.blocks)


# ---------------------------------------------------------------------------
# Item editor dialog
# ---------------------------------------------------------------------------

class BL4ItemEditor(QDialog):
    def __init__(self, parent, item: BL4Item, apply_callback: Callable[[BL4Item, dict[str, Any]], None]):
        super().__init__(parent)
        self.item = item
        self._apply_callback = apply_callback
        self.setWindowTitle(f"Edit BL4 Item — {item.display_name}")
        self.resize(980, 700)
        root = QVBoxLayout(self)

        header = QFrame(); header.setObjectName("Panel"); hl = QHBoxLayout(header)
        title = QLabel(item.display_name); title.setObjectName("AccentTitle"); hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(QLabel(f"Slot {item.slot}"))
        root.addWidget(header)

        tabs = QTabWidget(); root.addWidget(tabs, 1)

        # Summary
        summary = QWidget(); sl = QVBoxLayout(summary)
        info = QGroupBox("Item Identity"); form = QFormLayout(info)
        for label, value in (
            ("Item", item.display_name), ("Type", item.item_type),
            ("Manufacturer", item.manufacturer), ("Family ID", str(item.category_id)),
            ("Rarity", item.rarity), ("Serial Format", "BL4 Base85 / token stream"),
        ):
            form.addRow(label + ":", QLabel(value))
        sl.addWidget(info)

        fields = QGroupBox("Editable Core Values"); ff = QFormLayout(fields)
        self.level = QSpinBox(); self.level.setRange(1, 999); self.level.setValue(item.level or 1)
        self.seed = QSpinBox(); self.seed.setRange(0, 65535); self.seed.setValue(item.seed or 0)
        ff.addRow("Item Level:", self.level)
        ff.addRow("Random Seed:", self.seed)
        sl.addWidget(fields)

        flags = QGroupBox("Inventory State"); fl = QFormLayout(flags)
        self.favorite = QCheckBox("Favorite")
        self.junk = QCheckBox("Junk")
        self.backpack = QCheckBox("Backpack item (bit 512)")
        self.backpack.setChecked(bool(item.state_flags & 512))
        self.favorite.setChecked(bool(item.state_flags & 2))
        self.junk.setChecked(bool(item.state_flags & 4))
        fl.addRow(self.favorite)
        fl.addRow(self.junk)
        fl.addRow(self.backpack)
        self.label_combo = QComboBox(); self.label_combo.addItems(["No Label", "Label 1", "Label 2", "Label 3", "Label 4"])
        for i, bit in enumerate((16, 32, 64, 128), 1):
            if item.state_flags & bit: self.label_combo.setCurrentIndex(i)
        fl.addRow("Label:", self.label_combo)
        sl.addWidget(flags)
        note = QLabel("Rarity, exact item name, element, and stat cards require the BL4 part/manifest database. This editor will not invent those values.")
        note.setWordWrap(True); note.setObjectName("Muted"); sl.addWidget(note)
        sl.addStretch(1)
        tabs.addTab(summary, "Summary")

        # Parts
        parts_tab = QWidget(); pl = QVBoxLayout(parts_tab)
        self.parts_table = QTableWidget(0, 4)
        self.parts_table.setHorizontalHeaderLabels(["#", "Part ID", "Modifier", "Values"])
        self.parts_table.setAlternatingRowColors(True)
        self.parts_table.setSelectionBehavior(QTableWidget.SelectRows)
        for idx, part in enumerate(item.parts):
            r = self.parts_table.rowCount(); self.parts_table.insertRow(r)
            vals = [str(idx), str(part.index), part.subtype.title(), ", ".join(map(str, part.values or [])) if part.subtype == "list" else (str(part.value) if part.subtype == "int" else "—")]
            for c, value in enumerate(vals):
                self.parts_table.setItem(r, c, QTableWidgetItem(value))
        pl.addWidget(self.parts_table, 1)
        part_buttons = QHBoxLayout()
        edit_part = QPushButton("Edit Selected Part…"); edit_part.clicked.connect(self._edit_selected_part)
        part_buttons.addWidget(edit_part); part_buttons.addStretch(1)
        pl.addLayout(part_buttons)
        warning = QLabel("Advanced part-ID editing can create an invalid or impossible item. Use it only when you know the part pool for this family.")
        warning.setWordWrap(True); warning.setObjectName("Muted"); pl.addWidget(warning)
        tabs.addTab(parts_tab, "Parts")

        # Serial
        serial_tab = QWidget(); xl = QVBoxLayout(serial_tab)
        serial_info = QLabel("Decoded token stream — useful for advanced inspection. Changes made here are not applied directly; use the structured editors above.")
        serial_info.setWordWrap(True); serial_info.setObjectName("Muted"); xl.addWidget(serial_info)
        self.serial_box = QPlainTextEdit(); self.serial_box.setReadOnly(True)
        self.serial_box.setPlainText(" ".join(f"{i}: {b.display()}" for i, b in enumerate(item.blocks)))
        xl.addWidget(self.serial_box, 1)
        raw_box = QPlainTextEdit(); raw_box.setReadOnly(True); raw_box.setMaximumHeight(120); raw_box.setPlainText(item.serial)
        xl.addWidget(QLabel("Current Serial:")); xl.addWidget(raw_box)
        tabs.addTab(serial_tab, "Serial Inspector")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _edit_selected_part(self):
        row = self.parts_table.currentRow()
        if row < 0:
            return
        part = self.item.parts[row]
        dialog = QDialog(self); dialog.setWindowTitle(f"Edit Part {row + 1}"); form = QFormLayout(dialog)
        index = QSpinBox(); index.setRange(0, 65535); index.setValue(part.index)
        form.addRow("Part ID:", index)
        value = QSpinBox(); value.setRange(0, 65535); value.setValue(part.value if part.subtype == "int" else ((part.values or [0])[0]))
        if part.subtype != "none": form.addRow("Value:", value)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            part.index = index.value()
            if part.subtype == "int": part.value = value.value()
            elif part.subtype == "list" and part.values: part.values[0] = value.value()
            self.parts_table.item(row, 1).setText(str(part.index))
            self.parts_table.item(row, 3).setText(str(part.value) if part.subtype == "int" else ", ".join(map(str, part.values or [])))
        except Exception as exc:
            QMessageBox.warning(self, "Part Edit Failed", str(exc))

    def _save(self):
        try:
            old_serial = self.item.serial
            old_flags = self.item.state_flags
            self.item.set_level(self.level.value())
            self.item.set_seed(self.seed.value())
            flags = 1
            if self.favorite.isChecked(): flags |= 2
            if self.junk.isChecked(): flags |= 4
            label_bits = (0, 16, 32, 64, 128)
            flags |= label_bits[self.label_combo.currentIndex()]
            if self.backpack.isChecked(): flags |= 512
            self.item.state_flags = flags
            # Part edits made in the table are serialized now.
            self.item.serial = encode_item_blocks(self.item.blocks)
            self._apply_callback(self.item, {"old_serial": old_serial, "old_flags": old_flags})
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Apply Item", str(exc))


# ---------------------------------------------------------------------------
# Dedicated BL4 workspace
# ---------------------------------------------------------------------------


def _get(sf, path, default=None):
    try:
        return sf.get(path)
    except Exception:
        return default



def validate_bl4_save(sf) -> list[str]:
    """Return human-readable validation problems for known BL4 structures.

    This intentionally validates only structures we understand. Unknown YAML fields are
    not treated as errors, and the function never mutates the save.
    """
    problems: list[str] = []
    bp = _get(sf, "state.inventory.items.backpack", {}) or {}
    if not isinstance(bp, dict):
        problems.append("Backpack container is not a mapping.")
    else:
        seen_slots = set()
        for slot, raw in bp.items():
            if slot in seen_slots:
                problems.append(f"Duplicate backpack slot: {slot}")
            seen_slots.add(slot)
            if not isinstance(raw, dict):
                problems.append(f"{slot}: inventory record is not a mapping.")
                continue
            serial = raw.get("serial", "")
            if not isinstance(serial, str) or not serial.startswith("@U"):
                problems.append(f"{slot}: missing or invalid BL4 serial.")
                continue
            try:
                blocks = decode_item_blocks(serial)
                if encode_item_blocks(blocks) != serial:
                    problems.append(f"{slot}: serial does not round-trip exactly.")
                level = extract_level(blocks)
                if level is None or not 1 <= int(level) <= 999:
                    problems.append(f"{slot}: invalid item level {level!r}.")
            except Exception as exc:
                problems.append(f"{slot}: serial decode failed ({exc}).")
            flags = raw.get("state_flags", 0)
            if not isinstance(flags, int) or flags < 0:
                problems.append(f"{slot}: invalid state flags {flags!r}.")

    lost = _get(sf, "state.lostloot", {}) or {}
    if isinstance(lost, dict):
        items = lost.get("items", [])
        if not isinstance(items, list):
            problems.append("Lost Loot items is not a list.")
        else:
            for i, raw in enumerate(items):
                serial = raw.get("serial", "") if isinstance(raw, dict) else ""
                if not isinstance(serial, str) or not serial.startswith("@U"):
                    problems.append(f"Lost Loot {i + 1}: invalid serial.")
                else:
                    try:
                        blocks = decode_item_blocks(serial)
                        if encode_item_blocks(blocks) != serial:
                            problems.append(f"Lost Loot {i + 1}: serial does not round-trip exactly.")
                    except Exception as exc:
                        problems.append(f"Lost Loot {i + 1}: serial decode failed ({exc}).")
        slots = lost.get("slots")
        if slots is not None and (not isinstance(slots, int) or slots < 0):
            problems.append(f"Lost Loot slot capacity is invalid: {slots!r}")
    elif lost:
        problems.append("Lost Loot container is not a mapping.")

    level = _get(sf, "state.experience[0].level", None)
    if level is not None and (not isinstance(level, int) or not 1 <= level <= 999):
        problems.append(f"Character level is outside the supported range: {level!r}")
    cash = _get(sf, "state.currencies.cash", None)
    eridium = _get(sf, "state.currencies.eridium", None)
    for label, value in (("Cash", cash), ("Eridium", eridium)):
        if value is not None and (not isinstance(value, int) or value < 0):
            problems.append(f"{label} is invalid: {value!r}")
    return problems


class BL4Workspace(QDialog):
    COMMON_FIELDS = [
        ("Character Name", "state.char_name"), ("Vault Hunter Class", "state.class"),
        ("Game Difficulty", "state.player_difficulty"), ("Character Level", "state.experience[0].level"),
        ("Character XP", "state.experience[0].points"), ("Specialization Level", "state.experience[1].level"),
        ("Specialization XP", "state.experience[1].points"), ("Mayhem Level", "globals.mayhem_level"),
        ("Highest Mayhem Level Unlocked", "state.highest_unlocked_mayhem_level"),
        ("True Vault Hunter Mode", "state.true_mode"), ("Total Playtime (seconds)", "state.total_playtime"),
        ("Personal Vehicle", "state.personal_vehicle"), ("Vehicle Hover Drive", "state.hover_drive"),
    ]
    CURRENCY_FIELDS = [
        ("Cash", "state.currencies.cash"), ("Eridium", "state.currencies.eridium"),
        ("Assault Rifle Ammo", "state.ammo.assaultrifle"), ("Pistol Ammo", "state.ammo.pistol"),
        ("Shotgun Ammo", "state.ammo.shotgun"), ("SMG Ammo", "state.ammo.smg"),
        ("Sniper Ammo", "state.ammo.sniper"), ("Repair Kits", "state.ammo.repairkit"),
        ("Character Progress Points", "progression.point_pools.characterprogresspoints"),
        ("Specialization Tokens", "progression.point_pools.specializationtokenpool"),
    ]

    def __init__(self, parent, sf, edit_callback: Callable[[str], None], record_callback: Callable[[str], None]):
        super().__init__(parent)
        self.sf = sf; self._edit_callback = edit_callback; self._record_callback = record_callback
        self.setWindowTitle("Borderlands 4 — Save Editor")
        self.resize(1240, 820)
        root = QVBoxLayout(self)
        header = QHBoxLayout(); title = QLabel("BORDERLANDS 4"); title.setObjectName("AccentTitle"); header.addWidget(title)
        header.addStretch(1); header.addWidget(QLabel("Player-facing editor — raw YAML stays out of the way")); root.addLayout(header)
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        self._build_character(); self._build_currency(); self._build_inventory(); self._build_lost_loot(); self._build_loadout(); self._build_progression(); self._build_missions(); self._build_challenges()
        buttons = QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def _field_button(self, label, path):
        row = QWidget(); lay = QHBoxLayout(row); lay.setContentsMargins(0, 0, 0, 0)
        text = QLabel(str(_get(self.sf, path, "<missing>"))); text.setTextInteractionFlags(Qt.TextSelectableByMouse); lay.addWidget(text, 1)
        btn = QPushButton("Edit…"); btn.clicked.connect(lambda: self._edit_path(path, text)); lay.addWidget(btn); return row

    def _edit_path(self, path, label=None):
        self._edit_callback(path)
        if label is not None: label.setText(str(_get(self.sf, path, "<missing>")))
        self.refresh()

    def _form_tab(self, title, fields):
        tab = QWidget(); outer = QVBoxLayout(tab); box = QGroupBox(title); form = QFormLayout(box)
        for label, path in fields: form.addRow(label + ":", self._field_button(label, path))
        outer.addWidget(box); outer.addStretch(1); self.tabs.addTab(tab, title)

    def _build_character(self): self._form_tab("Character", self.COMMON_FIELDS)
    def _build_currency(self): self._form_tab("Currency & Ammo", self.CURRENCY_FIELDS)

    def _inventory_items(self):
        bp = _get(self.sf, "state.inventory.items.backpack", {}) or {}
        out = []
        if isinstance(bp, dict):
            for slot, raw in bp.items():
                if not isinstance(raw, dict): continue
                serial = raw.get("serial", "")
                if not isinstance(serial, str) or not serial.startswith("@U"): continue
                try: out.append(BL4Item.from_inventory(slot, raw))
                except Exception: continue
        return out

    def _build_inventory(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        toolbar = QHBoxLayout(); self.inventory_filter = QLineEdit(); self.inventory_filter.setPlaceholderText("Search item, manufacturer, type, level, slot, or part ID…"); self.inventory_filter.textChanged.connect(self._filter_inventory)
        toolbar.addWidget(self.inventory_filter, 1)
        self.inventory_count = QLabel(); toolbar.addWidget(self.inventory_count)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal); layout.addWidget(splitter, 1)
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 8, 0)
        self.inventory_table = QTableWidget(0, 7); self.inventory_table.setHorizontalHeaderLabels(["Slot", "Item", "Type", "Level", "Rarity", "State", "Family"]); self.inventory_table.setAlternatingRowColors(True); self.inventory_table.setSelectionBehavior(QTableWidget.SelectRows); self.inventory_table.setSelectionMode(QTableWidget.ExtendedSelection); self.inventory_table.setSortingEnabled(True); self.inventory_table.itemSelectionChanged.connect(self._show_selected_item)
        ll.addWidget(self.inventory_table, 1)
        splitter.addWidget(left)

        self.item_panel = QWidget(); ip = QVBoxLayout(self.item_panel); ip.setContentsMargins(8, 0, 0, 0)
        self.item_title = QLabel("Select an item"); self.item_title.setObjectName("AccentTitle"); ip.addWidget(self.item_title)
        self.item_summary = QGroupBox("Item Details"); self.item_form = QFormLayout(self.item_summary); ip.addWidget(self.item_summary)
        actions = QHBoxLayout(); self.bulk_level_btn = QPushButton("Bulk Level…"); self.bulk_level_btn.clicked.connect(self._bulk_level); actions.addWidget(self.bulk_level_btn)
        self.bulk_favorite_btn = QPushButton("Favorite Selected"); self.bulk_favorite_btn.clicked.connect(lambda: self._bulk_flag("favorite")); actions.addWidget(self.bulk_favorite_btn)
        self.bulk_junk_btn = QPushButton("Junk Selected"); self.bulk_junk_btn.clicked.connect(lambda: self._bulk_flag("junk")); actions.addWidget(self.bulk_junk_btn)
        self.bulk_clear_junk_btn = QPushButton("Clear Junk"); self.bulk_clear_junk_btn.clicked.connect(lambda: self._bulk_flag("clear_junk")); actions.addWidget(self.bulk_clear_junk_btn)
        self.item_edit_btn = QPushButton("Edit Item…"); self.item_edit_btn.clicked.connect(self._edit_selected_item); self.item_edit_btn.setEnabled(False); actions.addWidget(self.item_edit_btn)
        self.item_copy_btn = QPushButton("Copy Serial"); self.item_copy_btn.clicked.connect(self._copy_selected_serial); self.item_copy_btn.setEnabled(False); actions.addWidget(self.item_copy_btn)
        self.item_duplicate_btn = QPushButton("Duplicate"); self.item_duplicate_btn.clicked.connect(self._duplicate_selected); self.item_duplicate_btn.setEnabled(False); actions.addWidget(self.item_duplicate_btn)
        self.item_remove_btn = QPushButton("Remove"); self.item_remove_btn.clicked.connect(self._remove_selected); self.item_remove_btn.setEnabled(False); actions.addWidget(self.item_remove_btn)
        self.add_serial_btn = QPushButton("Add Serial…"); self.add_serial_btn.clicked.connect(self._add_serial); actions.addWidget(self.add_serial_btn); actions.addStretch(1); ip.addLayout(actions)
        ip.addWidget(QLabel("Parts")); self.parts_preview = QTableWidget(0, 3); self.parts_preview.setHorizontalHeaderLabels(["#", "Part ID", "Value"]); self.parts_preview.setAlternatingRowColors(True); ip.addWidget(self.parts_preview, 1)
        splitter.addWidget(self.item_panel); splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)
        self.tabs.addTab(tab, "Inventory & Gear")
        self._populate_inventory()

    def _populate_inventory(self):
        self.inventory_table.setSortingEnabled(False); self.inventory_table.setRowCount(0)
        items = self._inventory_items(); self.inventory_count.setText(f"{len(items)} items")
        for item in items:
            r = self.inventory_table.rowCount(); self.inventory_table.insertRow(r)
            vals = [item.slot, item.display_name, item.item_type, str(item.level or "?"), item.rarity, item_flags(item.state_flags), str(item.category_id)]
            for c, value in enumerate(vals):
                cell = QTableWidgetItem(value); cell.setData(Qt.UserRole, item.slot); self.inventory_table.setItem(r, c, cell)
        self.inventory_table.setSortingEnabled(True)
        if self.inventory_table.rowCount(): self.inventory_table.selectRow(0)
        else: self._clear_item_panel()

    def _filter_inventory(self, text):
        needle = text.lower().strip()
        for r in range(self.inventory_table.rowCount()):
            hay = " ".join(self.inventory_table.item(r, c).text() for c in range(self.inventory_table.columnCount()) if self.inventory_table.item(r, c)).lower()
            self.inventory_table.setRowHidden(r, bool(needle) and needle not in hay)

    def _selected_slot(self):
        rows = self.inventory_table.selectionModel().selectedRows()
        if not rows: return None
        return self.inventory_table.item(rows[0].row(), 0).text()

    def _selected_item(self):
        slot = self._selected_slot()
        if slot is None: return None
        raw = _get(self.sf, f"state.inventory.items.backpack.{slot}", None)
        if not isinstance(raw, dict): return None
        try: return BL4Item.from_inventory(slot, raw)
        except Exception: return None

    def _clear_item_panel(self):
        self.item_title.setText("Select an item")
        while self.item_form.rowCount(): self.item_form.removeRow(0)
        self.parts_preview.setRowCount(0)
        for btn in (self.item_edit_btn, self.item_copy_btn, self.item_duplicate_btn, self.item_remove_btn): btn.setEnabled(False)

    def _show_selected_item(self):
        item = self._selected_item()
        if not item: self._clear_item_panel(); return
        self.item_title.setText(f"{item.display_name}  —  Slot {item.slot}")
        while self.item_form.rowCount(): self.item_form.removeRow(0)
        details = [("Item Type", item.item_type), ("Manufacturer", item.manufacturer), ("Family ID", str(item.category_id)), ("Level", str(item.level or "Unknown")), ("Rarity", item.rarity), ("Random Seed", str(item.seed or "Unknown")), ("State", item_flags(item.state_flags)), ("Serial Length", str(len(item.serial)))]
        for label, value in details: self.item_form.addRow(label + ":", QLabel(value))
        self.parts_preview.setRowCount(0)
        for i, part in enumerate(item.parts):
            r = self.parts_preview.rowCount(); self.parts_preview.insertRow(r)
            value = part.value if part.subtype == "int" else ", ".join(map(str, part.values or [])) if part.subtype == "list" else "—"
            for c, val in enumerate((str(i), str(part.index), str(value))): self.parts_preview.setItem(r, c, QTableWidgetItem(val))
        for btn in (self.item_edit_btn, self.item_copy_btn, self.item_duplicate_btn, self.item_remove_btn): btn.setEnabled(True)

    def _edit_selected_item(self):
        item = self._selected_item()
        if not item: return
        before = item.serial
        dialog = BL4ItemEditor(self, item, self._apply_item)
        if dialog.exec() == QDialog.Accepted and item.serial != before:
            self._show_selected_item()
            self._populate_inventory()

    def _apply_item(self, item: BL4Item, old: dict[str, Any]):
        path = f"state.inventory.items.backpack.{item.slot}"
        raw = _get(self.sf, path, None)
        if not isinstance(raw, dict): raise ValueError("Inventory slot disappeared")
        self._record_callback(f"Edit BL4 item {item.slot} — {item.display_name}")
        raw["serial"] = item.serial
        raw["state_flags"] = item.state_flags

    def _copy_selected_serial(self):
        item = self._selected_item()
        if item:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(item.serial)

    def _duplicate_selected(self):
        item = self._selected_item()
        if not item: return
        bp = _get(self.sf, "state.inventory.items.backpack", {})
        if not isinstance(bp, dict): return
        new_slot = None
        for i in range(1000):
            candidate = f"slot_{i}"
            if candidate not in bp: new_slot = candidate; break
        if new_slot is None: QMessageBox.warning(self, "Backpack Full", "Could not find a free backpack slot."); return
        self._record_callback(f"Duplicate BL4 item {item.slot} → {new_slot}")
        bp[new_slot] = {"serial": item.serial, "state_flags": int(item.state_flags) | 512}
        self._populate_inventory()
        for r in range(self.inventory_table.rowCount()):
            if self.inventory_table.item(r, 0).text() == new_slot: self.inventory_table.selectRow(r); break

    def _remove_selected(self):
        slot = self._selected_slot()
        if slot is None: return
        item = self._selected_item()
        if not item: return
        if QMessageBox.question(self, "Remove Item", f"Remove {item.display_name} from {slot}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        bp = _get(self.sf, "state.inventory.items.backpack", {})
        if isinstance(bp, dict) and slot in bp:
            self._record_callback(f"Remove BL4 item {slot} — {item.display_name}")
            del bp[slot]
            self._populate_inventory()


    def _selected_slots(self):
        rows = self.inventory_table.selectionModel().selectedRows()
        return [self.inventory_table.item(index.row(), 0).text() for index in rows if self.inventory_table.item(index.row(), 0)]

    def _bulk_level(self):
        slots = self._selected_slots()
        if not slots:
            QMessageBox.information(self, "Bulk Level", "Select one or more inventory items first.")
            return
        current = _get(self.sf, "state.experience[0].level", 60) or 60
        level, ok = QInputDialog.getInt(self, "Set Item Level", "Level:", int(current), 1, 999)
        if not ok:
            return
        self._record_callback(f"Set {len(slots)} BL4 item(s) to level {level}")
        changed = 0
        for slot in slots:
            raw = _get(self.sf, f"state.inventory.items.backpack.{slot}", None)
            if not isinstance(raw, dict):
                continue
            serial = raw.get("serial", "")
            try:
                item = BL4Item.from_inventory(slot, raw)
                old = item.serial
                item.set_level(level)
                item.serial = encode_item_blocks(item.blocks)
                if item.serial != old:
                    raw["serial"] = item.serial
                    changed += 1
            except Exception:
                continue
        if changed:
            self._populate_inventory()
            self._show_selected_item()

    def _bulk_flag(self, mode):
        slots = self._selected_slots()
        if not slots:
            QMessageBox.information(self, "Bulk Edit", "Select one or more inventory items first.")
            return
        label = {"favorite": "favorite", "junk": "junk", "clear_junk": "clear junk"}[mode]
        self._record_callback(f"Bulk {label}: {len(slots)} BL4 item(s)")
        for slot in slots:
            raw = _get(self.sf, f"state.inventory.items.backpack.{slot}", None)
            if not isinstance(raw, dict):
                continue
            flags = int(raw.get("state_flags", 0) or 0)
            if mode == "favorite":
                flags |= 2; flags &= ~4
            elif mode == "junk":
                flags |= 4; flags &= ~2
            else:
                flags &= ~4
            raw["state_flags"] = flags
        self._populate_inventory()

    def _add_serial(self):
        serial, ok = QInputDialog.getText(self, "Add BL4 Item", "Paste BL4 Base85 serial:")
        if not ok or not serial.strip():
            return
        serial = serial.strip()
        try:
            blocks = decode_item_blocks(serial)
            if encode_item_blocks(blocks) != serial:
                raise ValueError("The serial did not pass an exact round-trip check.")
            bp = _get(self.sf, "state.inventory.items.backpack", None)
            if not isinstance(bp, dict):
                raise ValueError("Backpack container is missing.")
            for i in range(1000):
                slot = f"slot_{i}"
                if slot not in bp:
                    break
            else:
                raise ValueError("No free backpack slot was found.")
            self._record_callback(f"Add BL4 serial → {slot}")
            bp[slot] = {"serial": serial, "state_flags": 1 | 512}
            self._populate_inventory()

        except Exception as exc:
            QMessageBox.warning(self, "Invalid BL4 Serial", str(exc))

    def _build_lost_loot(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        top = QHBoxLayout(); top.addWidget(QLabel("Lost Loot")); top.addStretch(1)
        self.lost_count = QLabel(); top.addWidget(self.lost_count); layout.addLayout(top)
        self.lost_table = QTableWidget(0, 5)
        self.lost_table.setHorizontalHeaderLabels(["Slot", "Item", "Type", "Level", "In Machine"])
        self.lost_table.setSelectionBehavior(QTableWidget.SelectRows); self.lost_table.setSelectionMode(QTableWidget.SingleSelection); self.lost_table.setAlternatingRowColors(True)
        layout.addWidget(self.lost_table, 1)
        buttons = QHBoxLayout()
        take = QPushButton("Send to Backpack"); take.clicked.connect(self._lost_to_backpack); buttons.addWidget(take)
        remove = QPushButton("Remove"); remove.clicked.connect(self._remove_lost); buttons.addWidget(remove)
        clear = QPushButton("Clear Lost Loot"); clear.clicked.connect(self._clear_lost); buttons.addWidget(clear); buttons.addStretch(1)
        validate = QPushButton("Validate Save"); validate.clicked.connect(self._show_validation); buttons.addWidget(validate)
        layout.addLayout(buttons); self.tabs.addTab(tab, "Lost Loot"); self._populate_lost_loot()

    def _lost_items(self):
        lost = _get(self.sf, "state.lostloot", {}) or {}
        return lost.get("items", []) if isinstance(lost, dict) and isinstance(lost.get("items", []), list) else []

    def _populate_lost_loot(self):
        self.lost_table.setRowCount(0); items = self._lost_items(); self.lost_count.setText(f"{len(items)} / {_get(self.sf, 'state.lostloot.slots', len(items))} slots")
        for i, raw in enumerate(items):
            serial = raw.get("serial", "") if isinstance(raw, dict) else ""
            try:
                item = BL4Item.from_inventory(f"lost_{i}", {"serial": serial, "state_flags": 1})
                vals = [str(i + 1), item.display_name, item.item_type, str(item.level or "?"), "Yes" if raw.get("in_machine") else "No"]
            except Exception:
                vals = [str(i + 1), "Invalid Item", "Unknown", "?", "Yes" if isinstance(raw, dict) and raw.get("in_machine") else "No"]
            r = self.lost_table.rowCount(); self.lost_table.insertRow(r)
            for c, val in enumerate(vals): self.lost_table.setItem(r, c, QTableWidgetItem(val))

    def _lost_selected_index(self):
        row = self.lost_table.currentRow()
        return row if row >= 0 else None

    def _lost_to_backpack(self):
        idx = self._lost_selected_index()
        if idx is None: return
        items = self._lost_items()
        if idx >= len(items): return
        raw = items[idx]
        serial = raw.get("serial", "") if isinstance(raw, dict) else ""
        try: decode_item_blocks(serial)
        except Exception as exc: QMessageBox.warning(self, "Invalid Lost Loot Item", str(exc)); return
        bp = _get(self.sf, "state.inventory.items.backpack", None)
        if not isinstance(bp, dict): QMessageBox.warning(self, "Backpack Missing", "The backpack container is missing."); return
        slot = next((f"slot_{i}" for i in range(1000) if f"slot_{i}" not in bp), None)
        if slot is None: QMessageBox.warning(self, "Backpack Full", "No free backpack slot was found."); return
        self._record_callback(f"Move Lost Loot {idx + 1} → {slot}")
        bp[slot] = {"serial": serial, "state_flags": 1 | 512}
        items.pop(idx); self._populate_lost_loot(); self._populate_inventory()

    def _remove_lost(self):
        idx = self._lost_selected_index()
        if idx is None: return
        items = self._lost_items()
        if idx >= len(items): return
        if QMessageBox.question(self, "Remove Lost Loot", "Remove the selected Lost Loot item?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        self._record_callback(f"Remove Lost Loot item {idx + 1}"); items.pop(idx); self._populate_lost_loot()

    def _clear_lost(self):
        items = self._lost_items()
        if not items: return
        if QMessageBox.question(self, "Clear Lost Loot", f"Remove all {len(items)} Lost Loot items?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        self._record_callback(f"Clear Lost Loot ({len(items)} items)"); items.clear(); self._populate_lost_loot()

    def _build_loadout(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        info = QGroupBox("Equipped Gear"); form = QFormLayout(info)
        equipped = _get(self.sf, "state.inventory.equipped_inventory.equipped", None)
        if isinstance(equipped, dict):
            for key, value in equipped.items(): form.addRow(str(key) + ":", QLabel(str(value)))
        else:
            form.addRow("Current Equipped Record:", QLabel("No equipped item record is present in this save."))
        form.addRow("Unlocked Equipment Slots:", QLabel(str(_get(self.sf, "state.inventory.equip_slots_unlocked", []))))
        layout.addWidget(info)
        note = QLabel("The save currently exposes an equipped-inventory container, but its internal equipped schema is not fully resolved. This panel is intentionally read-only until the structure is verified.")
        note.setWordWrap(True); note.setObjectName("Muted"); layout.addWidget(note)
        sync = QPushButton("Sync All Backpack Items to Character Level"); sync.clicked.connect(self._sync_item_levels); layout.addWidget(sync)
        layout.addStretch(1); self.tabs.addTab(tab, "Loadout")

    def _sync_item_levels(self):
        level = int(_get(self.sf, "state.experience[0].level", 1) or 1)
        items = self._inventory_items()
        if not items: return
        self._record_callback(f"Sync {len(items)} BL4 item(s) to character level {level}")
        changed = 0
        for item in items:
            if item.level == level: continue
            try:
                raw = _get(self.sf, f"state.inventory.items.backpack.{item.slot}", None)
                if not isinstance(raw, dict): continue
                item.set_level(level); item.serial = encode_item_blocks(item.blocks); raw["serial"] = item.serial; changed += 1
            except Exception: continue
        self._populate_inventory(); self._show_validation()

    def _show_validation(self):
        problems = validate_bl4_save(self.sf)
        if problems:
            text = "Validation found issues:\n\n" + "\n".join("• " + p for p in problems[:40])
            if len(problems) > 40: text += f"\n\n…and {len(problems) - 40} more."
            QMessageBox.warning(self, "BL4 Save Validation", text)
        else:
            QMessageBox.information(self, "BL4 Save Validation", "No problems were found in the known BL4 structures.\n\nUnknown game fields are not treated as errors.")

    def _build_progression(self):
        self._form_tab("Progression & Unlocks", [
            ("Highest Vault Hunter Level", "globals.highest_unlocked_vault_hunter_level"),
            ("Current Vault Hunter Level", "globals.vault_hunter_level"),
            ("Current Mayhem Level", "globals.mayhem_level"),
            ("Highest Mayhem Level Unlocked", "globals.highest_unlocked_mayhem_level"),
            ("Main Campaign Complete", "globals.mainmissioncomplete"),
            ("Prologue Complete", "globals.prologue_completed"),
            ("Repkits Unlocked", "globals.repkit_unlocked"),
            ("Glide Unlocked", "globals.movegrant_glide"),
            ("Grapple Grabber Unlocked", "globals.movegrant_grapplegrabber"),
            ("Ordonite Gloves Unlocked", "globals.movegrant_ordonitegloves"),
            ("Echolocation Unlocked", "globals.movegrant_echolocation"),
            ("Specialization Tokens", "progression.point_pools.specializationtokenpool"),
            ("Character Progress Points", "progression.point_pools.characterprogresspoints"),
        ])

    def _build_missions(self):
        tab = QWidget(); lay = QVBoxLayout(tab); self.mission_filter = QLineEdit(); self.mission_filter.setPlaceholderText("Search mission name, objective, or status…"); self.mission_filter.textChanged.connect(self._filter_missions); lay.addWidget(self.mission_filter)
        self.mission_table = QTableWidget(0, 3); self.mission_table.setHorizontalHeaderLabels(["Mission / Objective", "Field", "Value"]); self.mission_table.setAlternatingRowColors(True); self.mission_table.setSelectionBehavior(QTableWidget.SelectRows); lay.addWidget(self.mission_table, 1); self.tabs.addTab(tab, "Missions"); self._populate_missions()

    @staticmethod
    def _humanize(text: str) -> str:
        replacements = {"mainmissioncomplete": "Main Campaign Complete", "ui_flags": "UI Flags", "endstate": "Completion State", "local_sets": "Local Sets"}
        text = replacements.get(text, text)
        return text.replace("_", " ").replace("-", " ").title()

    def _mission_label(self, path: str) -> tuple[str, str]:
        bits = path.split(".")[1:]
        bits = [b for b in bits if b]
        if not bits: return "Mission", "Value"
        leaf = bits[-1]
        context = next((self._humanize(x) for x in reversed(bits[:-1]) if x not in {"local_sets", "missionset"}), "Mission")
        field = self._humanize(leaf)
        if leaf.endswith("_endstate"):
            field = self._humanize(leaf[:-8]) + " Completion State"
        return context, field

    def _populate_missions(self):
        rows = []
        def walk(node, path="missions"):
            if isinstance(node, dict):
                for k, v in node.items(): walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node): walk(v, f"{path}[{i}]")
            else: rows.append((path, node))
        walk(_get(self.sf, "missions", {}))
        self.mission_table.setRowCount(0)
        for path, value in rows:
            mission, field = self._mission_label(path); r = self.mission_table.rowCount(); self.mission_table.insertRow(r)
            self.mission_table.setItem(r, 0, QTableWidgetItem(mission)); self.mission_table.setItem(r, 1, QTableWidgetItem(field)); self.mission_table.setItem(r, 2, QTableWidgetItem(str(value)))
            self.mission_table.item(r, 0).setToolTip(path)

    def _filter_missions(self, text):
        needle = text.lower().strip()
        for r in range(self.mission_table.rowCount()):
            hay = " ".join(self.mission_table.item(r, c).text() for c in range(3)).lower(); self.mission_table.setRowHidden(r, bool(needle) and needle not in hay)

    def _build_challenges(self):
        tab = QWidget(); lay = QVBoxLayout(tab); self.challenge_filter = QLineEdit(); self.challenge_filter.setPlaceholderText("Search challenge…"); self.challenge_filter.textChanged.connect(self._filter_challenges); lay.addWidget(self.challenge_filter)
        self.challenge_table = QTableWidget(0, 2); self.challenge_table.setHorizontalHeaderLabels(["Challenge", "Value"]); self.challenge_table.setAlternatingRowColors(True); lay.addWidget(self.challenge_table, 1); self.tabs.addTab(tab, "Challenges")
        rows = []
        def walk(node, path="stats.challenge"):
            if isinstance(node, dict):
                for k, v in node.items(): walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node): walk(v, f"{path}[{i}]")
            else: rows.append((path, v if False else node))
        walk(_get(self.sf, "stats.challenge", {}))
        for path, value in rows:
            r = self.challenge_table.rowCount(); self.challenge_table.insertRow(r); self.challenge_table.setItem(r, 0, QTableWidgetItem(self._humanize(path.rsplit(".", 1)[-1]))); self.challenge_table.setItem(r, 1, QTableWidgetItem(str(value))); self.challenge_table.item(r, 0).setToolTip(path)

    def _filter_challenges(self, text):
        needle = text.lower().strip()
        for r in range(self.challenge_table.rowCount()):
            hay = " ".join(self.challenge_table.item(r, c).text() for c in range(2) if self.challenge_table.item(r, c)).lower(); self.challenge_table.setRowHidden(r, bool(needle) and needle not in hay)

    def refresh(self):
        current = self.tabs.currentIndex(); self.tabs.clear(); self._build_character(); self._build_currency(); self._build_inventory(); self._build_lost_loot(); self._build_loadout(); self._build_progression(); self._build_missions(); self._build_challenges(); self.tabs.setCurrentIndex(min(current, self.tabs.count() - 1))
