# Z's Multi Tool

A modular Windows desktop app that bundles **32 utilities** — media tools, security, gaming, design, networking, AI, and system utilities — into one **CustomTkinter** interface with a searchable plugin catalog.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)

![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-4ea1ff)

![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

![Version](https://img.shields.io/badge/version-4.0.0-green)

**Repository:** [github.com/Zyvelia/Z-s-Multi-Tool-2.0](https://github.com/Zyvelia/Z-s-Multi-Tool-2.0/tree/main)

---

## What is this?

Instead of one monolithic app, every tool lives in its own folder under `modules/`, registers itself on startup, and appears as a card on the **catalog page**. Opening a card loads that module inside a single window.

**Highlights:**

* **Plugin catalog** — search, filter by category, and enable/disable tools from Settings
* **Per-module themes** — each module has a ⚙ gear menu with its own color theme and optional module settings
* **Catalog themes** — global app appearance presets
* **Mini widgets** — some modules, such as Media Player and Remote Hub, show compact controls on their catalog cards
* **Shared services** — Discord RPC, Tailscale remote access, authentication/crypto, and settings live in `core/services/`
* **Remote Hub** — one Tailscale URL for your phone, with QR code, unified Quick Send inbox, and links to live modules
* **Self-updater** — optional GitHub Releases update check from Settings

---

## Modules (32)

### 🎵 Media

|     | Module                     | What it does                                                                                                                                                                                                                                                                                                                                                 |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 🎵  | **Media Player**           | VLC-powered **music + video** library. SQLite-indexed collection with fast incremental scanning, automatic indexing, shuffle/playlists, drag-and-drop, cue-sheet support, Discord "now playing," and a built-in **Video Player** tab. Supports 80+ audio/video formats. Optional **Tailscale remote access** lets your phone browse and stream your library. |
| 🏷️ | **Media Metadata Editor**  | Edit **audio tags** such as title, artist, and album, **image EXIF** fields, and **file timestamps**. Includes batch-friendly tabs for audio, images, and timestamps.                                                                                                                                                                                        |
| 🔊  | **Soundboard**             | Play sound clips through your speakers or virtual audio cable / microphone path — useful for Discord, streaming, or quick SFX.                                                                                                                                                                                                                               |
| ▶   | **YouTube Downloader**     | Download YouTube videos and playlists as **MP3 or MP4** via yt-dlp. Configurable output paths, cookie browser support, and optional **phone remote control** over Tailscale.                                                                                                                                                                                 |
| 🎞  | **Video to GIF Converter** | Convert video files into optimized **GIFs** with a simple UI — no command line required.                                                                                                                                                                                                                                                                     |

### 🔐 Security

|    | Module              | What it does                                                                                                                                                                                                                                                                                                |
| -- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🔍 | **Hash Tools**      | Generate and verify **MD5, SHA-1, SHA-256, SHA-512**, and other hashes for files and text. Compare hashes to check integrity.                                                                                                                                                                               |
| 🔒 | **File Encryption** | **Encrypt and decrypt** individual files with a password. Includes a lock screen while the vault key is in memory.                                                                                                                                                                                          |
| 🔐 | **Secure Vault**    | All-in-one **password manager** and **TOTP authenticator (2FA)**. Encrypted at rest and unlocked with a master password. Includes **security audit** for weak/reused/breached passwords, notes + URLs, emergency kit export, optional **FIDO2 security key** unlock, and **Tailscale remote vault access**. |
| 🛡 | **Security Center** | **Have I Been Pwned** password + email checks, plus **vault audit** for weak, reused, and breached saved passwords.                                                                                                                                                                                         |

### 🎮 Gaming

|    | Module                  | What it does                                                                                                                                                                                                                                                                                |
| -- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🎮 | **Gaming Hub**          | **Scan, launch, and manage** installed games across drives. Save backup hints, per-game notes, drive selection, and optional **Tailscale remote access** to browse your library from a phone.                                                                                               |
| 🎮 | **Game Server Manager** | Universal **dedicated game server** manager for **Minecraft Java & Bedrock**, Satisfactory, Terraria, Valheim, Palworld, Project Zomboid, **SteamCMD** installations, and custom servers. Start/stop servers, access consoles, RCON, configs, backups, and server file editing from one UI. |

### 📁 Files

|    | Module               | What it does                                                                                                                                               |
| -- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 📁 | **File Manager**     | **Universal file viewer/editor** — open text, hex, images, audio previews, archives, metadata side panels, and basic editing. Includes a multi-tab layout. |
| 🗂 | **Folder Generator** | Create **predefined folder structures** for games and projects from JSON templates, including ROM hacks and asset pipelines.                               |
| 🗑 | **File Shredder**    | **Securely overwrite and delete** files and folders so deleted data is much harder to recover.                                                             |

### 🌐 Network

|    | Module                  | What it does                                                                                                                                                  |
| -- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🌐 | **Network Auditor**     | **Discover devices** on your LAN, **scan ports**, and review basic security findings. Uses Scapy + Nmap and requires Npcap/Nmap on the machine.               |
| 🔀 | **Port Forward Helper** | Detect your router through **UPnP** and add/remove **port forwards** without logging into the router administration page.                                     |
| 📤 | **Quick Send**          | **Send files between your phone and PC** on your tailnet using inbox/outbox folders and a received-files log.                                                 |
| 📡 | **Remote Hub**          | One **phone-friendly landing page** over Tailscale. Scan a QR code, view recent Quick Send files, and jump to whichever supported modules are currently live. |

### 🖥️ System

|     | Module                    | What it does                                                                                                                                                                           |
| --- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🖥️ | **System Monitor**        | Live **CPU, RAM, disk, network, and GPU** statistics with a process list and optional **mini desktop widget**.                                                                         |
| 🩺  | **Environment Checker**   | One-screen **dependency health check** for VLC, Tailscale, WebView2, Nmap/Npcap, disk space, and other requirements. Helps identify missing dependencies before modules fail silently. |
| 🚀  | **Startup Manager**       | See and **enable/disable** programs and tasks that run when Windows starts, including registry Run keys, startup folders, and scheduled tasks.                                         |
| 🧬  | **Duplicate File Finder** | Scan folders for **byte-identical files** and reclaim wasted disk space.                                                                                                               |
| 🔧  | **Driver/Update Checker** | Review **installed drivers** and check for driver/software updates using Windows Update Agent integration where available.                                                             |

### 🎨 Design

|     | Module                      | What it does                                                                                                       |
| --- | --------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 🎨  | **Color Picker**            | Pick colors by **hex, RGB, or HSV**, use an **eyedropper**, and generate **harmony palettes** from a base color.   |
| 🧩  | **Icon/Favicon Generator**  | Turn one image into a complete **favicon.ico + PNG icon set + site.webmanifest** for websites.                     |
| 🖼️ | **Image Palette Extractor** | Extract **dominant colors** from images as copyable hex/RGB swatches.                                              |
| 🔳  | **QR Generator**            | Create **QR codes** from text, URLs, Wi-Fi credentials, or contact information and save/share the resulting image. |

### 🤖 AI

|    | Module      | What it does                                                                                                                                                                        |
| -- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🤖 | **AI Chat** | Chat with a **hosted AI model** or a **local model** using Ollama / llama.cpp. Includes slash commands, **`/build`** multi-file project generation, and a saved **prompt library**. |

### 📋 Productivity

|    | Module                | What it does                                                                                                                                              |
| -- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 📋 | **Clipboard Manager** | **Clipboard history** while the app is open — search, pin, and re-copy previous items. Configurable maximum size and polling interval through ⚙ settings. |
| 📝 | **Notes**             | Simple **free-form notes** with attached links — a lightweight scratch pad inside the app.                                                                |

### 🧰 Utilities

|     | Module                | What it does                                                                                                                                 |
| --- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 📦  | **App Installer**     | Search for and install applications through **winget**, or run custom installation commands.                                                 |
| 🕹️ | **Game Stats & News** | **Live game stats** through your own API keys, including Fortnite, Steam, or custom APIs, plus **custom RSS/news feeds** and saved articles. |

---

## Architecture

```text
main.py                       # Entry: SettingsManager + App mainloop

core/
  app.py                      # Main window, wires catalog / settings / modules
  page_manager.py             # Page routing (catalog, settings, active module)
  plugin_manager.py            # Loads modules/, holds registered tool metadata
  module_shell.py              # Wraps each module: ⚙ settings, per-module themes
  module_themes.py             # Module theme presets + persistence
  theme.py                     # Shared design tokens (colors, spacing, buttons)
  settings.py                  # Persistent app settings (JSON)
  updater.py                   # GitHub Releases self-updater (APP_VERSION)
  services/                    # Auth, crypto, Discord, Tailscale, vault web, etc.

pages/
  catalog_page.py              # Home grid of tool cards + search/filter
  catalog_theme.py             # Global catalog appearance themes
  settings_page.py             # App settings, tool toggles, about, updates

modules/<Category>/<Tool>/
  __init__.py                  # register(plugin_manager)
  ui.py                        # Module UI (ctk.CTkFrame)
  ...                          # Module-specific logic
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

* `"widget": build_mini_widget` — small embed on the catalog card
* `MODULE_SETTINGS_TITLE` + `build_module_settings()` on the page class — extra ⚙ panel sections

---

## Requirements

* **Python 3.11+** (3.14 supported on current builds)
* **Windows** (most modules assume Win32 APIs, winget, UPnP, etc.)

### Python packages

Install everything with:

```bash
pip install -r requirements.txt
```

Key dependencies:

| Package                    | Used for                                                                  |
| -------------------------- | ------------------------------------------------------------------------- |
| `customtkinter`            | UI framework                                                              |
| `pillow`                   | Images, icons, thumbnails                                                 |
| `python-vlc`               | Media Player / video playback                                             |
| `mutagen`                  | Audio metadata / library tags                                             |
| `yt-dlp`                   | YouTube Downloader                                                        |
| `cryptography`             | Encryption, Secure Vault                                                  |
| `psutil`                   | System Monitor                                                            |
| `scapy`, `python-nmap`     | Network Auditor                                                           |
| `watchdog`                 | Media Player auto-index                                                   |
| `tkinterdnd2`              | Drag-and-drop in Media Player                                             |
| `sounddevice`, `soundfile` | Soundboard                                                                |
| `pypresence`               | Discord Rich Presence                                                     |
| `pyperclip`                | Clipboard Manager                                                         |
| `qrcode`                   | QR Generator                                                              |
| `openai`                   | AI Chat hosted models                                                     |
| `fido2`                    | Optional FIDO2 USB security key unlock                                    |
| `pywin32`                  | Windows-only features such as timestamps, startup management, and updates |

See `requirements.txt` for the full dependency list and version floors.

### External dependencies

| Tool                   | Needed for                                                                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **VLC**                | Media Player — `python-vlc` wraps `libvlc.dll`. Install VLC or ship `libvlc.dll` + `plugins/` next to the app.                       |
| **ffmpeg**             | Optional fallback transcoding for exotic audio formats when VLC cannot decode them natively.                                         |
| **Npcap + Nmap**       | Network Auditor — packet capture and port scanning.                                                                                  |
| **Ollama / llama.cpp** | AI Chat — optional local model backends.                                                                                             |
| **Tailscale**          | Remote access features in Media Player, Secure Vault, YouTube Downloader, Gaming Hub, Soundboard, Notes, Quick Send, and Remote Hub. |
| **winget**             | App Installer — Windows Package Manager CLI.                                                                                         |
| **mGBA** (optional)    | Folder Generator — some GBA templates expect `modules/Files/Folder Generator/assets/mGBA.exe`. Not included in the repo.             |

> **Note:** `pygame` is **no longer required**. Media Player uses VLC, and File Manager's optional audio preview degrades gracefully without pygame.

---

## Running from source

```bash
py.bat
```

or:

```bash
python main.py
```

Use **Escape** to return to the catalog from most pages. Each module's ⚙ gear opens its settings/theme panel.

---

## Building a standalone `.exe`

From the project root:

```bat
build.bat
```

This uses PyInstaller to produce:

```text
dist/Z's Multi Tool.exe
```

The build process also refreshes `requirements-lock.txt`.

See `build.bat` for bundled paths and build-specific caveats.

The following dependencies still need to exist on the target machine or be installed separately:

* **VLC**
* **Npcap/Nmap**
* Other required Windows components

### Console build

For a build that shows stdout/stderr:

```bat
build_console.bat
```

### Windows installer

After `build.bat`, compile `install.iss` with **Inno Setup 6+**.

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" install.iss
```

Optional installer tasks can download/install:

* **Npcap**
* **Nmap**

---

## Data & privacy

Local application data lives under `%APPDATA%` and the project's `data/` folder for vaults, settings, and caches.

**Treat the following as sensitive and do not commit them:**

* `data/` — vault files, keys, and local caches
* `settings.json` — personal preferences
* Master keys
* API keys entered in modules such as Security Center, Game Stats & News, and AI Chat

The **Secure Vault** and **File Encryption** modules use local encryption. Back up your master password and vault data separately.

---

## Remote access — Tailscale

Several modules can expose a **localhost-only** web UI intended to be reached through Tailscale.

Remote-enabled modules include:

| Module                 | Remote feature                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| **Remote Hub**         | Single landing page with QR code, unified Quick Send inbox, and links to supported modules |
| **Media Player**       | Browse and stream your library from a phone                                                |
| **Secure Vault**       | Read passwords and TOTP entries remotely                                                   |
| **YouTube Downloader** | Queue downloads remotely                                                                   |
| **Gaming Hub**         | Browse your game library                                                                   |
| **Soundboard**         | Trigger sounds remotely                                                                    |
| **Notes**              | Read and edit notes remotely                                                               |
| **Quick Send**         | Send files to and from your PC                                                             |

Configure each module's ⚙ **Remote access** section, or use **Remote Hub → Go Live** when supported.

An optional access code can be configured before exposing services beyond your trusted tailnet.

---

## Contributing / adding a module

1. Create `modules/<Category>/<Your Tool>/`
2. Add `__init__.py` with `register(plugin_manager)`
3. Add `ui.py` with a `ctk.CTkFrame` page class `(parent, manager)`
4. Use `from core import theme` for colors
5. Read `theme.*` at **widget build time**, not import time, so per-module themes work after ⚙ theme changes
6. Restart the app — the catalog automatically discovers new module folders

---

## License & author

Personal utility collection by **Zyvelia**.

Some third-party assets and dependencies used by the application may have their own licenses. Please refer to the respective project's license terms where applicable.