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