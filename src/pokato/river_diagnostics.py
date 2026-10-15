"""Actual-window river/session/replay smoke check, usable in a frozen build."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
import traceback
from PIL import ImageGrab
from .app import App
from .vision.capture import enable_dpi_awareness


def river_smoke(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root, samples=100, database=":memory:")
    app.paused = True
    started = time.monotonic()
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": []}
    phase = "drive"
    tick_job = None

    def finish(error=None):
        report["ok"] = error is None
        if error:
            report["error"] = error
        report["elapsed_seconds"] = round(time.monotonic()-started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.close()

    root.report_callback_exception = lambda kind, value, tb: finish("".join(traceback.format_exception(kind, value, tb)))

    def tick():
        nonlocal phase, tick_job
        try:
            if time.monotonic()-started > 60:
                raise TimeoutError(f"River smoke timed out at {phase}: {app.last_error}")
            game, latest = app.game, app.latest
            if phase == "drive":
                seen = latest and latest.actor == game.actor and latest.street == game.street and len(app.tracker.events) == len(game.events)
                if seen and game.street == "R" and game.actor == 0 and app.advice and app.advice.engine == "river-tree":
                    assert app.advice.branches and app.advice.nodes
                    assert "adapting" in app.profile_label.cget("text")
                    assert "90% posterior" in app.assumptions.cget("text")
                    assert all(s.models for s in app.archive.snapshots(app.session, game.hand_id))
                    app.toggle_details()
                    app.open_replay()
                    review = app.replay_window
                    index = next(i for i, s in enumerate(review.snapshots) if s.observation.street == "R" and s.observation.actor == 0)
                    review.select_snapshot(index)
                    review.calculate()
                    report["checks"].extend(("captured complete river action history", "session-only Bayesian evidence",
                                              "river EVs, response branches and public-belief continuations", "frozen replay model snapshots"))
                    phase = "review"
                elif seen and not (game.street == "R" and game.actor == 0):
                    if game.actor == 0:
                        app.call_action()
                    else:
                        action = "F" if game.street == "P" and game.actor in (2, 3, 4, 5) else "K" if game.legal()["check"] else "C"
                        game.act(action)
                        app.invalidate("Advancing local smoke fixture…")
                        app.draw()
            elif phase == "review":
                review = app.replay_window
                if hasattr(review, "last_results") and review.future is None and review.pending is None:
                    assert review.last_results[1].engine == "river-tree"
                    assert "FIRST OPPONENT RESPONSE" in review.output.get("1.0", "end")
                    report.update(actions=len(app.advice.actions), nodes=app.advice.nodes,
                                  session_decisions=app.history.session_model(app.session, 1).opportunities)
                    report["checks"].append("saved replay displays river branches and Bayesian evidence")
                    phase = "snapshot"
            elif phase == "snapshot":
                    app.replay_window.window.update_idletasks()
                    ImageGrab.grab(window=app.replay_window.window.winfo_id()).save(report_path.with_suffix(".png"))
                    finish()
                    return
            tick_job = root.after(75, tick)
        except Exception:
            finish(traceback.format_exc())

    tick_job = root.after(500, tick)
    root.mainloop()
    return 0 if report["ok"] else 1
