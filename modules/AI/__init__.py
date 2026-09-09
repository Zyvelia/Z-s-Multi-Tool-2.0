def register(plugin_manager):
    plugin_manager.register({
        "name": "AI Chat",
        "category": "AI",
        "desc": (
            "One chat for a hosted API or a local Ollama / llama.cpp model. Agent mode can run app actions "
            "(game servers, notes, messages, stats). /build generates projects."
        ),
        "icon": "🤖",
        "qt_page": "modules.AI.ui:AIChatModule",
    })
