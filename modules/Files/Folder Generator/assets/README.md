# Assets

Drop your stub executable here as `mGba.exe`.

When "Create executable file" is enabled, the generator copies this file to
each game's folder and renames the copy to the game's real executable name
(e.g. `HTGame.exe`) - so every generated game folder ends up with a working,
double-clickable file instead of an empty placeholder.

If `mGba.exe` isn't present here (or wherever you point the "Stub Executable"
field in the UI to), the generator falls back to creating an empty
placeholder file, exactly like before, and lets you know in the status log.
