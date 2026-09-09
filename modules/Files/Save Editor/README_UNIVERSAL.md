# Universal Save Editor

This version includes a built-in Borderlands 4 decryption profile and a configurable readable-view profile.

## Important BL4 fix

BL4 decrypts to tagged YAML. The editor now recognizes BL4 from the decrypted BL4 structure **without depending on generic YAML auto-detection**. If PyYAML is unavailable in the host application, the module uses a small BL4-compatible YAML fallback parser instead of incorrectly falling back to `raw_binary`.

The fallback supports the structures used by the supplied BL4 save: nested mappings, sequences, strings, numbers, booleans, nulls, hexadecimal integers, and arbitrary YAML tags. Edited values are serialized back through the BL4 encryption pipeline.

## Universal customization

Readable sections remain data-driven in `save_editor_view_profiles.json`; decryption and readable layout are separate concepts. Add another game by creating another decryption profile and another view profile rather than changing the UI.

User overrides live in the normal Save Editor AppData directory and override bundled profiles by name/id.

## Borderlands 4 Gear Editor (v10)

The BL4 workspace now treats backpack records as actual BL4 items instead of raw serial strings. It decodes the BL4 Base85/token stream, identifies weapon/equipment family IDs, manufacturer/type, level, seed, parts, and inventory state flags. Items can be selected in a searchable inventory, opened in a structured editor, have level/seed/state flags changed, have advanced part IDs edited, duplicated, removed, and have their serial copied.

The serial codec is round-trip tested against the bundled development fixture used during development. Rarity and exact named-item/stat resolution are intentionally shown as unresolved until a verified BL4 part/manifest database is bundled; the editor does not guess those values.

## BL4 Workspace v12

The Borderlands 4 workspace now includes:

- Multi-select inventory management.
- Bulk item-level changes.
- Bulk Favorite/Junk/Clear Junk operations.
- Paste a validated BL4 Base85 serial directly into the backpack.
- Automatic Backpack flagging for duplicated/imported items.
- Lost Loot manager with send-to-backpack, remove, and clear operations.
- Read-only Loadout/equipment-slot inspection until the equipped-item schema is fully verified.
- One-click synchronization of backpack item levels to the character level.
- Known-structure BL4 save validation with exact serial round-trip checks.
- Automatic pre-save backups for existing save files.
- A bundled BL4 family/category catalog (`bl4_catalog.json`).

The catalog intentionally does not invent item rarity, elements, names, or stat values. Those require a verified game-manifest/parts dataset; unresolved values remain explicitly unresolved.

## Game-specific organization

Game-specific integrations are stored under `games/<GameName>/`. Borderlands 4 lives in `games/Borderlands4/` and contains its parser/editor and catalog. New save-editor games should follow the same structure so the generic editor root remains clean.
