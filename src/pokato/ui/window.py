"""Frameless Tk windows with explicit move, resize, maximize and minimize controls."""
import ctypes
from ctypes import wintypes
import sys
import tkinter as tk

BG = "#11151d"
BORDER = "#303842"
TEXT = "#eef2f7"
MUTED = "#8592a3"
ACCENT = "#9ee8ce"


class NativeWindow:
    """Typed Win32 calls scoped to our own Tk window."""
    def __init__(self, window):
        self.window = window
        self.api = ctypes.windll.user32 if sys.platform == "win32" else None
        if self.api:
            self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            self.api.GetAncestor.restype = wintypes.HWND
            self.api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            self.api.IsIconic.argtypes = [wintypes.HWND]
            self.api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            self.api.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
            self.api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            self.api.MonitorFromWindow.restype = wintypes.HANDLE

    @property
    def handle(self):
        return self.api.GetAncestor(self.window.winfo_id(), 2) if self.api else None

    def taskbar(self):
        if self.api:
            handle = self.handle
            style = self.api.GetWindowLongW(handle, -20)
            self.api.SetWindowLongW(handle, -20, (style | 0x40000) & ~0x80)

    def minimized(self):
        return bool(self.api.IsIconic(self.handle)) if self.api else self.window.state() == "iconic"

    def dpi(self):
        if self.api and hasattr(self.api, "GetDpiForWindow"):
            self.api.GetDpiForWindow.argtypes = [wintypes.HWND]
            self.api.GetDpiForWindow.restype = wintypes.UINT
            return self.api.GetDpiForWindow(self.handle) or 96
        return round(self.window.winfo_fpixels("1i"))

    def work_area(self):
        if self.api:
            class MonitorInfo(ctypes.Structure):
                _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                            ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            self.api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            if self.api.GetMonitorInfoW(self.api.MonitorFromWindow(self.handle, 2), ctypes.byref(info)):
                r = info.work
                return r.left, r.top, r.right - r.left, r.bottom - r.top
        return 0, 0, self.window.winfo_screenwidth(), self.window.winfo_screenheight() - 48


class WindowChrome:
    def __init__(self, window, title, subtitle, close, minimum=(360, 420), alpha=1.0, scale=1.0):
        self.window, self.minimum = window, minimum
        self.native = NativeWindow(window)
        self.maximized = False
        self.restore_geometry = None
        window.overrideredirect(True)
        window.configure(bg=BORDER)
        window.resizable(True, True)
        window.minsize(*minimum)
        window.attributes("-alpha", alpha)
        self.shell = tk.Frame(window, bg=BG, highlightthickness=0)
        self.shell.pack(fill="both", expand=True, padx=1, pady=1)
        self.header = tk.Frame(self.shell, bg=BG, height=49)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        mark = tk.Label(self.header, text="◈", bg=BG, fg=ACCENT, font=("Segoe UI", 18))
        mark.pack(side="left", padx=(17, 9))
        name = tk.Label(self.header, text=title, bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold"))
        name.pack(side="left")
        caption = tk.Label(self.header, text=subtitle, bg=BG, fg=MUTED, font=("Segoe UI", 9))
        caption.pack(side="left", padx=10)
        self.title_widgets = (mark, name, caption)
        self.close_button = self.control("×", close, "#b56e7a")
        self.max_button = self.control("□", self.toggle_maximize)
        self.min_button = self.control("−", self.minimize)
        for widget in (self.header, mark, name, caption):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<Double-Button-1>", lambda e: self.toggle_maximize())
        tk.Frame(self.shell, height=1, bg="#252c37").pack(fill="x", padx=14)
        self.footer = tk.Frame(self.shell, bg=BG, height=21)
        self.footer.pack(side="bottom", fill="x")
        self.footer.pack_propagate(False)
        self.hint = tk.Label(self.footer, text="Drag header to move · double-click to expand", bg=BG,
                             fg="#627080", font=("Segoe UI", 8))
        self.hint.pack(side="left", padx=16)
        self.grip = tk.Label(self.footer, text="◢", bg=BG, fg=MUTED, cursor="size_nw_se", font=("Segoe UI", 11))
        self.grip.pack(side="right", padx=4)
        self.bind_resize(self.grip, "se")
        self.body = tk.Frame(self.shell, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.edges = {}
        for direction, placement, cursor in (
            ("w", dict(x=0, y=5, width=5, relheight=1, height=-10), "size_we"),
            ("e", dict(relx=1, x=-5, y=5, width=5, relheight=1, height=-10), "size_we"),
            ("n", dict(x=5, y=0, relwidth=1, width=-10, height=4), "size_ns"),
            ("s", dict(x=5, rely=1, y=-4, relwidth=1, width=-10, height=4), "size_ns"),
        ):
            edge = tk.Frame(window, bg=BORDER, cursor=cursor)
            edge.place(**placement)
            self.bind_resize(edge, direction)
            self.edges[direction] = edge
        window.bind("<Map>", self.on_map, add="+")
        window.after_idle(self.native.taskbar)
        self.set_scale(scale)

    def set_scale(self, scale):
        from .sizing import font_pixels
        self.scale = scale
        self.header.configure(height=round(49 * scale))
        self.footer.configure(height=round(27 * scale))
        for widget, size, bold in zip(self.title_widgets, (18, 11, 9), (False, True, False)):
            widget.configure(font=("Segoe UI", -font_pixels(size, scale), "bold" if bold else "normal"))
        for button in (self.close_button, self.max_button, self.min_button):
            button.configure(font=("Segoe UI", -font_pixels(12, scale)))
        self.hint.configure(font=("Segoe UI", -font_pixels(8, scale)))
        self.grip.configure(font=("Segoe UI", -font_pixels(11, scale)))
        self.hint.pack_configure(padx=round(12 * scale))

    def control(self, text, command, hover="#303b48"):
        button = tk.Button(self.header, text=text, command=command, bg=BG, fg=MUTED,
                           activebackground=hover, activeforeground=TEXT, relief="flat", bd=0,
                           font=("Segoe UI", 12), width=3, cursor="hand2", takefocus=False)
        button.pack(side="right", fill="y", pady=8, padx=2)
        button.bind("<Enter>", lambda e: button.configure(bg=hover, fg=TEXT))
        button.bind("<Leave>", lambda e: button.configure(bg=BG, fg=MUTED))
        return button

    def on_map(self, event):
        if event.widget == self.window:
            self.window.overrideredirect(True)
            self.window.after_idle(self.native.taskbar)

    def start_drag(self, event):
        self.drag_origin = (event.x_root, event.y_root, self.window.winfo_x(), self.window.winfo_y())

    def drag(self, event):
        if self.maximized:
            self.toggle_maximize()
            self.window.update_idletasks()
            x, y = event.x_root - self.window.winfo_width() // 2, event.y_root - 20
            self.window.geometry(f"{x:+d}{y:+d}")
            self.drag_origin = (event.x_root, event.y_root, x, y)
        x, y, wx, wy = self.drag_origin
        self.window.geometry(f"{wx + event.x_root - x:+d}{wy + event.y_root - y:+d}")

    def bind_resize(self, widget, direction):
        widget.bind("<ButtonPress-1>", lambda e: self.start_resize(e, direction))
        widget.bind("<B1-Motion>", self.resize)

    def start_resize(self, event, direction):
        self.resize_origin = (event.x_root, event.y_root, self.window.winfo_x(), self.window.winfo_y(),
                              self.window.winfo_width(), self.window.winfo_height(), direction)

    def resize(self, event):
        if self.maximized:
            return
        px, py, x, y, width, height, direction = self.resize_origin
        dx, dy = event.x_root - px, event.y_root - py
        new_w = max(self.minimum[0], width + (dx if "e" in direction else -dx if "w" in direction else 0))
        new_h = max(self.minimum[1], height + (dy if "s" in direction else -dy if "n" in direction else 0))
        if "w" in direction:
            x += width - new_w
        if "n" in direction:
            y += height - new_h
        self.window.geometry(f"{new_w}x{new_h}{x:+d}{y:+d}")

    def toggle_maximize(self):
        if self.maximized:
            self.window.geometry(self.restore_geometry)
        else:
            self.restore_geometry = self.window.geometry()
            x, y, width, height = self.native.work_area()
            self.window.geometry(f"{width}x{height}{x:+d}{y:+d}")
        self.maximized = not self.maximized
        self.max_button.configure(text="❐" if self.maximized else "□")

    def minimize(self):
        if self.native.api:
            self.native.api.ShowWindow(self.native.handle, 6)
        else:
            self.window.overrideredirect(False)
            self.window.iconify()

    def restore(self):
        if self.native.api:
            self.native.api.ShowWindow(self.native.handle, 9)
        self.window.deiconify()
        self.window.lift()
