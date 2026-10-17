"""Continuous desktop frames, with a fallback mask for the application's HUD."""
import ctypes
import sys
import time
from PIL import ImageGrab, ImageDraw
from .sources import Frame, rgb_image


class DesktopSource:
    live = True

    def __init__(self):
        self.started = time.monotonic()
        self.index = 0
        self.closed = False
        self.mask = None

    def next(self):
        if self.closed:
            return None
        image = rgb_image(ImageGrab.grab(all_screens=True))
        if self.mask:
            left = ctypes.windll.user32.GetSystemMetrics(76) if sys.platform == 'win32' else 0
            top = ctypes.windll.user32.GetSystemMetrics(77) if sys.platform == 'win32' else 0
            x0, y0, x1, y1 = self.mask
            ImageDraw.Draw(image).rectangle((x0-left, y0-top, x1-left, y1-top), fill='#11151d')
        frame = Frame(image, self.index, time.monotonic()-self.started, 'Visible desktop')
        self.index += 1
        return frame

    def close(self):
        self.closed = True
