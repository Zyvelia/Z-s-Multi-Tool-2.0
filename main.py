import os
import sys

# Point Playwright at the bundled browser binaries (dist\ms-playwright\)
# when running as a frozen PyInstaller exe. Must happen BEFORE anything
# imports playwright (directly or indirectly via core.app/modules), or it
# falls back to the default per-user cache path and fails on a machine
# where Playwright was never installed system-wide.
if getattr(sys, "frozen", False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(
        os.path.dirname(sys.executable), "ms-playwright"
    )

from core.settings import SettingsManager
from core.app import App

if __name__ == "__main__":

    settings = SettingsManager()
    app = App(settings)

    app.mainloop()