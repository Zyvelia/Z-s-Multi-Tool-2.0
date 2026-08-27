import os
import queue
import tempfile
import threading

import customtkinter as ctk
from PIL import Image

from core import theme
from .utils import download_bytes


class ReaderFrame(ctk.CTkFrame):
    """
    Displays one page at a time from either local file paths (already
    downloaded chapter) or remote URLs (streamed on the fly + cached to a
    temp dir for smooth prev/next).
    """

    def __init__(self, parent, on_page_change=None, **kwargs):
        super().__init__(parent, fg_color=theme.BG, **kwargs)
        self.on_page_change = on_page_change
        self._session = None
        self._pages = []          # list of local paths OR urls
        self._is_remote = False
        self._cache_dir = None
        self._current = 0
        self._ctk_image = None
        # customtkinter/Tk will raise a TclError if the CTkImage backing the
        # canvas's current -image is garbage-collected before the widget is
        # reconfigured to stop using it. Rather than ever switching to
        # image=None, we always switch to this tiny transparent image (which
        # this frame keeps a permanent reference to), so the widget always
        # has a live image to point at.
        blank = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        self._blank_image = ctk.CTkImage(light_image=blank, dark_image=blank, size=(1, 1))
        self._load_queue = queue.Queue()
        self._closed = False
        self._build_ui()
        self.after(100, self._poll_loads)

    def _build_ui(self):
        self.title_label = ctk.CTkLabel(
            self, text="No chapter loaded — pick one from Chapters or Downloads",
            text_color=theme.FAINT, anchor="w",
        )
        self.title_label.pack(fill="x", padx=8, pady=(6, 0))

        top = ctk.CTkFrame(self, fg_color=theme.PANEL, height=40)
        top.pack(fill="x", side="top", pady=(6, 0))
        top.pack_propagate(False)

        self.prev_btn = ctk.CTkButton(top, text="◀ Prev", width=90, command=self.prev_page)
        self.prev_btn.pack(side="left", padx=8, pady=4)

        self.page_label = ctk.CTkLabel(top, text="Page 0 / 0", text_color=theme.TEXT)
        self.page_label.pack(side="left", expand=True)

        self.next_btn = ctk.CTkButton(top, text="Next ▶", width=90, command=self.next_page)
        self.next_btn.pack(side="right", padx=8, pady=4)

        self.canvas = ctk.CTkLabel(self, text="", fg_color=theme.BG)
        self.canvas.pack(fill="both", expand=True)

        self._bind_arrow_keys()
        self.bind("<Destroy>", self._on_destroy)

    def _bind_arrow_keys(self):
        # bind_all() is disallowed by the host app (it would register the
        # handler on every widget in the whole application, so arrow-key
        # navigation from this module could keep firing - or clash with
        # another module's own bindings - even after this page is closed).
        # Binding to just this module's own top-level window scopes the
        # shortcut to this window only, and we restore whatever was bound
        # there before us when we're torn down.
        self._toplevel = self.winfo_toplevel()
        self._prev_left_bind = self._toplevel.bind("<Left>")
        self._prev_right_bind = self._toplevel.bind("<Right>")
        self._toplevel.bind("<Left>", self._on_left)
        self._toplevel.bind("<Right>", self._on_right)

    def _on_left(self, event=None):
        self.prev_page()

    def _on_right(self, event=None):
        self.next_page()

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self:
            return
        self._closed = True
        toplevel = getattr(self, "_toplevel", None)
        if toplevel is None:
            return
        try:
            if self._prev_left_bind:
                toplevel.bind("<Left>", self._prev_left_bind)
            else:
                toplevel.unbind("<Left>")
            if self._prev_right_bind:
                toplevel.bind("<Right>", self._prev_right_bind)
            else:
                toplevel.unbind("<Right>")
        except Exception:
            pass

    def _clear_canvas_image(self, text):
        # Keep a live reference to *some* image at all times; see the note
        # in __init__ about why we never hand Tk image=None directly.
        self._ctk_image = self._blank_image
        self.canvas.configure(image=self._blank_image, text=text)

    def set_status(self, text):
        self._clear_canvas_image(text)

    def set_title(self, text):
        self.title_label.configure(text=text)

    def load_local(self, image_paths, start_index=0):
        self._is_remote = False
        self._pages = list(image_paths)
        self._current = max(0, min(start_index, len(self._pages) - 1))
        self._show_current()

    def load_remote(self, page_urls, session, start_index=0):
        self._is_remote = True
        self._session = session
        self._pages = list(page_urls)
        self._cache_dir = tempfile.mkdtemp(prefix="mangadex_reader_")
        self._current = max(0, min(start_index, len(self._pages) - 1))
        self._show_current()

    def prev_page(self):
        if self._current > 0:
            self._current -= 1
            self._show_current()

    def next_page(self):
        if self._current < len(self._pages) - 1:
            self._current += 1
            self._show_current()

    def _show_current(self):
        total = len(self._pages)
        self.page_label.configure(text=f"Page {self._current + 1} / {total}")
        if total == 0:
            return
        if self.on_page_change:
            self.on_page_change(self._current)

        if self._is_remote:
            threading.Thread(target=self._resolve_remote_page, args=(self._current,), daemon=True).start()
        else:
            self._render_path(self._pages[self._current])

    def _resolve_remote_page(self, index):
        url = self._pages[index]
        cache_path = os.path.join(self._cache_dir, f"{index:03}{os.path.splitext(url)[1] or '.jpg'}")
        if not os.path.exists(cache_path):
            try:
                download_bytes(self._session, url, cache_path)
            except Exception as exc:
                self._load_queue.put(("error", index, str(exc)))
                return
        self._load_queue.put(("ready", index, cache_path))

    def _poll_loads(self):
        if self._closed:
            return
        try:
            while True:
                kind, index, payload = self._load_queue.get_nowait()
                if kind == "ready" and index == self._current:
                    self._render_path(payload)
                elif kind == "error" and index == self._current:
                    self._clear_canvas_image(f"Failed to load page: {payload}")
        except queue.Empty:
            pass
        except Exception:
            pass
        if not self._closed:
            self.after(100, self._poll_loads)

    def _render_path(self, path):
        try:
            img = Image.open(path)
            max_w = max(self.winfo_width() - 40, 400)
            max_h = max(self.winfo_height() - 80, 400)
            ratio = min(max_w / img.width, max_h / img.height, 1.0) or 1.0
            size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            self._ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            self.canvas.configure(image=self._ctk_image, text="")
        except Exception as exc:
            self._clear_canvas_image(f"Could not render page: {exc}")
