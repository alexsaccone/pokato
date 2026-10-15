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
from .ui.sizing import geometry


def river_smoke(report_path, street="R"):
    if street not in ("T", "R"):
        raise ValueError("Smoke street must be turn or river")
    engine = "turn-tree" if street == "T" else "river-tree"
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root, samples=100, database=":memory:", settings_path=False)
    app.paused = True
    if street == "T":
        app.hud.attributes("-alpha", 1.0)
        app.opacity_button.configure(text="100%")
        # Leave room for the expanded opaque HUD beside the practice window.
        app.root.geometry(geometry(app.display.fit(min(1500, app.display.width//2),
                                                   app.display.height-2*app.display.margin)))
    started = time.monotonic()
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": []}
    phase = "drive"
    tick_job = None
    hud_ready_after = 0.

    def finish(error=None):
        report["ok"] = error is None
        if error:
            report["error"] = error
        report["elapsed_seconds"] = round(time.monotonic()-started, 2)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.close()

    root.report_callback_exception = lambda kind, value, tb: finish("".join(traceback.format_exception(kind, value, tb)))

    def begin_review():
        nonlocal phase
        app.open_replay()
        review = app.replay_window
        index = next(i for i, s in enumerate(review.snapshots) if s.observation.street == street and s.observation.actor == 0)
        review.select_snapshot(index)
        review.calculate()
        phase = "review"

    def show_hud():
        nonlocal hud_ready_after
        app.open_hud()
        if not app.details_open:
            app.toggle_details()
        width, height, _, y = app.hud_display.fit(860*app.hud_scale, 940*app.hud_scale)
        x = app.hud_display.x + app.hud_display.width-width-app.hud_display.margin
        app.hud.geometry(geometry(app.hud_display.fit(width, height, x, y)))
        hud_ready_after = time.monotonic()+.5

    def tick():
        nonlocal phase, tick_job, hud_ready_after
        try:
            if time.monotonic()-started > 90:
                raise TimeoutError(f"River smoke timed out at {phase}: {app.last_error}")
            game, latest = app.game, app.latest
            if phase == "drive":
                seen = latest and latest.actor == game.actor and latest.street == game.street and len(app.tracker.events) == len(game.events)
                if seen and game.street == street and game.actor == 0 and app.advice and app.advice.engine == engine:
                    assert app.advice.branches and app.advice.nodes
                    assert "adapting" in app.profile_label.cget("text")
                    assert "90% posterior" in app.assumptions.cget("text")
                    assert all(s.models for s in app.archive.snapshots(app.session, game.hand_id))
                    if street == "T":
                        assert app.advice.uncertainty and app.advice.uncertainty.draws == 24
                        assert app.advice.runouts and app.advice.equity.exact
                        assert abs(sum(r.probability for r in app.advice.runouts)-1) < 1e-8
                        assert "policy agreement" in app.model_label.cget("text")
                        assert "APPROXIMATE 80% POLICY SENSITIVITY" in app.assumptions.cget("text")
                    app.toggle_details()
                    report["checks"].extend((f"captured complete {street} action history", "session-only Bayesian evidence",
                                              f"{engine} EVs, response branches and public-belief continuations", "frozen replay model snapshots"))
                    if street == "T":
                        show_hud()
                        phase = "hud"
                    else:
                        begin_review()
                elif seen and not (game.street == street and game.actor == 0):
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
                    assert review.last_results[1].engine == engine
                    assert "FIRST OPPONENT RESPONSE" in review.output.get("1.0", "end")
                    report.update(actions=len(app.advice.actions), nodes=app.advice.nodes,
                                  session_decisions=app.history.session_model(app.session, 1).opportunities)
                    report["checks"].append("saved replay displays river branches and Bayesian evidence")
                    if street == "T":
                        assert review.last_results[0].uncertainty == app.advice.uncertainty
                        assert "RIVER CARD / PROBABILITY" in review.output.get("1.0", "end")
                        report["checks"].append("replay reproduces frozen turn policy sensitivity and card probabilities")
                        report.update(policy_draws=app.advice.uncertainty.draws, runouts=len(app.advice.runouts))
                    phase = "snapshot"
            elif phase == "snapshot":
                app.replay_window.window.update_idletasks()
                ImageGrab.grab(window=app.replay_window.window.winfo_id()).save(report_path.with_suffix(".png"))
                if street == "T":
                    app.replay_window.close()
                    app.call_action()
                    assert app.advice is None and not app.runout_chart.winfo_manager()
                    report["checks"].append("hero action immediately clears turn advice and river-card chart")
                finish()
                return
            elif phase == "hud" and time.monotonic() >= hud_ready_after:
                if not app.hud.winfo_viewable():
                    # A hidden Windows launch may defer its first show. Retry
                    # our own coach window within the overall smoke timeout.
                    show_hud()
                    tick_job = root.after(75, tick)
                    return
                assert app.hud.winfo_viewable() and app.runout_chart.winfo_ismapped(), (
                    f"HUD visible={app.hud.winfo_viewable()}, chart mapped={app.runout_chart.winfo_ismapped()}, "
                    f"advice={bool(app.advice)}, capture error={app.last_error}")
                assert app.details_open and app.details_button.cget("text") == "Less"
                assert "APPROXIMATE 80% POLICY BAND" in app.action_label.cget("text")
                # Capture the opaque HUD before replay changes window focus.
                # This avoids layered-window and restore timing artifacts.
                hud_image = ImageGrab.grab(window=app.hud.winfo_id()).convert("RGB")
                hud_image.save(report_path.with_name(report_path.stem+"-hud.png"))
                width, height = hud_image.size
                assert abs(width-app.hud.winfo_width()) <= 8 and abs(height-app.hud.winfo_height()) <= 8
                center = hud_image.crop((width//4, height//4, width*3//4, height*3//4))
                pixels = list(center.getdata())
                assert sum(sum(pixel) > 30 for pixel in pixels) > len(pixels)*.5, "HUD capture is blank"
                chart = app.runout_chart
                report.update(hud_size=(width, height), card_chart_size=(chart.winfo_width(), chart.winfo_height()),
                              card_chart_requested_height=app.hp(170))
                x, y = chart.winfo_rootx()-app.hud.winfo_rootx(), chart.winfo_rooty()-app.hud.winfo_rooty()
                assert 0 <= x < width and 0 <= y and y+chart.winfo_height() < height
                graphic = hud_image.crop((x, y, x+chart.winfo_width(), y+chart.winfo_height()))
                assert any(g > 100 and g > r+10 for r, g, b in graphic.getdata()), "River-card bars did not render"
                report["checks"].append("HUD renders policy bands and river-card graphic")
                begin_review()
            tick_job = root.after(75, tick)
        except Exception:
            finish(traceback.format_exc())

    tick_job = root.after(500, tick)
    root.mainloop()
    return 0 if report["ok"] else 1
