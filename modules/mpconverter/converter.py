# modules/mp4_to_gif/converter.py
#
# All ffmpeg interaction lives here, kept separate from ui.py so the
# subprocess/parsing logic can be tested or reused without CTk.
#
# Conversion is done as ffmpeg's standard two-pass palette method
# (palettegen -> paletteuse) rather than a single-pass -vf, since a
# single pass produces washed-out, banded GIFs. Two passes cost a
# little more time but the quality difference is the whole reason to
# offer a GUI tool instead of "just run ffmpeg" in the first place.

import json
import os
import re
import shutil
import subprocess
import tempfile

# Hide the console window ffmpeg would otherwise flash open on Windows.
_STARTUPINFO = None
if os.name == "nt":
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW

_TIME_RE = re.compile(r"out_time_ms=(\d+)")


class ConversionError(Exception):
    pass


class ConversionCancelled(Exception):
    pass


def _find_exe(name: str):
    """
    Locate ffmpeg/ffprobe. Checks a local bin/ folder next to this module
    first (same convention as yt_downloader's _find_ffmpeg), then falls
    back to system PATH.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "bin", f"{name}.exe"),
        os.path.join(os.path.dirname(here), "bin", f"{name}.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    found = shutil.which(name)
    if found:
        return found

    return None


def find_ffmpeg():
    return _find_exe("ffmpeg")


def find_ffprobe():
    return _find_exe("ffprobe")


def probe(path: str) -> dict:
    """
    Returns {"duration": float seconds or None, "width": int or None,
    "height": int or None}. Falls back to all-None fields if ffprobe
    isn't available — the UI just won't be able to show a trim range
    or a resolution-aware default.
    """
    info = {"duration": None, "width": None, "height": None}

    ffprobe = find_ffprobe()
    if not ffprobe:
        return info

    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration:stream=width,height",
                "-select_streams", "v:0",
                "-of", "json",
                path,
            ],
            capture_output=True, text=True, timeout=15,
            startupinfo=_STARTUPINFO,
        )
        data = json.loads(result.stdout or "{}")

        fmt = data.get("format", {})
        if "duration" in fmt:
            info["duration"] = float(fmt["duration"])

        streams = data.get("streams", [])
        if streams:
            info["width"] = streams[0].get("width")
            info["height"] = streams[0].get("height")

    except Exception as e:
        print(f"[mp4_to_gif] probe failed: {e}")

    return info


def _run_with_progress(cmd, total_seconds, on_progress, stage_fraction, cancel_event):
    """
    Runs an ffmpeg command with -progress pipe:1 and calls
    on_progress(overall_fraction) as it reports out_time_ms.
    stage_fraction is (start, end) — the slice of the overall 0..1
    progress bar this particular ffmpeg pass is allowed to fill.
    """
    start_frac, end_frac = stage_fraction

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        startupinfo=_STARTUPINFO,
    )

    stderr_tail = []

    try:
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                raise ConversionCancelled()

            stderr_tail.append(line)
            if len(stderr_tail) > 40:
                stderr_tail.pop(0)

            match = _TIME_RE.search(line)
            if match and total_seconds:
                done_seconds = int(match.group(1)) / 1_000_000
                local_frac = min(done_seconds / total_seconds, 1.0)
                overall = start_frac + (end_frac - start_frac) * local_frac
                if on_progress:
                    on_progress(overall)
    finally:
        proc.wait()

    if proc.returncode != 0 and not (cancel_event and cancel_event.is_set()):
        raise ConversionError("".join(stderr_tail[-15:]) or "ffmpeg exited with an error")


def convert(
    input_path: str,
    output_path: str,
    fps: int = 15,
    width: int = 480,
    start: float = None,
    end: float = None,
    loop: bool = True,
    dither: str = "bayer",
    on_progress=None,
    cancel_event=None,
):
    """
    Converts input_path to a GIF at output_path using the palettegen /
    paletteuse two-pass method. Raises ConversionError or
    ConversionCancelled on failure. on_progress, if given, is called
    with a float 0..1 as the conversion advances across BOTH passes.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ConversionError(
            "ffmpeg.exe not found. Place it in a 'bin' folder next to this "
            "module, next to the app, or make sure it's on your system PATH."
        )

    if not os.path.isfile(input_path):
        raise ConversionError(f"Input file not found: {input_path}")

    duration = None
    if start is not None and end is not None:
        duration = max(end - start, 0.01)

    scale_filter = f"scale={width}:-2:flags=lanczos" if width else "scale=iw:-2:flags=lanczos"

    trim_args = []
    if start is not None:
        trim_args += ["-ss", str(start)]
    if duration is not None:
        trim_args += ["-t", str(duration)]

    with tempfile.TemporaryDirectory(prefix="mp4togif_") as tmp_dir:
        # ASCII-only temp path, same rationale as the soundboard's ffmpeg
        # calls — Windows temp paths with unusual characters have tripped
        # ffmpeg up before.
        palette_path = os.path.join(tmp_dir, "palette.png")

        palette_cmd = [
            ffmpeg, "-y", "-progress", "pipe:1", "-nostats",
            *trim_args,
            "-i", input_path,
            "-vf", f"fps={fps},{scale_filter},palettegen=stats_mode=diff",
            palette_path,
        ]
        _run_with_progress(palette_cmd, duration, on_progress, (0.0, 0.45), cancel_event)

        gif_cmd = [
            ffmpeg, "-y", "-progress", "pipe:1", "-nostats",
            *trim_args,
            "-i", input_path,
            "-i", palette_path,
            "-lavfi",
            f"fps={fps},{scale_filter}[x];[x][1:v]paletteuse=dither={dither}",
            "-loop", "0" if loop else "-1",
            output_path,
        ]
        _run_with_progress(gif_cmd, duration, on_progress, (0.45, 1.0), cancel_event)

    if on_progress:
        on_progress(1.0)

    return output_path
