# Z's Multi Tool

A modular Python desktop app that bundles a bunch of personal utilities — media
tools, security utilities, gaming helpers, and system info — into one
CustomTkinter interface with a plugin-style catalog.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-4ea1ff)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## What is this

Instead of one monolithic app, every tool lives in its own folder under
`modules/`, registers itself with the app on startup, and shows up as a card
in the catalog page. Opening a card swaps it into the shared page manager, so
everything lives inside a single window with one consistent dark
navy-and-gold theme.

## Modules

| Icon | Name | Category | What it does |
|---|---|---|---|
| 🖥️ | System Monitor | System | Live system statistics |
| 🎬 | Media Center | Media | Play music and videos with VLC |
| 🎵 | Music Player | Media | VLC-powered audio player |
| 🔊 | Soundboard | Media | Play sounds through your mic or audio device |
| ▶ | YT Downloader | Media | Download YouTube videos and playlists as MP3 or MP4 |
| 🌦️ | Weather & News | Info | Live weather + custom news feeds, saved articles, and settings |
| 🔍 | Hash Tools | Security | Generate and verify hashes |
| 🔒 | File Encryptor | Security | Encrypt and decrypt files |
| 🔐 | Password Vault | Utilities | Encrypted password manager |
| 🌐 | Network Auditor | Networking | Scan and audit your local network |
| 🎮 | Gaming Hub | Gaming | Scan, launch and manage games |
| 🗂 | Folder Structure Generator | Tools | Create predefined folder structures for games from JSON templates (needs `mGBA.exe`, see below) |
| 📁 | Universal File Viewer | Tools | View, edit and manage any file — text, hex, images, audio, archives |
| 📝 | Notes | Utilities | Free-form notes with attached links |

## Architecture

```
main.py                  # entry point: builds SettingsManager + App, runs mainloop
core/
  app.py                 # App window, wires everything together
  page_manager.py        # manager.container / manager.show_page("catalog") — page routing
  plugin_loader.py        # walks modules/, imports each package, triggers register()
  plugin_manager.py       # holds registered tool metadata, exposes it to the catalog
  tool_registry.py        # {name, category, desc, icon, open} schema + storage
  settings.py             # persistent app settings
  theme.py                # shared colors/spacing (navy/gold theme)
  services/                # shared services (auth, crypto, vault, discord RPC)
pages/
  catalog_page.py         # the home grid of tool cards, search/filter
  settings_page.py        # app-level settings UI
modules/<name>/
  __init__.py             # register(plugin_manager) — declares name/category/desc/icon/open()
  ui.py                    # the module's CTkFrame-based page
  ...                      # module-specific logic files
data/                      # local JSON data + vault files (gitignored, see below)
```

**Plugin contract:** every folder under `modules/` needs an `__init__.py`
that exposes a `register(plugin_manager)` function. That function calls
`plugin_manager.register({...})` with:

```python
{
    "name": "Your Tool Name",
    "category": "Media | Security | Tools | ...",
    "desc": "One-line description shown on the card",
    "icon": "🔊",
    "open": open_your_tool,   # callable(manager) -> ctk.CTkFrame
}
```

`open_your_tool(manager)` returns a `ctk.CTkFrame` built against
`manager.container` (must stay the `App` instance, not a sub-frame — modules
reach shared services through it) and gets shown via
`manager.show_page("your_tool_name")`.

## Requirements

- Python 3.11+ (3.13 supported)
- Windows (VLC/vlc bindings, DS4Windows-style tooling, and some modules assume
  a Windows environment)

### Third-party packages

```
customtkinter
pillow
mutagen
pygame
python-vlc
sounddevice
soundfile
cryptography
pyperclip
pypresence
requests
psutil
scapy
python-nmap
youtube_dl
yt-dlp
numpy
```

Install with:
```
pip install customtkinter pillow mutagen pygame python-vlc sounddevice soundfile cryptography pyperclip pypresence requests psutil scapy python-nmap youtube_dl yt-dlp numpy
```

**External, non-pip dependencies:**
- **VLC** — `python-vlc` just talks to a VLC install; the Media Center module
  needs VLC itself installed (or `libvlc.dll` + the VLC `plugins` folder sitting
  next to the app) to actually play anything.
- **Npcap + Nmap** — the Network Auditor module uses `scapy` and `python-nmap`,
  which need Npcap and Nmap installed on the machine for packet capture / port
  scanning to work.
- **mGBA** — the Folder Structure Generator module expects
  `modules/folder_gen/assets/mGBA.exe` (the [mGBA](https://mgba.io/) Game Boy
  Advance emulator) for its GBA-related templates. It's not committed to this
  repo (42MB third-party binary, not our code) — download mGBA's Windows
  build from https://mgba.io/downloads.html and drop `mGBA.exe` into that
  folder yourself, or that specific template feature won't work.

## Running from source

```
py.bat
```
or directly:
```
python main.py
```

## Building a standalone .exe

Run `build.bat` from the project root. It installs PyInstaller if needed,
cleans old `build`/`dist` folders, and produces a single-file, windowed
`Z's Multi Tool.exe` in `dist/`, bundling `core/`, `modules/`, `pages/`,
`data/`, and `settings.json`.

See the notes inside `build.bat` for the VLC/Npcap caveats above — those still
need to exist on whatever machine runs the exe, PyInstaller can't bundle
system-level drivers.

## Notes / known constraints

- `keyboard`-library-based hotkeys (used by other tools in this ecosystem,
   require running as Administrator.
- CustomTkinter widgets should use a real color constant instead of
  `border_color="transparent"` (use `BORDER`/`BG_PANEL` from `core/theme.py`)
  to avoid rendering glitches.
- Navigation uses a single `Escape` key binding on the root window instead of
  per-module back buttons.
- `data/` contains local settings and vault files (including `master.key` and
  `vault.json`) — treat this folder as sensitive/local-only, don't commit or
  share it as-is.