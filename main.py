from core.settings import SettingsManager
from core.app import App

if __name__ == "__main__":

    settings = SettingsManager()
    app = App(settings)

    app.mainloop()