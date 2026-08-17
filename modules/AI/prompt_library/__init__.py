# modules/AI/AI Chat/prompt_library/__init__.py
#
# Lives inside the "AI Chat" package as a tab, not as its own top-level
# tool — plugin_manager stops recursing once it finds AI Chat's own
# __init__.py, so this subfolder is never auto-registered separately.
# Import it directly (see ui.py's PromptLibraryUI) from AI Chat/page.py.

from .ui import PromptLibraryUI

__all__ = ["PromptLibraryUI"]
