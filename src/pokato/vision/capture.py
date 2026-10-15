"""Capture only the local practice widget; no arbitrary-client discovery."""
import ctypes
import sys
from PIL import ImageGrab


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def capture_widget(widget):
    if sys.platform == "win32":
        # Capture our own HWND directly. Desktop bounding-box capture can read
        # another foreground window instead when the practice table is covered.
        # PrintWindow returns the widget's rendered pixels, not its game state.
        return ImageGrab.grab(window=widget.winfo_id())
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return ImageGrab.grab(bbox=(x, y, x + widget.winfo_width(), y + widget.winfo_height()), all_screens=True)
