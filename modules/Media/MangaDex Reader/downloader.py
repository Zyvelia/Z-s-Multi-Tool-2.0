"""
Chapter downloader. Runs on background threads; progress/results are pushed
onto a queue.Queue that the UI polls with `.after()`, matching the rest of
the app's threading pattern.
"""
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import library
from .utils import chapter_folder_name, sanitize, pack_as_cbz, download_bytes

MAX_CONCURRENT_PAGES = 4


class DownloadJob:
    __slots__ = ("chapter", "manga_id", "manga_title", "fmt", "data_saver")

    def __init__(self, chapter, manga_id, manga_title, fmt, data_saver=False):
        self.chapter = chapter          # dict from api.get_chapters()
        self.manga_id = manga_id
        self.manga_title = manga_title
        self.fmt = fmt                  # "images" | "cbz"
        self.data_saver = data_saver


class DownloadManager:
    """
    events put on self.events:
      ("queued", chapter_id, total_in_queue)
      ("start", chapter_id, page_count)
      ("page", chapter_id, done, total)
      ("done", chapter_id, dest_path)
      ("error", chapter_id, message)
    """

    def __init__(self, api_client):
        self.api = api_client
        self.events = queue.Queue()
        self._queue = queue.Queue()
        self._lib = library.Library()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def enqueue(self, job: DownloadJob):
        self._queue.put(job)
        self.events.put(("queued", job.chapter["id"], self._queue.qsize()))

    def _run(self):
        while True:
            job = self._queue.get()
            try:
                self._process(job)
            except Exception as exc:  # keep the worker alive no matter what
                self.events.put(("error", job.chapter["id"], str(exc)))

    def _process(self, job: DownloadJob):
        chapter = job.chapter
        cid = chapter["id"]
        urls = self.api.get_page_urls(cid, data_saver=job.data_saver)
        total = len(urls)
        self.events.put(("start", cid, total))

        manga_dir = os.path.join(library.DOWNLOADS_ROOT, sanitize(job.manga_title))
        ch_name = chapter_folder_name(chapter)
        work_dir = os.path.join(manga_dir, ch_name)
        os.makedirs(work_dir, exist_ok=True)

        page_paths = [None] * total
        done_count = 0
        lock = threading.Lock()

        def fetch(i, url):
            ext = os.path.splitext(url)[1] or ".jpg"
            dest = os.path.join(work_dir, f"{i + 1:03}{ext}")
            download_bytes(self.api.session, url, dest)
            return i, dest

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PAGES) as pool:
            futures = [pool.submit(fetch, i, u) for i, u in enumerate(urls)]
            for fut in as_completed(futures):
                i, dest = fut.result()
                page_paths[i] = dest
                with lock:
                    done_count += 1
                self.events.put(("page", cid, done_count, total))

        if job.fmt == "cbz":
            cbz_path = os.path.join(manga_dir, f"{ch_name}.cbz")
            pack_as_cbz(page_paths, cbz_path)
            # loose images were only scratch space for the archive
            for p in page_paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
            try:
                os.rmdir(work_dir)
            except OSError:
                pass
            final_path = cbz_path
        else:
            final_path = work_dir

        self._lib.record_download(job.manga_id, job.manga_title, chapter, job.fmt, final_path)
        self.events.put(("done", cid, final_path))
