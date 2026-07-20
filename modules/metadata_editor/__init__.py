# modules/metadata_editor/__init__.py

from .ui import MetadataEditorPage


def _patch_ctkimage_master():
    """
    Workaround for a long-standing customtkinter bug where CTkImage's
    internal PIL.ImageTk.PhotoImage objects can lose their underlying Tcl
    image, raising:

        _tkinter.TclError: image "pyimageN" doesn't exist

    This happens because CTkImage creates PhotoImage() without an explicit
    `master`, so it falls back to tkinter's implicit default-root lookup —
    which can resolve to a different/garbage-collected Tcl interpreter
    context in apps with multiple windows or frequently rebuilt frames
    (e.g. a "Batch Edit..." popout Toplevel, or switching between module
    pages). Pinning an explicit master fixes it reliably.

    See: https://github.com/TomSchimansky/CustomTkinter/discussions/2543
    """
    try:
        import tkinter
        from PIL import ImageTk
        import customtkinter as ctk

        if getattr(ctk.CTkImage, "_pyimage_master_patched", False):
            return  # already patched (e.g. module reloaded)

        def _get_scaled_light_photo_image(self, scaled_size):
            if scaled_size not in self._scaled_light_photo_images:
                self._scaled_light_photo_images[scaled_size] = ImageTk.PhotoImage(
                    self._light_image.resize(scaled_size),
                    master=tkinter._default_root,
                )
            return self._scaled_light_photo_images[scaled_size]

        def _get_scaled_dark_photo_image(self, scaled_size):
            if scaled_size not in self._scaled_dark_photo_images:
                self._scaled_dark_photo_images[scaled_size] = ImageTk.PhotoImage(
                    self._dark_image.resize(scaled_size),
                    master=tkinter._default_root,
                )
            return self._scaled_dark_photo_images[scaled_size]

        ctk.CTkImage._get_scaled_light_photo_image = _get_scaled_light_photo_image
        ctk.CTkImage._get_scaled_dark_photo_image = _get_scaled_dark_photo_image
        ctk.CTkImage._pyimage_master_patched = True
    except Exception:
        # Never let this workaround itself break app startup.
        pass


_patch_ctkimage_master()


def open_metadata_editor(manager):
    # manager.container is your actual CTk root/app
    return MetadataEditorPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Metadata Editor",
        "category": "Utilities",
        "desc": "Edit audio tags, image EXIF fields, and file timestamps",
        "icon": "🏷️",
        "open": open_metadata_editor,
    })
