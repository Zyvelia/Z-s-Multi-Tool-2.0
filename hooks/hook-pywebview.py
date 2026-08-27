"""PyInstaller hook — bundle pywebview for Brick Breaker embed."""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("pywebview")
tmp = collect_all("clr_loader")
datas += tmp[0]
binaries += tmp[1]
hiddenimports += tmp[2]

hiddenimports += [
    "pythonnet",
    "clr",
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "webview.guilib",
]
