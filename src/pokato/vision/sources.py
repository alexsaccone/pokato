"""Local frame inputs independent of client, font, aspect ratio or poker rules."""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import math
from pathlib import Path
import sys
import time
from PIL import Image, ImageOps, ImageGrab

MAX_PIXELS = 40000000


def rgb_image(image):
    if min(image.size) < 2 or image.width*image.height > MAX_PIXELS:
        raise ValueError("Image dimensions must be between 2 pixels and 40 megapixels")
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


@dataclass(frozen=True)
class Frame:
    image: object
    index: int
    timestamp: float
    source: str


class ImageSource:
    live = False

    def __init__(self, paths):
        self.paths = tuple(Path(p).resolve() for p in paths)
        if not self.paths or any(not p.is_file() for p in self.paths):
            raise ValueError("Choose existing local images")
        self.file_index = self.page = self.index = 0
        self.image = None
        self.closed = False

    def next(self):
        if self.closed:
            return None
        while self.file_index < len(self.paths):
            if self.image is None:
                self.image = Image.open(self.paths[self.file_index])
                self.page = 0
            try:
                self.image.seek(self.page)
            except EOFError:
                self.image.close()
                self.image = None
                self.file_index += 1
                continue
            image = rgb_image(self.image)
            frame = Frame(image, self.index, self.index*.25, str(self.paths[self.file_index]))
            self.page += 1
            self.index += 1
            return frame
        return None

    def close(self):
        self.closed = True
        if self.image:
            self.image.close()
            self.image = None


class VideoSource:
    live = False

    def __init__(self, path):
        import cv2
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise ValueError("Choose a local video file")
        self.capture = cv2.VideoCapture(str(self.path))
        if not self.capture.isOpened():
            self.capture.release()
            raise ValueError("Video codec unavailable or file could not be decoded")
        width, height = self.capture.get(cv2.CAP_PROP_FRAME_WIDTH), self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not math.isfinite(width*height) or width*height > MAX_PIXELS:
            self.capture.release()
            raise ValueError("Video frame exceeds 40 megapixels")
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(self.fps) or self.fps <= 0:
            self.fps = 30.
        self.index = 0
        self.closed = False

    def next(self):
        import cv2
        if self.closed:
            return None
        ok, array = self.capture.read()
        if not ok:
            return None
        if array.shape[0]*array.shape[1] > MAX_PIXELS:
            raise ValueError("Video frame exceeds 40 megapixels")
        image = Image.fromarray(cv2.cvtColor(array, cv2.COLOR_BGR2RGB))
        frame = Frame(image, self.index, self.index/self.fps, str(self.path))
        self.index += 1
        return frame

    def close(self):
        self.capture.release()
        self.closed = True


def windows_api():
    if sys.platform != "win32":
        raise ValueError("Window capture is available on Windows")
    api = ctypes.windll.user32
    api.IsWindow.argtypes = api.IsWindowVisible.argtypes = api.IsIconic.argtypes = [wintypes.HWND]
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return api


def list_windows():
    api = windows_api()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    result = []

    def collect(handle, parameter):
        length = api.GetWindowTextLengthW(handle)
        if api.IsWindowVisible(handle) and length:
            title = ctypes.create_unicode_buffer(length+1)
            api.GetWindowTextW(handle, title, length+1)
            result.append((int(handle), title.value))
        return True

    callback = callback_type(collect)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows(callback, 0)
    return tuple(result)


class CaptureSource:
    live = True

    def __init__(self, *, window=None, bounds=None):
        if (window is None) == (bounds is None):
            raise ValueError("Choose one window or one screen region")
        if bounds is not None and (len(bounds) != 4 or any(type(v) is not int for v in bounds) or
                                   bounds[0] >= bounds[2] or bounds[1] >= bounds[3] or
                                   (bounds[2]-bounds[0])*(bounds[3]-bounds[1]) > MAX_PIXELS):
            raise ValueError("Invalid screen region")
        self.window, self.bounds = window, bounds
        self.index, self.started = 0, time.monotonic()
        self.closed = False

    def next(self):
        if self.closed:
            return None
        if self.window is not None:
            api = windows_api()
            if not api.IsWindow(self.window) or not api.IsWindowVisible(self.window) or api.IsIconic(self.window):
                raise ValueError("Selected window is closed, hidden or minimized")
            rect = wintypes.RECT()
            if not api.GetWindowRect(self.window, ctypes.byref(rect)):
                raise ValueError("Could not read selected window bounds")
            if (rect.right-rect.left)*(rect.bottom-rect.top) > MAX_PIXELS:
                raise ValueError("Selected window exceeds 40 megapixels")
            image = ImageGrab.grab(window=self.window)
            source = "Selected window"
        else:
            image = ImageGrab.grab(bbox=self.bounds, all_screens=True)
            source = "Selected screen region"
        frame = Frame(rgb_image(image), self.index, time.monotonic()-self.started, source)
        self.index += 1
        return frame

    def close(self):
        self.closed = True
