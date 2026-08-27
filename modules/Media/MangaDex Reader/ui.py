import threading

import customtkinter as ctk

from core import theme
from .api import MangaDexClient, DEFAULT_RATINGS, ALL_RATINGS
from .downloader import DownloadManager, DownloadJob
from .library import Library, THUMB_CACHE_DIR
from .utils import ThumbCache, list_chapter_images, extract_cbz
from .reader import ReaderFrame


class MangaDexPage(ctk.CTkFrame):
    def __init__(self, parent, manager, **kwargs):
        super().__init__(parent, fg_color=theme.BG, **kwargs)
        self.manager = manager
        self.api = MangaDexClient()
        self.downloads = DownloadManager(self.api)
        self.library = Library()
        self.thumbs = ThumbCache(THUMB_CACHE_DIR)

        self._search_results = {}     # manga_id -> manga dict
        self._browse_results = {}     # manga_id -> manga dict
        self._browse_offset = 0
        self._browse_total = 0
        self._current_manga = None
        self._chapters = []
        self._chapter_checks = {}     # chapter_id -> CTkCheckBox var
        self._show_explicit = ctk.BooleanVar(value=False)
        self._closed = False

        self._build_ui()
        self.bind("<Destroy>", self._on_page_destroy)
        self.after(150, self._poll_download_events)
        self.after(200, lambda: self._do_browse(reset=True))

    # ---------------------------------------------------------------- UI

    def _build_ui(self):
        self.tabs = ctk.CTkTabview(self, fg_color=theme.PANEL)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.tabs.add("Browse")
        self.tabs.add("Search")
        self.tabs.add("Chapters")
        self.tabs.add("Reader")
        self.tabs.add("Downloads")

        self._build_browse_tab(self.tabs.tab("Browse"))
        self._build_search_tab(self.tabs.tab("Search"))
        self._build_chapters_tab(self.tabs.tab("Chapters"))
        self._build_reader_tab(self.tabs.tab("Reader"))
        self._build_downloads_tab(self.tabs.tab("Downloads"))

        ctk.CTkLabel(
            self, text="Manga data and images courtesy of MangaDex (api.mangadex.org)",
            text_color=theme.FAINT, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=14, pady=(4, 8))

    def _build_browse_tab(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(bar, text="Sort by:", text_color=theme.TEXT).pack(side="left", padx=(0, 6))

        self.browse_sort_menu = ctk.CTkOptionMenu(
            bar, values=list(MangaDexClient.BROWSE_SORTS.keys()),
            command=lambda choice: self._do_browse(reset=True),
        )
        self.browse_sort_menu.set("Popular")
        self.browse_sort_menu.pack(side="left")

        ctk.CTkButton(bar, text="Refresh", width=90, command=lambda: self._do_browse(reset=True)).pack(
            side="left", padx=8
        )

        ctk.CTkCheckBox(
            bar, text="Show explicit (18+)", variable=self._show_explicit,
            command=lambda: self._do_browse(reset=True),
        ).pack(side="left", padx=(12, 0))

        self.browse_status = ctk.CTkLabel(tab, text="", text_color=theme.FAINT)
        self.browse_status.pack(anchor="w", padx=10)

        self.browse_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.browse_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        self.browse_load_more_btn = ctk.CTkButton(
            tab, text="Load more", command=lambda: self._do_browse(reset=False),
        )
        self.browse_load_more_btn.pack(pady=(0, 10))

    def _build_search_tab(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=10)

        self.search_entry = ctk.CTkEntry(bar, placeholder_text="Search MangaDex...", fg_color=theme.PANEL_2)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        ctk.CTkButton(bar, text="Search", width=90, command=self._do_search).pack(side="left")

        ctk.CTkCheckBox(
            bar, text="Show explicit (18+)", variable=self._show_explicit,
        ).pack(side="left", padx=(12, 0))

        self.search_status = ctk.CTkLabel(tab, text="", text_color=theme.FAINT)
        self.search_status.pack(anchor="w", padx=10)

        self.results_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.results_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_chapters_tab(self, tab):
        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=10)

        self.manga_title_label = ctk.CTkLabel(
            header, text="Select a manga from Search", font=ctk.CTkFont(size=18, weight="bold"),
            text_color=theme.TEXT,
        )
        self.manga_title_label.pack(side="left")

        self.lang_menu = ctk.CTkOptionMenu(header, values=["All languages"], command=self._on_lang_change)
        self.lang_menu.pack(side="right")

        self.chapters_status = ctk.CTkLabel(tab, text="", text_color=theme.FAINT)
        self.chapters_status.pack(anchor="w", padx=10)

        fmt_bar = ctk.CTkFrame(tab, fg_color="transparent")
        fmt_bar.pack(fill="x", padx=10)
        self.download_fmt = ctk.CTkOptionMenu(fmt_bar, values=["Folder of images", "CBZ archive"])
        self.download_fmt.pack(side="left")
        ctk.CTkButton(fmt_bar, text="Download Selected", command=self._download_selected).pack(side="left", padx=8)
        ctk.CTkButton(fmt_bar, text="Select All", width=90, command=self._select_all_chapters).pack(side="left")
        ctk.CTkButton(fmt_bar, text="Select None", width=90, command=self._select_no_chapters).pack(side="left", padx=8)

        self.chapters_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.chapters_scroll.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_reader_tab(self, tab):
        self.reader = ReaderFrame(tab, on_page_change=self._on_reader_page_change)
        self.reader.pack(fill="both", expand=True)

    def _build_downloads_tab(self, tab):
        self.downloads_status = ctk.CTkLabel(tab, text="No active downloads.", text_color=theme.FAINT)
        self.downloads_status.pack(anchor="w", padx=10, pady=(10, 0))

        self.downloads_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.downloads_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        self._download_rows = {}   # chapter_id -> (frame, progress_bar, label)

        self._refresh_history()

    def _refresh_history(self):
        for row in self.downloads_scroll.winfo_children():
            row.destroy()
        for manga_id, chapter_id, manga_title, ch_label, lang, fmt, path, when in self.library.list_downloads():
            row = ctk.CTkFrame(self.downloads_scroll, fg_color=theme.PANEL_2)
            row.pack(fill="x", pady=3)

            header = ctk.CTkFrame(row, fg_color="transparent")
            header.pack(fill="x", padx=8, pady=(6, 2))
            ctk.CTkLabel(
                header, text=f"{manga_title} — Ch. {ch_label} [{lang or '?'}] ({fmt}) · {when}",
                text_color=theme.TEXT, anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                header, text="Read", width=70,
                command=lambda p=path, f=fmt, mt=manga_title, cl=ch_label, mid=manga_id, cid=chapter_id:
                    self._read_local(p, f, mt, cl, mid, cid),
            ).pack(side="right")

            bar = ctk.CTkProgressBar(row)
            bar.set(1.0)
            bar.pack(fill="x", padx=8, pady=(0, 8))

    # ------------------------------------------------------------ search

    def _do_search(self):
        query = self.search_entry.get().strip()
        if not query:
            return
        self.search_status.configure(text="Searching...")
        for w in self.results_scroll.winfo_children():
            w.destroy()
        threading.Thread(target=self._search_worker, args=(query,), daemon=True).start()

    def _search_worker(self, query):
        ratings = ALL_RATINGS if self._show_explicit.get() else DEFAULT_RATINGS
        try:
            results = self.api.search_manga(query, content_ratings=ratings)
        except Exception as exc:
            self.after(0, lambda: self.search_status.configure(text=f"Search failed: {exc}"))
            return
        self.after(0, lambda: self._render_results(results))

    def _render_results(self, results):
        self.search_status.configure(text=f"{len(results)} result(s)")
        for manga in results:
            self._search_results[manga["id"]] = manga
            self._add_result_row(manga, self.results_scroll)

    # ------------------------------------------------------------ browse

    def _do_browse(self, reset=True):
        sort = self.browse_sort_menu.get()
        if reset:
            self._browse_offset = 0
            self._browse_total = 0
            for w in self.browse_scroll.winfo_children():
                w.destroy()
            self.browse_status.configure(text="Loading...")
        else:
            self.browse_status.configure(text=self.browse_status.cget("text") + " · loading more...")
        self.browse_load_more_btn.configure(state="disabled")
        threading.Thread(
            target=self._browse_worker, args=(sort, self._browse_offset), daemon=True,
        ).start()

    def _browse_worker(self, sort, offset):
        ratings = ALL_RATINGS if self._show_explicit.get() else DEFAULT_RATINGS
        try:
            results, total = self.api.browse_manga(sort=sort, offset=offset, content_ratings=ratings)
        except Exception as exc:
            self.after(0, lambda: self.browse_status.configure(text=f"Browse failed: {exc}"))
            self.after(0, lambda: self.browse_load_more_btn.configure(state="normal"))
            return
        self.after(0, lambda: self._render_browse(results, total))

    def _render_browse(self, results, total):
        self._browse_total = total
        for manga in results:
            self._browse_results[manga["id"]] = manga
            self._add_result_row(manga, self.browse_scroll)
        self._browse_offset += len(results)
        self.browse_status.configure(text=f"Showing {self._browse_offset} of {total}")
        more_available = self._browse_offset < total and len(results) > 0
        self.browse_load_more_btn.configure(state="normal" if more_available else "disabled")

    def _add_result_row(self, manga, parent_scroll):
        row = ctk.CTkFrame(parent_scroll, fg_color=theme.PANEL_2)
        row.pack(fill="x", pady=4)

        thumb_label = ctk.CTkLabel(row, text="", width=60)
        thumb_label.pack(side="left", padx=8, pady=8)
        threading.Thread(target=self._load_thumb, args=(manga, thumb_label), daemon=True).start()

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkLabel(
            info, text=manga["title"], font=ctk.CTkFont(size=14, weight="bold"),
            text_color=theme.TEXT, anchor="w",
        ).pack(fill="x")
        subtitle = f"{manga['status'].title()} · {manga.get('year') or '?'} · {', '.join(manga['tags'][:4])}"
        ctk.CTkLabel(info, text=subtitle, text_color=theme.FAINT, anchor="w").pack(fill="x")

        ctk.CTkButton(
            row, text="Open", width=80, command=lambda m=manga: self._open_manga(m),
        ).pack(side="right", padx=8)

    def _load_thumb(self, manga, label_widget):
        path = self.thumbs.get_or_fetch(self.api.session, manga["id"], manga.get("cover_thumb_url"))
        if not path:
            return
        try:
            from PIL import Image
            img = Image.open(path)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(60, 84))
            self.after(0, lambda: label_widget.configure(image=ctk_img))
            label_widget.image = ctk_img
        except Exception:
            pass

    # ---------------------------------------------------------- chapters

    def _open_manga(self, manga):
        self._current_manga = manga
        self.manga_title_label.configure(text=manga["title"])
        self.tabs.set("Chapters")

        langs = ["All languages"] + sorted(manga.get("available_languages") or [])
        self.lang_menu.configure(values=langs)
        self.lang_menu.set("All languages")
        self._load_chapters(None)

    def _on_lang_change(self, choice):
        langs = None if choice == "All languages" else [choice]
        self._load_chapters(langs)

    def _load_chapters(self, languages):
        for w in self.chapters_scroll.winfo_children():
            w.destroy()
        self._chapter_checks = {}
        manga = self._current_manga
        if not manga:
            return
        self.chapters_status.configure(text="Loading chapters...")
        threading.Thread(target=self._chapters_worker, args=(manga["id"], languages), daemon=True).start()

    def _chapters_worker(self, manga_id, languages):
        try:
            chapters = self.api.get_chapters(manga_id, languages=languages)
        except Exception as exc:
            self.after(0, lambda: self.chapters_status.configure(text=f"Failed to load chapters: {exc}"))
            return
        self.after(0, lambda: self._render_chapters(chapters))

    def _render_chapters(self, chapters):
        self._chapters = chapters
        if not chapters:
            self.chapters_status.configure(text="No chapters found for this language.")
            return
        self.chapters_status.configure(text=f"{len(chapters)} chapter(s)")
        for chapter in chapters:
            self._add_chapter_row(chapter)

    def _add_chapter_row(self, chapter):
        row = ctk.CTkFrame(self.chapters_scroll, fg_color=theme.PANEL_2)
        row.pack(fill="x", pady=2)

        var = ctk.BooleanVar(value=False)
        self._chapter_checks[chapter["id"]] = var
        ctk.CTkCheckBox(row, text="", variable=var, width=20).pack(side="left", padx=8)

        label = f"Ch. {chapter['chapter'] or '?'}"
        if chapter.get("volume"):
            label = f"Vol. {chapter['volume']} · {label}"
        if chapter.get("title"):
            label += f" — {chapter['title']}"
        label += f"  [{chapter['language']}]  ({chapter['group']})"

        already = self.library.is_downloaded(chapter["id"])
        color = theme.ACCENT if already else theme.TEXT
        ctk.CTkLabel(row, text=label, text_color=color, anchor="w").pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            row, text="Read", width=70, command=lambda c=chapter: self._read_chapter(c),
        ).pack(side="right", padx=8)

    def _select_all_chapters(self):
        for var in self._chapter_checks.values():
            var.set(True)

    def _select_no_chapters(self):
        for var in self._chapter_checks.values():
            var.set(False)

    # --------------------------------------------------------- downloads

    def _download_selected(self):
        if not self._current_manga:
            return
        fmt = "cbz" if self.download_fmt.get().startswith("CBZ") else "images"
        selected = [c for c in self._chapters if self._chapter_checks.get(c["id"], ctk.BooleanVar()).get()]
        for chapter in selected:
            job = DownloadJob(chapter, self._current_manga["id"], self._current_manga["title"], fmt)
            self.downloads.enqueue(job)
        self.tabs.set("Downloads")

    def _on_page_destroy(self, event=None):
        if event is not None and event.widget is not self:
            return
        self._closed = True

    def _poll_download_events(self):
        if self._closed:
            return
        import queue as _q
        try:
            while True:
                event = self.downloads.events.get_nowait()
                kind, chapter_id, *rest = event
                payload = rest[0] if len(rest) == 1 else tuple(rest)
                self._handle_download_event(kind, chapter_id, payload)
        except _q.Empty:
            pass
        if not self._closed:
            self.after(150, self._poll_download_events)

    def _handle_download_event(self, kind, chapter_id, payload):
        try:
            self._handle_download_event_inner(kind, chapter_id, payload)
        except Exception:
            # A row's widgets can already be gone (e.g. page reopened after
            # being closed); an event for it is stale, not a reason to crash
            # the whole polling loop.
            pass

    def _handle_download_event_inner(self, kind, chapter_id, payload):
        if kind == "queued":
            self.downloads_status.configure(text=f"{payload} chapter(s) queued")
            row = ctk.CTkFrame(self.downloads_scroll, fg_color=theme.PANEL_2)
            row.pack(fill="x", pady=3)
            label = ctk.CTkLabel(row, text=f"Chapter {chapter_id[:8]} — queued", text_color=theme.TEXT, anchor="w")
            label.pack(fill="x", padx=8, pady=(6, 2))
            bar = ctk.CTkProgressBar(row)
            bar.set(0)
            bar.pack(fill="x", padx=8, pady=(0, 8))
            self._download_rows[chapter_id] = (row, bar, label)
        elif kind == "start":
            row = self._download_rows.get(chapter_id)
            if row:
                row[2].configure(text=f"Chapter {chapter_id[:8]} — downloading 0/{payload}")
        elif kind == "page":
            row = self._download_rows.get(chapter_id)
            done, total = payload if isinstance(payload, tuple) else (payload, None)
            if row and total:
                row[2].configure(text=f"Chapter {chapter_id[:8]} — downloading {done}/{total}")
                row[1].set(done / total)
        elif kind == "done":
            row = self._download_rows.get(chapter_id)
            if row:
                row[2].configure(text=f"Done — saved to {payload}")
                row[1].set(1.0)
            self._refresh_history()
        elif kind == "error":
            row = self._download_rows.get(chapter_id)
            if row:
                row[2].configure(text=f"Error: {payload}", text_color="#ff6b6b")

    # ------------------------------------------------------------ reader

    def _read_chapter(self, chapter):
        self._reading_chapter = chapter
        self.reader.set_title(f"{(self._current_manga or {}).get('title', 'Manga')} — Ch. {chapter.get('chapter') or '?'}")
        self.reader.set_status(f"Loading Ch. {chapter.get('chapter') or '?'}...")
        self.tabs.set("Reader")
        threading.Thread(target=self._read_chapter_worker, args=(chapter,), daemon=True).start()

    def _read_chapter_worker(self, chapter):
        try:
            urls = self.api.get_page_urls(chapter["id"])
        except Exception as exc:
            self.after(0, lambda: self.reader.set_status(f"Could not open chapter: {exc}"))
            return
        self.after(0, lambda: self.reader.load_remote(urls, self.api.session))

    def _read_local(self, path, fmt, manga_title, chapter_label, manga_id, chapter_id):
        # Opening a previously downloaded chapter straight from disk, no
        # network needed. cbz archives get unzipped to a temp dir first.
        self._current_manga = {"id": manga_id, "title": manga_title}
        self._reading_chapter = {"id": chapter_id, "chapter": chapter_label}
        self.reader.set_title(f"{manga_title} — Ch. {chapter_label}")
        self.reader.set_status("Opening downloaded chapter...")
        self.tabs.set("Reader")
        threading.Thread(target=self._read_local_worker, args=(path, fmt), daemon=True).start()

    def _read_local_worker(self, path, fmt):
        try:
            images = extract_cbz(path) if fmt == "cbz" else list_chapter_images(path)
        except Exception as exc:
            self.after(0, lambda: self.reader.set_status(f"Could not open chapter: {exc}"))
            return
        if not images:
            self.after(0, lambda: self.reader.set_status("No pages found for this download."))
            return
        self.after(0, lambda: self.reader.load_local(images))

    def _on_reader_page_change(self, index):
        if self._current_manga and getattr(self, "_reading_chapter", None):
            self.library.save_progress(
                self._current_manga["id"], self._current_manga["title"],
                self._reading_chapter["id"],
                f"Ch. {self._reading_chapter.get('chapter') or '?'}",
                index,
            )
