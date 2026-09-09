# Z's Multi Tool

A modular Windows desktop app that bundles **42 utilities** — media tools, security, gaming, design, networking, AI, and system utilities — into one **Qt (PySide6)** interface with a searchable plugin catalog. CustomTkinter is gone; `python main.py` is Qt only.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)

![Qt](https://img.shields.io/badge/UI-PySide6-41cd52)

![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

![Version](https://img.shields.io/badge/version-4.0.5-green)

**Repository:** [github.com/Zyvelia/Z-s-Multi-Tool-2.0](https://github.com/Zyvelia/Z-s-Multi-Tool-2.0/tree/main)

**Phone app:** [Zs Multi Tool Remote](https://github.com/Zyvelia) (Flutter) talks to the same Tailscale HTTPS ports listed below.

---

## What is this?

Instead of one monolithic app, every tool lives in its own folder under `modules/`, registers itself on startup, and appears as a card on the **catalog page**. Opening a card loads that module inside a single window.

**Highlights:**

* **Plugin catalog** — home page. Search, filter by category, enable/disable tools from Settings. Escape / Settings Back return here
* **Marketplace** — header **Market** button. Browse, search, install, uninstall, update, update-all, and roll back modules. New tools show up from the catalog without a new Multi Tool release
* **Automatic module builds** — publishing a tool assigns the next build number for you (`Build 3 · 2026-09-06`). You never pick 1.2.0
* **Per-module themes** — each module has a ⚙ gear with the same catalog color presets plus that tool's own options (remote access, etc.)
* **Module UIs live with the tool** — `modules/<Category>/<Tool>/ui.py`, lazy-loaded from a `qt_page` string so plugin `__init__.py` never imports Qt
* **Remote Hub** — one Tailscale URL for the phone app, with QR code, unified Quick Send inbox, and links to live modules
* **Shared services** — Discord RPC, Tailscale, auth/crypto, and settings live in `core/services/`
* **Self-updater** — optional GitHub Releases update check from Settings (`APP_VERSION` **4.0.5`). That updates the core app only; tools update from the Marketplace

---

## Modules (42)

### 🎵 Media

|     | Module                     | What it does |
| --- | -------------------------- | ------------ |
| 🎵  | **Media Player**           | VLC **music library** with a browser table (search, artists, disk folders, virtual Title/Artist/Album/Time). Sticky transport bar; **Video** is a pop-out window (second VLC engine only when you open it). SQLite incremental index + background folder watch. Shuffle / repeat / queue follow. Cue sheets. Phone stream stays off until ⚙ remote settings. HTTPS **8444**. |
| 🏷️ | **Media Metadata Editor**  | Edit **audio tags** (title, artist, album) including **batch audio**, plus **image EXIF** and **file timestamps**. |
| 🔊  | **Soundboard**             | Play clips through speakers or a virtual cable / mic path. **Per-clip volume**. Optional phone trigger on HTTPS **8447**. |
| ▶   | **YouTube Downloader**     | Download YouTube videos and playlists as **MP3 or MP4** via yt-dlp. Cookie browser support. Phone queue on HTTPS **8445**. |
| 🎞  | **Video to GIF Converter** | Convert video to optimized **GIFs**. Size-fit options and **drag-and-drop**. |
| 📖 | **MangaDex Reader**        | Browse **MangaDex**, download chapters, OCR / translate / TTS assist. Needs Tesseract for Japanese OCR. |

### 🔐 Security

|    | Module              | What it does |
| -- | ------------------- | ------------ |
| 🔍 | **Hash Tools**      | Generate and verify **MD5, SHA-1, SHA-256, SHA-512**, and other hashes for files and text. Compare hashes to check integrity. |
| 🔒 | **File Encryption** | **Encrypt and decrypt** files with a password. Lock screen; optional **hardware security key** unlock when a key is enrolled. |
| 🔐 | **Secure Vault**    | All-in-one **password manager** and **TOTP authenticator (2FA)**. Encrypted at rest and unlocked with a master password. Includes **security audit** for weak/reused/breached passwords, notes + URLs, emergency kit export, optional **FIDO2 security key** unlock, and **Tailscale remote vault access** (HTTPS **8443**). |
| 🛡 | **Security Center** | **Have I Been Pwned** password + email checks, plus **vault audit** for weak, reused, and breached saved passwords. |

### 🎮 Gaming

|    | Module                  | What it does |
| -- | ----------------------- | ------------ |
| 🎮 | **Gaming Hub**          | **Scan, launch, and manage** installed games across drives. Save backup hints, per-game notes, drive selection. Phone browse/launch on HTTPS **8446**. |
| 🎮 | **Game Server Manager** | Universal **dedicated game server** manager for **Minecraft Java & Bedrock**, Satisfactory, Terraria, Valheim, Palworld, Project Zomboid, **SteamCMD** installations, and custom servers. Start/stop, consoles, RCON, configs, backups. Hub Go Live exposes start/stop/ready to the phone on HTTPS **8453**. |

### 📁 Files

|    | Module               | What it does |
| -- | -------------------- | ------------ |
| 📁 | **File Manager**     | **Universal file viewer** — text, hex, images, **in-app audio**, **zip explorer**, metadata side panels, multi-tab. |
| 🗂 | **Folder Generator** | Create **predefined folder structures** for games and projects from JSON templates, including ROM hacks and asset pipelines. |
| 🗑 | **File Shredder**    | **Securely overwrite and delete** files and folders so deleted data is much harder to recover. |

### 🌐 Network

|    | Module                  | What it does |
| -- | ----------------------- | ------------ |
| 🌐 | **Network Auditor**     | **Discover devices** on your LAN, **scan ports**, and review basic security findings. Uses Scapy + Nmap and requires Npcap/Nmap on the machine. |
| 🔀 | **Port Forward Helper** | Detect your router through **UPnP** and add/remove **port forwards** without logging into the router administration page. |
| 📤 | **Quick Send**          | **Send files between your phone and PC** on your tailnet using inbox/outbox folders and a received-files log. HTTPS **8449**. |
| 📡 | **Remote Hub**          | One **phone-friendly landing page** over Tailscale. Scan a QR code, view recent Quick Send files, and jump to whichever supported modules are currently live. |
| 🖥 | **SSH / Serial**        | **SSH** into a Pi, VPS, or LAN box (password or key; hosts saved, passwords not). **Serial** console on a COM port. Optional “open in Windows Terminal.” |
| 🟠 | **Tailnet Social**      | Issue **invite keys** so friends on the tailnet can share a **jukebox queue**, trigger the **soundboard**, and (if allowed) send a **limited GSM console** line. Night page goes live with Remote Hub. HTTPS **8450**. |

### 🖥️ System

|     | Module                    | What it does |
| --- | ------------------------- | ------------ |
| 🖥️ | **System Monitor**        | Live **CPU, RAM, disk, network, and GPU** statistics with a process list and optional **mini desktop widget**. |
| 🩺  | **Environment Checker**   | One-screen **dependency health check** for VLC, Tailscale, WebView2, Nmap/Npcap, disk space, and other requirements. Optional **pip outdated / update** for this interpreter. |
| 🧹  | **Startup Optimizer**     | Scan startup apps and services, see what's safe to disable, and clean up boot load (registry Run keys, startup folders, scheduled tasks). |
| 🧬  | **Duplicate File Finder** | Scan folders for **byte-identical files** and reclaim wasted disk space. |
| 🔧  | **Driver/Update Checker** | Review **installed drivers** and check for driver/software updates using Windows Update Agent integration where available. |
| 🧊  | **Disposable Sandbox**    | Linked-clone a **VMware Workstation** snapshot. Close the clone and it is deleted. Drop folder is shared **read-only**. Base VM is not written. |
| 📱  | **Phone Screen**          | Mirror an **Android** phone or emulator (USB / wireless ADB). **Tap and swipe**. Optional scrcpy HD window. Refresh also probes **BlueStacks** `adb_port` from `bluestacks.conf`. |
| ⚖  | **Resource Governor**     | RAM/CPU **budgets**. When the machine is over the line, **new game-server starts** are blocked (UI + agent). Does not kill processes. |
| ⏪  | **Time Travel**           | Timeline of **GSM world zips**, Gaming Hub save backups, live AppData files, and **Windows VSS** shadows. Copy out or restore a GSM zip. |
| 🗺  | **Disk Map**              | Walk a drive and show **biggest folders first**. Click a bar to go in. |

### 🎨 Design

|     | Module                      | What it does |
| --- | --------------------------- | ------------ |
| 🎨  | **Color Picker**            | Pick colors by **hex, RGB, or HSV**, use an **eyedropper**, and generate **harmony palettes** from a base color. |
| 🧩  | **Icon/Favicon Generator**  | Turn one image into a complete **favicon.ico + PNG icon set + site.webmanifest** for websites. |
| 🖼️ | **Image Palette Extractor** | Extract **dominant colors** from images as copyable hex/RGB swatches. |
| 🔳  | **QR Generator**            | Create **QR codes** from text, URLs, Wi-Fi credentials, or contact information and save/share the resulting image. |

### 🤖 AI

|    | Module      | What it does |
| -- | ----------- | ------------ |
| 🤖 | **AI Chat** | One box for a **hosted API** or a **local** Ollama / llama.cpp model. **Agent mode** can run app actions. Slash commands, **`/build`**, and a **prompt library**. Hosted API key stays on this PC. Hub Go Live exposes the same chat to the phone on HTTPS **8454**. |

### 📋 Productivity

|    | Module                | What it does |
| -- | --------------------- | ------------ |
| 📋 | **Clipboard Manager** | **Clipboard history** while the app is open — search, pin, and re-copy previous items. Configurable maximum size and polling interval through ⚙ settings. |
| 📝 | **Notes**             | Free-form notes with links. Phone edit on HTTPS **8448**. |
| 💬 | **Messages**          | Chat with **this PC** from a phone on the tailnet (not a friend-to-friend mesh). HTTPS **8452**. |
| 🔎 | **Personal Search**   | Substring search across **notes, messages, activity, game servers, MangaDex downloads**, and a few AppData json files. |

### 🧰 Utilities

|     | Module                | What it does |
| --- | --------------------- | ------------ |
| 📦  | **App Installer**     | Search for and install applications through **winget**, or run custom installation commands. |
| 🕹️ | **Game Stats & News** | **Live game stats** through your own API keys, including Fortnite, Steam, or custom APIs, plus **custom RSS/news feeds** and saved articles. |

---

## Architecture

```text
main.py                       # Entry: SettingsManager + Qt app (core.qt.app.run)

core/
  qt/app.py                   # QApplication, services, MainWindow
  qt/page_bridge.py           # catalog / now / marketplace / settings / qt_tool_host
  qt/marketplace_view.py      # Module marketplace (core shell, not a plugin)
  qt/module_shell.py          # ⚙ gear, per-module theme, optional extras
  qt/remote_common.py         # Shared Tailscale / App Serve / vault / music panels
  marketplace/                # .zmod packages, auto build numbers, overlay install
  plugin_manager.py           # Loads modules/ + marketplace overlay, qt_page → lazy import
  module_themes.py            # Module theme presets + persistence
  theme.py                    # Shared design tokens
  settings.py                 # Persistent app settings (JSON)
  updater.py                  # GitHub Releases self-updater (APP_VERSION 4.0.5)
  win_subprocess.py           # Windows: hide console flashes from child processes
  services/                   # Auth, crypto, Discord, Tailscale, vault web, etc.

pages/
  catalog_theme.py            # Catalog appearance themes (used by Qt home)

modules/<Category>/<Tool>/
  __init__.py                 # register() only — no UI imports
  ui.py                       # QWidget page (parent, manager)
  ...                         # backends / web servers (no CustomTkinter)
```

Folders with spaces cannot use `from modules.X.Y import …`. Use `importlib.import_module("modules.Media.Media Player.db")` (and the same for other spaced names).

### Plugin contract

Every tool under `modules/` exposes `register(plugin_manager)` and calls:

```python
plugin_manager.register({
    "name": "Your Tool",
    "category": "Media",           # shown in catalog filters
    "desc": "One-line card summary",
    "icon": "🎵",
    "qt_page": "modules.Your.Tool.ui:YourPage",
})
```

`qt_page` is a `QWidget` subclass constructed as `(parent, manager)`. The Qt shell adds the ⚙ gear bar, theme picker, and optional `build_qt_module_settings(parent, manager)`. Extra settings scroll in the same page as the theme cards.

Do **not** put `page_class` or live widgets on the register dict — they are ignored. Do **not** import UI from `__init__.py`.

### Marketplace and module versions

The **Market** page is part of the core shell. Installed packages land in `%APPDATA%\ZsMultiTool\marketplace\modules\` and are merged into the same `modules.` import path the Plugin Manager already uses, so `qt_page` strings stay `modules.…ui:Class`. Overlay copies win over the bundled folder; uninstalling an overlay falls back to the included tool.

You do not pick semantic versions. **Publish next build** on a card (or the Publish filter) packages that tool as a `.zmod` and increments an integer build:

```text
Edit Media Player → Market → Publish next build → Build 2 · 2026-09-06
        ↓
Other PCs see "Media Player — Update available"
        ↓
Update / Update all  (older builds cannot replace newer ones)
        ↓
Roll back if the new build misbehaves
```

A module update never requires a new Z's Multi Tool release. Only core/shell changes do.

The default catalog is the local publisher store on this PC (`marketplace/publisher/index.json` + `packages/`). Settings → Module Marketplace can point at a hosted `index.json` later. Each package is checked with SHA-256; a `signature` field is reserved for third-party publishers.

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

| Package                    | Used for |
| -------------------------- | -------- |
| `PySide6`                  | Qt UI (`QtCore` / `QtGui` / `QtWidgets` / `QtMultimedia`). Do not `--collect-all PySide6` in the freezer — it pulls QML/Charts. |
| `pillow`                   | Images, icons, thumbnails |
| `python-vlc`               | Media Player / video playback |
| `mutagen`                  | Audio metadata / library tags |
| `yt-dlp`                   | YouTube Downloader |
| `cryptography`             | Encryption, Secure Vault |
| `psutil`                   | System Monitor |
| `scapy`, `python-nmap`     | Network Auditor |
| `watchdog`                 | Media Player folder watch (runs off the UI thread) |
| `sounddevice`, `soundfile` | Soundboard |
| `pypresence`               | Discord Rich Presence |
| `pyperclip`                | Clipboard Manager |
| `qrcode`                   | QR Generator |
| `openai`                   | AI Chat hosted models |
| `fido2`                    | Optional FIDO2 USB security key unlock |
| `pywin32`                  | Windows-only features such as timestamps, startup management, and updates |

See `requirements.txt` for the full dependency list and version floors.

`customtkinter` is **not** a dependency. Do not add it back.

### External dependencies

| Tool                   | Needed for |
| ---------------------- | ---------- |
| **VLC**                | Media Player — `python-vlc` wraps `libvlc.dll`. Install VLC or ship `libvlc.dll` + `plugins/` next to the app. |
| **ffmpeg**             | Optional fallback transcoding for exotic audio formats when VLC cannot decode them natively. |
| **Npcap + Nmap**       | Network Auditor — packet capture and port scanning. |
| **Ollama / llama.cpp** | AI Chat — optional local model backends. |
| **Tailscale**          | Phone remote: vault, music, YT, games, soundboard, notes, send, social, messages, GSM, chat, device trust. |
| **winget**             | App Installer — Windows Package Manager CLI. |
| **ADB** (optional)     | Phone Screen. BlueStacks needs Android Debug Bridge enabled in its Advanced settings. |
| **mGBA** (optional)    | Folder Generator — some GBA templates expect `modules/Files/Folder Generator/assets/mGBA.exe`. Not included in the repo. |

> **Note:** `pygame` is **no longer required**. Media Player uses VLC. File Manager's audio preview uses Qt multimedia.

---

## Running from source

```bash
py.bat
```

or:

```bash
python main.py
```

That always starts the Qt shell. There is no `--classic` / CustomTkinter mode.

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

The build process also refreshes `requirements-lock.txt`. Hidden-imports cover `QtCore` / `QtGui` / `QtWidgets` / `QtMultimedia` only — Charts, QML, and WebEngine are excluded.

See `build.bat` for bundled paths and build-specific caveats.

The following dependencies still need to exist on the target machine or be installed separately:

* **VLC**
* **Npcap/Nmap**
* **FFmpeg / yt-dlp** (installer can offer these)
* Other required Windows components

### Console build

For a build that shows stdout/stderr:

```bat
build_console.bat
```

### Windows installer

After `build.bat`, compile `install.iss` with **Inno Setup 6+** (version **4.0.5**, same as `APP_VERSION`).

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" install.iss
```

Optional installer tasks can download/install:

* **VLC**
* **Npcap**
* **Nmap**
* **FFmpeg**
* **yt-dlp**

---

## Data & privacy

Local application data lives under `%APPDATA%` and the project's `data/` folder for vaults, settings, and caches. The music library index is `%APPDATA%\MusicPlayerApp\library.db`.

**Treat the following as sensitive and do not commit them:**

* `data/` — vault files, keys, and local caches
* `settings.json` — personal preferences
* Master keys
* API keys entered in modules such as Security Center, Game Stats & News, and AI Chat (hosted key is memory-only on this PC)

The **Secure Vault** and **File Encryption** modules use local encryption. Back up your master password and vault data separately.

---

## Remote access — Tailscale

Modules expose a **localhost-only** web UI. Tailscale Serve maps those to fixed HTTPS ports (`APP_HTTPS_PORTS` in `core/services/tailscale_service.py`). Pair the phone with **Remote Hub → Go Live** (device trust on **8455**).

| HTTPS | Module | What the phone can do |
| ----- | ------ | --------------------- |
| **8443** | Secure Vault | Read passwords and TOTP |
| **8444** | Media Player | Browse and stream the library |
| **8445** | YouTube Downloader | Queue downloads |
| **8446** | Gaming Hub | Browse / launch games |
| **8447** | Soundboard | Trigger clips |
| **8448** | Notes | Read and edit notes |
| **8449** | Quick Send | Files to and from the PC |
| **8450** | Tailnet Social / Night | Jukebox, soundboard, limited GSM line (invite key) |
| **8452** | Messages | Chat with this PC |
| **8453** | Game Server Manager | Start / stop / ready |
| **8454** | AI Chat | Same model / agent as the desktop box |
| **8455** | Device trust | Pair the phone to the hub |

Configure each module's ⚙ **Remote access** section (shared panels in `core/qt/remote_common.py`), or use **Remote Hub → Go Live** when supported.

An optional access code can be configured before exposing services beyond your trusted tailnet.

---

## Contributing / adding a module

1. Create `modules/<Category>/<Your Tool>/`
2. Add `__init__.py` with `register(plugin_manager)` and a **string** `qt_page` (`"modules.Category.Tool.ui:YourPage"`). Do not import UI at register time
3. Add `ui.py` next to that backend — a `QWidget` subclass `(parent, manager)`. Optional `build_qt_module_settings(parent, manager)` for extras under the gear
4. No CustomTkinter. No `core/qt/tools/` page files
5. Restart the app — the catalog discovers new module folders. To ship an update without a new Multi Tool release, open **Market → Publish next build** on that card

---

## License & author

Personal utility collection by **Zyvelia**.

Some third-party assets and dependencies used by the application may have their own licenses. Please refer to the respective project's license terms where applicable.
