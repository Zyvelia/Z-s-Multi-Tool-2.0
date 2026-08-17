from .page import AIChatModule


def open_ai_terminal(manager):

    return AIChatModule(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "AI Chat",
            "category": "AI",
            "desc": (
                "Chat with a hosted AI model or a local one (Ollama/llama.cpp), "
                "run slash-commands, generate multi-file projects with /build, "
                "and save/reuse prompts - all in one tabbed module."
            ),
            "icon": "🤖",
            "open": open_ai_terminal,
        }
    )
