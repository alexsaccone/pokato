"""Saved-hand review. Every edit is a scenario separate from the original."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import tkinter as tk
from PIL import Image, ImageTk
from pokato.analysis.coach import analyze
from pokato.analysis.ranges import parse_range
from pokato.core.cards import display_card, display_notation, normalize_notation
from pokato.replay.render import render_observation
from pokato.replay.store import observation_from_dict, validate_observation
from pokato.simulator.render import NAMES
from .window import WindowChrome, BG, TEXT, MUTED, ACCENT
from .sizing import geometry

PANEL = "#1a212c"


class ReplayWindow:
    def __init__(self, app):
        self.app, self.archive = app, app.archive
        self.scale = max(1.0, min(1.6, app.display.compact_scale))
        self.window = tk.Toplevel(app.root)
        self.window.title("Pokato · saved-hand review")
        self.window.geometry(geometry(app.display.fit(1400 * self.scale, 1000 * self.scale)))
        self.closed = False
        self.was_paused = app.paused
        app.paused = True
        app.pause_button.configure(text="Review open", state="disabled")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pokato-replay")
        self.future = self.pending = None
        self.revision = 0
        self.hands, self.snapshots = [], []
        self.index, self.hand_index = 0, 0
        self.scenario_o = None
        self.chrome = WindowChrome(self.window, "pokato", "SAVED HAND REVIEW", self.close,
                                   minimum=(min(1000, app.display.width), min(650, app.display.height)), scale=self.scale)
        self.chrome.hint.configure(text="Practice bots paused during review · originals remain unchanged")
        body = self.chrome.body
        left = tk.Frame(body, bg=BG, padx=12, pady=12)
        left.pack(side="left", fill="y")
        self.label(left, "SAVED HANDS", bold=True).pack(anchor="w")
        self.button(left, "Refresh", self.refresh).pack(fill="x", pady=8)
        self.hand_list = tk.Listbox(left, width=27, bg=PANEL, fg=TEXT, selectbackground="#344b4a",
                                   font=("Segoe UI", -round(15*self.scale)), exportselection=False, bd=0, highlightthickness=0)
        self.hand_list.pack(fill="both", expand=True)
        self.hand_list.bind("<<ListboxSelect>>", self.select_hand)
        content = tk.Frame(body, bg=BG, padx=12, pady=12)
        content.pack(side="left", fill="both", expand=True)
        self.heading = self.label(content, "No saved hands yet", 20, True)
        self.heading.pack(fill="x")
        self.navigation = tk.Frame(content, bg=BG)
        self.navigation.pack(fill="x", pady=6)
        for title, command in (("First", lambda: self.select_snapshot(0)),
                               ("Previous", lambda: self.select_snapshot(self.index - 1)),
                               ("Next", lambda: self.select_snapshot(self.index + 1)),
                               ("Next decision", self.next_decision),
                               ("Last", lambda: self.select_snapshot(len(self.snapshots) - 1))):
            self.button(self.navigation, title, command).pack(side="left", padx=(0, 5))
        self.position = self.label(content, "", color=MUTED)
        self.position.pack(fill="x")
        main = tk.Frame(content, bg=BG)
        main.pack(fill="both", expand=True, pady=8)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)
        table_side = tk.Frame(main, bg=BG)
        table_side.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.preview = tk.Label(table_side, bg=BG, bd=0)
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Configure>", lambda e: self.draw_snapshot())
        self.actions = tk.Text(table_side, height=5, bg=PANEL, fg=MUTED, wrap="word", bd=0, font=("Segoe UI", -round(14*self.scale)))
        self.actions.pack(fill="x", pady=(8, 0))
        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        self.label(right, "OPPONENT RANGES", 16, True).pack(anchor="w")
        self.label(right, "Auto uses evidence saved at this point.\nExamples: QQ+, ATs+, AKo, A♠K♥:0.5\n* = all combinations; weights 0–1.\nFolded players' ranges have no effect.", color=MUTED).pack(fill="x", pady=6)
        self.range_entries = {}
        for seat in range(1, 6):
            self.label(right, NAMES[seat], 14).pack(anchor="w", pady=(3, 0))
            var = tk.StringVar(value="Auto")
            entry = tk.Entry(right, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                             font=("Consolas", -round(15*self.scale)), relief="flat")
            entry.pack(fill="x", ipady=4)
            entry.bind("<KeyRelease>", self.edited_ranges)
            self.range_entries[seat] = var
        toolbar = tk.Frame(right, bg=BG)
        toolbar.pack(fill="x", pady=10)
        self.calculate_button = self.button(toolbar, "Calculate & save", self.calculate)
        self.calculate_button.pack(side="left", padx=(0, 5))
        self.button(toolbar, "Reset", self.reset).pack(side="left", padx=(0, 5))
        self.button(right, "Correct state…", self.correct_state).pack(anchor="w")
        self.status = self.label(right, "Select an observed decision.", color=ACCENT)
        self.status.configure(wraplength=round(340*self.scale))
        self.status.pack(fill="x", pady=8)
        self.output = tk.Text(right, height=12, bg=PANEL, fg=TEXT, wrap="word", bd=0, font=("Consolas", -round(14*self.scale)))
        self.output.pack(fill="both", expand=True)
        self.refresh()
        self.poll_job = self.window.after(100, self.poll)

    def label(self, parent, text, size=15, bold=False, color=TEXT):
        return tk.Label(parent, text=text, bg=BG, fg=color, anchor="w", justify="left",
                        font=("Segoe UI", -round(size*self.scale), "bold" if bold else "normal"))

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=PANEL, fg=TEXT, bd=0,
                         activebackground="#344b4a", activeforeground=TEXT, padx=10, pady=7,
                         font=("Segoe UI", -round(14*self.scale)), cursor="hand2")

    @staticmethod
    def write(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh(self):
        self.hands = self.archive.hands()
        self.hand_list.delete(0, "end")
        for hand in self.hands:
            stamp = datetime.fromisoformat(hand.created.replace("Z", "+00:00")).astimezone().strftime("%m/%d %H:%M")
            self.hand_list.insert("end", f"{stamp} · #{hand.hand} · {'complete' if hand.completed else 'partial'}")
        if self.hands:
            self.hand_list.selection_set(0)
            self.select_hand()
        else:
            self.status.configure(text="Play a hand to save observations. Legacy statistics do not contain replay snapshots.")

    def select_hand(self, event=None):
        selection = self.hand_list.curselection()
        if not selection:
            return
        self.hand_index = selection[0]
        hand = self.hands[self.hand_index]
        self.snapshots = self.archive.snapshots(hand.session, hand.hand)
        initial = next((i for i, s in enumerate(self.snapshots) if s.observation.actor == 0), 0)
        self.select_snapshot(initial)

    def invalidate(self):
        self.revision += 1
        self.pending = None
        self.write(self.output, "")
        if hasattr(self, "last_results"):
            del self.last_results
        self.calculate_button.configure(state="normal")

    def edited_ranges(self, event=None):
        for var in self.range_entries.values():
            formatted = display_notation(var.get())
            if formatted != var.get():
                var.set(formatted)
        self.invalidate()
        self.status.configure(text="Range edits pending. Calculate to compare and save.")

    def select_snapshot(self, index):
        if not self.snapshots:
            return
        self.invalidate()
        self.index = max(0, min(index, len(self.snapshots) - 1))
        snapshot = self.snapshots[self.index]
        hand = self.hands[self.hand_index]
        saved = self.archive.scenario(hand.session, hand.hand, len(snapshot.events))
        self.scenario_o = observation_from_dict(saved["observation"]) if saved else snapshot.observation
        for seat, var in self.range_entries.items():
            var.set(display_notation(saved["ranges"].get(str(seat), "Auto")) if saved else "Auto")
        o = self.scenario_o
        self.heading.configure(text=f"Hand #{o.hand} · {'saved scenario' if saved else 'original observation'}")
        self.update_position()
        self.write(self.actions, "\n".join(f"#{e.seq} {NAMES[e.seat]} · {e.street} · {e.action} +{e.amount}"
                                         for e in snapshot.events))
        self.actions.see("end")
        self.status.configure(text="Calculate to compare original and scenario." if o.actor == 0 else "Browse to your turn to calculate action EV.")
        self.draw_snapshot()

    def update_position(self):
        o = self.scenario_o
        self.position.configure(text=f"Snapshot {self.index + 1}/{len(self.snapshots)} · {o.street} · "
                                     f"Turn: {NAMES[o.actor] if o.actor >= 0 else 'complete'} · "
                                     f"Pot {o.pot} · Call {o.call}")

    def draw_snapshot(self):
        if self.scenario_o is None or self.closed:
            return
        frame = render_observation(self.scenario_o)
        w, h = max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height())
        scale = min(w / frame.width, h / frame.height)
        frame = frame.resize((max(1, round(frame.width * scale)), max(1, round(frame.height * scale))), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(frame)
        self.preview.configure(image=self.photo)

    def next_decision(self):
        for i in range(self.index + 1, len(self.snapshots)):
            if self.snapshots[i].observation.actor == 0:
                self.select_snapshot(i)
                return
        self.status.configure(text="No later observed decision for you in this hand.")

    def calculate(self):
        self.invalidate()
        if self.scenario_o is None or self.scenario_o.actor != 0:
            self.status.configure(text="Select your turn first.")
            return
        try:
            ranges, expressions = {}, {}
            for seat, var in self.range_entries.items():
                var.set(display_notation(var.get()))
                expression = normalize_notation(var.get().strip())
                expressions[str(seat)] = expression or "Auto"
                if expression and expression.lower() != "auto":
                    ranges[seat] = parse_range(expression)
                    if self.scenario_o.seats[seat].status != "F" and not ranges[seat].available(self.scenario_o.hole + self.scenario_o.board):
                        raise ValueError(f"{NAMES[seat]}'s range is fully blocked by known cards")
            snapshot = self.snapshots[self.index]
            self.pending = (self.revision, snapshot, self.scenario_o, ranges, expressions)
            self.calculate_button.configure(state="disabled")
            self.status.configure(text="Calculating original and scenario…")
        except ValueError as exc:
            self.status.configure(text=str(exc))

    def poll(self):
        if self.closed:
            return
        if self.future is not None and self.future.done():
            future, data = self.future, self.job
            self.future = None
            if data[0] == self.revision:
                self.calculate_button.configure(state="normal")
                try:
                    original, scenario = future.result()
                    self.show_results(original, scenario)
                    hand = self.hands[self.hand_index]
                    self.archive.save_scenario(hand.session, hand.hand, len(data[1].events), data[2], data[4])
                    self.heading.configure(text=f"Hand #{data[2].hand} · saved scenario")
                    self.status.configure(text="Scenario saved. Originals unchanged. See results for sampling and policy sensitivity limits.")
                except ValueError as exc:
                    self.status.configure(text=str(exc))
        if self.future is None and self.pending is not None:
            self.job, self.pending = self.pending, None
            self.future = self.executor.submit(self.work, self.job, self.app.samples)
        self.poll_job = self.window.after(100, self.poll)

    @staticmethod
    def work(data, samples):
        _, snapshot, o, ranges, _ = data
        original = analyze(snapshot.observation, snapshot.profiles, snapshot.events, samples, models=snapshot.models)
        scenario = original if not ranges and o == snapshot.observation else analyze(
            o, snapshot.profiles, snapshot.events, samples, ranges, snapshot.models)
        return original, scenario

    def show_results(self, original, scenario):
        if original is None or scenario is None:
            self.write(self.output, "No decision to analyze at this snapshot.")
            return
        lines = ["ACTION            ORIGINAL   SCENARIO    DELTA"]
        before = {a.label: a.ev for a in original.actions}
        after = {a.label: a.ev for a in scenario.actions}
        for action in dict.fromkeys([*before, *after]):
            a, b = before.get(action), after.get(action)
            lines.append(f"{action:<17} {a:+8.1f}" if a is not None else f"{action:<17}      n/a")
            lines[-1] += f" {b:+9.1f}" if b is not None else "       n/a"
            lines[-1] += f" {b-a:+8.1f}" if a is not None and b is not None else "      n/a"
        if scenario.uncertainty:
            u = scenario.uncertainty
            lines.extend(["", "APPROXIMATE 80% POLICY SENSITIVITY", u.summary(scenario.actions[0].label),
                          f"{u.draws} policies · {u.hands}/{u.total_hands} prior hands · seed {u.seed}",
                          f"Mean-policy quadrature shift: {u.quadrature_shift:.1f} chips (not an error bound)"])
            for a in u.actions:
                lines.append(f"{a.label}: [{a.low:+.1f}, {a.high:+.1f}] chips · preferred in {a.best_fraction:.0%} of draws")
        eq = scenario.equity
        lines.extend(["", f"Scenario: {scenario.recommendation}",
                      f"Pot-weighted equity: {eq.share:.1%}",
                      f"{'Exact' if eq.exact else 'Sampled'} · {eq.samples} deals", "", "POTS AFTER CHECK/CALL"])
        for i, pot in enumerate(scenario.pots, 1):
            label = "Refund" if pot.refund else f"Pot {i}"
            lines.append(f"{label}: {pot.amount} chips · eligible {','.join(NAMES[s] for s in pot.eligible)}")
            lines.append(f"  Your payout {pot.hero_award:.2f} ± {1.96 * pot.error:.2f} sampling")
        if scenario.engine not in ("river-tree", "turn-tree"):
            lines.extend(["", "EV SAMPLING INTERVALS"] + [f"{a.label}: ±{1.96*a.error:.2f} chips" for a in scenario.actions])
        else:
            lines.extend(["", "Finite-tree EVs use exact integration. Response/range uncertainty is not an EV confidence interval."])
        if scenario.engine in ("river-tree", "turn-tree"):
            street = "TURN / RIVER" if scenario.engine == "turn-tree" else "RIVER"
            lines.extend(["", f"{street} TREE · {scenario.nodes} decision nodes", "SESSION RESPONSE MODEL · 90% POSTERIOR INTERVALS",
                          *scenario.evidence, "", "FIRST OPPONENT RESPONSE / HERO CONTINUATION"])
            for b in scenario.branches:
                lines.append(f"{b.action} → {b.response}: {b.probability:.1%}; then {b.continuation}; EV {b.ev:+.1f}")
        if scenario.runouts:
            lines.extend(["", "RIVER CARD / PROBABILITY / SHOWDOWN EQUITY", "Current range, before future betting; no sampling error."])
            for r in sorted(scenario.runouts, key=lambda r: r.share, reverse=True):
                lines.append(f"{display_card(r.card)}: {r.probability:.2%} / {r.share:.1%}")
        lines.extend(["", scenario.assumptions])
        self.write(self.output, "\n".join(lines))
        self.last_results = (original, scenario)

    def reset(self):
        if not self.snapshots:
            return
        hand = self.hands[self.hand_index]
        self.archive.reset_scenario(hand.session, hand.hand, len(self.snapshots[self.index].events))
        self.select_snapshot(self.index)

    def correct_state(self):
        if self.scenario_o is not None:
            CorrectionDialog(self)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.window.after_cancel(self.poll_job)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.app.paused = self.was_paused
        self.app.pause_button.configure(text="Resume bots" if self.was_paused else "Pause bots", state="normal")
        self.window.destroy()


class CorrectionDialog:
    def __init__(self, review):
        self.review, self.original = review, review.scenario_o
        self.window = tk.Toplevel(review.window)
        self.window.title("Correct scenario state")
        self.window.configure(bg=BG)
        self.window.transient(review.window)
        self.window.grab_set()
        frame = tk.Frame(self.window, bg=BG, padx=20, pady=20)
        frame.pack(fill="both", expand=True)
        review.label(frame, "Edit scenario only · original observations stay unchanged", 17, True).grid(row=0, column=0, columnspan=5, pady=8)
        self.vars = {}
        for row, (key, value) in enumerate((("hole", display_notation(" ".join(self.original.hole))),
                                          ("board", display_notation(" ".join(self.original.board)))), 1):
            review.label(frame, key.title()).grid(row=row, column=0, sticky="w")
            self.vars[key] = tk.StringVar(value=value)
            def format_input(*args, var=self.vars[key]):
                formatted = display_notation(var.get())
                if formatted != var.get():
                    var.set(formatted)
            self.vars[key].trace_add("write", format_input)
            tk.Entry(frame, textvariable=self.vars[key], width=36,
                     font=("Consolas", -round(15*review.scale))).grid(row=row, column=1, columnspan=4, sticky="ew", pady=5)
        for col, title in enumerate(("Seat", "Status A/F/I", "Stack", "Street bet", "Total in pot")):
            review.label(frame, title).grid(row=3, column=col, padx=8, pady=8)
        self.seats = []
        for i, seat in enumerate(self.original.seats):
            review.label(frame, NAMES[i]).grid(row=4+i, column=0, sticky="w")
            variables = []
            for col, value in enumerate((seat.status, seat.stack, seat.bet, seat.invested), 1):
                var = tk.StringVar(value=str(value))
                tk.Entry(frame, textvariable=var, width=12, font=("Consolas", -round(15*review.scale))).grid(row=4+i, column=col, padx=4, pady=4)
                variables.append(var)
            self.seats.append(variables)
        self.error = review.label(frame, "Board length must match this snapshot. Corrected scenarios compare check/call and fold only.", color=MUTED)
        self.error.configure(wraplength=round(650*review.scale))
        self.error.grid(row=10, column=0, columnspan=5, pady=10)
        review.button(frame, "Apply to scenario", self.apply).grid(row=11, column=3, columnspan=2, sticky="e")

    def apply(self):
        try:
            from pokato.vision.reader import Seat
            hole = tuple(normalize_notation(self.vars["hole"].get()).split())
            board = tuple(normalize_notation(self.vars["board"].get()).split())
            if len(board) != len(self.original.board):
                raise ValueError("Keep the original snapshot's board length")
            seats = tuple(Seat(row[0].get().strip().upper(), *(int(var.get()) for var in row[1:])) for row in self.seats)
            actor = self.original.actor
            call = min(seats[actor].stack, max(max(s.bet for s in seats), 10 if self.original.street == "P" else 0) - seats[actor].bet) if actor >= 0 else 0
            corrected = replace(self.original, hole=hole, board=board, seats=seats,
                                pot=sum(s.invested for s in seats), call=call, minimum=0, maximum=0)
            validate_observation(corrected)
            self.review.invalidate()
            self.review.scenario_o = corrected
            self.review.heading.configure(text=f"Hand #{corrected.hand} · edited scenario")
            self.review.status.configure(text="Correction pending. Calculate to compare and save.")
            self.review.update_position()
            self.review.draw_snapshot()
            self.window.destroy()
        except ValueError as exc:
            self.error.configure(text=str(exc), fg="#e8b18d")
