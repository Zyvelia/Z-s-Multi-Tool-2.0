"""
OCR, translation, and read-aloud for a manga page.

OCR: Tesseract if installed (best with jpn / jpn_vert for raw scans),
then Windows.Media.Ocr if the WinRT packages are present.
Speech: Windows SAPI (no extra install).
Translate: Google's public gtx endpoint via requests (no API key).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

import requests

OCR_LANGS = {
    "Japanese (vertical)": "jpn_vert+jpn",
    "Japanese": "jpn",
    "Chinese Simplified": "chi_sim",
    "Chinese Traditional": "chi_tra",
    "Korean": "kor",
    "English": "eng",
}

TRANSLATE_LANGS = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Portuguese": "pt",
    "Italian": "it",
    "Russian": "ru",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese (Simplified)": "zh-CN",
    "Chinese (Traditional)": "zh-TW",
    "Arabic": "ar",
    "Hindi": "hi",
    "Thai": "th",
    "Vietnamese": "vi",
}

_WIN_OCR_LANG = {
    "Japanese (vertical)": "ja",
    "Japanese": "ja",
    "Chinese Simplified": "zh-Hans",
    "Chinese Traditional": "zh-Hant",
    "Korean": "ko",
    "English": "en",
}

_TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


class AssistError(Exception):
    pass


def find_tesseract() -> Path | None:
    which = shutil.which("tesseract")
    if which:
        return Path(which)
    for path in _TESSERACT_CANDIDATES:
        if path.is_file():
            return path
    return None


def ocr_status() -> str:
    tess = find_tesseract()
    if tess:
        return f"Tesseract · {tess}"
    try:
        import winrt.windows.media.ocr  # noqa: F401
        return "Windows OCR"
    except Exception:
        return (
            "No OCR engine. Install Tesseract with Japanese data for raw manga: "
            "winget install UB-Mannheim.TesseractOCR"
        )


def ocr_page(image_path: str, ocr_label: str = "Japanese (vertical)") -> str:
    if not image_path or not os.path.isfile(image_path):
        raise AssistError("No page image is loaded yet.")
    tess = find_tesseract()
    if tess:
        return _ocr_tesseract(tess, image_path, OCR_LANGS.get(ocr_label, "jpn_vert+jpn"))
    text = _ocr_windows(image_path, _WIN_OCR_LANG.get(ocr_label, "ja"))
    if text is not None:
        return text
    raise AssistError(
        "Need an OCR engine for the page. Install Tesseract "
        "(winget install UB-Mannheim.TesseractOCR) and tick Japanese / jpn_vert "
        "in the installer so untranslated manga can be read."
    )


def _ocr_tesseract(exe: Path, image_path: str, langs: str) -> str:
    try:
        proc = subprocess.run(
            [str(exe), image_path, "stdout", "-l", langs, "--psm", "5" if "jpn_vert" in langs else "6"],
            capture_output=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as e:
        raise AssistError("Tesseract timed out on this page.") from e
    except OSError as e:
        raise AssistError(str(e)) from e
    text = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 and not text:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        if "Failed loading language" in err or "Failed to load" in err:
            # Vertical pack missing — retry with jpn or eng.
            fallback = "jpn" if "jpn" in langs else "eng"
            proc = subprocess.run(
                [str(exe), image_path, "stdout", "-l", fallback, "--psm", "6"],
                capture_output=True,
                timeout=90,
            )
            text = proc.stdout.decode("utf-8", errors="replace").strip()
            if text:
                return text
            raise AssistError(
                f"Tesseract is missing language data for {langs}. "
                "Re-run the Tesseract installer and add Japanese (jpn / jpn_vert)."
            )
        raise AssistError(err or "Tesseract failed.")
    if not text:
        raise AssistError("No text found on this page.")
    return text


def _ocr_windows(image_path: str, lang: str) -> str | None:
    try:
        import asyncio
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import StorageFile, FileAccessMode
    except Exception:
        return None

    async def _run() -> str:
        if not OcrEngine.is_language_supported(Language(lang)):
            engine = OcrEngine.try_create_from_user_profile_languages()
        else:
            engine = OcrEngine.try_create_from_language(Language(lang))
        if engine is None:
            raise AssistError(
                f"Windows OCR has no pack for {lang}. "
                "Settings → Time & language → Language → add Japanese (OCR)."
            )
        file = await StorageFile.get_file_from_path_async(os.path.abspath(image_path))
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        return (result.text or "").strip()

    try:
        text = asyncio.run(_run())
    except AssistError:
        raise
    except Exception:
        return None
    if not text:
        raise AssistError("Windows OCR found no text on this page.")
    return text


def translate_text(text: str, dest_label: str = "English") -> str:
    dest = TRANSLATE_LANGS.get(dest_label, "en")
    chunks = _chunks(text, 4000)
    parts = []
    for chunk in chunks:
        parts.append(_translate_chunk(chunk, dest))
    out = "\n".join(parts).strip()
    if not out:
        raise AssistError("Translation came back empty.")
    return out


def _chunks(text: str, size: int) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text]
    out = []
    start = 0
    while start < len(text):
        out.append(text[start:start + size])
        start += size
    return out


def _translate_chunk(text: str, dest: str) -> str:
    try:
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": dest, "dt": "t", "q": text},
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 ZsMultiTool"},
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(part[0] for part in (data[0] or []) if part and part[0])
    except Exception as e:
        raise AssistError(f"Translation failed: {e}") from e


_voice = None
_voice_lock = threading.Lock()


def _sapi():
    global _voice
    with _voice_lock:
        if _voice is None:
            import win32com.client
            _voice = win32com.client.Dispatch("SAPI.SpVoice")
        return _voice


def speak(text: str) -> None:
    text = (text or "").strip()
    if not text:
        raise AssistError("Nothing to read.")
    voice = _sapi()
    # 2 = purge current, 1 = async
    voice.Speak("", 2)
    voice.Speak(text, 1)


def stop_speech() -> None:
    try:
        _sapi().Speak("", 2)
    except Exception:
        pass
