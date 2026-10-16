"""Scoped reader typography and scrollable panels; never change global Tk scaling."""
import tkinter as tk
from tkinter import ttk
from .sizing import HudFonts


class ReaderTheme:
    def __init__(self, window, scale):
        self.prefix = f"Reader{window.winfo_id()}"
        self.style = ttk.Style(window)
        self.fonts = HudFonts(window, scale)
        self.set_scale(scale)

    def name(self, kind):
        return f"{self.prefix}.{kind}"

    def px(self, value):
        return max(1, round(value*self.scale))

    def set_scale(self, scale):
        self.scale = scale
        self.fonts.set_scale(scale)
        body, bold = self.fonts.get(10), self.fonts.get(10, True)
        for kind in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TMenubutton"):
            self.style.configure(self.name(kind), font=body)
        for kind in ("TButton", "TCheckbutton", "TRadiobutton", "TMenubutton"):
            self.style.configure(self.name(kind), padding=(self.px(9), self.px(5)))
        for kind in ("TEntry", "TCombobox"):
            self.style.configure(self.name(kind), padding=self.px(4), arrowsize=self.px(18))
        self.style.configure(self.name("Treeview"), font=body,
                             rowheight=body.metrics("linespace")+self.px(8))
        self.style.configure(self.name("Treeview.Heading"), font=bold, padding=self.px(5))

    def apply(self, widget):
        kind = widget.winfo_class()
        if kind in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TMenubutton", "TEntry", "TCombobox", "Treeview"):
            widget.configure(style=self.name(kind))
        if kind in ("TEntry", "TCombobox", "Text", "Listbox", "Entry", "Label", "Button", "Menu"):
            widget.configure(font=self.fonts.get(10))
        if kind == "TCombobox":
            # The popup list has its own font, independent of the entry field.
            popup = widget.tk.call("ttk::combobox::PopdownWindow", str(widget))
            widget.tk.call(f"{popup}.f.l", "configure", "-font", str(self.fonts.get(10)))
        if kind == "Scrollbar":
            widget.configure(width=self.px(16))
        for child in widget.winfo_children():
            self.apply(child)


class ScrollPanel(ttk.Frame):
    """Keep large text reachable on short displays instead of clipping controls."""
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme = theme
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background="#f0f0f0")
        self.scroll = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview, width=theme.px(16))
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.body = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self.resize)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<MouseWheel>", self.wheel)

    def resize(self, event):
        self.canvas.itemconfigure(self.item, width=max(1, event.width))

    def wheel(self, event):
        if event.state & 4:  # Ctrl+wheel belongs to the reader's text zoom.
            return None
        self.canvas.yview_scroll(-int(event.delta/120)*3, "units")
        return "break"

    def bind_wheel(self, widget=None):
        widget = widget or self.body
        if widget.winfo_class() not in ("Treeview", "Text", "Listbox", "TCombobox", "Entry", "TEntry"):
            widget.bind("<MouseWheel>", self.wheel, add="+")
        for child in widget.winfo_children():
            self.bind_wheel(child)
