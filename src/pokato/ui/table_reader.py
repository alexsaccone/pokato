"""Client-independent calibration studio and a recognition-only floating HUD."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk
from pokato.core.cards import display_card, display_notation, SUIT_SYMBOLS
from pokato.vision.calibrated import CalibratedReader
from pokato.vision.layouts import Layout, Region, field_choices
from pokato.vision.sources import CaptureSource, ImageSource, VideoSource, Frame, list_windows
from pokato.vision.table_history import TableHistory
from .window import WindowChrome, NativeWindow, BG, TEXT, MUTED, ACCENT


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
        _, _, work_w, work_h = NativeWindow(self.window).work_area()
        self.window.geometry(f"{min(1380, work_w-32)}x{min(920, work_h-32)}+16+16")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Alt-F4>", lambda e: self.close())
        self.chrome = WindowChrome(self.window, "pokato", "TABLE READER", self.close,
                                   minimum=(min(980, work_w-32), min(680, work_h-32)))
        self.status = tk.StringVar(value="Open an image or demo, then draw regions and teach visible examples.")
        self.chrome.hint.configure(textvariable=self.status)
        self.build()
        self.build_hud()
        self.refresh_profile()
        self.job = self.root.after(80, self.poll)
        self.window.after_idle(self.chrome.restore)

    def toolbar(self, parent):
        bar = ttk.Frame(parent, padding=(5, 3))
        bar.pack(fill="x")
        return bar

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=label, command=lambda: self.safe(command))
        button.pack(side="left", padx=3, pady=2)
        return button

    def safe(self, action):
        try:
            return action()
        except (OSError, ValueError, TypeError, ArithmeticError) as exc:
            self.status.set(str(exc))
            messagebox.showerror("Table reader", str(exc), parent=self.window)

    def build(self):
        host = self.chrome.body
        inputs = self.toolbar(host)
        for label, action in (("Images…", self.open_images), ("Video…", self.open_video),
                              ("Window…", self.choose_window), ("Screen region…", self.choose_screen),
                              ("Demo", self.open_demo), ("Next frame", self.next_frame)):
            self.button(inputs, label, action)
        self.run_button = self.button(inputs, "Start", self.toggle_run)
        self.button(inputs, "Show HUD", self.show_hud)
        profiles = self.toolbar(host)
        for label, action in (("New layout", self.new_layout), ("Load layout…", self.load_layout),
                              ("Save layout…", self.save_layout), ("Settings…", self.settings),
                              ("Save frame…", self.save_frame), ("Export readings…", self.export)):
            self.button(profiles, label, action)
        self.profile_label = ttk.Label(host, padding=(9, 4), anchor="w")
        self.profile_label.pack(fill="x")
        panes = ttk.Panedwindow(host, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=4)
        visual, inspector = ttk.Frame(panes), ttk.Frame(panes, width=360)
        panes.add(visual, weight=3)
        panes.add(inspector, weight=2)
        ttk.Label(visual, text="Drag a rectangle around one field, with background padding.", padding=5).pack(fill="x")
        self.canvas = tk.Canvas(visual, background="#0b0e14", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw_preview())
        self.canvas.bind("<ButtonPress-1>", self.begin_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end_drag)
        editor = ttk.Frame(visual, padding=5)
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
        ttk.Label(inspector, text="Readings · similarity is not a probability\nDouble-click a field for a provisional correction.", padding=6).pack(fill="x")
        self.crop_label = ttk.Label(inspector, anchor="center")
        self.crop_label.pack(fill="x", pady=3)
        columns = ("value", "score", "issue")
        self.fields = ttk.Treeview(inspector, columns=columns, show="tree headings", selectmode="browse")
        self.fields.heading("#0", text="Field")
        self.fields.column("#0", width=110, minwidth=90)
        for key, label, width in (("value", "Value", 80), ("score", "Similarity", 70), ("issue", "Issue / provenance", 180)):
            self.fields.heading(key, text=label)
            self.fields.column(key, width=width, minwidth=50)
        scroll = ttk.Scrollbar(inspector, orient="vertical", command=self.fields.yview)
        scroll.pack(side="right", fill="y")
        self.fields.configure(yscrollcommand=scroll.set)
        self.fields.pack(fill="both", expand=True)
        self.fields.bind("<<TreeviewSelect>>", self.tree_select)
        self.fields.bind("<Double-1>", lambda e: self.safe(self.correct_field))
        self.detail = ttk.Label(inspector, text="No frame read", wraplength=400, padding=6)
        self.detail.pack(fill="x")
        self.timeline = tk.Text(inspector, height=7, wrap="word", state="disabled", font=("Segoe UI", 10))
        self.timeline.pack(fill="x", padx=4, pady=4)
        ttk.Label(host, text="Seat 0 = you; number seats clockwise. External mode reads the table; recommendations remain withheld.", padding=6).pack(fill="x")

    def button_grid(self, parent, text, command, row, column):
        ttk.Button(parent, text=text, command=lambda: self.safe(command)).grid(row=row, column=column, padx=3, pady=3, sticky="ew")

    def build_hud(self):
        self.hud = tk.Toplevel(self.root)
        self.hud.title("Pokato · Recognized table")
        self.hud.attributes("-topmost", True)
        self.hud.geometry("440x350+50+50")
        self.hud.protocol("WM_DELETE_WINDOW", self.hud.withdraw)
        self.hud_chrome = WindowChrome(self.hud, "pokato", "RECOGNIZED TABLE", self.hud.withdraw, minimum=(350, 300))
        self.hud_chrome.hint.configure(text="Keep this HUD outside the captured screen region")
        body = self.hud_chrome.body
        self.hud_state = tk.Label(body, text="No input selected", bg=BG, fg=ACCENT, anchor="w", font=("Segoe UI", 12, "bold"))
        self.hud_state.pack(fill="x", padx=16, pady=8)
        self.hud_cards = tk.Label(body, text="", bg=BG, fg=TEXT, anchor="w", justify="left", font=("Segoe UI Symbol", 19))
        self.hud_cards.pack(fill="x", padx=16)
        self.hud_info = tk.Label(body, text="", bg=BG, fg=TEXT, anchor="w", justify="left", font=("Segoe UI", 11))
        self.hud_info.pack(fill="x", padx=16, pady=8)
        self.hud_quality = tk.Label(body, text="Recognition only · recommendations withheld", bg=BG, fg=MUTED,
                                    justify="left", anchor="w", wraplength=390, font=("Segoe UI", 10))
        self.hud_quality.pack(fill="x", padx=16, pady=6)
        self.hud_quality.bind("<Configure>", lambda e: self.hud_quality.configure(wraplength=max(200, e.width)))
        self.hud.withdraw()

    def refresh_profile(self):
        self.field_combo.configure(values=[name for name, _ in field_choices(self.layout.seat_count)])
        if self.field.get() not in self.field_combo.cget("values"):
            self.field.set("anchor")
        self.profile_label.configure(text=f"{self.layout.name} · {self.layout.seat_count} seats · unit {self.layout.chip_unit} · "
                                    f"{len(self.layout.regions)} regions · {len(self.layout.examples)} examples")
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
        if self.frame and region:
            crop = region.crop(self.frame.image)
            factor = min(330/crop.width, 72/crop.height)
            self.crop_photo = ImageTk.PhotoImage(crop.resize((max(1, round(crop.width*factor)), max(1, round(crop.height*factor))), Image.Resampling.NEAREST))
            self.crop_label.configure(image=self.crop_photo)
        else:
            self.crop_label.configure(image="")
        self.draw_preview()

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
            self.canvas.create_text(ox+x0*pw, max(oy+8, oy+y0*ph-8), text=self.field.get(), fill="#ffff80", anchor="w")

    def point(self, event):
        if not self.preview_transform:
            return None
        ox, oy, w, h = self.preview_transform
        return max(0., min(1., (event.x-ox)/w)), max(0., min(1., (event.y-oy)/h))

    def begin_drag(self, event):
        self.running = False
        self.run_button.configure(text="Start")
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
        self.run_button.configure(text="Start")
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

    def manage_examples(self):
        dialog = tk.Toplevel(self.window)
        dialog.title("Labeled examples · select to remove")
        dialog.geometry("540x400")
        listing = tk.Listbox(dialog, selectmode="extended")
        listing.pack(fill="both", expand=True, padx=8, pady=8)
        for example in self.layout.examples:
            label = SUIT_SYMBOLS.get(example.label, example.label) if example.kind == "suit" else display_notation(example.label)
            listing.insert("end", f"{example.group} / {example.kind} / {label}")
        def remove():
            for i in reversed(listing.curselection()):
                del self.layout.examples[i]
                listing.delete(i)
            self.changed()
        ttk.Button(dialog, text="Remove selected examples", command=lambda: self.safe(remove)).pack(pady=6)

    def correct_field(self):
        if self.future is not None:
            raise ValueError("Wait for the current frame before correcting it")
        name = self.field.get()
        if not self.frame or name not in self.layout.regions:
            return
        text = simpledialog.askstring("Provisional correction", f"{name}: enter the visible label.\nThis marks history unverified; it does not train the reader.", parent=self.window)
        if text is not None:
            self.overrides[name] = text
            self.request_read(reuse=True)

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
        dialog = tk.Toplevel(self.window)
        dialog.title("Layout settings")
        values = {}
        options = (("name", "Layout name"), ("seat_count", "Seats (2–10; seat 0 is you)"),
                   ("chip_unit", "One chip unit (e.g. 0.01 for cents)"),
                   ("small_blind", "Small blind (integer chip units)"), ("big_blind", "Big blind (integer chip units)"),
                   ("decimal_separator", "Decimal separator (. or ,)"), ("threshold", "Minimum visual similarity (0.5–1)"),
                   ("margin", "Minimum separation from other labels"), ("contrast", "Foreground contrast (1–254)"))
        for row, (key, label) in enumerate(options):
            ttk.Label(dialog, text=label, padding=5).grid(row=row, column=0, sticky="w")
            value = tk.StringVar(value=str(getattr(self.layout, key)))
            ttk.Entry(dialog, textvariable=value, width=30).grid(row=row, column=1, padx=6)
            values[key] = value
        includes = tk.BooleanVar(value=self.layout.pot_includes_bets)
        ttk.Checkbutton(dialog, text="Displayed pot includes current bets", variable=includes).grid(row=9, column=0, columnspan=2, pady=6)
        reference = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="Use this frame's dimensions as reference", variable=reference).grid(row=10, column=0, columnspan=2)
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
        ttk.Button(dialog, text="Apply and reset inferred history", command=lambda: self.safe(apply)).grid(row=11, column=0, columnspan=2, pady=12)

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
        dialog = tk.Toplevel(self.window)
        dialog.title("Select the window to capture")
        dialog.geometry("650x420")
        listing = tk.Listbox(dialog)
        listing.pack(fill="both", expand=True, padx=8, pady=8)
        for _, title in windows:
            listing.insert("end", title)
        def choose():
            selected = listing.curselection()
            if selected:
                self.replace_source(CaptureSource(window=windows[selected[0]][0]))
                dialog.destroy()
        ttk.Button(dialog, text="Capture selected window", command=lambda: self.safe(choose)).pack(pady=8)

    def choose_screen(self):
        self.running = False
        self.run_button.configure(text="Start")
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
        canvas.create_text(40, 35, anchor="nw", text="Drag the table area · Esc cancels", fill="white", font=("Segoe UI", 24))
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
            self.window.after(250, accept)
        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", lambda e: self.safe(lambda: release(e)))
        overlay.bind("<Escape>", lambda e: cancel())
        overlay.focus_force()

    def next_frame(self):
        self.running = False
        self.run_button.configure(text="Start")
        self.request_read()

    def toggle_run(self):
        if not self.source:
            raise ValueError("Choose an input first")
        self.running = not self.running
        self.run_button.configure(text="Pause" if self.running else "Start")
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
                        self.run_button.configure(text="Start")
                        self.status.set("End of input · reopen it to replay")
                        self.hud_state.configure(text="End of input · last frame")
                    else:
                        self.deliver(reading)
            except Exception as exc:
                if generation == self.generation:
                    self.running = False
                    self.run_button.configure(text="Start")
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
