# modules/metadata_editor/ui.py
#
# Top-level page for the Metadata Editor. Just a tabview shell — each tab
# is its own self-contained CTkFrame in this package (audio_tab.py,
# image_tab.py, timestamp_tab.py), same split as music_player's
# ui.py / remote_access_tab.py.

import customtkinter as ctk

from core import theme
from .audio_tab import AudioTagsTab
from .image_tab import ImageExifTab
from .timestamp_tab import FileTimestampsTab

BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT


class MetadataEditorPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager

        self.tabview = ctk.CTkTabview(
            self,
            fg_color=PANEL,
            segmented_button_fg_color=PANEL_2,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT,
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=12)

        tab_audio = self.tabview.add("Audio Tags")
        tab_image = self.tabview.add("Image EXIF")
        tab_files = self.tabview.add("File Timestamps")

        AudioTagsTab(tab_audio, manager).pack(fill="both", expand=True)
        ImageExifTab(tab_image, manager).pack(fill="both", expand=True)
        FileTimestampsTab(tab_files, manager).pack(fill="both", expand=True)
