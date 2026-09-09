"""CTk-free playback helpers shared by the phone web server and the Qt page."""

from __future__ import annotations

import os
import subprocess
import tempfile

AUDIO_EXT = (".mp3", ".wav", ".flac", ".ogg", ".m4a")


def get_output_devices() -> list:
    try:
        import sounddevice as sd
        devs = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                devs.append({"index": i, "name": d["name"]})
        return devs
    except Exception as e:
        print(f"[Soundboard] sounddevice not available: {e}")
        return []


def load_audio_numpy(path: str):
    """Load any audio file -> (samples_float32 shape [N,2], samplerate)."""
    import numpy as np

    ext = os.path.splitext(path)[1].lower()
    try:
        import shutil
        import soundfile as sf

        if ext in (".mp3", ".m4a", ".ogg", ".flac"):
            tmp_in = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_in.close()
            tmp_out.close()
            try:
                shutil.copy2(path, tmp_in.name)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in.name, "-ar", "44100",
                     "-ac", "2", "-f", "wav", tmp_out.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
                )
                data, sr = sf.read(tmp_out.name, dtype="float32", always_2d=True)
            finally:
                for f in (tmp_in.name, tmp_out.name):
                    try:
                        os.unlink(f)
                    except Exception:
                        pass
        else:
            data, sr = sf.read(path, dtype="float32", always_2d=True)

        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        return data, sr
    except Exception as e:
        print(f"[Soundboard] Failed to load {path}: {e}")
        return None, 0


def play_on_device(samples, samplerate, device_index, volume=1.0):
    try:
        import numpy as np
        import sounddevice as sd
        out = (samples * volume).astype(np.float32)
        sd.play(out, samplerate=samplerate, device=device_index, blocking=False)
    except Exception as e:
        print(f"[Soundboard] Playback error on device {device_index}: {e}")


def stop_all():
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass
