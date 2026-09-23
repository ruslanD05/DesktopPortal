"""Animated random pack selector."""
import random
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

from packs import PACKS_DIR, load_collections, pack_enabled, pack_wallpapers, save_settings


ALL_PACKS = 'All enabled packs'


class RandomWheel:
    CARD_WIDTH = 150
    CARD_HEIGHT = 175
    GAP = 14

    def __init__(self, portal):
        self.portal = portal
        self.window = tk.Toplevel(portal.root)
        self.window.title('Random theme wheel')
        self.window.geometry('900x390')
        self.window.minsize(720, 350)
        self.window.transient(portal.root)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.job = None
        self.spinning = False
        self.images = {}

        frame = ttk.Frame(self.window, padding=22)
        frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame)
        header.pack(fill='x', pady=(0, 12))
        ttk.Label(header, text='Choose from').pack(side='left')
        collections = load_collections()
        self.collections = collections
        choices = [ALL_PACKS] + [
            name for name, members in collections.items()
            if any(pack_enabled(portal.packs.get(item, {'enabled': False})) for item in members)
        ]
        saved = portal.settings.get('wheel_collection', ALL_PACKS)
        self.scope = tk.StringVar(value=saved if saved in choices else ALL_PACKS)
        ttk.Combobox(
            header, textvariable=self.scope, values=choices,
            state='readonly', width=28,
        ).pack(side='left', padx=(8, 12))
        self.spin_button = ttk.Button(
            header, text='Spin', style='Accent.TButton',
            command=lambda: portal.run(self.spin),
        )
        self.spin_button.pack(side='left')
        self.result = tk.StringVar(value='Choose a collection and spin.')
        ttk.Label(header, textvariable=self.result).pack(side='right')

        self.canvas = tk.Canvas(
            frame, height=220, highlightthickness=0,
            background=portal.colors['subtle'],
        )
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.draw())
        ttk.Label(
            frame,
            text='Only enabled packs participate. The selected pack activates automatically.',
        ).pack(anchor='w', pady=(10, 0))
        self.sequence = []
        self.offset = 0

    def candidates(self):
        enabled = [
            pack_id for pack_id, pack in self.portal.packs.items()
            if pack_enabled(pack)
        ]
        scope = self.scope.get()
        if scope == ALL_PACKS:
            return enabled
        members = self.collections.get(scope, [])
        return [pack_id for pack_id in members if pack_id in enabled]

    def thumbnail(self, pack_id):
        if pack_id in self.images:
            return self.images[pack_id]
        pack = self.portal.packs[pack_id]
        image = None
        wallpapers = pack_wallpapers(pack)
        if wallpapers:
            path = PACKS_DIR / pack_id / wallpapers[0]
            try:
                with Image.open(path) as source:
                    image = ImageOps.fit(source.convert('RGB'), (134, 126))
            except OSError:
                image = None
        if image is None:
            image = Image.new('RGB', (134, 126), '#465166')
            draw = ImageDraw.Draw(image)
            draw.ellipse((42, 30, 92, 80), fill='#dce3ee')
            draw.rectangle((63, 76, 71, 105), fill='#dce3ee')
        result = ImageTk.PhotoImage(image, master=self.window)
        self.images[pack_id] = result
        return result

    def spin(self):
        if self.spinning:
            return
        candidates = self.candidates()
        if not candidates:
            raise ValueError('This selection has no enabled packs.')
        self.portal.settings['wheel_collection'] = self.scope.get()
        save_settings(self.portal.settings)
        chooser = random.SystemRandom()
        winner = chooser.choice(candidates)
        self.sequence = [chooser.choice(candidates) for _ in range(38)]
        self.sequence.append(winner)
        self.sequence.extend(chooser.choice(candidates) for _ in range(4))
        self.winner_index = 38
        self.start_time = time.perf_counter()
        self.duration = 4.8
        self.start_offset = 0
        center = max(1, self.canvas.winfo_width()) / 2
        step = self.CARD_WIDTH + self.GAP
        self.target_offset = (
            self.winner_index * step + self.CARD_WIDTH / 2 - center
            + chooser.uniform(-self.CARD_WIDTH * 0.25, self.CARD_WIDTH * 0.25)
        )
        self.spinning = True
        self.spin_button.configure(state='disabled')
        self.result.set('Spinning…')
        self.animate()

    def animate(self):
        elapsed = time.perf_counter() - self.start_time
        progress = min(1.0, elapsed / self.duration)
        eased = 1 - (1 - progress) ** 4
        self.offset = self.start_offset + (self.target_offset - self.start_offset) * eased
        self.draw()
        if progress < 1:
            self.job = self.window.after(16, self.animate)
            return
        self.job = None
        self.spinning = False
        self.spin_button.configure(state='normal')
        winner = self.sequence[self.winner_index]
        self.result.set(f'Winner: {self.portal.packs[winner]["name"]}')
        self.portal.activate(winner)
        self.portal.tag_controlled = False
        self.draw(winner=True)

    def draw(self, winner=False):
        self.canvas.delete('all')
        if not self.sequence:
            width = max(1, self.canvas.winfo_width())
            self.canvas.create_text(
                width / 2, 105, text='Press Spin',
                fill=self.portal.colors['muted'], font=('Segoe UI Semibold', 18),
            )
            return
        step = self.CARD_WIDTH + self.GAP
        canvas_width = max(1, self.canvas.winfo_width())
        for index, pack_id in enumerate(self.sequence):
            x = index * step - self.offset
            if x > canvas_width or x + self.CARD_WIDTH < 0:
                continue
            selected = winner and index == self.winner_index
            outline = self.portal.colors['accent'] if selected else self.portal.colors['quiet']
            self.canvas.create_rectangle(
                x, 16, x + self.CARD_WIDTH, 196,
                fill=self.portal.colors['surface'], outline=outline,
                width=4 if selected else 1,
            )
            self.canvas.create_image(x + 75, 81, image=self.thumbnail(pack_id))
            self.canvas.create_text(
                x + 75, 170, text=self.portal.packs[pack_id]['name'], width=134,
                fill=self.portal.colors['text'], font=('Segoe UI Semibold', 9),
            )
        center = canvas_width / 2
        self.canvas.create_polygon(
            center - 9, 0, center + 9, 0, center, 13,
            fill=self.portal.colors['accent'], outline='',
        )

    def close(self):
        if self.job is not None:
            self.window.after_cancel(self.job)
        self.portal.random_wheel = None
        self.window.destroy()
