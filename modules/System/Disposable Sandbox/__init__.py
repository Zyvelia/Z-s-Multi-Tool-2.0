def register(plugin_manager):
    plugin_manager.register({
        "name": "Disposable Sandbox",
        "category": "System",
        "desc": "Linked-clone a VMware snapshot, share a read-only drop folder, then delete the clone when it powers off.",
        "icon": "🧊",
        "qt_page": "modules.System.Disposable Sandbox.ui:DisposableSandboxPage",
    })
