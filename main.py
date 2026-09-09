from core.win_subprocess import install as install_hidden_subprocess

install_hidden_subprocess()

from core.settings import SettingsManager
from core.qt.app import run

if __name__ == "__main__":
    run(SettingsManager())
