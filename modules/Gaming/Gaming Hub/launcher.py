import subprocess
import os


class GameLauncher:

    def launch(
        self,
        game
    ):

        if not game.exe_path:

            raise Exception(
                "No executable found."
            )

        if not os.path.exists(
            game.exe_path
        ):

            raise Exception(
                "Executable missing."
            )

        exe_dir = os.path.dirname(game.exe_path)

        subprocess.Popen(
            [game.exe_path],
            cwd=exe_dir or None
        )