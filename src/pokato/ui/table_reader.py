"""Client-independent calibration studio and a recognition-only floating HUD."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from pokato.core.cards import display_card, display_notation, SUIT_SYMBOLS
from pokato.vision.calibrated import CalibratedReader
from pokato.vision.layouts import Layout, Region, field_choices
from pokato.vision.sources import CaptureSource, ImageSource, VideoSource, Frame, list_windows
from pokato.vision.table_history import TableHistory
from .window import WindowChrome, NativeWindow, BG, TEXT, MUTED, ACCENT
from .sizing import Display, Preferences, HudFonts, geometry
from .reader_style import ReaderTheme, ScrollPanel


class DemoSource:
    live = False

    def __init__(self, frames):
        self.frames, self.index = frames, 0

    def next(self):
        if self.index >= len(self.frames):
            return None
        image, _ = self.frames[self.index]
        frame = Frame(image, self.index, self.index*.25, "Synthetic demo")
        self.index += 1
        return frame

    def close(self):
        self.frames = ()


def read_job(source, layout, frame=None, overrides=None):
    frame = frame if frame is not None else source.next()
    return None if frame is None else CalibratedReader(layout).read(frame, overrides)


class ReaderWindow:
    def __init__(self, app):
        self.app, self.root = app, app.root
        self.closed = self.running = False
        self.source = self.frame = self.reading = self.result = None
        self.future = None
        self.generation = 0
        self.future_generation = 0
        self.pending_read = False
        self.pending_reuse = False
        self.overrides = {}
        self.records = []
        self.layout = Layout()
        self.profile_path = None
        self.selected_box = None
        self.drag_start = None
        self.preview_transform = None
        self.last_delivery = 0
        self.screen_restore = None
        self.monitor_job = None
        self.dialogs = []
        self.display = Display.detect(app.root) if app.watch_monitor else app.display
        self.hud_display = self.display
        self.preferences = Preferences(app.preferences.path or False, key="reader_zoom")
        self.zoom = self.preferences.zoom
        self.scale = self.display.scale*self.zoom
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pokato-reader")
        self.history = TableHistory(self.layout, 1)
        self.was_paused = app.paused
        self.was_hud_visible = bool(app.hud.winfo_viewable())
        app.paused = True
        app.pause_button.configure(text="Resume bots")
        app.invalidate("External reader open")
        app.hud.withdraw()
        app.root.withdraw()
        self.window = tk.Toplevel(self.root)
        self.window.title("Pokato · Table reader")
        self.window.geometry(geometry(self.display.fit(1320*self.scale, 880*self.scale)))
        self.theme = ReaderTheme(self.window, self.scale)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Alt-F4>", lambda e: self.close())
        self.chrome = WindowChrome(self.window, "pokato", "TABLE READER", self.close,
                                   minimum=self.display.fit(980*self.scale, 640*self.scale)[:2], scale=self.scale*.8)
        self.status = tk.StringVar(value="Open an image or demo, then draw regions and teach visible examples.")
        self.chrome.hint.configure(textvariable=self.status)
        self.build()
        self.build_hud()
        self.apply_scale(grow=False)
        self.refresh_profile()
        self.bind_zoom(self.window)
        self.window.bind("<Configure>", self.configure_window, add="+")
        self.hud.bind("<Configure>", self.configure_window, add="+")
        self.job = self.root.after(80, self.poll)
        self.window.after_idle(self.chrome.restore)

    def toolbar(self, parent):
        bar = ttk.Frame(parent, padding=(5, 3))
        bar.pack(fill="x")
        bar.bind("<Configure>", lambda e: self.wrap_buttons(bar))
        self.toolbars.append(bar)
        return bar

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=label, width=0, command=lambda: self.safe(command))
        button.grid(row=0, column=len(parent.winfo_children())-1, padx=3, pady=2)
        return button

    def wrap_buttons(self, parent):
        available = max(1, parent.winfo_width()-self.px(12))
        row = column = used = 0
        for widget in parent.winfo_children():
            if widget.winfo_class() == "Menu":
                continue
            width = widget.winfo_reqwidth()+self.px(6)
            if used and used+width > available:
                row, column, used = row+1, 0, 0
            widget.grid(row=row, column=column, padx=self.px(3), pady=self.px(2), sticky="w")
            column, used = column+1, used+width

    def safe(self, action):
        try:
            return action()
        except (OSError, ValueError, TypeError, ArithmeticError) as exc:
            self.status.set(str(exc))
            messagebox.showerror("Table reader", str(exc), parent=self.window)

    def build(self):
        host = self.chrome.body
        self.toolbars = []
        self.run_label = tk.StringVar(value="Start")
        self.compact_commands = False
        zoom_bar = self.toolbar(host)
        ttk.Label(zoom_bar, text="Text size").grid(row=0, column=0)
        self.button(zoom_bar, "A−", lambda: self.set_zoom(self.zoom-.1))
        self.zoom_label = ttk.Label(zoom_bar, text=f"{self.zoom:.0%}")
        self.zoom_label.grid(row=0, column=2)
        self.button(zoom_bar, "A+", lambda: self.set_zoom(self.zoom+.1))
        self.button(zoom_bar, "Reset", lambda: self.set_zoom(1.))
        self.inputs_toolbar = inputs = self.toolbar(host)
        for label, action in (("Images…", self.open_images), ("Video…", self.open_video),
                              ("Window…", self.choose_window), ("Screen region…", self.choose_screen),
                              ("Demo", self.open_demo), ("Next frame", self.next_frame)):
            self.button(inputs, label, action)
        self.run_button = self.button(inputs, "Start", self.toggle_run)
        self.run_button.configure(textvariable=self.run_label)
        self.button(inputs, "Show HUD", self.show_hud)
        self.profiles_toolbar = profiles = self.toolbar(host)
        for label, action in (("New layout", self.new_layout), ("Load layout…", self.load_layout),
                              ("Save layout…", self.save_layout), ("Settings…", self.settings),
                              ("Save frame…", self.save_frame), ("Export readings…", self.export)):
            self.button(profiles, label, action)
        self.compact_toolbar = compact = self.toolbar(host)
        for label, commands in (("Input", (("Images…", self.open_images), ("Video…", self.open_video),
                                            ("Window…", self.choose_window), ("Screen region…", self.choose_screen), ("Demo", self.open_demo))),
                                ("Layout", (("New layout", self.new_layout), ("Load layout…", self.load_layout),
                                             ("Save layout…", self.save_layout), ("Settings…", self.settings),
                                             ("Save frame…", self.save_frame), ("Export readings…", self.export))),
                                ("View", (("Table & calibration", lambda: self.choose_pane("table")),
                                           ("Readings & history", lambda: self.choose_pane("readings")),
                                           ("Next frame", self.next_frame), ("Show HUD", self.show_hud)))):
            menu = tk.Menu(compact, tearoff=False, font=self.theme.fonts.get(10))
            for text, action in commands:
                menu.add_command(label=text, command=lambda action=action: self.safe(action))
            button = ttk.Menubutton(compact, text=label, menu=menu)
            button.grid(row=0, column=len([w for w in compact.winfo_children() if w.winfo_class() != "Menu"])-1, padx=3)
        self.compact_run_button = self.button(compact, "Start", self.toggle_run)
        self.compact_run_button.configure(textvariable=self.run_label)
        compact.pack_forget()
        self.profile_label = ttk.Label(host, padding=(9, 4), anchor="w")
        self.profile_label.pack(fill="x")
        self.pane_switch = ttk.Frame(host, padding=4)
        self.pane_choice = tk.StringVar(value="table")
        for text, value in (("Table & calibration", "table"), ("Readings & history", "readings")):
            ttk.Radiobutton(self.pane_switch, text=text, variable=self.pane_choice, value=value,
                            command=self.layout_panes).pack(side="left", padx=4)
        self.panes = panes = ttk.Panedwindow(host, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=4)
        self.visual_panel, self.inspector_panel = ScrollPanel(panes, self.theme), ScrollPanel(panes, self.theme)
        visual, inspector = self.visual_panel.body, self.inspector_panel.body
        panes.add(self.visual_panel, weight=1)
        panes.add(self.inspector_panel, weight=1)
        self.pane_mode = None
        self.panes.bind("<Configure>", lambda e: self.layout_panes())
        self.preview_hint = ttk.Label(visual, text="Drag a rectangle around one field, with background padding.", padding=5)
        self.preview_hint.pack(fill="x")
        self.canvas = tk.Canvas(visual, background="#0b0e14", highlightthickness=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda e: self.draw_preview())
        self.canvas.bind("<ButtonPress-1>", self.begin_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end_drag)
        self.editor = editor = ttk.Frame(visual, padding=5)
        editor.pack(fill="x")
        self.field = tk.StringVar(value="anchor")
        self.field_combo = ttk.Combobox(editor, textvariable=self.field, state="readonly", width=19)
        self.field_combo.grid(row=0, column=0, sticky="ew", padx=2)
        self.field_combo.bind("<<ComboboxSelected>>", lambda e: self.select_field())
        self.button_grid(editor, "Set region", self.set_region, 0, 1)
        self.button_grid(editor, "Remove", self.remove_region, 0, 2)
        ttk.Label(editor, text="Template group (blank = shared default)").grid(row=1, column=0, columnspan=2, sticky="w")
        self.group = tk.StringVar()
        ttk.Entry(editor, textvariable=self.group, width=20).grid(row=2, column=0, sticky="ew", padx=2)
        ttk.Label(editor, text="Amount ×").grid(row=2, column=1, sticky="e")
        self.multiplier = tk.StringVar(value="1")
        ttk.Entry(editor, textvariable=self.multiplier, width=9).grid(row=2, column=2, sticky="ew")
        self.example_label = tk.StringVar()
        ttk.Entry(editor, textvariable=self.example_label, width=20).grid(row=3, column=0, sticky="ew", padx=2, pady=5)
        self.button_grid(editor, "Teach example", self.teach, 3, 1)
        self.button_grid(editor, "Examples…", self.manage_examples, 3, 2)
        self.help_text = ttk.Label(editor, text="", wraplength=560, padding=3)
        self.help_text.grid(row=4, column=0, columnspan=3, sticky="ew")
        editor.columnconfigure(0, weight=1)
        self.inspector_hint = ttk.Label(inspector, text="Readings · similarity is not a probability\nDouble-click a field for a provisional correction.", padding=6)
        self.inspector_hint.pack(fill="x")
        self.crop_label = ttk.Label(inspector, anchor="center")
        self.crop_label.pack(fill="x", pady=3)
        columns = ("value", "score", "issue")
        table = ttk.Frame(inspector)
        table.pack(fill="x", expand=True)
        self.fields = ttk.Treeview(table, columns=columns, show="tree headings", selectmode="browse", height=9)
        self.fields.heading("#0", text="Field")
        self.fields.column("#0", width=110, minwidth=90)
        for key, label, width in (("value", "Value", 80), ("score", "Similarity", 70), ("issue", "Issue / provenance", 180)):
            self.fields.heading(key, text=label)
            self.fields.column(key, width=width, minwidth=50)
        scroll = tk.Scrollbar(table, orient="vertical", command=self.fields.yview)
        scroll.pack(side="right", fill="y")
        horizontal = tk.Scrollbar(inspector, orient="horizontal", command=self.fields.xview)
        horizontal.pack(fill="x")
        self.fields.configure(xscrollcommand=horizontal.set)
        self.fields.configure(yscrollcommand=scroll.set)
        self.fields.pack(fill="both", expand=True)
        self.fields.bind("<<TreeviewSelect>>", self.tree_select)
        self.fields.bind("<Double-1>", lambda e: self.safe(self.correct_field))
        self.detail = ttk.Label(inspector, text="No frame read", wraplength=400, padding=6)
        self.detail.pack(fill="x")
        self.timeline = tk.Text(inspector, height=7, wrap="word", state="disabled", font=("Segoe UI", 10))
        self.timeline.pack(fill="x", padx=4, pady=4)
        self.reader_note = ttk.Label(visual, text="Seat 0 = you; number seats clockwise. External mode reads the table; recommendations remain withheld.", padding=6)
        self.reader_note.pack(fill="x")
        visual.bind("<Configure>", self.wrap_visual, add="+")
        inspector.bind("<Configure>", self.wrap_inspector, add="+")
        self.visual_panel.canvas.bind("<Configure>", lambda e: self.fit_preview(), add="+")
        self.visual_panel.bind_wheel()
        self.inspector_panel.bind_wheel()

    def button_grid(self, parent, text, command, row, column):
        ttk.Button(parent, text=text, width=0, command=lambda: self.safe(command)).grid(row=row, column=column, padx=3, pady=3, sticky="ew")

    def build_hud(self):
        self.hud = tk.Toplevel(self.root)
        self.hud.title("Pokato · Recognized table")
        self.hud.attributes("-topmost", True)
        self.hud.geometry(geometry(self.hud_display.hud_rect()))
        self.hud.protocol("WM_DELETE_WINDOW", self.hud.withdraw)
        self.hud_fonts = HudFonts(self.hud, self.hud_display.compact_scale*self.zoom)
        self.hud_chrome = WindowChrome(self.hud, "pokato", "TABLE READER", self.hud.withdraw, minimum=(350, 300))
        self.hud_chrome.hint.pack_forget()
        self.hud_zoom_buttons = []
        for text, command in (("A−", lambda: self.set_zoom(self.zoom-.1)), ("A+", lambda: self.set_zoom(self.zoom+.1)), ("Reset", lambda: self.set_zoom(1.))):
            button = tk.Button(self.hud_chrome.footer, text=text, command=command, bg=BG, fg=TEXT,
                               activebackground="#303b48", activeforeground=TEXT, relief="flat", borderwidth=0)
            button.pack(side="left", padx=5)
            self.hud_zoom_buttons.append(button)
        self.hud_scroll = ScrollPanel(self.hud_chrome.body, self.theme)
        self.hud_scroll.canvas.configure(background=BG)
        self.theme.style.configure(self.theme.name("Hud.TFrame"), background=BG)
        self.hud_scroll.body.configure(style=self.theme.name("Hud.TFrame"))
        self.hud_scroll.pack(fill="both", expand=True)
        body = self.hud_scroll.body
        self.hud_state = tk.Label(body, text="No input selected", bg=BG, fg=ACCENT, anchor="w", justify="left", font=self.hud_fonts.get(11, True))
        self.hud_state.pack(fill="x", padx=16, pady=8)
        self.hud_cards = tk.Label(body, text="", bg=BG, fg=TEXT, anchor="w", justify="left", font=self.hud_fonts.get(19))
        self.hud_cards.pack(fill="x", padx=16)
        self.hud_info = tk.Label(body, text="", bg=BG, fg=TEXT, anchor="w", justify="left", font=self.hud_fonts.get(10))
        self.hud_info.pack(fill="x", padx=16, pady=8)
        self.hud_quality = tk.Label(body, text="Recognition only · recommendations withheld", bg=BG, fg=MUTED,
                                    justify="left", anchor="w", wraplength=390, font=self.hud_fonts.get(10))
        self.hud_quality.pack(fill="x", padx=16, pady=6)
        self.hud_quality.bind("<Configure>", lambda e: self.hud_quality.configure(wraplength=max(200, e.width)))
        self.hud_scroll.body.bind("<Configure>", self.wrap_hud, add="+")
        self.hud_scroll.bind_wheel()
        self.bind_zoom(self.hud)
        self.hud.withdraw()

    def px(self, value):
        return max(1, round(value*self.scale))

    def bind_zoom(self, window):
        for sequence in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            window.bind(sequence, lambda e: self.zoom_key(.1))
        for sequence in ("<Control-minus>", "<Control-KP_Subtract>"):
            window.bind(sequence, lambda e: self.zoom_key(-.1))
        window.bind("<Control-0>", lambda e: self.zoom_key(reset=True))
        window.bind("<Control-MouseWheel>", lambda e: self.zoom_key(.1 if e.delta > 0 else -.1))

    def zoom_key(self, delta=0., reset=False):
        self.set_zoom(1. if reset else self.zoom+delta)
        return "break"

    def set_zoom(self, zoom):
        self.preferences.save(zoom)
        self.zoom = self.preferences.zoom
        self.apply_scale()

    def apply_scale(self, grow=True):
        self.scale = self.display.scale*self.zoom
        self.theme.set_scale(self.scale)
        self.theme.apply(self.chrome.body)
        for dialog in self.dialogs:
            if dialog.winfo_exists():
                self.theme.apply(dialog)
        self.chrome.set_scale(self.scale*.8)
        self.chrome.hint.configure(fg=MUTED)
        self.zoom_label.configure(text=f"{self.zoom:.0%}")
        self.profile_label.configure(font=self.theme.fonts.get(9))
        minimum = self.display.fit(980*self.scale, 640*self.scale)[:2]
        self.chrome.minimum = minimum
        self.window.minsize(*minimum)
        if grow and not self.chrome.maximized:
            self.window.geometry(geometry(self.display.fit(max(self.window.winfo_width(), 1320*self.scale),
                max(self.window.winfo_height(), 880*self.scale), self.window.winfo_x(), self.window.winfo_y())))
        for key, title, width in (("#0", "Field", 125), ("value", "Value", 100),
                                  ("score", "Similarity", 100), ("issue", "Issue / provenance", 200)):
            size = max(self.px(width), self.theme.fonts.get(10, True).measure(title)+self.px(16))
            self.fields.column(key, width=size, minwidth=size, stretch=key == "issue")
        hud_scale = self.hud_display.compact_scale*self.zoom
        self.hud_fonts.set_scale(hud_scale)
        self.hud_chrome.set_scale(hud_scale*.8)
        self.hud_chrome.hint.pack_forget()
        self.hud_chrome.footer.configure(height=round(42*hud_scale))
        for button in self.hud_zoom_buttons:
            button.configure(font=self.hud_fonts.get(9), padx=round(8*hud_scale), pady=round(3*hud_scale))
        for label in (self.hud_state, self.hud_cards, self.hud_info, self.hud_quality):
            label.pack_configure(padx=round(14*hud_scale), pady=round(5*hud_scale))
        hud_minimum = self.hud_display.fit(500*hud_scale, 340*hud_scale)[:2]
        self.hud_chrome.minimum = hud_minimum
        self.hud.minsize(*hud_minimum)
        self.hud_scroll.scroll.configure(width=max(16, round(16*hud_scale)))
        if grow and not self.hud_chrome.maximized:
            width, height, _, _ = self.hud_display.hud_rect()
            self.hud.geometry(geometry(self.hud_display.fit(max(self.hud.winfo_width(), width, hud_minimum[0]),
                max(self.hud.winfo_height(), height, hud_minimum[1]), self.hud.winfo_x(), self.hud.winfo_y())))
        for toolbar in self.toolbars:
            self.wrap_buttons(toolbar)
        self.layout_commands()
        self.layout_panes()
        self.fit_preview()
        if self.frame:
            self.draw_crop()
            self.draw_preview()

    def configure_window(self, event):
        if event.widget not in (self.window, self.hud) or self.closed:
            return
        if event.widget == self.window:
            self.profile_label.configure(wraplength=max(100, event.width-self.px(20)))
            self.layout_commands()
        if self.monitor_job:
            self.root.after_cancel(self.monitor_job)
        self.monitor_job = self.root.after(250, self.refresh_monitor)

    def refresh_monitor(self):
        self.monitor_job = None
        if self.closed:
            return
        display = Display.detect(self.window) if self.app.watch_monitor else self.app.display
        hud_display = Display.detect(self.hud) if self.app.watch_monitor else self.app.display
        changed = display.scale != self.display.scale or hud_display.compact_scale != self.hud_display.compact_scale
        self.display, self.hud_display = display, hud_display
        if changed:
            self.apply_scale(grow=False)

    def layout_panes(self):
        width = self.panes.winfo_width()
        if width <= 1:
            return
        wide = width >= self.px(1100)
        mode = "both" if wide else self.pane_choice.get()
        if mode != self.pane_mode:
            for pane in self.panes.panes():
                self.panes.forget(pane)
            if wide:
                self.pane_switch.pack_forget()
                self.panes.add(self.visual_panel, weight=1)
                self.panes.add(self.inspector_panel, weight=1)
            else:
                if not self.compact_commands:
                    self.pane_switch.pack(fill="x", before=self.panes)
                self.panes.add(self.visual_panel if mode == "table" else self.inspector_panel, weight=1)
            self.pane_mode = mode

    def layout_commands(self):
        compact = self.window.winfo_height()/self.scale < 700
        self.compact_commands = compact
        if compact:
            self.inputs_toolbar.pack_forget()
            self.profiles_toolbar.pack_forget()
            self.compact_toolbar.pack(fill="x", before=self.profile_label)
            self.pane_switch.pack_forget()
        else:
            self.compact_toolbar.pack_forget()
            self.inputs_toolbar.pack(fill="x", before=self.profile_label)
            self.profiles_toolbar.pack(fill="x", before=self.profile_label)
            if self.pane_mode not in (None, "both"):
                self.pane_switch.pack(fill="x", before=self.panes)
        self.update_profile_label()

    def choose_pane(self, name):
        self.pane_choice.set(name)
        self.layout_panes()

    def update_profile_label(self):
        detail = (f"{self.layout.seat_count} seats · {len(self.layout.regions)} regions · "
                  f"{len(self.layout.examples)} examples")
        self.profile_label.configure(text=detail if self.compact_commands else
                                     f"{self.layout.name} · unit {self.layout.chip_unit} · {detail}")

    def wrap_visual(self, event):
        width = max(100, event.width-self.px(20))
        for label in (self.preview_hint, self.help_text, self.reader_note):
            label.configure(wraplength=width)
        self.fit_preview()

    def wrap_inspector(self, event):
        width = max(100, event.width-self.px(20))
        self.inspector_hint.configure(wraplength=width)
        self.detail.configure(wraplength=width)

    def wrap_hud(self, event):
        width = max(100, event.width-round(34*self.hud_fonts.scale))
        for label in (self.hud_state, self.hud_cards, self.hud_info, self.hud_quality):
            label.configure(wraplength=width)

    def fit_preview(self):
        if not hasattr(self, "editor"):
            return
        available = self.visual_panel.canvas.winfo_height()
        others = self.editor.winfo_reqheight()+self.preview_hint.winfo_reqheight()+self.reader_note.winfo_reqheight()
        height = max(self.px(180), available-others-self.px(12))
        if int(self.canvas.cget("height")) != height:
            self.canvas.configure(height=height)

    def refresh_profile(self):
        self.field_combo.configure(values=[name for name, _ in field_choices(self.layout.seat_count)])
        if self.field.get() not in self.field_combo.cget("values"):
            self.field.set("anchor")
        self.update_profile_label()
        self.select_field()

    def select_field(self):
        name = self.field.get()
        region = self.layout.regions.get(name)
        self.selected_box = region.box if region else None
        self.group.set(region.group if region else "")
        self.multiplier.set(region.multiplier if region else "1")
        kind = dict(field_choices(self.layout.seat_count)).get(name, "")
        self.help_text.configure(text={
            "rank": "Label 2–9, T (ten), J, Q, K, A or empty. Crop rank only; include padding.",
            "suit": "Label ♣ ♦ ♥ ♠ or empty. Crop suit only; include padding.",
            "number": "Label the visible amount, e.g. $12.50. Use =0 to explicitly teach a blank zero bet or all-in stack. Amount × handles BB displays.",
            "flag": "Label yes when this seat has the marker, no otherwise. Teach both states for each marker region.",
            "status": "Label A = in hand, F = folded/empty, I = all-in. Teach each visible state.",
            "anchor": "Crop a stable, distinctive table graphic; label match. Avoid clocks or changing text.",
            "identity": "Optional: crop the player name. A changed visual fingerprint invalidates this hand's history. No label needed."
        }.get(kind, ""))
        if self.reading:
            found = next((f for f in self.reading.fields if f.name == name), None)
            if found:
                raw = SUIT_SYMBOLS.get(found.raw, found.raw) if kind == "suit" else display_notation(found.raw)
                self.detail.configure(text=f"{name} · raw {raw}\nSimilarity {found.score:.3f} · "
                                      f"margin {found.margin:.3f}\n{found.issue or ('Manual correction' if found.manual else 'Automatic read')}")
        self.draw_crop(region)
        self.draw_preview()

    def draw_crop(self, region=None):
        region = region or self.layout.regions.get(self.field.get())
        if self.frame and region:
            try:
                crop = region.crop(self.frame.image)
                factor = min(self.px(330)/crop.width, self.px(90)/crop.height)
                self.crop_photo = ImageTk.PhotoImage(crop.resize((max(1, round(crop.width*factor)), max(1, round(crop.height*factor))), Image.Resampling.NEAREST))
                self.crop_label.configure(image=self.crop_photo)
            except ValueError:
                self.crop_label.configure(image="")
        else:
            self.crop_label.configure(image="")

    def tree_select(self, event=None):
        selection = self.fields.selection()
        if selection:
            self.field.set(selection[0])
            self.select_field()

    def draw_preview(self):
        self.canvas.delete("all")
        if self.frame is None:
            return
        w, h = max(2, self.canvas.winfo_width()), max(2, self.canvas.winfo_height())
        iw, ih = self.frame.image.size
        scale = min(w/iw, h/ih)
        pw, ph = max(1, round(iw*scale)), max(1, round(ih*scale))
        ox, oy = (w-pw)//2, (h-ph)//2
        self.preview_transform = ox, oy, pw, ph
        self.preview_photo = ImageTk.PhotoImage(self.frame.image.resize((pw, ph), Image.Resampling.BILINEAR))
        self.canvas.create_image(ox, oy, image=self.preview_photo, anchor="nw")
        bad = {f.name for f in self.reading.fields if f.issue} if self.reading else set()
        for name, region in self.layout.regions.items():
            x0, y0, x1, y1 = region.box
            color = "#ffb480" if name in bad else "#74bfb1"
            self.canvas.create_rectangle(ox+x0*pw, oy+y0*ph, ox+x1*pw, oy+y1*ph, outline=color, width=1)
        if self.selected_box:
            x0, y0, x1, y1 = self.selected_box
            self.canvas.create_rectangle(ox+x0*pw, oy+y0*ph, ox+x1*pw, oy+y1*ph, outline="#ffff80", width=2)
            self.canvas.create_text(ox+x0*pw, max(oy+self.px(8), oy+y0*ph-self.px(8)),
                                    text=self.field.get(), fill="#ffff80", anchor="w", font=self.theme.fonts.get(9))

    def point(self, event):
        if not self.preview_transform:
            return None
        ox, oy, w, h = self.preview_transform
        return max(0., min(1., (event.x-ox)/w)), max(0., min(1., (event.y-oy)/h))

    def begin_drag(self, event):
        self.running = False
        self.run_label.set("Start")
        if self.future is not None:
            self.status.set("Wait for the current frame, then draw the region")
            return
        self.drag_start = self.point(event)

    def drag(self, event):
        point = self.point(event)
        if self.drag_start and point:
            x, y = self.drag_start
            self.selected_box = min(x, point[0]), min(y, point[1]), max(x, point[0]), max(y, point[1])
            self.draw_preview()

    def end_drag(self, event):
        self.drag(event)
        self.drag_start = None

    def reset_history(self, message="Layout changed; inferred history reset"):
        self.generation += 1
        self.running = False
        self.run_label.set("Start")
        self.history = TableHistory(self.layout, 2 if self.source and self.source.live else 1)
        self.overrides = {}
        self.records = []
        self.result = self.reading = None
        self.fields.delete(*self.fields.get_children())
        self.crop_label.configure(image="")
        self.detail.configure(text="No current reading")
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        self.timeline.configure(state="disabled")
        self.status.set(message)
        self.clear_hud(message)

    def changed(self):
        self.layout.validate()
        self.reset_history()
        self.refresh_profile()
        if self.frame:
            self.request_read(reuse=True)

    def set_region(self):
        if self.frame is None or self.selected_box is None:
            raise ValueError("Open a frame and drag a rectangle first")
        if self.future is not None:
            raise ValueError("Wait for the current frame before changing its regions")
        name = self.field.get()
        kind = dict(field_choices(self.layout.seat_count))[name]
        region = Region(name, self.selected_box, kind, self.group.get().strip(), self.multiplier.get().strip())
        region.pixels(self.frame.image.size)
        self.layout.regions[name] = region
        self.changed()

    def remove_region(self):
        self.layout.regions.pop(self.field.get(), None)
        self.changed()

    def teach(self):
        if self.future is not None:
            raise ValueError("Wait for the current frame before teaching an example")
        if self.frame is None or self.field.get() not in self.layout.regions:
            raise ValueError("Set this field's region first")
        CalibratedReader.teach(self.layout, self.layout.regions[self.field.get()], self.frame.image, self.example_label.get())
        self.changed()

    def new_dialog(self, title, width=800, height=540):
        self.running = False
        self.run_label.set("Start")
        dialog = tk.Toplevel(self.window)
        dialog.title(title)
        dialog.geometry(geometry(self.display.fit(width*self.scale, height*self.scale,
            self.window.winfo_x()+self.px(32), self.window.winfo_y()+self.px(32))))
        dialog.footer = ttk.Frame(dialog, padding=self.px(8))
        dialog.footer.pack(side="bottom", fill="x")
        dialog.panel = ScrollPanel(dialog, self.theme)
        dialog.panel.pack(fill="both", expand=True)
        dialog.body = dialog.panel.body
        self.dialogs.append(dialog)
        self.bind_zoom(dialog)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        return dialog

    def finish_dialog(self, dialog):
        self.theme.apply(dialog)
        dialog.panel.bind_wheel()
        dialog.lift()
        return dialog

    def list_widget(self, parent, multiple=False):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True, padx=self.px(8), pady=self.px(8))
        listing = tk.Listbox(container, selectmode="extended" if multiple else "browse", height=10)
        vertical = tk.Scrollbar(container, orient="vertical", command=listing.yview)
        vertical.pack(side="right", fill="y")
        horizontal = tk.Scrollbar(container, orient="horizontal", command=listing.xview)
        horizontal.pack(side="bottom", fill="x")
        listing.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        listing.pack(fill="both", expand=True)
        return listing

    def manage_examples(self):
        dialog = self.new_dialog("Labeled examples · select to remove")
        listing = self.list_widget(dialog.body, multiple=True)
        for example in self.layout.examples:
            label = SUIT_SYMBOLS.get(example.label, example.label) if example.kind == "suit" else display_notation(example.label)
            listing.insert("end", f"{example.group} / {example.kind} / {label}")
        def remove():
            for i in reversed(listing.curselection()):
                del self.layout.examples[i]
                listing.delete(i)
            self.changed()
        ttk.Button(dialog.footer, text="Remove selected examples", command=lambda: self.safe(remove)).pack(pady=6)
        return self.finish_dialog(dialog)

    def correct_field(self):
        if self.future is not None:
            raise ValueError("Wait for the current frame before correcting it")
        name = self.field.get()
        if not self.frame or name not in self.layout.regions:
            return
        frame, generation = self.frame, self.generation
        dialog = self.new_dialog("Provisional correction", 740, 280)
        ttk.Label(dialog.body, text=f"{name}: enter the visible label.\nThis marks history unverified; it does not train the reader.",
                  wraplength=self.px(650), padding=self.px(12)).pack(fill="x")
        value = tk.StringVar()
        entry = ttk.Entry(dialog.body, textvariable=value)
        entry.pack(fill="x", padx=self.px(12), pady=self.px(8))
        def apply():
            if self.frame is not frame or self.generation != generation:
                raise ValueError("The frame changed; reopen its correction")
            self.overrides[name] = value.get()
            self.request_read(reuse=True)
            dialog.destroy()
        ttk.Button(dialog.footer, text="Apply correction", command=lambda: self.safe(apply)).pack(side="left", padx=8)
        ttk.Button(dialog.footer, text="Cancel", command=dialog.destroy).pack(side="left", padx=8)
        dialog.bind("<Return>", lambda e: self.safe(apply))
        self.finish_dialog(dialog)
        entry.focus_set()
        return dialog

    def new_layout(self):
        self.layout = Layout(reference_size=self.frame.image.size if self.frame else (980, 800))
        self.profile_path = None
        self.changed()

    def load_layout(self, path=None):
        path = path or filedialog.askopenfilename(parent=self.window, title="Load table layout", filetypes=[("Layout", "*.json")])
        if path:
            layout = Layout.load(path)
            CalibratedReader(layout)  # Validate templates before replacing the current profile.
            self.layout, self.profile_path = layout, Path(path)
            self.changed()

    def save_layout(self, path=None):
        path = path or filedialog.asksaveasfilename(parent=self.window, title="Save table layout", defaultextension=".json",
                                                  initialfile=self.profile_path.name if self.profile_path else "table-layout.json")
        if path:
            self.layout.save(path)
            self.profile_path = Path(path)
            self.status.set(f"Saved {self.profile_path.name}; includes labeled crops, not full frames")

    def settings(self):
        dialog = self.new_dialog("Layout settings", 880, 650)
        form = dialog.body
        values = {}
        options = (("name", "Layout name"), ("seat_count", "Seats (2–10; seat 0 is you)"),
                   ("chip_unit", "One chip unit (e.g. 0.01 for cents)"),
                   ("small_blind", "Small blind (integer chip units)"), ("big_blind", "Big blind (integer chip units)"),
                   ("decimal_separator", "Decimal separator (. or ,)"), ("threshold", "Minimum visual similarity (0.5–1)"),
                   ("margin", "Minimum separation from other labels"), ("contrast", "Foreground contrast (1–254)"))
        for row, (key, label) in enumerate(options):
            label_widget = ttk.Label(form, text=label, padding=self.px(5), wraplength=self.px(400))
            label_widget.grid(row=row, column=0, sticky="w")
            value = tk.StringVar(value=str(getattr(self.layout, key)))
            ttk.Entry(form, textvariable=value, width=20).grid(row=row, column=1, padx=self.px(6), pady=self.px(5), sticky="ew")
            values[key] = value
        includes = tk.BooleanVar(value=self.layout.pot_includes_bets)
        ttk.Checkbutton(form, text="Displayed pot includes current bets", variable=includes).grid(row=9, column=0, columnspan=2, pady=self.px(6), sticky="w")
        reference = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Use this frame's dimensions as reference", variable=reference).grid(row=10, column=0, columnspan=2, sticky="w")
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        def wrap(event):
            for child in form.winfo_children():
                if child.winfo_class() == "TLabel":
                    child.configure(wraplength=max(100, round(event.width*.53)))
        form.bind("<Configure>", wrap, add="+")
        def apply():
            layout = deepcopy(self.layout)
            for key, value in values.items():
                cast = int if key in ("seat_count", "small_blind", "big_blind", "contrast") else float if key in ("threshold", "margin") else str
                setattr(layout, key, cast(value.get()))
            layout.pot_includes_bets = includes.get()
            if reference.get() and self.frame:
                layout.reference_size = self.frame.image.size
            layout.regions = {key: value for key, value in layout.regions.items() if key in dict(field_choices(layout.seat_count))}
            layout.validate()
            self.layout = layout
            self.changed()
            dialog.destroy()
        ttk.Button(dialog.footer, text="Apply and reset inferred history", command=lambda: self.safe(apply)).pack(pady=self.px(5))
        return self.finish_dialog(dialog)

    def replace_source(self, source):
        old = self.source
        self.source, self.frame = source, None
        if old is not None:
            # Queue release behind any read; never release a decoder mid-read.
            self.executor.submit(old.close)
        self.reset_history("Input selected · use Next frame or Start")
        self.pending_read = True
        self.pending_reuse = False
        self.draw_preview()

    def open_images(self):
        paths = filedialog.askopenfilenames(parent=self.window, title="Choose images in frame order",
                    filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"), ("All files", "*.*")])
        if paths:
            self.replace_source(ImageSource(paths))

    def open_video(self):
        path = filedialog.askopenfilename(parent=self.window, title="Open local recording",
                    filetypes=[("Videos", "*.mp4 *.mkv *.avi *.mov *.webm"), ("All files", "*.*")])
        if path:
            self.replace_source(VideoSource(path))

    def open_demo(self, style="wide"):
        from pokato.vision.fixtures import demo_frames
        self.layout, frames = demo_frames(style)
        self.profile_path = None
        self.replace_source(DemoSource(frames))
        self.refresh_profile()

    def choose_window(self):
        windows = list_windows()
        dialog = self.new_dialog("Select the window to capture", 850, 540)
        listing = self.list_widget(dialog.body)
        for _, title in windows:
            listing.insert("end", title)
        mode = tk.StringVar(value="Visible client area (GPU games)")
        ttk.Combobox(dialog.footer, textvariable=mode, state="readonly", width=38,
                     values=("Visible client area (GPU games)", "Native window capture")).pack(fill="x", pady=self.px(4))
        ttk.Label(dialog.footer, text="Visible capture: keep the table unobstructed. Move Pokato and its HUD away from it.",
                  wraplength=self.px(700)).pack(fill="x")
        def choose():
            selected = listing.curselection()
            if selected:
                self.replace_source(CaptureSource(window=windows[selected[0]][0],
                    window_mode="visible" if mode.get().startswith("Visible") else "native"))
                dialog.destroy()
        ttk.Button(dialog.footer, text="Capture selected window", command=lambda: self.safe(choose)).pack(pady=self.px(8))
        return self.finish_dialog(dialog)

    def choose_screen(self):
        self.running = False
        self.run_label.set("Start")
        hud_visible = bool(self.hud.winfo_viewable())
        self.window.withdraw()
        self.hud.withdraw()
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", .25)
        api = NativeWindow(overlay).api
        if api:
            left, top, width, height = (api.GetSystemMetrics(n) for n in (76, 77, 78, 79))
        else:
            left, top, width, height = 0, 0, overlay.winfo_screenwidth(), overlay.winfo_screenheight()
        overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")
        canvas = tk.Canvas(overlay, bg="black", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(self.px(40), self.px(35), anchor="nw", text="Drag the table area · Esc cancels",
                           fill="white", font=self.theme.fonts.get(16, True))
        start = []
        def restore():
            self.chrome.restore()
            if hud_visible:
                self.hud_chrome.restore()
        def cancel():
            overlay.destroy()
            restore()
        def press(event):
            start[:] = [event.x, event.y]
        def move(event):
            if start:
                canvas.delete("selection")
                canvas.create_rectangle(*start, event.x, event.y, outline="yellow", width=4, tags="selection")
        def release(event):
            if not start:
                return
            bounds = (left+min(start[0], event.x), top+min(start[1], event.y),
                      left+max(start[0], event.x), top+max(start[1], event.y))
            if bounds[2]-bounds[0] < 2 or bounds[3]-bounds[1] < 2:
                cancel()
                return
            try:
                source = CaptureSource(bounds=bounds)
            except ValueError:
                cancel()
                raise
            overlay.destroy()
            def accept():
                self.replace_source(source)
                # Capture the first frame before restoring windows over the
                # user's selected area. Later streaming requires moving or
                # minimizing the studio/HUD outside that area.
                self.screen_restore = restore
            self.root.after(250, lambda: None if self.closed else accept())
        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", lambda e: self.safe(lambda: release(e)))
        overlay.bind("<Escape>", lambda e: cancel())
        overlay.bind("<Alt-F4>", lambda e: cancel())
        overlay.protocol("WM_DELETE_WINDOW", cancel)
        overlay.focus_force()

    def next_frame(self):
        self.running = False
        self.run_label.set("Start")
        self.request_read()

    def toggle_run(self):
        if not self.source:
            raise ValueError("Choose an input first")
        self.running = not self.running
        self.run_label.set("Pause" if self.running else "Start")
        if self.running:
            self.request_read()
        else:
            self.hud_state.configure(text="Paused · last frame")

    def request_read(self, reuse=False):
        if self.closed or self.future is not None:
            self.pending_read = True
            self.pending_reuse = reuse
            return
        if reuse and self.frame is None or not reuse and self.source is None:
            return
        self.pending_read = False
        self.pending_reuse = False
        if not reuse:
            self.overrides = {}
        self.future_generation = self.generation
        self.future = self.executor.submit(read_job, self.source, deepcopy(self.layout),
                                           self.frame if reuse else None, dict(self.overrides))

    def poll(self):
        if self.closed:
            return
        if self.future is not None and self.future.done():
            future, generation = self.future, self.future_generation
            self.future = None
            try:
                reading = future.result()
                if generation == self.generation:
                    if reading is None:
                        self.running = False
                        self.run_label.set("Start")
                        self.status.set("End of input · reopen it to replay")
                        self.hud_state.configure(text="End of input · last frame")
                    else:
                        self.deliver(reading)
            except Exception as exc:
                if generation == self.generation:
                    self.running = False
                    self.run_label.set("Start")
                    self.status.set(f"Input stopped: {exc}")
                    self.reading = self.result = None
                    self.fields.delete(*self.fields.get_children())
                    self.clear_hud(f"Input stopped: {exc}")
            if generation == self.generation and self.screen_restore:
                restore, self.screen_restore = self.screen_restore, None
                restore()
        if self.future is None and (self.pending_read or self.running and time.monotonic()-self.last_delivery >= .35):
            self.request_read(reuse=self.pending_reuse)
        if self.running and self.source and self.source.live and self.last_delivery and time.monotonic()-self.last_delivery > 2:
            self.clear_hud("Capture delayed · waiting for a fresh frame")
        self.job = self.root.after(80, self.poll)

    def deliver(self, reading):
        self.frame, self.reading = reading.frame, reading
        self.last_delivery = time.monotonic()
        if not self.layout.regions and not self.layout.examples:
            self.layout.reference_size = self.frame.image.size
        self.result = self.history.accept(reading)
        self.fields.delete(*self.fields.get_children())
        for found in reading.fields:
            value = "—" if found.value is None else display_notation(str(found.value))
            if self.layout.regions[found.name].kind == "suit":
                value = SUIT_SYMBOLS.get(value, value)
            self.fields.insert("", "end", iid=found.name, text=found.name,
                               values=(value, f"{found.score:.3f}", found.issue or ("manual" if found.manual else "automatic")))
        message = self.result.message
        self.status.set(f"Frame {self.frame.index} · {self.result.quality} · {message[:130]}")
        descriptions = {"B": "blind", "F": "fold", "K": "check", "C": "call", "R": "raise"}
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        self.timeline.insert("end", "\n".join(f"Seat {e.seat} · {e.street} · {descriptions[e.action]}"
                             + (f" +{self.amount(e.amount)}" if e.amount else "") for e in self.result.events[-8:]))
        self.timeline.configure(state="disabled")
        self.records.append({"frame": self.frame.index, "timestamp": self.frame.timestamp,
                             "source": self.frame.source, "fields": [asdict(f) for f in reading.fields],
                             "snapshot": asdict(reading.snapshot) if reading.snapshot else None,
                             "issues": reading.issues, "history": asdict(self.result)})
        self.records = self.records[-1000:]
        if reading.snapshot:
            snapshot = reading.snapshot
            streets = {"P": "Preflop", "F": "Flop", "T": "Turn", "R": "River", "X": "Between hands"}
            self.hud_state.configure(text=f"{streets[snapshot.street]} · {self.result.quality} · frame {snapshot.index}")
            self.hud_cards.configure(text="  ".join(display_card(c) for c in snapshot.hole)+"\n"+
                                     ("  ".join(display_card(c) for c in snapshot.board) or "Board not dealt"))
            self.hud_info.configure(text=f"Pot {self.amount(snapshot.pot)} · Dealer seat {snapshot.button}\n"+
                                    (f"Acting seat {snapshot.actor}" if snapshot.actor >= 0 else "No acting player"))
            self.hud_quality.configure(text=f"{message}\nRecognition only · recommendations withheld")
        else:
            self.clear_hud(message)
        self.select_field()

    def amount(self, value):
        return format(Decimal(value)*Decimal(self.layout.chip_unit), "f")

    def clear_hud(self, message):
        self.hud_state.configure(text="State unverified")
        self.hud_cards.configure(text="")
        self.hud_info.configure(text="")
        self.hud_quality.configure(text=f"{message}\nRecognition only · recommendations withheld")

    def show_hud(self):
        self.hud_chrome.restore()

    def save_frame(self):
        if not self.frame:
            raise ValueError("Read a frame first")
        path = filedialog.asksaveasfilename(parent=self.window, title="Save current frame", defaultextension=".png")
        if path:
            self.frame.image.save(path, format="PNG")

    def export(self, path=None):
        if not self.records:
            raise ValueError("There are no readings to export")
        path = path or filedialog.asksaveasfilename(parent=self.window, title="Export readings and inferred actions", defaultextension=".json")
        if path:
            payload = {"version": 1, "layout": self.layout.name, "chip_unit": self.layout.chip_unit,
                       "recommendations_enabled": False, "similarity_is_probability": False,
                       "note": "Reconciled frames do not prove complete history. Image timestamps are nominal. Last 1000 readings only.",
                       "readings": self.records}
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status.set(f"Exported {len(self.records)} readings")

    def close(self, restore=True):
        if self.closed:
            return
        self.closed = True
        self.running = False
        self.root.after_cancel(self.job)
        if self.monitor_job:
            self.root.after_cancel(self.monitor_job)
        if self.source:
            self.executor.submit(self.source.close)
        self.executor.shutdown(wait=False)
        self.hud.destroy()
        self.window.destroy()
        if restore and not self.app.closed:
            self.app.paused = self.was_paused
            self.app.pause_button.configure(text="Resume bots" if self.was_paused else "Pause bots")
            self.app.chrome.restore()
            if self.was_hud_visible:
                self.app.hud_chrome.restore()
            self.app.invalidate("Reading practice table…")
