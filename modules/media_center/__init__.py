from .ui import MediaCenterPage

# No register() here on purpose — Media Center used to be its own catalog
# tile, but it now lives inside Music Player as a tab (see
# modules/music_player/ui.py) instead of appearing separately. Deleting
# `register()` is enough: core/plugin_manager.py only adds a catalog tile
# for modules that define one (`if hasattr(module, "register")`), so this
# stays a normal importable package without needing to touch the loader
# itself. MediaCenterPage is still imported directly from .ui by
# music_player, so that keeps working unchanged.
