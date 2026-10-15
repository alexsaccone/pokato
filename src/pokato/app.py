"""Desktop composition root. Simulator truth never enters the coach pipeline."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
import uuid
from PIL import ImageTk
from pokato.core.game import Game
from pokato.simulator.bots import choose_action
from pokato.simulator.render import render, NAMES
from pokato.simulator.layout import WIDTH, HEIGHT
from pokato.vision.capture import capture_widget, enable_dpi_awareness
from pokato.vision.reader import Reader, ReadError
from pokato.vision.tracker import Tracker
from pokato.analysis.history import History
from pokato.analysis.coach import analyze

BG, PANEL, TEXT, MUTED, ACCENT = "#101c1d", "#192c29", "#e4eee7", "#9db5a9", "#e2c38a"


class App:
    def __init__(self, root, seed=7, samples=400, database=None):
        self.root, self.samples = root, samples
        # The V1 optical layout uses physical pixels. Keep Tk typography in
        # that same coordinate system even on 200%/250% Windows displays.
        root.tk.call("tk", "scaling", 96 / 72)
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
        root.configure(bg=BG)
        root.resizable(False, False)
        root.geometry("+30+30")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.table = tk.Label(root, borderwidth=0, highlightthickness=0, bg=BG)
        self.table.pack()
        controls = tk.Frame(root, bg=BG, padx=18, pady=10)
        controls.pack(fill="x")
        self.fold = self.button(controls, "Fold", lambda: self.hero_action("F"))
        self.call = self.button(controls, "Check", self.call_action)
        tk.Label(controls, text="Raise to", bg=BG, fg=MUTED).pack(side="left", padx=(12, 4))
        self.raise_to = tk.StringVar(value="30")
        self.raise_entry = tk.Entry(controls, textvariable=self.raise_to, width=8, bg=PANEL, fg=TEXT, insertbackground=TEXT)
        self.raise_entry.pack(side="left", padx=4)
        self.raise_button = self.button(controls, "Raise", lambda: self.hero_action("R"))
        self.next_button = self.button(controls, "Deal next hand", self.new_hand)
        self.pause_button = self.button(controls, "Pause bots", self.toggle_pause)
        self.message = tk.StringVar(value="Practice chips · automatic rebuy at 0 · window capture reads only the local table")
        tk.Label(root, textvariable=self.message, bg=BG, fg=MUTED, anchor="w", padx=18, pady=5).pack(fill="x")
        self.build_hud()
        self.new_hand()
        root.after(350, self.observe)
        root.after(1400, self.bot_tick)

    @staticmethod
    def button(parent, text, command):
        button = tk.Button(parent, text=text, command=command, bg=PANEL, fg=TEXT,
                           activebackground="#325449", activeforeground=TEXT, relief="flat", padx=12, pady=7)
        button.pack(side="left", padx=4)
        return button

    def label(self, text="", size=11, color=TEXT, bold=False, wrap=310):
        label = tk.Label(self.hud_body, text=text, bg=BG, fg=color, justify="left", anchor="w",
                         font=("Segoe UI", size, "bold" if bold else "normal"), wraplength=wrap)
        label.pack(fill="x", pady=4)
        return label

    def build_hud(self):
        self.hud = tk.Toplevel(self.root)
        self.hud.title("Pokato · practice coach")
        self.hud.configure(bg=BG)
        self.hud.geometry(f"410x840+{min(1035, self.root.winfo_screenwidth() - 430)}+30")
        self.hud.minsize(380, 500)
        self.hud.attributes("-topmost", True)
        self.hud.protocol("WM_DELETE_WINDOW", self.hud.withdraw)
        # Scrollable body also works on laptops shorter than the full panel.
        canvas = tk.Canvas(self.hud, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.hud, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        self.hud_body = tk.Frame(canvas, bg=BG, padx=18, pady=14)
        body_id = canvas.create_window((0, 0), window=self.hud_body, anchor="nw")
        self.hud_body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_id, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units"))
        self.label("POKATO / COACH", 17, ACCENT, True)
        self.label("LOCAL SIMULATOR · PIXEL INPUT", 9, MUTED)
        self.capture_status = self.label("Waiting for the first screen capture…", 10, MUTED)
        self.state_label = self.label("", 12, TEXT, True)
        self.cards_label = self.label("", 14, ACCENT, True)
        self.metrics = self.label("", 11)
        self.chart = tk.Canvas(self.hud_body, width=350, height=70, bg=BG, highlightthickness=0)
        self.chart.pack(fill="x", pady=6)
        self.recommendation = self.label("Waiting for your turn", 13, ACCENT, True)
        self.action_label = self.label("", 11)
        self.assumptions = self.label("", 9, MUTED)
        self.label("OBSERVED OPPONENTS", 11, TEXT, True)
        self.profile_label = self.label("", 10, MUTED)
        self.label("RECENT ACTIONS", 11, TEXT, True)
        self.events_label = self.label("", 10, MUTED)
        self.label("Ranges and response models are heuristic. This prototype does not solve poker or predict winnings.", 9, MUTED)
        self.label("Window capture reads only the practice table. Minimize it to stop advice. Reopen HUD with H.", 9, MUTED)
        self.root.bind("h", lambda e: self.hud.deiconify())

    def draw(self):
        self.photo = ImageTk.PhotoImage(render(self.game))
        self.table.configure(image=self.photo)
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
            if not self.root.winfo_viewable():
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
            self.capture_status.configure(text=f"Screen verified · template match {o.confidence:.1%} · hand {o.hand}")
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
            self.capture_status.configure(text=f"Capture paused: {exc}")
            self.invalidate("Advice withheld · verify table visibility")
            self.state_label.configure(text="State unverified")
            self.cards_label.configure(text="")
        self.root.after(200, self.observe)

    def update_observed(self, o):
        streets = {"P": "PREFLOP", "F": "FLOP", "T": "TURN", "R": "RIVER", "X": "COMPLETE"}
        position = ["BTN", "SB", "BB", "UTG", "HJ", "CO"][(0 - o.button) % 6]
        self.state_label.configure(text=f"{streets[o.street]} · You: {position}\nPot {o.pot} · To call {o.call} chips")
        self.cards_label.configure(text=f"{' '.join(o.hole)}\n{' '.join(o.board) or 'Board not dealt'}")
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
        odds = f"Break-even equity {advice.threshold:.1%}" if advice.actions else "Per-pot odds unavailable"
        self.metrics.configure(text=f"{advice.hand_name}\nRange equity {eq.share:.1%}{interval}\n{odds}\n{method}")
        self.chart.delete("all")
        for y, label, value, color in ((15, "Equity", eq.share, "#86c6a4"), (45, "Price", advice.threshold, ACCENT)):
            self.chart.create_text(0, y, text=label, fill=MUTED, anchor="w", font=("Segoe UI", 10))
            self.chart.create_rectangle(60, y - 7, 340, y + 7, fill=PANEL, outline="")
            if advice.actions or label == "Equity":
                self.chart.create_rectangle(60, y - 7, 60 + 280 * value, y + 7, fill=color, outline="")
        self.recommendation.configure(text=advice.recommendation)
        self.action_label.configure(text="\n".join(f"{a.label}: {a.ev:+.1f} chips" +
                                                   (f" ± {1.96 * a.error:.1f} sampling" if a.error else "")
                                                   for a in advice.actions))
        self.assumptions.configure(text=advice.assumptions)

    def close(self):
        if self.closed:
            return
        self.closed = True
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
