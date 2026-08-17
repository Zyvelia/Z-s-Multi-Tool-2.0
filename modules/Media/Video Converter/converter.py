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


def _build_scale_filter(width, max_height):
    """
    width alone: scale to that width, height auto (-2) — aspect ratio
    preserved, same as before.
    width + max_height: fit inside a width x max_height box (e.g. the
    320x320 "keep it inside this box" case), preserving aspect ratio
    and never upscaling past the source. force_original_aspect_ratio
    keeps the ratio; decrease means it only ever shrinks to fit.
    """
    if width and max_height:
        return (
            f"scale=w={width}:h={max_height}:"
            f"force_original_aspect_ratio=decrease:flags=lanczos"
        )
    if width:
        return f"scale={width}:-2:flags=lanczos"
    return "scale=iw:-2:flags=lanczos"


def convert(
    input_path: str,
    output_path: str,
    fps: int = 15,
    width: int = 480,
    max_height: int = None,
    colors: int = 256,
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

    max_height, if given alongside width, fits the output inside a
    width x max_height box instead of scaling to a fixed width — e.g.
    width=320, max_height=320 keeps the whole frame within 320x320
    without distorting it.

    colors caps the palette size (palettegen's max_colors, 4-256).
    Lower values shrink the file at some cost to color fidelity —
    used by convert_within_size() when stepping quality down.
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

    colors = max(4, min(256, int(colors)))
    scale_filter = _build_scale_filter(width, max_height)

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
            "-vf", f"fps={fps},{scale_filter},palettegen=stats_mode=diff:max_colors={colors}",
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


def convert_within_size(
    input_path: str,
    output_path: str,
    max_size_mb: float = 10.0,
    fps: int = 15,
    width: int = 480,
    max_height: int = None,
    start: float = None,
    end: float = None,
    loop: bool = True,
    dither: str = "bayer",
    on_progress=None,
    on_attempt=None,
    cancel_event=None,
    max_attempts: int = 6,
):
    """
    Converts, then — if the result is over max_size_mb — steps fps,
    width, and palette size down and re-converts, repeating up to
    max_attempts times. Stops as soon as a pass lands at or under the
    target, or after the last attempt (keeping the smallest result it
    produced, even if that still exceeds the target — a very long or
    busy source may simply not fit).

    on_attempt(attempt_number, fps, width, colors), if given, fires
    right before each attempt so the UI can show what's being tried.
    Returns (output_path, size_bytes, attempts_used, met_target: bool).
    """
    target_bytes = max_size_mb * 1024 * 1024
    cur_fps, cur_width, cur_colors = fps, width, 256

    for attempt in range(1, max_attempts + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise ConversionCancelled()

        if on_attempt:
            on_attempt(attempt, cur_fps, cur_width, cur_colors)

        convert(
            input_path, output_path,
            fps=cur_fps, width=cur_width, max_height=max_height,
            colors=cur_colors,
            start=start, end=end, loop=loop, dither=dither,
            on_progress=on_progress, cancel_event=cancel_event,
        )

        size = os.path.getsize(output_path)
        if size <= target_bytes:
            return output_path, size, attempt, True
        if attempt == max_attempts:
            return output_path, size, attempt, False

        # Step quality down for the next pass. Width does the most work
        # for file size, so it shrinks fastest; fps and color count
        # follow so motion and gradients don't fall apart too early.
        cur_width = max(80, int(cur_width * 0.80))
        cur_fps = max(6, cur_fps - 2)
        cur_colors = max(32, cur_colors - 32)

    # unreachable, but keeps type-checkers happy
    return output_path, os.path.getsize(output_path), max_attempts, False
