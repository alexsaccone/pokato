"""Default entry point: one HUD, one button, automatic local screen analysis."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog
from .sizing import Display, HudFonts, Preferences, geometry
from .window import WindowChrome, NativeWindow, BG, TEXT, MUTED, ACCENT
from .reader_style import ReaderTheme, ScrollPanel
from pokato.core.cards import display_card
from pokato.vision.automatic import AutomaticReader
from pokato.vision.hole_tracking import HoleCardTracker
from pokato.vision.screen import DesktopSource
from pokato.vision.sources import ImageSource


class AutomaticHUD:
    def __init__(self, root, *, reader=None, source_factory=DesktopSource, display=None, settings_path=None):
        self.root, self.reader, self.source_factory = root, reader or AutomaticReader(), source_factory
        self.root.tk.call('tk', 'scaling', 96/72)
        self.display = display or Display.detect(root)
        self.preferences = Preferences(settings_path, key='automatic_zoom')
        self.zoom = self.preferences.zoom
        self.scale = self.display.compact_scale*self.zoom
        self.fonts = HudFonts(root, self.scale)
        self.closed = self.running = False
        self.source = self.future = self.reading = None
        self.hole_tracker = HoleCardTracker()
        self.generation = self.future_generation = 0
        self.next_capture = 0.
        self.last_read = None
        self.last_signature = None
        self.stable = 0
        self.practice = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pokato-screen')
        root.title('Pokato')
        # A readable HUD is the sole default window. The optical input has no
        # dependency on its size, zoom or location.
        width, height, x, y = self.display.hud_rect()
        root.geometry(geometry(self.display.fit(width, max(height, 390*self.scale), x, y)))
        self.chrome = WindowChrome(root, 'pokato', 'LIVE TABLE', self.close,
                                   minimum=(400, 340), scale=self.scale*.8)
        root.attributes('-topmost', True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.chrome.hint.configure(text='Local screen analysis · nothing uploaded')
        self.top = tk.Frame(self.chrome.body, bg=BG)
        self.top.pack(fill='x', padx=12, pady=(8, 4))
        self.start_button = tk.Button(self.top, text='Start analysis', command=self.toggle, bg=ACCENT, fg=BG,
                                     activebackground='#c3f5e7', relief='flat', bd=0, padx=16, pady=8,
                                     font=self.fonts.get(11, True), cursor='hand2')
        self.start_button.pack(side='left', fill='x', expand=True)
        self.menu_button = tk.Button(self.top, text='⋯', command=self.show_menu, bg=BG, fg=MUTED,
                                     font=self.fonts.get(11, True), relief='flat', bd=0, padx=12)
        self.menu_button.pack(side='right')
        self.menu = tk.Menu(root, tearoff=False, font=self.fonts.get(10))
        self.menu.add_command(label='Open an image…', command=self.open_image)
        self.menu.add_separator()
        self.menu.add_command(label='Practice table', command=self.open_practice)
        self.menu.add_command(label='Advanced calibration tools', command=lambda: self.open_practice(advanced=True))
        self.theme = ReaderTheme(root, self.scale)
        self.theme.style.configure(self.theme.name('TFrame'), background=BG)
        self.panel = ScrollPanel(self.chrome.body, self.theme)
        self.panel.configure(style=self.theme.name('TFrame'))
        self.panel.pack(fill='both', expand=True, padx=8)
        self.panel.body.configure(style=self.theme.name('TFrame'))
        self.panel.canvas.configure(background=BG)
        self.status = self.label('Ready · open your poker table', 10, True, ACCENT)
        self.cards = tk.Canvas(self.panel.body, bg=BG, highlightthickness=0, height=170)
        self.cards.pack(fill='x', padx=8, pady=8)
        self.cards.bind('<Configure>', lambda e: self.draw_cards())
        self.pot = self.label('The table will be detected automatically.', 10)
        self.players = self.label('', 9, color=MUTED)
        self.detail = self.label('', 9, color=MUTED)
        self.footer = tk.Frame(self.chrome.body, bg=BG)
        # Reserve the controls before the scrollable content consumes space on
        # short screens or at large text zoom.
        self.footer.pack(side='bottom', fill='x', padx=12, pady=4, before=self.panel)
        for text, step in (('A−', -.1), ('A+', .1)):
            tk.Button(self.footer, text=text, command=lambda delta=step: self.set_zoom(self.zoom+delta),
                      font=self.fonts.get(9), bg=BG, fg=MUTED, relief='flat').pack(side='left')
        self.age = tk.Label(self.footer, text='', bg=BG, fg=MUTED, font=self.fonts.get(8))
        self.age.pack(side='right')
        self.excluded = False
        root.bind('<Map>', lambda e: root.after_idle(self.exclude), add='+')
        root.bind('<Control-plus>', lambda e: self.set_zoom(self.zoom+.1))
        root.bind('<Control-minus>', lambda e: self.set_zoom(self.zoom-.1))
        root.bind('<Alt-F4>', lambda e: self.close())
        root.after_idle(self.exclude)
        self.apply_scale()
        self.panel.bind_wheel()
        self.job = root.after(80, self.poll)

    def label(self, text, size, bold=False, color=TEXT):
        label = tk.Label(self.panel.body, text=text, bg=BG, fg=color, anchor='w', justify='left',
                         font=self.fonts.get(size, bold), wraplength=420)
        label.pack(fill='x', padx=10, pady=4)
        self.panel.body.bind('<Configure>', self.wrap, add='+')
        return label

    def wrap(self, event=None):
        width = max(180, self.panel.canvas.winfo_width()-24)
        for label in (self.status, self.pot, self.players, self.detail):
            label.configure(wraplength=width)

    def apply_scale(self):
        self.fonts.set_scale(self.scale)
        self.theme.set_scale(self.scale)
        self.panel.scroll.configure(width=self.theme.px(12))
        self.chrome.set_scale(self.scale*.8)
        self.cards.configure(height=round(76*self.scale))
        self.wrap()
        self.draw_cards()

    def set_zoom(self, zoom):
        self.zoom = round(min(2., max(.8, zoom)), 2)
        self.preferences.save(self.zoom)
        self.scale = self.display.compact_scale*self.zoom
        self.apply_scale()
        width, height, _, _ = self.display.hud_rect()
        self.root.geometry(geometry(self.display.fit(
            max(self.root.winfo_width(), width*self.zoom),
            max(self.root.winfo_height(), max(height, 390*self.display.compact_scale)*self.zoom),
            self.root.winfo_x(), self.root.winfo_y())))

    def exclude(self):
        if not self.closed:
            self.excluded = NativeWindow(self.root).exclude_from_capture()

    def show_menu(self):
        self.menu.tk_popup(self.menu_button.winfo_rootx(), self.menu_button.winfo_rooty()+self.menu_button.winfo_height())

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self, source=None):
        if self.closed:
            return
        self.stop()
        self.source = source or self.source_factory()
        self.running = True
        self.start_button.configure(text='Stop analysis', bg='#f0ba93')
        self.status.configure(text='Finding your poker table…')
        self.pot.configure(text='Keep the poker table visible. Setup is automatic.')
        self.detail.configure(text='')
        self.next_capture = 0.

    def stop(self):
        self.generation += 1
        self.running = False
        if self.source:
            self.source.close()
        self.source = None
        if self.future:
            self.future.cancel()
        self.clear('Paused · click Start analysis to resume')
        self.start_button.configure(text='Start analysis', bg=ACCENT)

    def clear(self, status):
        self.hole_tracker.reset()
        self.reading = None
        self.last_read = None
        self.last_signature = None
        self.stable = 0
        self.status.configure(text=status)
        self.pot.configure(text='')
        self.players.configure(text='')
        self.detail.configure(text='')
        self.age.configure(text='')
        self.draw_cards()

    def open_image(self):
        path = filedialog.askopenfilename(parent=self.root, title='Analyze a poker screenshot',
                 filetypes=[('Images', '*.png *.jpg *.jpeg *.webp *.bmp'), ('All files', '*.*')])
        if path:
            self.start(ImageSource([Path(path)]))

    def open_practice(self, advanced=False):
        if self.practice:
            self.practice.root.deiconify()
            return
        self.stop()
        self.root.withdraw()
        from pokato.app import App
        window = tk.Toplevel(self.root)
        self.practice = App(window)
        def restore(event):
            if event.widget == window:
                self.practice = None
                if not self.closed:
                    self.root.deiconify()
                    self.job = self.root.after(80, self.poll)
        window.bind('<Destroy>', restore, add='+')
        if advanced:
            self.practice.open_table_reader()

    @staticmethod
    def analyze(source, reader):
        frame = source.next()
        return None if frame is None else reader.read(frame)

    def poll(self):
        if self.closed:
            return
        now = time.monotonic()
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.future_generation == self.generation and self.running:
                try:
                    reading = future.result()
                    if reading is None:
                        self.running = False
                        self.start_button.configure(text='Start analysis', bg=ACCENT)
                        self.age.configure(text='Screenshot')
                    else:
                        self.deliver(reading)
                except Exception as error:
                    self.clear('Waiting for a readable screen')
                    self.detail.configure(text=str(error)[:200])
                self.next_capture = now+.35
        if self.running and self.future is None and now >= self.next_capture:
            if isinstance(self.source, DesktopSource):
                x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
                self.source.mask = None if self.excluded else (x, y, x+self.root.winfo_width(), y+self.root.winfo_height())
            self.future_generation = self.generation
            self.future = self.executor.submit(self.analyze, self.source, self.reader)
        if self.running:
            elapsed = now-self.last_read if self.last_read else 0
            self.age.configure(text=f'Updated {elapsed:.0f}s ago' if self.last_read else 'Analyzing…')
            if self.last_read and elapsed > 10:
                self.clear('Reacquiring your table…')
        self.job = self.root.after(80, self.poll)

    def deliver(self, reading):
        if self.source and self.source.live:
            reading = self.hole_tracker.update(reading)
        self.last_read = time.monotonic()
        self.reading = reading
        if not reading.table_found:
            self.last_signature = None
            self.stable = 0
            self.status.configure(text='Looking for a poker table…')
            self.pot.configure(text='Keep one table visible. Recognition adapts as the screen changes.')
            self.players.configure(text='')
            self.detail.configure(text=' · '.join(reading.issues))
        else:
            signature = (tuple(c.value for c in reading.board), tuple(c.value for c in reading.hand), reading.hero_verified)
            self.stable = self.stable+1 if signature == self.last_signature else 1
            self.last_signature = signature
            self.status.configure(text='Screenshot analyzed' if self.source and not self.source.live else
                                  'Table detected · waiting for cards' if not (reading.hand or reading.board) else
                                  'Table detected · live' if self.stable >= 2 else 'Table detected · checking cards')
            self.pot.configure(text='\n'.join(f'{p.label.title() or "Displayed pot"}: {"≈" if p.approximate else ""}{p.raw}'
                                          for p in reading.pots) or 'Pot not visible')
            self.players.configure(text=f'{len(reading.players)} player stacks detected' if reading.players else 'Player stacks not visible')
            notes = list(reading.issues)
            if reading.hand_status:
                notes.append(reading.hand_status)
            if reading.hand and not reading.hero_verified:
                notes.append('Hand owner is uncertain')
            if any(c.value is None for c in (*reading.board, *reading.hand)):
                notes.append('Some cards are unreadable')
            notes.append('Recommendations await verified action history')
            self.detail.configure(text=' · '.join(notes))
        self.draw_cards()

    def draw_cards(self):
        if not hasattr(self, 'cards'):
            return
        self.cards.delete('all')
        width = max(350, self.cards.winfo_width())
        scale = self.scale
        board = self.reading.board if self.reading and self.reading.table_found else ()
        hand = self.reading.hand if self.reading and self.reading.table_found else ()
        step = min(round(65*scale), int((width-24)/7.2))
        for column, label, values, count in ((0, 'BOARD', board, 5), (5.2, 'HAND' if self.reading and self.reading.hero_verified else 'VISIBLE HAND', hand, 2)):
            offset = 4+column*step
            self.cards.create_text(offset, 0, text=label, fill=MUTED, anchor='nw', font=self.fonts.get(8))
            y = round(23*scale)
            for i in range(count):
                x = offset+i*step
                card = values[i] if i < len(values) else None
                value = card.value if card else None
                self.cards.create_rectangle(x, y, x+step-7, y+round(43*scale), fill='#edf0f4' if value else '#232d3b', outline='')
                self.cards.create_text(x+(step-7)/2, y+round(21*scale), text=display_card(value) if value else '?' if card else '·',
                    fill=('#b0273a' if value and value[1] in 'hd' else '#11151d') if value else MUTED,
                    font=self.fonts.get(12, True))

    def close(self):
        if self.closed:
            return
        self.stop()
        self.closed = True
        self.root.after_cancel(self.job)
        if self.practice:
            self.practice.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()
