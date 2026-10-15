"""Desktop composition root. Simulator truth never enters the coach pipeline."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import tkinter as tk
import uuid
from PIL import Image, ImageTk
from pokato.core.game import Game
from pokato.simulator.bots import choose_action
from pokato.simulator.render import render, NAMES
from pokato.simulator.layout import WIDTH, HEIGHT
from pokato.vision.capture import capture_widget, enable_dpi_awareness
from pokato.vision.reader import Reader, ReadError
from pokato.vision.tracker import Tracker
from pokato.analysis.history import History
from pokato.analysis.coach import analyze
from pokato.ui.window import WindowChrome, BG, TEXT, MUTED, ACCENT
from pokato.ui.sizing import Display, HudFonts, Preferences, font_pixels, geometry

PANEL = "#1a212c"


class App:
    def __init__(self, root, seed=7, samples=400, database=None, *, display=None, settings_path=None):
        self.root, self.samples = root, samples
        # The V1 optical layout uses physical pixels. Keep Tk typography in
        # that same coordinate system even on 200%/250% Windows displays.
        root.tk.call("tk", "scaling", 96 / 72)
        self.display = display or Display.detect(root)
        self.watch_monitor = display is None
        self.preferences = Preferences(False if database == ":memory:" and settings_path is None else settings_path)
        self.hud_zoom = self.preferences.zoom
        self.hud_display = self.display
        self.hud_scale = self.display.scale * self.hud_zoom
        self.monitor_job = None
        self.game = Game(seed)
        self.reader, self.tracker = Reader(), Tracker()
        self.history = History(database or Path.home() / ".pokato" / "practice.sqlite3")
        self.session = uuid.uuid4().hex
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pokato-analysis")
        self.future = None
        self.future_key = None
        self.current_key = None
        self.latest = None
        self.advice = None
        self.closed = False
        self.paused = False
        self.last_seen = 0
        self.last_error = None
        root.title("Pokato · local Hold'em practice")
        table_rect = self.display.table_rect()
        root.geometry(geometry(table_rect))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Alt-F4>", lambda e: self.close())
        self.chrome = WindowChrome(root, "pokato", "PRACTICE TABLE", self.close,
                                   minimum=(min(WIDTH + 24, table_rect[0]), min(HEIGHT + 140, table_rect[1])),
                                   scale=self.display.scale)
        self.viewport = tk.Canvas(self.chrome.body, bg=BG, highlightthickness=0)
        self.viewport.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        self.table = tk.Label(self.viewport, borderwidth=0, highlightthickness=0, bg=BG)
        self.table_window = self.viewport.create_window(0, 0, window=self.table, anchor="nw", width=WIDTH, height=HEIGHT)
        self.viewport.bind("<Configure>", self.resize_table)
        self.viewport.bind("<MouseWheel>", lambda e: self.viewport.yview_scroll(-int(e.delta / 120) * 3, "units"))
        self.viewport.bind("<Shift-MouseWheel>", lambda e: self.viewport.xview_scroll(-int(e.delta / 120) * 3, "units"))
        self.table.bind("<MouseWheel>", lambda e: self.viewport.yview_scroll(-int(e.delta / 120) * 3, "units"))
        self.table.bind("<Shift-MouseWheel>", lambda e: self.viewport.xview_scroll(-int(e.delta / 120) * 3, "units"))
        self.table.bind("<ButtonPress-2>", lambda e: self.viewport.scan_mark(e.x_root - self.viewport.winfo_rootx(), e.y_root - self.viewport.winfo_rooty()))
        self.table.bind("<B2-Motion>", lambda e: self.viewport.scan_dragto(e.x_root - self.viewport.winfo_rootx(), e.y_root - self.viewport.winfo_rooty(), gain=1))
        self.table_frame = None
        self.table_size = None
        controls = tk.Frame(self.chrome.body, bg=BG, padx=12, pady=2 if self.display.height < 900 else 10)
        controls.pack(fill="x")
        self.controls = controls
        self.fold = self.button(controls, "Fold", lambda: self.hero_action("F"))
        self.call = self.button(controls, "Check", self.call_action)
        raise_controls = tk.Frame(controls, bg=BG)
        raise_controls.pack(side="left")
        tk.Label(raise_controls, text="Raise to", bg=BG, fg=MUTED,
                 font=("Segoe UI", -font_pixels(9, self.display.scale))).pack(side="left", padx=(8, 4))
        self.raise_to = tk.StringVar(value="30")
        self.raise_entry = tk.Entry(raise_controls, textvariable=self.raise_to, width=7, bg=PANEL, fg=TEXT,
                                   insertbackground=TEXT, relief="flat", font=("Segoe UI", -font_pixels(11, self.display.scale)))
        self.raise_entry.pack(side="left", padx=4)
        self.raise_button = self.button(raise_controls, "Raise", lambda: self.hero_action("R"))
        self.next_button = self.button(controls, "Deal next hand", self.new_hand)
        self.pause_button = self.button(controls, "Pause bots", self.toggle_pause)
        self.button(controls, "Show coach", self.open_hud)
        self.control_items = list(controls.winfo_children())
        for widget in self.control_items:
            widget.pack_forget()
        controls.bind("<Configure>", self.layout_controls)
        self.message = tk.StringVar(value="LOCAL PRACTICE · 5/10 CHIPS · NO RAKE")
        self.chrome.hint.configure(textvariable=self.message)
        self.build_hud()
        self.new_hand()
        root.after(350, self.observe)
        root.after(1400, self.bot_tick)

    def button(self, parent, text, command):
        button = tk.Button(parent, text=text, command=command, bg=PANEL, fg=TEXT,
                           activebackground="#303b48", activeforeground=TEXT, relief="flat", bd=0,
                           cursor="hand2", font=("Segoe UI", -font_pixels(10, self.display.scale)),
                           padx=12, pady=2 if self.display.height < 900 else 8)
        button.pack(side="left", padx=4)
        return button

    def layout_controls(self, event=None):
        available = max(1, self.controls.winfo_width() - 24)
        row = column = used = 0
        for widget in self.control_items:
            width = widget.winfo_reqwidth() + 8
            if used and used + width > available:
                row, column, used = row + 1, 0, 0
            widget.grid(row=row, column=column, padx=4, pady=3, sticky="w")
            column, used = column + 1, used + width

    def label(self, parent, text="", size=10, color=TEXT, bold=False):
        label = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color, justify="left", anchor="w",
                         font=self.hud_fonts.get(size, bold), wraplength=round(330 * self.hud_scale))
        label.pack(fill="x", pady=self.hp(3))
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(120, e.width - 3)))
        return label

    def panel(self, parent, title):
        panel = tk.Frame(parent, bg=PANEL, padx=self.hp(16), pady=self.hp(11), highlightthickness=1, highlightbackground="#29323e")
        panel._hud_panel = True
        panel.pack(fill="x", pady=(0, self.hp(10)))
        self.label(panel, title, 8, MUTED, True)
        return panel

    def build_hud(self):
        self.hud = tk.Toplevel(self.root)
        self.hud_fonts = HudFonts(self.hud, self.hud_scale)
        self.hud.title("Pokato · practice coach")
        self.hud.geometry(geometry(self.hud_display.hud_rect(self.hud_zoom,
                                     beside=self.display.table_rect()[2] + self.display.table_rect()[0] + self.display.margin)))
        self.hud.attributes("-topmost", True)
        self.hud.protocol("WM_DELETE_WINDOW", self.hud.withdraw)
        self.hud_chrome = WindowChrome(self.hud, "pokato", "COACH", self.hud.withdraw,
                                      minimum=self.hud_minimum(), alpha=0.94, scale=self.hud_scale)
        self.hud_chrome.hint.configure(text="Scroll for detail")
        self.opacity_button = tk.Button(self.hud_chrome.footer, text="Glass 94%", command=self.cycle_opacity,
                                        bg=BG, fg=MUTED, activebackground=PANEL, activeforeground=TEXT,
                                        relief="flat", bd=0, font=self.hud_fonts.get(8), cursor="hand2")
        self.opacity_button.pack(side="right", padx=8)
        self.hud.bind("<Escape>", lambda e: self.hud.withdraw())
        toolbar = tk.Frame(self.hud_chrome.body, bg=BG, padx=self.hp(16), pady=self.hp(8))
        toolbar.pack(fill="x")
        self.zoom_toolbar = toolbar
        tk.Label(toolbar, text="Text", bg=BG, fg=MUTED, font=self.hud_fonts.get(9)).pack(side="left", padx=(0, self.hp(12)))
        self.zoom_out = self.zoom_button(toolbar, "A−", lambda: self.set_hud_zoom(self.hud_zoom - 0.1))
        self.zoom_label = tk.Label(toolbar, text=f"{self.hud_zoom:.0%}", bg=BG, fg=TEXT, font=self.hud_fonts.get(9))
        self.zoom_label.pack(side="left", padx=self.hp(8))
        self.zoom_in = self.zoom_button(toolbar, "A+", lambda: self.set_hud_zoom(self.hud_zoom + 0.1))
        self.zoom_reset = self.zoom_button(toolbar, "Reset", lambda: self.set_hud_zoom(1.0))
        for sequence in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.hud.bind(sequence, lambda e: self.set_hud_zoom(self.hud_zoom + 0.1))
        for sequence in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.hud.bind(sequence, lambda e: self.set_hud_zoom(self.hud_zoom - 0.1))
        self.hud.bind("<Control-0>", lambda e: self.set_hud_zoom(1.0))
        canvas = tk.Canvas(self.hud_chrome.body, bg=BG, highlightthickness=0)
        self.hud_canvas = canvas
        canvas.pack(side="left", fill="both", expand=True)
        self.hud_body = tk.Frame(canvas, bg=BG, padx=self.hp(16), pady=self.hp(12))
        body_id = canvas.create_window((0, 0), window=self.hud_body, anchor="nw")
        self.hud_body_id = body_id
        self.hud_body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: self.layout_hud(e.width, body_id))
        self.hud.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units"))
        self.hud.bind("<Control-MouseWheel>", self.zoom_wheel)
        self.hud.bind("<Configure>", self.schedule_monitor_refresh, add="+")
        self.capture_status = self.label(self.hud_body, "● Connecting to practice table", 9, ACCENT)
        summary = self.panel(self.hud_body, "CURRENT HAND")
        self.state_label = self.label(summary, "", 10, MUTED)
        self.cards_label = self.label(summary, "", 22, TEXT, True)
        self.board_label = self.label(summary, "Board not dealt", 11, MUTED)
        self.pot_label = self.label(summary, "", 11, TEXT)
        self.columns = tk.Frame(self.hud_body, bg=BG)
        self.columns.pack(fill="x")
        self.analysis_column = tk.Frame(self.columns, bg=BG)
        self.detail_column = tk.Frame(self.columns, bg=BG)
        odds = self.panel(self.analysis_column, "PROBABILITIES")
        numbers = tk.Frame(odds, bg=PANEL)
        numbers.pack(fill="x", pady=(4, 7))
        for column in (0, 1):
            numbers.columnconfigure(column, weight=1)
        self.equity_number = tk.Label(numbers, text="—", bg=PANEL, fg=ACCENT, font=self.hud_fonts.get(26, True), anchor="w")
        self.equity_number.grid(row=0, column=0, sticky="w")
        self.price_number = tk.Label(numbers, text="—", bg=PANEL, fg=TEXT, font=self.hud_fonts.get(26, True), anchor="w")
        self.price_number.grid(row=0, column=1, sticky="w")
        for col, text in enumerate(("RANGE EQUITY", "BREAK-EVEN")):
            tk.Label(numbers, text=text, bg=PANEL, fg=MUTED, font=self.hud_fonts.get(8)).grid(row=1, column=col, sticky="w")
        self.chart = tk.Canvas(odds, width=300, height=self.hp(47), bg=PANEL, highlightthickness=0)
        self.chart.pack(fill="x", pady=6)
        self.chart.bind("<Configure>", lambda e: self.draw_chart())
        self.metrics = self.label(odds, "Waiting for your turn", 9, MUTED)
        decision = self.panel(self.analysis_column, "YOUR DECISION")
        self.recommendation = self.label(decision, "Waiting for your turn", 16, ACCENT, True)
        self.action_label = self.label(decision, "", 11)
        self.assumptions = self.label(decision, "", 9, MUTED)
        evidence = self.panel(self.detail_column, "OPPONENT EVIDENCE")
        self.profile_label = self.label(evidence, "", 10, MUTED)
        recent = self.panel(self.detail_column, "ACTION HISTORY")
        self.events_label = self.label(recent, "", 10, MUTED)
        self.label(self.hud_body, "Local practice · estimates depend on assumed ranges and response models.", 8, MUTED)
        self.root.bind("h", lambda e: self.open_hud())

    def hp(self, pixels):
        return max(1, round(pixels * self.hud_scale))

    def hud_minimum(self):
        width, height, _, _ = self.hud_display.fit(360 * self.hud_scale, 440 * self.hud_scale)
        return width, height

    def zoom_button(self, parent, text, command):
        button = tk.Button(parent, text=text, command=command, bg=PANEL, fg=TEXT, bd=0,
                           activebackground="#303b48", activeforeground=TEXT, cursor="hand2",
                           font=self.hud_fonts.get(9), padx=self.hp(8), pady=self.hp(3))
        button.pack(side="left", padx=self.hp(3))
        return button

    def zoom_wheel(self, event):
        self.set_hud_zoom(self.hud_zoom + (0.1 if event.delta > 0 else -0.1))
        return "break"

    def set_hud_zoom(self, zoom):
        self.preferences.save(zoom)
        self.hud_zoom = self.preferences.zoom
        self.refresh_hud_scale()

    def refresh_hud_scale(self):
        self.hud_scale = self.hud_display.scale * self.hud_zoom
        self.hud_fonts.set_scale(self.hud_scale)
        self.hud_chrome.set_scale(self.hud_scale)
        self.hud_chrome.minimum = self.hud_minimum()
        self.hud.minsize(*self.hud_chrome.minimum)
        self.zoom_label.configure(text=f"{self.hud_zoom:.0%}")
        self.hud_body.configure(padx=self.hp(16), pady=self.hp(12))
        self.zoom_toolbar.configure(padx=self.hp(16), pady=self.hp(8))
        self.chart.configure(height=self.hp(47))
        def restyle(parent):
            for widget in parent.winfo_children():
                if getattr(widget, "_hud_panel", False):
                    widget.configure(padx=self.hp(16), pady=self.hp(11))
                    widget.pack_configure(pady=(0, self.hp(10)))
                elif isinstance(widget, tk.Label) and widget.winfo_manager() == "pack":
                    widget.pack_configure(pady=self.hp(3))
                restyle(widget)
        restyle(self.hud_body)
        if not self.hud_chrome.maximized:
            minimum_width, minimum_height = self.hud_minimum()
            self.hud.geometry(geometry(self.hud_display.fit(max(self.hud.winfo_width(), minimum_width),
                                          max(self.hud.winfo_height(), minimum_height), self.hud.winfo_x(), self.hud.winfo_y())))
        self.layout_hud(self.hud_canvas.winfo_width(), self.hud_body_id)
        self.draw_chart()

    def schedule_monitor_refresh(self, event):
        if event.widget != self.hud or not self.watch_monitor:
            return
        if self.monitor_job:
            self.root.after_cancel(self.monitor_job)
        self.monitor_job = self.root.after(250, self.refresh_monitor)

    def refresh_monitor(self):
        self.monitor_job = None
        display = Display.detect(self.hud)
        changed = display.scale != self.hud_display.scale
        self.hud_display = display
        if changed:
            self.refresh_hud_scale()

    def open_hud(self):
        if hasattr(self, "hud_chrome"):
            self.hud_chrome.restore()

    def cycle_opacity(self):
        levels = (0.94, 0.88, 1.0)
        current = float(self.hud.attributes("-alpha"))
        index = min(range(len(levels)), key=lambda i: abs(levels[i] - current))
        opacity = levels[(index + 1) % len(levels)]
        self.hud.attributes("-alpha", opacity)
        self.opacity_button.configure(text=f"Glass {opacity:.0%}")

    def layout_hud(self, width, body_id):
        self.hud_canvas.itemconfigure(body_id, width=width)
        wide = width >= self.hp(740)
        self.columns.columnconfigure(0, weight=3, uniform="hud")
        self.columns.columnconfigure(1, weight=2 if wide else 0, uniform="hud" if wide else "")
        self.analysis_column.grid(row=0, column=0, sticky="nsew", padx=(0, self.hp(10) if wide else 0))
        self.detail_column.grid(row=0 if wide else 1, column=1 if wide else 0, sticky="nsew")

    def resize_table(self, event=None):
        if self.table_frame is None:
            return
        scale = max(0.5, min(self.viewport.winfo_width() / WIDTH, self.viewport.winfo_height() / HEIGHT))
        size = (round(WIDTH * scale), round(HEIGHT * scale))
        view_w, view_h = self.viewport.winfo_width(), self.viewport.winfo_height()
        self.viewport.configure(scrollregion=(0, 0, max(view_w, size[0]), max(view_h, size[1])))
        self.viewport.coords(self.table_window, max(0, (view_w - size[0]) // 2), max(0, (view_h - size[1]) // 2))
        self.viewport.itemconfigure(self.table_window, width=size[0], height=size[1])
        if size == self.table_size and event is not None:
            return
        self.table_size = size
        frame = self.table_frame if size == (WIDTH, HEIGHT) else self.table_frame.resize(size, Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(frame)
        self.table.configure(image=self.photo)

    def draw(self):
        self.table_frame = render(self.game)
        self.resize_table()
        legal = self.game.legal()
        turn = self.game.actor == 0
        self.fold.configure(state="normal" if turn else "disabled")
        self.call.configure(state="normal" if turn else "disabled", text=f"Call {legal.get('call', 0)}" if legal.get("call") else "Check")
        self.raise_button.configure(state="normal" if turn and legal.get("min_raise") else "disabled")
        self.next_button.configure(state="normal" if self.game.actor < 0 else "disabled")
        if turn and legal.get("min_raise"):
            self.raise_to.set(str(legal["min_raise"]))

    def invalidate(self, message):
        self.current_key = None
        self.advice = None
        self.recommendation.configure(text=message)
        self.action_label.configure(text="")
        self.assumptions.configure(text="")
        self.metrics.configure(text="")
        self.equity_number.configure(text="—")
        self.price_number.configure(text="—")
        self.chart.delete("all")

    def new_hand(self):
        if self.game.actor >= 0:
            return
        self.game.new_hand()
        self.invalidate("Reading new hand…")
        self.draw()

    def hero_action(self, action):
        try:
            target = int(self.raise_to.get()) if action == "R" else 0
            self.game.act(action, target)
            self.invalidate("Waiting for your next decision…")
            self.draw()
        except ValueError as exc:
            self.message.set(str(exc))

    def call_action(self):
        self.hero_action("K" if self.game.legal().get("check") else "C")

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.configure(text="Resume bots" if self.paused else "Pause bots")

    def bot_tick(self):
        if self.closed:
            return
        if not self.paused and self.game.actor not in (-1, 0):
            self.game.act(*choose_action(self.game))
            self.invalidate("Waiting for your turn…")
            self.draw()
        self.root.after(1400, self.bot_tick)

    def observe(self):
        if self.closed:
            return
        try:
            if not self.root.winfo_viewable() or self.chrome.native.minimized():
                raise ReadError("Practice window is minimized")
            o = self.reader.read(capture_widget(self.table))
            self.tracker.accept(o)
            self.history.record(self.session, o.hand, self.tracker.events)
            self.latest = o
            self.last_seen = time.monotonic()
            self.last_error = None
            key = (o.hand, o.street, o.actor, len(self.tracker.events))
            if key != self.current_key:
                self.invalidate("Calculating…" if o.actor == 0 else "Waiting for your turn…")
                self.current_key = key
                self.update_observed(o)
            self.capture_status.configure(text=f"● Observing practice table   ·   Hand {o.hand}", fg=ACCENT)
            if self.future is not None and self.future.done():
                future, job_key = self.future, self.future_key
                self.future = None
                result = future.result()
                if job_key == self.current_key:
                    self.show_advice(result)
            if o.actor == 0 and self.advice is None and self.future is None:
                profiles = [self.history.profile(i) for i in range(6)]
                self.future_key = key
                self.future = self.executor.submit(analyze, o, profiles, tuple(self.tracker.events), self.samples)
        except (ReadError, OSError, ValueError) as exc:
            self.last_error = str(exc)
            self.capture_status.configure(text=f"○ Capture paused: {exc}", fg="#e8b18d")
            self.invalidate("Advice withheld · verify table visibility")
            self.state_label.configure(text="State unverified")
            self.cards_label.configure(text="")
            self.board_label.configure(text="")
            self.pot_label.configure(text="")
        self.root.after(200, self.observe)

    def update_observed(self, o):
        streets = {"P": "PREFLOP", "F": "FLOP", "T": "TURN", "R": "RIVER", "X": "COMPLETE"}
        position = ["BTN", "SB", "BB", "UTG", "HJ", "CO"][(0 - o.button) % 6]
        self.state_label.configure(text=f"{streets[o.street]}   /   {position}")
        symbols = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}
        pretty = lambda cards: "   ".join(c[0] + symbols[c[1]] for c in cards)
        self.cards_label.configure(text=pretty(o.hole))
        self.board_label.configure(text=pretty(o.board) or "Board not dealt")
        self.pot_label.configure(text=f"Pot  {o.pot}     ·     To call  {o.call}")
        rows = []
        for i in range(1, 6):
            p = self.history.profile(i)
            rows.append(f"{NAMES[i]} · {p.hands} preflop decisions\n"
                        f"  VPIP {p.vpip_count}/{p.hands} · PFR {p.pfr_count}/{p.hands} · Fold vs bet {p.folds}/{p.faced}")
        self.profile_label.configure(text="\n".join(rows))
        descriptions = {"B": "blind", "F": "fold", "K": "check", "C": "call", "R": "raise"}
        self.events_label.configure(text="\n".join(f"{NAMES[e.seat]} · {e.street} · {descriptions[e.action]}"
                                                  + (f" +{e.amount}" if e.amount else "") for e in self.tracker.events[-5:]))

    def show_advice(self, advice):
        if advice is None:
            return
        self.advice = advice
        eq = advice.equity
        method = f"Exact enumeration · {eq.samples} combinations" if eq.exact else f"Monte Carlo · {eq.samples} samples"
        interval = "" if eq.exact else f" ± {1.96 * eq.standard_error:.1%} sampling"
        self.equity_number.configure(text=f"{eq.share:.0%}")
        self.price_number.configure(text=f"{advice.threshold:.0%}" if advice.actions else "—")
        self.metrics.configure(text=f"{advice.hand_name} · {method}" + (f"\n{interval.strip()}" if interval else ""))
        self.draw_chart()
        self.recommendation.configure(text=advice.recommendation.replace(" · best modeled EV", ""))
        self.action_label.configure(text="\n".join(f"{a.label}: {a.ev:+.1f} chips" +
                                                   (f" ± {1.96 * a.error:.1f} sampling" if a.error else "")
                                                   for a in advice.actions))
        self.assumptions.configure(text=advice.assumptions)

    def draw_chart(self):
        self.chart.delete("all")
        if self.advice is None:
            return
        right = max(120, self.chart.winfo_width() - 4)
        for y, value, color in ((self.hp(12), self.advice.equity.share, ACCENT), (self.hp(35), self.advice.threshold, "#8b9db6")):
            self.chart.create_rectangle(0, y - self.hp(4), right, y + self.hp(4), fill="#293342", outline="")
            if self.advice.actions or y == self.hp(12):
                self.chart.create_rectangle(0, y - self.hp(4), right * value, y + self.hp(4), fill=color, outline="")

    def close(self):
        if self.closed:
            return
        self.closed = True
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.history.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Pokato local practice table and screen-reading coach")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--samples", type=int, default=400)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if not 50 <= args.samples <= 10000:
        parser.error("--samples must be between 50 and 10000")
    enable_dpi_awareness()
    root = tk.Tk()
    App(root, args.seed, args.samples, args.database)
    root.mainloop()


if __name__ == "__main__":
    main()
