# AI Terminal Module — Integration Guide

## 1. Where the files go

Copy the whole `modules/ai_terminal/` folder into your Multi Tool project so it
sits next to your other modules:

```
YourMultiTool/
├── main.py                      <- your existing entry point
├── modules/
│   ├── ai_terminal/              <- NEW — drop this folder in as-is
│   │   ├── __init__.py
│   │   ├── page.py
│   │   ├── client.py
│   │   ├── builder.py
│   │   ├── commands.py
│   │   └── security.py
│   └── (your other modules...)
└── AI_Projects/                  <- created automatically on first /build
```

`AI_Projects/` is created automatically at the app root (two levels above
`page.py`) the first time the module loads — you don't need to create it
yourself, and generated projects are **only ever** written there.

## 2. Dependencies

```bash
pip install openai customtkinter
```

Nothing else is required. The module only imports `customtkinter` (GUI) and
`openai` (SDK) — both already implied by your existing stack.

## 3. Wiring it into your app

This module follows the exact same plugin convention as your existing
`App Installer` module (`register(plugin_manager)` + an `open_*(manager)`
factory that builds the frame from `manager.container`/`manager`). No
changes to your plugin manager or loader are needed — just make sure your
loader picks up `modules/ai_terminal` the same way it picks up
`modules/app_installer`.

```python
# modules/ai_terminal/__init__.py  (already included, shown for reference)

from .page import AITerminalModule


def open_ai_terminal(manager):
    return AITerminalModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "AI Terminal",
            "category": "Tools",
            "desc": "Chat with an AI model, run slash-commands, and generate complete multi-file projects with /build.",
            "icon": "🤖",
            "open": open_ai_terminal,
        }
    )
```

`AITerminalModule(container, manager)` mirrors `AppInstallerModule(manager.container, manager)`
exactly:
- `container` is used as the `CTkFrame`'s master.
- `manager` is stored on `self.manager` in case you want to reach shared
  app state (theme, navigation, settings) later — the module doesn't
  assume anything about `manager`'s API beyond `.container`.
- The frame `.pack(fill="both", expand=True)`s itself into `container`
  during `__init__`, the same way your other modules present themselves
  once `open_*()` returns.

If you'd rather store generated projects somewhere other than the default
`<app_root>/AI_Projects`, pass `projects_root` through `open_ai_terminal`:

```python
def open_ai_terminal(manager):
    return AITerminalModule(
        manager.container,
        manager,
        projects_root="/custom/path/AI_Projects",
    )
```

## 4. What each file does

| File | Responsibility |
|---|---|
| `security.py` | `InMemorySecret` (API key never touches disk/logs/DB) + path-traversal-safe file writing for the builder. |
| `client.py` | All OpenAI-SDK calls (`test_connection`, `stream_chat`, `simple_chat`, `list_models`). Zero GUI code — usable from any script. |
| `builder.py` | `/build` pipeline: ask AI for a JSON project plan → ask AI to generate full file contents → validate every path → write only inside `AI_Projects/`. Never executes anything. |
| `commands.py` | Parses `/command args` strings and routes them to handlers. GUI-agnostic. |
| `page.py` | The actual `CTkFrame` module (`AITerminalModule`): config panel, terminal output, input bar, threading/queue glue. |
| `__init__.py` | `register(plugin_manager)` + `open_ai_terminal(manager)`, matching your existing module convention (see `App Installer`). |

## 5. Security properties (verified in this build)

- **API key**: lives only in a `CTkEntry` widget and `security.InMemorySecret`
  for the process lifetime. It is passed directly to the OpenAI SDK client
  constructor and is never written to a file, config, log line, or database.
  `repr()`/`str()` of the secret object never reveal the raw value.
- **Path safety**: `security.is_safe_relative_path()` rejects absolute paths,
  drive letters (`C:\`), and `..` traversal segments. `resolve_safe_path()`
  additionally re-verifies the resolved absolute path is still inside the
  target project directory before any file is opened for writing. Tested
  against `../evil.py`, `/etc/passwd`, `C:/Windows/system.ini`, and nested
  traversal (`a/../../b`) — all correctly rejected.
- **No command execution**: nowhere in `builder.py` (or anywhere else) is
  `subprocess`, `os.system`, or `exec`/`eval` called on AI output. The
  builder only ever calls `open(...).write(...)` on paths that passed the
  safety check.
- **Threading**: every network call (`test_connection`, `stream_chat`,
  `simple_chat`, `list_models`, and the whole `/build` pipeline) runs on a
  background `threading.Thread`. Results are marshalled back to the GUI
  through a `queue.Queue` drained by `page._poll_queue()` via
  `self.after(80, ...)` — so the Tk main loop is never blocked and only the
  main thread ever touches widgets.
- **Stop button**: sets a `threading.Event` that `stream_chat()` checks after
  every streamed chunk, closing the stream and returning whatever text was
  received so far.

## 6. Using it

- Type normally to chat with the model.
- `/help` — list commands.
- `/test` — verify provider/key/model (also triggered by **Connect / Test**).
- `/models` — list models the provider exposes.
- `/build <description>` — e.g.
  `/build Create a CustomTkinter inventory manager with SQLite, search, categories, settings, logging, and JSON import/export.`
  Watch the terminal for live progress (plan received → files generated →
  each file written) and the final path under `AI_Projects/`.
- `/clear` — wipes the terminal view only; conversation history stays intact.
- `/new` — wipes both the terminal view and the in-memory conversation
  history (fresh context for the AI).

## 7. Testing performed on this build

- `python3 -m py_compile` on all six module files — clean.
- Full headless instantiation of `AITerminalModule` inside a real `CTk()` root
  window under Xvfb — the config panel, terminal, and input bar all build
  and respond to Clear/New Session correctly.
- **End-to-end plugin-flow simulation**: a fake `plugin_manager` with a real
  `.container` CTkFrame and a `.register()` method was passed through
  `register(plugin_manager)` → menu metadata captured → `meta["open"](manager)`
  called exactly as your app would → confirmed the returned object is an
  `AITerminalModule`, that `page.manager is manager`, and that the frame
  packed itself into the container (`page.winfo_manager() == "pack"`).
- Unit-level checks on `InMemorySecret.masked()`/`repr()`, `is_safe_relative_path()`,
  `resolve_safe_path()` traversal rejection, and `commands.parse()`.

Note: no live request was made against `api.xkiro.com` (no API key was
available in this environment) — `test_connection()`, `stream_chat()`, and
the `/build` pipeline's two API calls are implemented against the standard
OpenAI SDK `chat.completions.create(...)` interface and will work with any
correctly configured OpenAI-compatible endpoint and key.