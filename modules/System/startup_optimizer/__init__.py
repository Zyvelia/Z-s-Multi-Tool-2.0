def register(plugin_manager):
    plugin_manager.register({
        "name": "Startup Optimizer",
        "category": "System",
        "desc": "Scan startup apps and services, see what's safe to disable, and clean up boot load.",
        "icon": "🧹",
        "qt_page": "modules.System.startup_optimizer.startup_optimizer.ui:StartupOptimizerModule",
    })
