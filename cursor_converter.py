"""Small standalone cursor converter: GUI by default, CLI with two paths."""
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from cursor_conversion import convert_cursor, read_cursor


class Converter:
    def __init__(self, root):
        self.root = root
        self.tracks = {}
        self.animation_id = None
        root.title('DesktopPortal Cursor Converter')
        root.geometry('580x380')
        root.minsize(480, 360)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        self.source = tk.StringVar()
        self.destination = tk.StringVar()
        self.size = tk.StringVar(value='All sizes')
        self.status = tk.StringVar(value='')
        ttk.Label(frame, text='Source cursor').grid(row=0, column=0, sticky='w')
        ttk.Entry(frame, textvariable=self.source, state='readonly').grid(row=1, column=0, sticky='ew')
        ttk.Button(frame, text='Browse...', command=self.browse_source).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(frame, text='Output folder').grid(row=2, column=0, sticky='w', pady=(14, 0))
        ttk.Entry(frame, textvariable=self.destination).grid(row=3, column=0, sticky='ew')
        ttk.Button(frame, text='Browse...', command=self.browse_destination).grid(row=3, column=1, padx=(8, 0))
        ttk.Label(frame, text='Cursor size').grid(row=4, column=0, sticky='w', pady=(14, 0))
        self.sizes = ttk.Combobox(frame, textvariable=self.size, state='readonly', values=['All sizes'], width=18)
        self.sizes.grid(row=5, column=0, sticky='w')
        self.sizes.bind('<<ComboboxSelected>>', lambda event: self.preview())
        preview = ttk.Frame(frame, height=96)
        preview.grid(row=6, column=0, columnspan=2, pady=12, sticky='ew')
        preview.grid_propagate(False)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.preview_label = ttk.Label(preview, anchor='center')
        self.preview_label.grid(row=0, column=0, sticky='nsew')
        self.convert_button = ttk.Button(frame, text='Convert', command=self.convert, state='disabled')
        self.convert_button.grid(row=7, column=1, sticky='e')
        ttk.Label(frame, textvariable=self.status, wraplength=430).grid(row=8, column=0, columnspan=2, sticky='w', pady=(12, 0))

    def browse_source(self):
        source = filedialog.askopenfilename(parent=self.root, filetypes=[('Cursor files', '*.cur *.ani *.xcursor'), ('All files', '*')])
        if not source:
            return
        try:
            kind, tracks = read_cursor(source)
        except (OSError, ValueError) as error:
            messagebox.showerror('Cannot open cursor', str(error), parent=self.root)
            return
        self.tracks = tracks
        self.source.set(source)
        self.destination.set(str(Path(source).parent))
        self.size.set('All sizes')
        self.sizes.configure(values=['All sizes', *map(str, sorted(tracks))])
        target = 'Windows CUR/ANI' if kind == 'xcursor' else 'Linux Xcursor'
        self.status.set(f'{kind.upper()} -> {target}')
        self.convert_button.configure(state='normal')
        self.preview()

    def browse_destination(self):
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            self.destination.set(folder)

    def preview(self):
        if self.animation_id is not None:
            self.root.after_cancel(self.animation_id)
            self.animation_id = None
        if not self.tracks:
            return
        nominal = max(self.tracks) if self.size.get() == 'All sizes' else int(self.size.get())
        frames = self.tracks[nominal]

        def show(index):
            item = frames[index]
            image = item.image.copy()
            image.thumbnail((96, 96))
            self.photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.photo)
            if len(frames) > 1:
                self.animation_id = self.root.after(max(1, item.delay), lambda: show((index + 1) % len(frames)))

        show(0)

    def convert(self):
        try:
            folder = Path(self.destination.get())
            if not self.destination.get().strip() or not folder.is_dir():
                raise ValueError('Choose an existing output folder.')
            size = None if self.size.get() == 'All sizes' else int(self.size.get())
            result = convert_cursor(self.source.get(), folder, size)
        except (OSError, ValueError) as error:
            messagebox.showerror('Conversion failed', str(error), parent=self.root)
            return
        self.status.set(f'Saved: {result.name}')
        messagebox.showinfo('Converted', str(result), parent=self.root)


def main():
    parser = argparse.ArgumentParser(description='Convert CUR/ANI <-> Xcursor. With no paths, open the GUI.')
    parser.add_argument('source', nargs='?')
    parser.add_argument('destination', nargs='?', help='Existing output folder or a new output filename')
    parser.add_argument('--size', type=int, help='Convert only this nominal size')
    args = parser.parse_args()
    if args.source is None:
        if args.destination or args.size is not None:
            parser.error('--size requires source and destination paths')
        root = tk.Tk()
        Converter(root)
        root.mainloop()
    else:
        if args.destination is None:
            parser.error('Provide an output folder or filename')
        try:
            print(convert_cursor(args.source, args.destination, args.size))
        except (OSError, ValueError) as error:
            parser.exit(1, f'Conversion failed: {error}\n')


if __name__ == '__main__':
    main()
