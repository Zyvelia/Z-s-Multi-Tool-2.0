# Z's Multi Tool

A modular Windows desktop app that bundles **31 utilities** — media tools, security, gaming, design, networking, AI, and system utilities — into one **CustomTkinter** interface with a searchable plugin catalog.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-4ea1ff)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Version](https://img.shields.io/badge/version-4.0.0-green)

**Repository:** [github.com/Zyvelia/Z-s-Multi-Tool-2.0](https://github.com/Zyvelia/Z-s-Multi-Tool-2.0/tree/main)

---

## What is this?

Instead of one monolithic app, every tool lives in its own folder under `modules/`, registers itself on startup, and appears as a card on the **catalog page**. Opening a card loads that module inside a single window.

**Highlights:**

- **Plugin catalog** — search, filter by category, enable/disable tools from Settings
- **Per-module themes** — each module has a ⚙ gear menu with its own color theme and optional module settings (remote access, clipboard options, etc.)
- **Catalog themes** — global app appearance presets (including Neon Pulse and others)
- **Mini widgets** — some modules (Media Player, Remote Hub) show a compact control on their catalog card
- **Shared services** — Discord RPC, Tailscale remote access, auth/crypto, and settings live in `core/services/`
- **Self-updater** — optional GitHub Releases check from Settings (v4.0.0+)

---

## Modules (31)

### 🎵 Media

| | Module | What it does |
|---|---|---|
| 🎵 | **Media Player** | VLC-powered **music + video** library. SQLite-indexed collection with fast incremental scanning, auto-index (filesystem watch + background sync), shuffle/playlists, drag-and-drop, cue-sheet support, Discord “now playing,” and a built-in **Video Player** tab. Supports 80+ audio/video formats. Optional **Tailscale remote access** so your phone can browse and stream your library. |
| 🏷️ | **Media Metadata Editor** | Edit **audio tags** (title, artist, album, etc.), **image EXIF** fields, and **file timestamps** (created/modified). Batch-friendly tabs for audio, images, and timestamps. |
| 🔊 | **Soundboard** | Play sound clips through your speakers or virtual audio cable / mic path — useful for Discord, streaming, or quick SFX. |
| ▶ | **YouTube Downloader** | Download YouTube videos and playlists as **MP3 or MP4** via yt-dlp. Configurable output paths, cookie browser support, and optional **phone remote control** over Tailscale. |
| 🎞 | **Video to GIF Converter** | Convert video files into optimized **GIFs** with a simple UI — no command line needed. |

### 🔐 Security

| | Module | What it does |
|---|---|---|
| 🔍 | **Hash Tools** | Generate and verify **MD5, SHA-1, SHA-256, SHA-512** (and more) for files and text. Compare hashes to check integrity. |
| 🔒 | **File Encryption** | **Encrypt and decrypt** individual files with a password. Lock screen while the vault key is in memory. |
| 🔐 | **Secure Vault** | All-in-one **password manager** and **TOTP authenticator (2FA)**. Encrypted at rest, unlock with master password. Optional **Tailscale remote vault access** from your phone. |
| 🕵️ | **Breach Checker** | Check **email addresses and passwords** against known data breaches using the Have I Been Pwned API (k-anonymity — your full password is never sent). |

### 🎮 Gaming

| | Module | What it does |
|---|---|---|
| 🎮 | **Gaming Hub** | **Scan, launch, and manage** installed games across drives. Save backup hints, per-game notes, drive selection, and optional **Tailscale remote access** to browse your library from a phone. |
| 🎮 | **Game Server Manager** | Universal **dedicated game server** manager — **Minecraft Java & Bedrock**, Satisfactory, Terraria, Valheim, Palworld, Project Zomboid, **SteamCMD** installs, and custom servers. Start/stop, console, RCON, configs, backups, and server file editing in one UI. |

### 📁 Files

| | Module | What it does |
|---|---|---|
| 📁 | **File Manager** | **Universal file viewer/editor** — open text, hex, images, audio previews, archives, metadata side panel, and basic editing. Multi-tab layout. |
| 🗂 | **Folder Generator** | Create **predefined folder structures** for games/projects from JSON templates (ROM hacks, asset pipelines, etc.). |
| 🗑 | **File Shredder** | **Securely overwrite and delete** files and folders so deleted data is much harder to recover. |

### 🌐 Network

| | Module | What it does |
|---|---|---|
| 🌐 | **Network Auditor** | **Discover devices** on your LAN, **scan ports**, and review basic security findings. Uses scapy + nmap (requires Npcap/Nmap on the machine). |
| 🔀 | **Port Forward Helper** | Detect your router via **UPnP** and add/remove **port forwards** without logging into the router admin page. |
| 📤 | **Quick Send** | **Send files between your phone and PC** on the local network — quick drag-and-drop style transfers. |
| 📡 | **Remote Hub** | One **phone-friendly landing page** (over Tailscale) with links into **Media Player**, **Secure Vault**, and **YouTube Downloader** remote UIs. |

### 🖥️ System

| | Module | What it does |
|---|---|---|
| 🖥️ | **System Monitor** | Live **CPU, RAM, disk, network, and GPU** stats with process list and an optional **mini desktop widget**. |
| 🚀 | **Startup Manager** | See and **enable/disable** everything that runs when Windows starts — registry Run keys, startup folders, scheduled tasks, and more. |
| 🧬 | **Duplicate File Finder** | Scan folders for **byte-identical files** and reclaim wasted disk space. |
| 🔧 | **Driver/Update Checker** | Review **installed drivers** and check for driver/software updates (Windows Update Agent integration where available). |

### 🎨 Design

| | Module | What it does |
|---|---|---|
| 🎨 | **Color Picker** | Pick colors by **hex, RGB, or HSV**, use an **eyedropper**, and generate **harmony palettes** from a base color. |
| 🧩 | **Icon/Favicon Generator** | Turn one image into a full **favicon.ico + PNG icon set + site.webmanifest** for websites. |
| 🖼️ | **Image Palette Extractor** | Pull **dominant colors** from any image as copyable hex/RGB swatches. |
| 🔳 | **QR Generator** | Create **QR codes** from text, URLs, Wi-Fi credentials, or contact info — save or share the image. |

### 🤖 AI

| | Module | What it does |
|---|---|---|
| 🤖 | **AI Chat** | Chat with a **hosted AI model** or a **local model** (Ollama / llama.cpp). Slash commands, **`/build`** multi-file project generation, and a saved **prompt library** — all in one tabbed module. |

### 📋 Productivity

| | Module | What it does |
|---|---|---|
| 📋 | **Clipboard Manager** | **Clipboard history** while the app is open — search, pin, and re-copy past items. Configurable max size and poll interval via ⚙ settings. |
| 📝 | **Notes** | Simple **free-form notes** with attached links — lightweight scratch pad inside the app. |

### 🧰 Utilities

| | Module | What it does |
|---|---|---|
| 📦 | **App Installer** | Search and install apps via **winget**, or run your own custom install commands. |
| 🕹️ | **Game Stats & News** | **Live game stats** via your own API keys (Fortnite, Steam, or any custom API), plus **custom RSS/news feeds** and saved articles. |

---

## Architecture

```
main.py                     # Entry: SettingsManager + App mainloop
core/
  app.py                    # Main window, wires catalog / settings / modules
  page_manager.py           # Page routing (catalog, settings, active module)
  plugin_manager.py         # Loads modules/, holds registered tool metadata
  module_shell.py           # Wraps each module: ⚙ settings, per-module themes
  module_themes.py          # Module theme presets + persistence
  theme.py                  # Shared design tokens (colors, spacing, buttons)
  settings.py               # Persistent app settings (JSON)
  updater.py                # GitHub Releases self-updater (APP_VERSION)
  services/                 # Auth, crypto, Discord, Tailscale, vault web, etc.
pages/
  catalog_page.py           # Home grid of tool cards + search/filter
  catalog_theme.py          # Global catalog appearance themes
  settings_page.py          # App settings, tool toggles, about, updates
modules/<Category>/<Tool>/
  __init__.py               # register(plugin_manager) — name, category, desc, page_class
  ui.py                     # Module UI (ctk.CTkFrame)
  ...                       # Module-specific logic
```

### Plugin contract

Every tool under `modules/` exposes `register(plugin_manager)` and calls:

```python
plugin_manager.register({
    "name": "Your Tool",
    "category": "Media",           # shown in catalog filters
    "desc": "One-line card summary",
    "icon": "🎵",
    "page_class": YourPageClass,   # preferred — auto-wrapped with ModuleShell
})
```

`page_class(parent, manager)` builds a `ctk.CTkFrame`. The shell adds the ⚙ gear bar, theme picker, and optional `build_module_settings()`.

Optional extras on registration:

- `"widget": build_mini_widget` — small embed on the catalog card
- `MODULE_SETTINGS_TITLE` + `build_module_settings()` on the page class — extra ⚙ panel sections

---

## Requirements

- **Python 3.11+** (3.13 supported)
- **Windows** (most modules assume Win32 APIs, winget, UPnP, etc.)

### Python packages

Install everything with:

```bash
pip install -r requirements.txt
```

Key dependencies:

| Package | Used for |
|---|---|
| `customtkinter` | UI framework |
| `pillow` | Images, icons, thumbnails |
| `python-vlc` | Media Player / video playback |
| `mutagen` | Audio metadata / library tags |
| `yt-dlp` | YouTube Downloader |
| `cryptography` | Encryption, Secure Vault |
| `psutil` | System Monitor |
| `scapy`, `python-nmap` | Network Auditor |
| `watchdog` | Media Player auto-index (live folder watch) |
| `tkinterdnd2` | Drag-and-drop in Media Player |
| `sounddevice`, `soundfile` | Soundboard |
| `pypresence` | Discord Rich Presence (Media Player) |
| `pyperclip` | Clipboard Manager |
| `qrcode` | QR Generator |
| `openai` | AI Chat (hosted models) |
| `pywin32` | Windows-only features (timestamps, startup, updates) |

See `requirements.txt` for the full list and version floors.

### External (non-pip) dependencies

| Tool | Needed for |
|---|---|
| **VLC** | Media Player — `python-vlc` wraps `libvlc.dll`. Install [VLC](https://www.videolan.org/) or ship `libvlc.dll` + `plugins/` next to the app. |
| **ffmpeg** | Optional fallback transcode for exotic audio (tracker/MIDI) when VLC can't decode natively. |
| **Npcap + Nmap** | Network Auditor — packet capture and port scanning. |
| **Ollama / llama.cpp** | AI Chat — optional local model backends (not bundled). |
| **Tailscale** | Remote access features in Media Player, Secure Vault, YouTube Downloader, Gaming Hub, Remote Hub. |
| **winget** | App Installer — Windows Package Manager CLI. |
| **mGBA** (optional) | Folder Generator — some GBA templates expect `modules/Files/Folder Generator/assets/mGBA.exe` ([download](https://mgba.io/downloads.html)). Not included in the repo. |

> **Note:** `pygame` is **no longer required**. Media Player uses VLC. File Manager's optional audio preview degrades gracefully without pygame.

---

## Running from source

```bash
py.bat
```

or:

```bash
python main.py
```

Use **Escape** to go back to the catalog from most pages. Each module's ⚙ gear opens its settings/theme panel.

---

## Building a standalone .exe

From the project root:

```bat
build.bat
```

This uses PyInstaller to produce `dist/Z's Multi Tool.exe` (windowed, single-file). See `build.bat` for bundled paths and VLC/Npcap caveats — system drivers and VLC still need to exist on the target machine.

Console build (shows stdout/stderr):

```bat
build_console.bat
```

---

## Data & privacy

Local app data lives under `%APPDATA%` (e.g. `MusicPlayerApp/library.db` for the media index) and the project `data/` folder for vaults, settings, and caches.

**Treat as sensitive / do not commit:**

- `data/` — vault files, keys, local caches
- `settings.json` — personal preferences
- Master keys, API keys entered in modules (Breach Checker, Game Stats & News, AI Chat)

The **Secure Vault** and **File Encryption** modules use local encryption — back up your master password and vault data separately.

---

## Remote access (Tailscale)

Several modules can expose a **localhost-only** web UI meant to be reached through **[Tailscale Serve](https://tailscale.com/kb/1242/serve)** (HTTPS on your tailnet, not the public internet):

- **Media Player** — browse/stream library from phone
- **Secure Vault** — read passwords/TOTP remotely
- **YouTube Downloader** — queue downloads remotely
- **Gaming Hub** — browse game library
- **Remote Hub** — single page linking to the above

Configure each module's ⚙ **Remote access** section and an optional API key before exposing anything beyond your tailnet.

---

## Contributing / adding a module

1. Create `modules/<Category>/<Your Tool>/`
2. Add `__init__.py` with `register(plugin_manager)`
3. Add `ui.py` with a `ctk.CTkFrame` page class `(parent, manager)`
4. Use `from core import theme` for colors — read `theme.*` at **widget build time**, not import time, so per-module themes work after ⚙ theme changes
5. Restart the app — the catalog picks up new folders automatically

---

## License & author

Personal utility collection by **Zyvelia**. Module-specific assets (emulators, icons) may have their own licenses — check each folder's README where present.
