"""Exercise saved review, range sensitivity, corrections and reset on real Tk widgets."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
from PIL import ImageGrab
from pokato.app import App
from pokato.ui.replay import CorrectionDialog
from pokato.vision.capture import enable_dpi_awareness


def main():
    enable_dpi_awareness()
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        root = tk.Tk()
        app = App(root, samples=100, database=Path(folder) / "practice.sqlite3", settings_path=False)
        started, failures = time.monotonic(), []
        state = {"phase": "capture"}

        def finish(error=None):
            if error:
                failures.append(str(error))
                print(f"FAIL: {error}", flush=True)
            else:
                print("PASS: capture -> saved replay -> range comparison -> correction -> reset", flush=True)
            app.close()

        def check():
            try:
                if time.monotonic() - started > 55:
                    raise AssertionError(f"Timed out at {state['phase']}: {app.last_error}")
                if state["phase"] == "capture" and app.advice is not None:
                    app.open_replay()
                    review = app.replay_window
                    assert review.snapshots and app.paused
                    original = review.snapshots[review.index].observation
                    state["original"] = original
                    seat = next(i for i, s in enumerate(original.seats) if i and s.status != "F")
                    state["seat"] = seat
                    review.range_entries[seat].set("AA")
                    review.calculate()
                    state["phase"] = "range"
                elif state["phase"] == "range":
                    review = app.replay_window
                    if hasattr(review, "last_results") and review.future is None and review.pending is None:
                        hand = review.hands[review.hand_index]
                        seq = len(review.snapshots[review.index].events)
                        saved = app.archive.scenario(hand.session, hand.hand, seq)
                        assert saved["ranges"][str(state["seat"])] == "AA"
                        assert app.archive.snapshots(hand.session, hand.hand)[review.index].observation == state["original"]
                        ImageGrab.grab(window=review.window.winfo_id()).save(output / "replay-smoke.png")
                        review.reset()
                        assert all(v.get() == "Auto" for v in review.range_entries.values())
                        dialog = CorrectionDialog(review)
                        dialog.vars["hole"].set("As As")
                        dialog.apply()
                        assert dialog.window.winfo_exists()
                        dialog.vars["hole"].set("As Ah")
                        dialog.apply()
                        assert review.scenario_o.hole == ("As", "Ah")
                        assert review.scenario_o.minimum == 0
                        review.calculate()
                        state["phase"] = "correction"
                elif state["phase"] == "correction":
                    review = app.replay_window
                    if review.future is None and review.pending is None:
                        hand = review.hands[review.hand_index]
                        seq = len(review.snapshots[review.index].events)
                        saved = app.archive.scenario(hand.session, hand.hand, seq)
                        assert saved["observation"]["hole"] == ["As", "Ah"]
                        assert review.snapshots[review.index].observation == state["original"]
                        review.reset()
                        assert review.scenario_o == state["original"]
                        review.close()
                        assert not app.paused
                        finish()
                        return
                root.after(150, check)
            except Exception as exc:
                finish(exc)

        root.report_callback_exception = lambda kind, value, tb: finish(value)
        root.after(500, check)
        root.mainloop()
        return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
