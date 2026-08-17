# modules/AI/AI Chat/local_model_runner/__init__.py
#
# Lives inside the "AI Chat" package as a tab, not as its own top-level
# tool — see prompt_library/__init__.py for why. Import directly (see
# ui.py's LocalModelRunnerUI) from AI Chat/page.py.

from .ui import LocalModelRunnerUI

__all__ = ["LocalModelRunnerUI"]
