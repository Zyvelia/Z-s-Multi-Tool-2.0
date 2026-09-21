# Z's Multi Tool

A modular Windows desktop app built with **Python 3.11+** and **Qt (PySide6)**. Z's Multi Tool provides a searchable catalog and a separate module marketplace so tools can be installed and updated without requiring a new core-app release.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Qt](https://img.shields.io/badge/UI-PySide6-41cd52)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Version](https://img.shields.io/badge/version-4.0.5-green)

**Repository:** https://github.com/Zyvelia/Z-s-Multi-Tool-2.0

**Marketplace:** https://github.com/Zyvelia/zmt-marketplace

---

## What is this?

Z's Multi Tool is a Qt desktop shell for a collection of independently installable tools.

The **core application** contains the catalog, settings, marketplace, shared services, updater, and UI framework. Individual tools are distributed as `.zmod` packages through the Marketplace rather than being required in the core repository.

This means a module can be updated independently:

```text
Core app
   │
   ├── Catalog
   ├── Settings
   ├── Marketplace
   └── Shared services
          │
          ▼
     Module packages
        (.zmod)
          │
          ▼
   Installed on the user's PC
```

### Highlights

- **Plugin catalog** — searchable home page with category filtering and module enable/disable controls.
- **Marketplace** — browse, search, install, uninstall, update, update-all, and roll back modules.
- **Independent module updates** — module updates do not require a new core-app release.
- **Automatic build numbers** — publishing assigns the next integer build automatically.
- **Per-module themes** — modules can expose their own settings and theme options.
- **Remote Hub** — one Tailscale-based landing page for supported phone features.
- **Shared services** — authentication, encryption, Discord RPC, Tailscale, settings, and other common services live in `core/services/`.
- **Self-updater** — optional GitHub Releases update checking for the core application.
- **Qt only** — CustomTkinter is not used.

---

## Marketplace

Modules are distributed separately from the core application through the Z's Multi Tool Marketplace.

**Marketplace repository:**
https://github.com/Zyvelia/zmt-marketplace

The marketplace contains the package index and `.zmod` packages:

```text
zmt-marketplace/
├── index.json
└── packages/
    ├── ai-chat/
    │   └── build-1.zmod
    ├── media-player/
    │   └── build-1.zmod
    └── ...
```

The public Z's Multi Tool repository does **not** need to contain the downloadable module source tree.

### Publishing a module

From the developer/publisher workflow:

```text
Edit module
    ↓
Publish next build
    ↓
Build N .zmod
    ↓
Update marketplace index
    ↓
Publish to zmt-marketplace
    ↓
Users see an available update
```

Users never need to choose a semantic version for a module. Builds use an integer sequence such as:

```text
Build 1
Build 2
Build 3
...
```

The Marketplace verifies package SHA-256 hashes. A `signature` field is reserved for future third-party publisher verification.

---

## Modules

The following are the current module categories and tools. Modules are distributed through the Marketplace and installed into the user's local module environment.

### 🎵 Media

| Module | What it does |
| --- | --- |
| **Media Player** | VLC music library with browser table, search, artists, disk folders, virtual Title/Artist/Album/Time fields, sticky transport bar, pop-out video, SQLite incremental indexing, folder watching, shuffle/repeat/queue, cue sheets, and optional phone streaming. |
| **Media Metadata Editor** | Edit audio tags including title, artist, and album; batch audio operations; image EXIF and file timestamps. |
| **Soundboard** | Play clips through speakers or a virtual cable/mic path with per-clip volume and optional phone control. |
| **YouTube Downloader** | Download YouTube videos and playlists as MP3 or MP4 through yt-dlp, with browser-cookie support and phone queue support. |
| **Video to GIF Converter** | Convert video to optimized GIFs with size-fit options and drag-and-drop. |
| **MangaDex Reader** | Browse MangaDex, download chapters, and assist with OCR, translation, and TTS. Japanese OCR requires Tesseract. |

### 🔐 Security

| Module | What it does |
| --- | --- |
| **Hash Tools** | Generate and verify MD5, SHA-1, SHA-256, SHA-512, and other hashes for files and text. |
| **File Encryption** | Encrypt and decrypt files with a password, lock screen, and optional hardware security-key unlock. |
| **Secure Vault** | Password manager and TOTP authenticator with encrypted storage, security audit, notes, URLs, emergency-kit export, optional FIDO2 unlock, and Tailscale remote access. |
| **Security Center** | Have I Been Pwned password/email checks plus vault auditing for weak, reused, and breached passwords. |

### 🎮 Gaming

| Module | What it does |
| --- | --- |
| **Gaming Hub** | Scan, launch, and manage installed games across drives, with save-backup hints, notes, drive selection, and phone access. |
| **Game Server Manager** | Dedicated server management for Minecraft Java/Bedrock, Satisfactory, Terraria, Valheim, Palworld, Project Zomboid, SteamCMD installations, and custom servers. Includes start/stop, consoles, RCON, configs, and backups. |

### 📁 Files

| Module | What it does |
| --- | --- |
| **File Manager** | Universal file viewer for text, hex, images, in-app audio, ZIP archives, metadata panels, and multi-tab browsing. |
| **Folder Generator** | Generate predefined folder structures from JSON templates for games and projects. |
| **File Shredder** | Securely overwrite and delete files and folders. |

### 🌐 Network

| Module | What it does |
| --- | --- |
| **Network Auditor** | Discover LAN devices, scan ports, and review basic security findings. Uses Scapy and Nmap/Npcap. |
| **Port Forward Helper** | Detect routers through UPnP and add/remove port forwards. |
| **Quick Send** | Transfer files between a phone and PC over the tailnet. |
| **Remote Hub** | Phone-friendly Tailscale landing page with QR pairing, Quick Send history, and links to supported live modules. |
| **SSH / Serial** | SSH and serial console access for PCs, servers, Pi systems, and other LAN devices. |
| **Tailnet Social** | Invite-key-based shared jukebox, soundboard controls, and limited GSM console access. |

### 🖥️ System

| Module | What it does |
| --- | --- |
| **System Monitor** | Live CPU, RAM, disk, network, and GPU statistics with process list and optional mini desktop widget. |
| **Environment Checker** | Dependency health checks for VLC, Tailscale, WebView2, Nmap/Npcap, disk space, and other requirements. |
| **Startup Optimizer** | Review startup applications/services and manage boot load from registry Run keys, startup folders, and scheduled tasks. |
| **Duplicate File Finder** | Find byte-identical files and reclaim disk space. |
| **Driver/Update Checker** | Review installed drivers and check for available updates where Windows Update Agent integration supports it. |
| **Disposable Sandbox** | Create linked VMware Workstation snapshot clones that are deleted when closed. |
| **Phone Screen** | Mirror Android devices or emulators through USB/wireless ADB, with optional scrcpy. |
| **Resource Governor** | Apply RAM/CPU budgets and block new game-server starts when the configured limit is exceeded. |
| **Time Travel** | Browse GSM world zips, Gaming Hub backups, live AppData files, and Windows VSS snapshots for restore/copy operations. |
| **Disk Map** | Scan a drive and display the largest folders first. |

### 🎨 Design

| Module | What it does |
| --- | --- |
| **Color Picker** | Pick colors using hex/RGB/HSV, eyedropper, and harmony palettes. |
| **Icon/Favicon Generator** | Generate favicon.ico, PNG icon sets, and site.webmanifest files. |
| **Image Palette Extractor** | Extract dominant colors from images as copyable swatches. |
| **QR Generator** | Generate QR codes for text, URLs, Wi-Fi credentials, and contacts. |

### 🤖 AI

| Module | What it does |
| --- | --- |
| **AI Chat** | Hosted API or local Ollama/llama.cpp chat, agent mode, slash commands, `/build`, and prompt library. Hosted API keys remain on the local PC. |

### 📋 Productivity

| Module | What it does |
| --- | --- |
| **Clipboard Manager** | Searchable clipboard history while the app is running, with pinning and re-copy support. |
| **Notes** | Free-form notes with links and optional phone editing. |
| **Messages** | Chat with the PC from a phone on the tailnet. |
| **Personal Search** | Search notes, messages, activity, game servers, MangaDex downloads, and selected local JSON data. |

### 🧰 Utilities

| Module | What it does |
| --- | --- |
| **App Installer** | Search for and install applications through winget or custom installation commands. |
| **Game Stats & News** | Live game statistics through configured API keys plus custom RSS/news feeds and saved articles. |

---

## Architecture

The core repository is intentionally focused on the application shell and shared functionality.

```text
main.py
│
├── core/
│   ├── qt/
│   │   ├── app.py
│   │   ├── page_bridge.py
│   │   ├── marketplace_view.py
│   │   ├── module_shell.py
│   │   └── remote_common.py
│   │
│   ├── marketplace/
│   │   └── package/install/update logic
│   │
│   ├── plugin_manager.py
│   ├── module_themes.py
│   ├── theme.py
│   ├── settings.py
│   ├── updater.py
│   └── services/
│       ├── auth
│       ├── crypto
│       ├── Discord RPC
│       ├── Tailscale
│       └── other shared services
│
└── pages/
    └── catalog_theme.py
```

Installed Marketplace modules are loaded through the same plugin system after installation. The Marketplace install location is managed by the application under the user's `%APPDATA%` data directory.

### Plugin contract

Every module exposes a `register(plugin_manager)` function and registers a string `qt_page`:

```python
plugin_manager.register({
    "name": "Your Tool",
    "category": "Media",
    "desc": "One-line card summary",
    "icon": "🎵",
    "qt_page": "modules.Your.Tool.ui:YourPage",
})
```

The `qt_page` points to a `QWidget` subclass constructed as `(parent, manager)`.

Do not put live widgets or `page_class` objects in the registration dictionary. Do not import the UI from `__init__.py`.

For module packages whose folder names contain spaces, use `importlib.import_module()` rather than a normal dotted Python import.

---

## Requirements

- **Python 3.11+**
- **Windows**

### Python packages

Install the development dependencies with:

```bash
pip install -r requirements.txt
```

Key dependencies include:

| Package | Used for |
| --- | --- |
| `PySide6` | Qt UI |
| `pillow` | Images and icons |
| `python-vlc` | Media playback |
| `mutagen` | Audio metadata |
| `yt-dlp` | YouTube Downloader |
| `cryptography` | Encryption and Secure Vault |
| `psutil` | System Monitor |
| `scapy`, `python-nmap` | Network Auditor |
| `watchdog` | Media Player folder watching |
| `sounddevice`, `soundfile` | Soundboard |
| `pypresence` | Discord Rich Presence |
| `pyperclip` | Clipboard Manager |
| `qrcode` | QR Generator |
| `openai` | AI Chat hosted models |
| `fido2` | Optional FIDO2 security-key support |
| `pywin32` | Windows-specific functionality |

`customtkinter` is **not** required.

### External dependencies

| Dependency | Used for |
| --- | --- |
| **VLC** | Media Player. `python-vlc` requires the VLC runtime (`libvlc.dll` and `plugins/`) unless VLC is installed separately. |
| **FFmpeg** | Optional fallback transcoding. |
| **Npcap + Nmap** | Network Auditor. |
| **Ollama / llama.cpp** | Optional local AI models. |
| **Tailscale** | Phone remote functionality. |
| **winget** | App Installer. |
| **ADB** | Phone Screen. |
| **mGBA** | Optional Folder Generator templates. |

---

## Running from source

From the project root:

```bash
python main.py
```

The application starts directly in the Qt shell.

Use **Escape** to return to the catalog from supported pages. Module settings and themes are available through the gear control.

---

## Building the application

From the project root:

```bat
build.bat
```

The PyInstaller build produces the standalone application under `dist/`.

The build configuration includes the Qt modules required by the application and avoids collecting unnecessary QML/Charts/WebEngine components.

Some external dependencies may still need to be installed separately on the target machine, depending on the installer/build configuration:

- VLC
- Npcap/Nmap
- FFmpeg / yt-dlp
- Other required Windows components

### Console build

For a build that keeps stdout/stderr visible:

```bat
build_console.bat
```

### Windows installer

The project can be packaged with Inno Setup 6+ using `install.iss`.

Optional installer tasks can handle installation of supported external dependencies such as:

- VLC
- Npcap
- Nmap
- FFmpeg
- yt-dlp

---

## Data & privacy

Local application data is stored under `%APPDATA%` and the application's local data directories.

### Never commit sensitive local data

The following should remain local and should not be committed to the public repository:

```text
data/
settings.json
master keys
API keys
local vault data
local caches
```

In particular, API keys used by Security Center, Game Stats & News, and AI Chat should remain on the user's PC.

The Secure Vault and File Encryption features use local encryption. Keep recovery information and vault backups separate from the source repository.

---

## Remote access — Tailscale

Supported modules expose localhost services that can be made available through Tailscale Serve and the Remote Hub.

| HTTPS | Module | Function |
| ---: | --- | --- |
| **8443** | Secure Vault | Passwords and TOTP |
| **8444** | Media Player | Browse and stream library |
| **8445** | YouTube Downloader | Download queue |
| **8446** | Gaming Hub | Browse / launch games |
| **8447** | Soundboard | Trigger clips |
| **8448** | Notes | Read and edit notes |
| **8449** | Quick Send | Transfer files |
| **8450** | Tailnet Social / Night | Jukebox, soundboard, limited GSM access |
| **8452** | Messages | Chat with the PC |
| **8453** | Game Server Manager | Start / stop / ready |
| **8454** | AI Chat | Desktop AI chat/agent |
| **8455** | Device trust | Pair the phone with the hub |

Remote access should only be exposed to devices and networks you trust. An optional access code can be configured before exposing supported services beyond the intended tailnet.

---

## Contributing / creating a module

Modules are developed separately and published through the Marketplace.

1. Create a module using the project's module contract.
2. Add `__init__.py` with `register(plugin_manager)`.
3. Register a string `qt_page` such as `modules.Category.Tool.ui:YourPage`.
4. Add `ui.py` containing the module's `QWidget` page.
5. Keep UI imports out of `__init__.py` registration.
6. Test the module locally.
7. Package it as a `.zmod` through the publisher workflow.
8. Publish the next integer build to the Marketplace.

A module update does not require a new Z's Multi Tool release. Core/shell changes are released separately.

---

## Repository layout

The public repository contains the core application and public build/source files. Developer-only publishing tools, local marketplace staging files, downloaded module source, and private credentials should remain outside the public repository or be excluded with `.gitignore`.

A typical developer workspace may look like:

```text
Z-s-Multi-Tool-2.0/
├── core/
├── pages/
├── main.py
├── requirements.txt
├── .gitignore
├── build.bat
├── build_console.bat
└── ...

Developer-only / local:
├── developer/
├── PublishedModules/
└── local module source/

Separate marketplace repository:
zmt-marketplace/
├── index.json
└── packages/
    └── *.zmod
```

The exact local developer layout can vary; the important separation is that private publisher credentials and developer-only tooling are not shipped with the public client.

---

## License & author

Personal utility collection by **Zyvelia**.

Third-party assets and dependencies may have their own licenses. Refer to the respective project's license terms where applicable.
