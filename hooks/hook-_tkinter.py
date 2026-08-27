# Override PyInstaller's stock _tkinter hook for Python 3.14+ zipfs Tcl/Tk.
import os
import sys

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from PyInstaller.utils.hooks.tcl_tk import tcltk_info

from tcl_tk_collect import collect_tcl_tk_datas


def hook(hook_api):
    datas = list(tcltk_info.data_files)
    if not datas:
        datas = collect_tcl_tk_datas()
    if datas:
        hook_api.add_datas(datas)
