# modules/color_picker/eyedropper.py
#
# "Pick a color from anywhere on screen" — implemented as a borderless,
# full-screen window showing a screenshot, so clicks land on our own Tk
# window (which we can read pixels back out of) instead of needing a
# global mouse hook / extra dependency (pyautogui, pynput, etc.) just to
# detect a click over some other application.
#
# Esc cancels. Click picks the pixel under the cursor and calls
# on_pick(hex_string).

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageGrab, ImageTk

from .color_utils import rgb_to_hex

SWATCH_SIZE = 90
SWATCH_OFFSET = 24


def _grab_full_screenshot() -> Image.Image:
    try:
        # all_screens=True is Windows-only (Pillow); falls back below on
        # any platform/Pillow version where it's not supported.
        return ImageGrab.grab(all_screens=True)
    except TypeError:
        return ImageGrab.grab()


def open_eyedropper(parent_widget, on_pick) -> None:
    """Opens the full-screen picker. on_pick receives a '#rrggbb' string,
    or is never called if the user cancels with Esc."""
    try:
        screenshot = _grab_full_screenshot()
    except Exception as e:
        messagebox.showerror("Eyedropper", f"Couldn't capture the screen: {e}")
        return

    overlay = tk.Toplevel(parent_widget)
    overlay.overrideredirect(True)
    overlay.geometry(f"{screenshot.width}x{screenshot.height}+0+0")
    overlay.attributes("-topmost", True)
    overlay.focus_force()
    try:
        overlay.config(cursor="tcross")
    except tk.TclError:
        pass

    canvas = tk.Canvas(overlay, width=screenshot.width, height=screenshot.height,
                        highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)

    # Keep references alive for the life of the overlay — Tk drops
    # PhotoImages with no live Python reference.
    tk_img = ImageTk.PhotoImage(screenshot)
    canvas.create_image(0, 0, image=tk_img, anchor="nw")
    canvas._keep_alive = tk_img

    swatch_rect = canvas.create_rectangle(0, 0, 0, 0, fill="#000000", outline="white", width=2)
    swatch_text = canvas.create_text(0, 0, text="", fill="white",
                                      font=("Segoe UI", 11, "bold"), anchor="n")
    canvas.itemconfigure(swatch_rect, state="hidden")
    canvas.itemconfigure(swatch_text, state="hidden")

    def pixel_at(x: int, y: int) -> tuple[int, int, int]:
        x = max(0, min(screenshot.width - 1, x))
        y = max(0, min(screenshot.height - 1, y))
        pixel = screenshot.getpixel((x, y))
        return pixel[:3]

    def on_motion(event: tk.Event) -> None:
        r, g, b = pixel_at(event.x, event.y)
        hex_color = rgb_to_hex(r, g, b)

        sx0, sy0 = event.x + SWATCH_OFFSET, event.y + SWATCH_OFFSET
        sx1, sy1 = sx0 + SWATCH_SIZE, sy0 + 28
        canvas.coords(swatch_rect, sx0, sy0, sx1, sy1)
        canvas.itemconfigure(swatch_rect, fill=hex_color, state="normal")
        canvas.coords(swatch_text, (sx0 + sx1) / 2, sy1 + 4)
        canvas.itemconfigure(swatch_text, text=hex_color, state="normal")

    def on_click(event: tk.Event) -> None:
        r, g, b = pixel_at(event.x, event.y)
        overlay.destroy()
        on_pick(rgb_to_hex(r, g, b))

    def on_cancel(_event=None) -> None:
        overlay.destroy()

    canvas.bind("<Motion>", on_motion)
    canvas.bind("<Button-1>", on_click)
    overlay.bind("<Escape>", on_cancel)
