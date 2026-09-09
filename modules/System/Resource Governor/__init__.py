def register(plugin_manager):
    plugin_manager.register({
        "name": "Resource Governor",
        "category": "System",
        "desc": "RAM/CPU budgets so game servers, Ollama, and transcodes do not stack blindly.",
        "icon": "⚖",
        "qt_page": "modules.System.Resource Governor.ui:ResourceGovernorPage",
    })
