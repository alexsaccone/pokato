"""Compact, non-scrolling essentials with optional supporting detail."""
import tkinter as tk
from pokato.core.cards import display_card
from .window import WindowChrome, BG, TEXT, MUTED, ACCENT
from .sizing import HudFonts, geometry

PANEL = "#1a212c"


def core_label(app, parent, text="", size=10, bold=False, color=TEXT):
    label = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color, anchor="w", justify="left",
                     font=app.hud_fonts.get(size, bold))
    return label


def build_coach(a):
    a.details_open = False
    a.compact_geometry = None
    a.hud = tk.Toplevel(a.root)
    a.hud_fonts = HudFonts(a.hud, a.hud_scale)
    a.hud.title("Pokato · practice coach")
    compact_rect = a.hud_display.hud_rect()
    a.hud.geometry(geometry(compact_rect))
    a.hud.attributes("-topmost", True)
    a.hud.protocol("WM_DELETE_WINDOW", a.hud.withdraw)
    a.hud_chrome = WindowChrome(a.hud, "pokato", "COACH", a.hud.withdraw,
                                minimum=a.hud_minimum(), alpha=0.94, scale=a.hud_scale * 0.75)
    a.hud_chrome.hint.pack_forget()
    a.hud_chrome.footer.configure(height=a.hp(32))
    a.zoom_toolbar = a.hud_chrome.footer
    a.zoom_out = a.zoom_button(a.zoom_toolbar, "A−", lambda: a.set_hud_zoom(a.hud_zoom - 0.1))
    a.zoom_label = tk.Label(a.zoom_toolbar, text=f"{a.hud_zoom:.0%}", bg=BG, fg=MUTED, font=a.hud_fonts.get(8))
    a.zoom_label.pack(side="left", padx=a.hp(3))
    a.zoom_in = a.zoom_button(a.zoom_toolbar, "A+", lambda: a.set_hud_zoom(a.hud_zoom + 0.1))
    a.zoom_reset = a.zoom_button(a.zoom_toolbar, "Reset", lambda: a.set_hud_zoom(1.0))
    a.details_button = a.zoom_button(a.zoom_toolbar, "Details", a.toggle_details)
    a.opacity_button = tk.Button(a.zoom_toolbar, text="94%", command=a.cycle_opacity, bg=BG, fg=MUTED,
                                 activebackground=PANEL, activeforeground=TEXT, relief="flat", bd=0,
                                 font=a.hud_fonts.get(8), cursor="hand2")
    a.opacity_button.pack(side="right", padx=a.hp(3))

    a.essentials = tk.Frame(a.hud_chrome.body, bg=BG, padx=a.hp(8), pady=a.hp(4))
    a.essentials.pack(fill="x")
    a.essentials.columnconfigure(0, weight=1)
    state = tk.Frame(a.essentials, bg=BG)
    state.grid(row=0, column=0, sticky="ew", pady=(0, a.hp(3)))
    a.state_label = core_label(a, state, "Reading hand…", 8, color=MUTED)
    a.state_label.pack(side="left")
    a.capture_status = core_label(a, state, "● Connecting", 8, color=ACCENT)
    a.capture_status.pack(side="right")

    cards = tk.Frame(a.essentials, bg=BG)
    cards.grid(row=1, column=0, sticky="ew", pady=(0, a.hp(5)))
    cards.columnconfigure(0, weight=1)
    cards.columnconfigure(1, weight=2)
    a.cards_label = core_label(a, cards, "—", 18, True)
    a.cards_label.grid(row=0, column=0, sticky="w")
    a.board_label = core_label(a, cards, "Board not dealt", 11, color=MUTED)
    a.board_label.grid(row=0, column=1, sticky="e")

    metrics = tk.Frame(a.essentials, bg=PANEL, padx=a.hp(8), pady=a.hp(4))
    metrics.grid(row=2, column=0, sticky="ew", pady=(0, a.hp(5)))
    a.metric_cells = []
    for column, title in enumerate(("POT", "CALL", "EQUITY", "POT ODDS")):
        metrics.columnconfigure(column, weight=1, uniform="metrics")
        cell = tk.Frame(metrics, bg=PANEL)
        cell.grid(row=0, column=column, sticky="ew")
        core_label(a, cell, title, 8, color=MUTED).pack(anchor="w")
        value = core_label(a, cell, "—", 14, True, ACCENT if column == 2 else TEXT)
        value.pack(fill="x")
        a.metric_cells.append(value)
    a.pot_label, a.call_number, a.equity_number, a.price_number = a.metric_cells

    decision = tk.Frame(a.essentials, bg=PANEL, padx=a.hp(8), pady=a.hp(5))
    decision.grid(row=3, column=0, sticky="ew", pady=(0, a.hp(5)))
    decision.columnconfigure(0, weight=1)
    a.recommendation = core_label(a, decision, "Waiting for your turn", 16, True, ACCENT)
    a.recommendation.grid(row=0, column=0, sticky="ew")
    a.best_ev_label = core_label(a, decision, "", 10, True)
    a.best_ev_label.grid(row=0, column=1, sticky="e", padx=(a.hp(6), 0))
    a.model_label = core_label(a, decision, "Model estimate", 8, color=MUTED)
    a.model_label.grid(row=1, column=0, columnspan=2, sticky="w")

    alternatives = tk.Frame(a.essentials, bg=BG)
    alternatives.grid(row=4, column=0, sticky="ew")
    a.ev_cells = []
    for column in range(3):
        alternatives.columnconfigure(column, weight=1, uniform="actions")
        cell = tk.Frame(alternatives, bg=BG)
        cell.grid(row=0, column=column, sticky="ew")
        action = core_label(a, cell, "—", 8, color=MUTED)
        action.pack(fill="x")
        value = core_label(a, cell, "—", 10, True)
        value.pack(fill="x")
        a.ev_cells.append((action, value))
    a.crucial_widgets = (a.state_label, a.cards_label, a.board_label, *a.metric_cells,
                          a.recommendation, a.best_ev_label, a.model_label, *[w for pair in a.ev_cells for w in pair])

    # Only this optional region scrolls; essentials are ordinary fixed widgets.
    a.hud_canvas = tk.Canvas(a.hud_chrome.body, bg=BG, highlightthickness=0)
    a.hud_body = tk.Frame(a.hud_canvas, bg=BG, padx=a.hp(8), pady=a.hp(8))
    a.hud_body_id = a.hud_canvas.create_window((0, 0), window=a.hud_body, anchor="nw")
    a.hud_body.bind("<Configure>", lambda e: a.hud_canvas.configure(scrollregion=a.hud_canvas.bbox("all")))
    a.hud_canvas.bind("<Configure>", lambda e: a.layout_hud(e.width, a.hud_body_id))
    a.columns = tk.Frame(a.hud_body, bg=BG)
    a.columns.pack(fill="x")
    a.analysis_column, a.detail_column = tk.Frame(a.columns, bg=BG), tk.Frame(a.columns, bg=BG)
    calculations = a.panel(a.analysis_column, "CALCULATIONS / ASSUMPTIONS")
    a.metrics = a.label(calculations, "Waiting for your turn", 9, MUTED)
    a.chart = tk.Canvas(calculations, height=a.hp(47), bg=PANEL, highlightthickness=0)
    a.chart.pack(fill="x")
    a.chart.bind("<Configure>", lambda e: a.draw_chart())
    a.runout_chart = tk.Canvas(calculations, height=a.hp(170), bg=PANEL, highlightthickness=0)
    a.runout_chart.bind("<Configure>", lambda e: draw_runouts(a))
    a.action_label = a.label(calculations, "", 10)
    a.assumptions = a.label(calculations, "", 9, MUTED)
    evidence = a.panel(a.detail_column, "OPPONENT EVIDENCE")
    a.profile_label = a.label(evidence, "", 10, MUTED)
    recent = a.panel(a.detail_column, "ACTION HISTORY")
    a.events_label = a.label(recent, "", 10, MUTED)

    a.hud.bind("<Escape>", lambda e: a.hud.withdraw())
    a.hud.bind("<MouseWheel>", lambda e: a.hud_canvas.yview_scroll(-int(e.delta / 120), "units") if a.details_open else None)
    a.hud.bind("<Control-MouseWheel>", a.zoom_wheel)
    for sequence in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
        a.hud.bind(sequence, lambda e: a.set_hud_zoom(a.hud_zoom + 0.1))
    for sequence in ("<Control-minus>", "<Control-KP_Subtract>"):
        a.hud.bind(sequence, lambda e: a.set_hud_zoom(a.hud_zoom - 0.1))
    a.hud.bind("<Control-0>", lambda e: a.set_hud_zoom(1.0))
    a.hud.bind("<Configure>", a.schedule_monitor_refresh, add="+")
    a.root.bind("h", lambda e: a.open_hud())
    # Apply the intended size after constructing the frameless wrapper. Measure
    # after mapping, when winfo_width is real rather than its initial 1 pixel.
    a.hud.geometry(geometry(compact_rect))
    a.hud.after(100, a.fit_essentials)


def refresh_coach(a):
    a.hud_scale = a.hud_display.compact_scale * a.hud_zoom
    a.hud_fonts.set_scale(a.hud_scale)
    a.hud_chrome.set_scale(a.hud_scale * 0.75)
    a.hud_chrome.hint.pack_forget()
    a.hud_chrome.footer.configure(height=a.hp(32))
    a.zoom_label.configure(text=f"{a.hud_zoom:.0%}")
    a.essentials.configure(padx=a.hp(8), pady=a.hp(4))
    a.hud_body.configure(padx=a.hp(8), pady=a.hp(8))
    a.chart.configure(height=a.hp(47))
    a.runout_chart.configure(height=a.hp(170))
    a.hud.minsize(*a.hud_minimum())
    if not a.details_open and not a.hud_chrome.maximized:
        width, height, _, _ = a.hud_display.hud_rect()
        a.hud.geometry(geometry(a.hud_display.fit(width, height, a.hud.winfo_x(), a.hud.winfo_y())))
        a.hud.update_idletasks()
    a.fit_essentials()
    a.layout_hud(max(200, a.hud_canvas.winfo_width()), a.hud_body_id)
    a.draw_chart()
    draw_runouts(a)


def draw_runouts(a):
    """Show extreme river-card equities; probabilities are range conditioned."""
    canvas = a.runout_chart
    canvas.delete("all")
    if not a.advice or not a.advice.runouts:
        canvas.pack_forget()
        return
    canvas.pack(fill="x", after=a.action_label)
    rows = sorted(a.advice.runouts, key=lambda r: (r.share, r.card))
    picks = rows[-3:][::-1] + rows[:3]
    width = max(a.hp(230), canvas.winfo_width())
    canvas.create_text(a.hp(2), a.hp(10), text="RIVER CARD → SHOWDOWN EQUITY", anchor="w",
                       fill=MUTED, font=a.hud_fonts.get(8))
    for i, row in enumerate(picks):
        y = a.hp(33+i*24)
        color = ACCENT if i < 3 else "#e8b18d"
        canvas.create_text(a.hp(2), y, text=display_card(row.card), anchor="w", fill=TEXT, font=a.hud_fonts.get(9, True))
        left, right = a.hp(31), width-a.hp(111)
        canvas.create_rectangle(left, y-a.hp(4), right, y+a.hp(4), fill="#293342", outline="")
        canvas.create_rectangle(left, y-a.hp(4), left+max(0, right-left)*row.share, y+a.hp(4), fill=color, outline="")
        canvas.create_text(width-a.hp(2), y, text=f"{row.share:.0%} · P {row.probability:.1%}",
                           anchor="e", fill=color, font=a.hud_fonts.get(8))
