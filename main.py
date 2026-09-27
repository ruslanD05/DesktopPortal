"""DesktopPortal interface. Run with Python or the packaged executable."""
from collections import deque
from datetime import datetime
from pathlib import Path
import queue
import shutil
import socket
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from PIL import Image, ImageDraw, ImageTk

from desktop import Desktop
from packs import (PACKS_DIR, load_packs, load_tags, save_tags, create_pack,
                   write_json, load_settings, save_settings, pack_effects,
                   pack_wallpapers, pack_assets, pack_enabled, load_collections,
                   save_collections, group_packs, DEFAULT_SETTINGS)
from cursor_roles import (CURSOR_MAPPING, CURSOR_ROLES, detect_cursor_role,
                          find_cursors)
from cursor_images import flip_cursor, preview_frames
from hotkeys import HotkeyManager, parse_hotkey
from pack_tools import (cleanup_assets, export_bundle, import_bundle,
                        unused_assets, validate_pack)
from platform_backend import capability_summary
from play_sound import (play_music, play_sound, set_music_volume, stop_music,
                        stop_sound)
from startup import startup_enabled, set_startup_enabled
from shutdown_hooks import ShutdownHooks
from tray import TrayIcon
from random_wheel import RandomWheel, ALL_PACKS

IPC_HOST = '127.0.0.1'
IPC_PORT = 45873


def recover_previous_desktop(desktop):
    if desktop.original is None:
        return None
    try:
        desktop.restore()
        return 'Original desktop restored after the previous session.'
    except Exception as error:
        return f'Previous desktop recovery failed: {error}'


class Portal:
    def __init__(self, root, desktop=None, monitor=True, command_socket=None,
                 start_hidden=False):
        self.root = root
        self.desktop = desktop or Desktop()
        self.events = queue.Queue()
        self.monitor = self.observer = None
        self.monitor_enabled = monitor
        self.binding = None
        self.preview_timer = None
        self.preview_previous = None
        self.random_wheel = None
        self.detection_paused = False
        self.activity = deque(maxlen=100)
        self.setup_prompted = False
        # reader -> (uid, pack_id). CardMonitor can report one physical tag
        # more than once, so the UID is retained for event deduplication.
        self.present = {}
        self.suppressed_uids = set()
        self.tag_controlled = False
        self.closed = False
        self.command_socket = command_socket
        self.packs = {}
        self.item_to_pack = {}
        self.item_to_collection = {}
        try:
            self.settings = load_settings()
        except Exception as error:
            self.settings = dict(DEFAULT_SETTINGS)
            messagebox.showerror('Settings unavailable', str(error), parent=root)
        self.desktop.settings = self.settings
        self.recovery_status = recover_previous_desktop(self.desktop)
        saved_cursor_size = self.settings.get('cursor_size')
        if saved_cursor_size is not None and self.desktop.backend.supports_cursor_size:
            self.desktop.backend.set_cursor_size(saved_cursor_size)
        try:
            self.tags = load_tags()
        except Exception as error:
            self.tags = {}
            messagebox.showerror('Tag bindings unavailable', str(error), parent=root)
            # Do not overwrite a damaged config accidentally.
            self.tags = None
        root.title('DesktopPortal')
        root.geometry('1040x640')
        root.minsize(780, 520)
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        self.more_menu = None
        self.apply_theme(self.settings.get('dark_mode', False))
        frame = ttk.Frame(root, padding=(28, 22, 28, 20), style='App.TFrame')
        frame.pack(fill='both', expand=True)

        header = ttk.Frame(frame, style='App.TFrame')
        header.pack(fill='x', pady=(0, 18))
        brand = ttk.Frame(header, style='App.TFrame')
        brand.pack(side='left')
        ttk.Label(brand, text='DesktopPortal', style='Title.TLabel').pack(anchor='w')
        ttk.Label(brand, text='Figurine-controlled desktop profiles', style='Subtitle.TLabel').pack(anchor='w', pady=(1, 0))
        header_actions = ttk.Frame(header, style='App.TFrame')
        header_actions.pack(side='right', pady=(4, 0))
        ttk.Button(header_actions, text='New pack', style='Quiet.TButton', command=lambda: self.run(self.new_pack)).pack(side='left', padx=(0, 7))
        ttk.Button(header_actions, text='Import', style='Quiet.TButton', command=lambda: self.run(self.import_packs)).pack(side='left', padx=(0, 7))
        ttk.Button(header_actions, text='Options', style='Quiet.TButton', command=lambda: self.run(self.open_options)).pack(side='left')

        surface = ttk.Frame(frame, padding=(18, 16), style='Surface.TFrame')
        surface.pack(fill='both', expand=True)
        table_header = ttk.Frame(surface, style='Surface.TFrame')
        table_header.pack(fill='x', pady=(0, 10))
        ttk.Label(table_header, text='Packs and collections', style='Section.TLabel').pack(side='left')
        self.pack_filter = tk.StringVar(value='All')
        filter_box = ttk.Combobox(
            table_header, textvariable=self.pack_filter,
            values=('All', 'Enabled', 'Disabled'), state='readonly', width=10,
        )
        filter_box.pack(side='right')
        self.search_text = tk.StringVar()
        search = ttk.Entry(table_header, textvariable=self.search_text, width=26)
        search.pack(side='right', padx=(0, 8))
        search.insert(0, '')
        ttk.Label(table_header, text='Search', style='Section.TLabel').pack(
            side='right', padx=(0, 7)
        )
        self.list = ttk.Treeview(
            surface,
            columns=('enabled', 'wallpapers', 'cursors', 'sounds', 'music', 'tags'),
            show='tree headings',
            selectmode='browse',
            # Keep the requested height small. The table expands with the
            # window, but gives the controls and footer priority when resized.
            height=4,
        )
        self.list.heading('#0', text='Pack', anchor='w')
        self.list.heading('enabled', text='Enabled', anchor='w')
        self.list.heading('wallpapers', text='Wallpapers', anchor='w')
        self.list.heading('cursors', text='Cursors', anchor='w')
        self.list.heading('sounds', text='Sounds', anchor='w')
        self.list.heading('music', text='Music', anchor='w')
        self.list.heading('tags', text='Bound tags', anchor='w')
        self.list.column('#0', width=220)
        self.list.column('enabled', width=70)
        self.list.column('wallpapers', width=105)
        self.list.column('cursors', width=100)
        self.list.column('sounds', width=75)
        self.list.column('music', width=75)
        self.list.column('tags', width=90)
        self.list.pack(fill='both', expand=True, pady=(0, 12))
        self.list.bind('<Double-1>', self.activate_double_clicked)
        self.list.bind('<<TreeviewSelect>>', lambda event: self.show_selected_effects())
        self.search_text.trace_add('write', lambda *_: self.reload())
        filter_box.bind('<<ComboboxSelected>>', lambda event: self.reload())
        self.main_effect_vars = {
            name: tk.BooleanVar(value=False)
            for name in ('wallpaper', 'cursors', 'sounds', 'music')
        }
        self.main_effect_labels = {
            name: tk.StringVar(value=name.title())
            for name in self.main_effect_vars
        }
        ttk.Separator(surface).pack(fill='x', pady=(0, 10))
        effect_bar = ttk.Frame(surface, style='Surface.TFrame')
        effect_bar.pack(fill='x')
        self.main_pack_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            effect_bar,
            text='Pack enabled',
            style='Surface.TCheckbutton',
            variable=self.main_pack_enabled,
            command=lambda: self.run(self.toggle_selected_pack),
        ).pack(side='left', padx=(0, 24))
        for name in ('wallpaper', 'cursors', 'sounds', 'music'):
            ttk.Checkbutton(
                effect_bar,
                textvariable=self.main_effect_labels[name],
                style='Surface.TCheckbutton',
                variable=self.main_effect_vars[name],
                command=lambda effect=name: self.run(
                    lambda: self.toggle_selected_effect(effect)
                ),
            ).pack(side='left', padx=(0, 18))
        actions = ttk.Frame(surface, style='Surface.TFrame')
        actions.pack(fill='x', pady=(14, 0))
        ttk.Button(actions, text='Activate', style='Accent.TButton', command=lambda: self.run(self.activate_selected)).pack(side='left', padx=(0, 7))
        for label, action in [('Preview', self.preview_selected),
                              ('Random wheel', self.open_random_wheel),
                              ('Edit pack', self.edit_pack), ('Bind tag', self.bind_tag)]:
            ttk.Button(actions, text=label, style='Quiet.TButton', command=lambda f=action: self.run(f)).pack(side='left', padx=(0, 7))
        more = ttk.Menubutton(actions, text='More  ···', style='Quiet.TButton')
        more.pack(side='left')
        more_menu = tk.Menu(more, tearoff=False, font=('Segoe UI', 10), relief='flat', borderwidth=1)
        for label, action in [
            ('Restore original desktop', self.restore), ('Cancel tag binding', self.cancel_binding),
            ('Collections…', self.open_collections), ('Export selected…', self.export_selected),
            ('Validate selected', self.validate_selected), ('Clean unused assets…', self.clean_selected),
            ('Unbind selected pack', self.unbind), ('Delete selected pack…', self.delete_selected),
            ('Diagnostics…', self.open_diagnostics),
            ('Reload', self.reload),
        ]:
            more_menu.add_command(label=label, command=lambda f=action: self.run(f))
        more_menu.add_separator()
        more_menu.add_command(label='Quit DesktopPortal', command=lambda: self.run(self.quit_app))
        more.configure(menu=more_menu)
        self.more_menu = more_menu
        self.apply_theme(self.settings.get('dark_mode', False))
        self.restore_on_remove = tk.BooleanVar(
            value=self.settings['restore_on_remove']
        )
        try:
            starts_with_windows = self.settings['start_with_windows']
        except OSError:
            starts_with_windows = False
        self.start_with_windows = tk.BooleanVar(value=starts_with_windows)
        self.status = tk.StringVar(value='Ready. Select a pack or scan a bound tag.')
        self.status.trace_add('write', self._record_status)
        self.reader_status = tk.StringVar(value='NFC listener disabled')
        footer = ttk.Frame(frame, style='App.TFrame')
        footer.pack(fill='x', pady=(14, 0))
        ttk.Label(footer, textvariable=self.status, style='Status.TLabel', anchor='w').pack(side='left', fill='x', expand=True)
        ttk.Label(footer, textvariable=self.reader_status, style='Status.TLabel', anchor='e').pack(side='right', padx=(8, 0))
        self.reload()
        self.hotkeys = HotkeyManager(self.events)
        hotkey_errors = self.hotkeys.start(self.hotkey_bindings())
        if hotkey_errors:
            self.activity.extend(f'Hotkey: {error}' for error in hotkey_errors)
        if self.recovery_status:
            self.status.set(self.recovery_status)
        if monitor:
            root.after(0, self.refresh_readers)
        root.protocol('WM_DELETE_WINDOW', self.hide)
        if start_hidden:
            root.withdraw()
        self.poll_id = root.after(100, self.poll)
        self.tray = TrayIcon(self)
        if not self.tray.start():
            self.activity.append('System tray unavailable: install pystray and Pillow.')
        if not start_hidden and not self.settings.get('setup_complete', False):
            self.root.after(300, self.open_setup_wizard)

    def apply_theme(self, dark):
        colors = (
            dict(app='#17191d', surface='#22252b', text='#f0f2f5', muted='#9ba3ae',
                 subtle='#2b2f36', quiet='#30353d', quiet_active='#3a404a',
                 accent='#dde3eb', accent_text='#171a1f', select='#39485d',
                 select_text='#ffffff')
            if dark else
            dict(app='#f4f5f7', surface='#ffffff', text='#20242a', muted='#69707d',
                 subtle='#eef1f5', quiet='#e9ecf1', quiet_active='#dfe3e9',
                 accent='#303846', accent_text='#ffffff', select='#dfe7f2',
                 select_text='#172131')
        )
        self.colors = colors
        self.root.configure(background=colors['app'])
        style = self.style
        style.configure('.', font=('Segoe UI', 10), background=colors['app'], foreground=colors['text'])
        style.configure('App.TFrame', background=colors['app'])
        style.configure('Surface.TFrame', background=colors['surface'])
        style.configure('Title.TLabel', font=('Segoe UI Semibold', 24), background=colors['app'], foreground=colors['text'])
        style.configure('Subtitle.TLabel', font=('Segoe UI', 10), background=colors['app'], foreground=colors['muted'])
        style.configure('Section.TLabel', font=('Segoe UI Semibold', 11), background=colors['surface'], foreground=colors['text'])
        style.configure('Drop.TLabel', background=colors['subtle'], foreground=colors['muted'], padding=(12, 12), anchor='center')
        style.configure('Status.TLabel', font=('Segoe UI', 9), background=colors['subtle'], foreground=colors['muted'], padding=(10, 7))
        style.configure('TButton', padding=(13, 8), borderwidth=0, relief='flat')
        style.configure('Accent.TButton', background=colors['accent'], foreground=colors['accent_text'], font=('Segoe UI Semibold', 10))
        style.map('Accent.TButton', background=[('active', colors['muted'])])
        style.configure('Quiet.TButton', background=colors['quiet'], foreground=colors['text'])
        style.map('Quiet.TButton', background=[('active', colors['quiet_active'])])
        style.configure('TCheckbutton', background=colors['app'], foreground=colors['text'], padding=(2, 4))
        style.map('TCheckbutton', background=[('active', colors['app'])])
        style.configure('Surface.TCheckbutton', background=colors['surface'], foreground=colors['text'], padding=(2, 4))
        style.map('Surface.TCheckbutton', background=[('active', colors['surface'])])
        style.configure('TEntry', fieldbackground=colors['surface'], foreground=colors['text'], insertcolor=colors['text'])
        style.configure('TCombobox', fieldbackground=colors['surface'], background=colors['quiet'], foreground=colors['text'], arrowcolor=colors['text'])
        style.configure('Treeview', background=colors['surface'], fieldbackground=colors['surface'], foreground=colors['text'], rowheight=34, borderwidth=0)
        style.configure('Treeview.Heading', background=colors['subtle'], foreground=colors['muted'], font=('Segoe UI Semibold', 9), padding=(8, 8), borderwidth=0)
        style.map('Treeview', background=[('selected', colors['select'])], foreground=[('selected', colors['select_text'])])
        if self.more_menu is not None:
            self.more_menu.configure(
                background=colors['surface'], foreground=colors['text'],
                activebackground=colors['select'], activeforeground=colors['select_text'],
            )

    def _record_status(self, *_):
        value = self.status.get()
        if value:
            self.activity.append(f'{datetime.now():%H:%M:%S}  {value}')

    def hotkey_bindings(self):
        return {
            'wheel': self.settings.get('hotkey_wheel', ''),
            'next': self.settings.get('hotkey_next', ''),
            'previous': self.settings.get('hotkey_previous', ''),
            'random': self.settings.get('hotkey_random', ''),
        }

    def run(self, action):
        try:
            action()
        except Exception as error:
            self.status.set(f'Error: {error}')
            messagebox.showerror('DesktopPortal', str(error), parent=self.root)

    def selected(self):
        selection = self.list.selection()
        if not selection:
            raise ValueError('Select a pack first.')
        pack_id = self.item_to_pack.get(selection[0])
        if pack_id is None:
            raise ValueError('Select a pack inside the collection.')
        return pack_id

    def activate_double_clicked(self, event):
        item = self.list.identify_row(event.y)
        if item in self.item_to_pack:
            self.run(self.activate_selected)

    def reload(self, selected_pack=None):
        selected = selected_pack
        selection = self.list.selection()
        if selected is None and selection:
            selected = self.item_to_pack.get(selection[0])
        had_groups = bool(self.list.get_children())
        expanded = {
            self.list.item(item, 'text')
            for item in self.list.get_children()
            if self.list.item(item, 'open')
        }
        self.packs, errors = load_packs()
        for item in self.list.get_children():
            self.list.delete(item)
        self.item_to_pack = {}
        self.item_to_collection = {}
        try:
            collections = load_collections()
        except (OSError, ValueError) as error:
            collections = {}
            errors.append(f'collections: {error}')
        first_pack_item = None
        selected_item = None
        query = self.search_text.get().strip().casefold()
        state_filter = self.pack_filter.get()
        for group_index, (name, members) in enumerate(
            group_packs(self.packs, collections)
        ):
            if query and query not in name.casefold():
                members = [
                    pack_id for pack_id in members
                    if query in pack_id.casefold()
                    or query in self.packs[pack_id]['name'].casefold()
                ]
            if state_filter != 'All':
                wanted = state_filter == 'Enabled'
                members = [
                    pack_id for pack_id in members
                    if pack_enabled(self.packs[pack_id]) == wanted
                ]
            if not members:
                continue
            parent = f'collection::{group_index}'
            self.item_to_collection[parent] = (name, list(members))
            enabled_count = sum(pack_enabled(self.packs[pack_id]) for pack_id in members)
            self.list.insert(
                '', 'end', iid=parent, text=name,
                values=(f'{enabled_count}/{len(members)} enabled', '', '', '', '', ''),
                open=(name in expanded) if had_groups else True,
            )
            for member_index, pack_id in enumerate(members):
                pack = self.packs[pack_id]
                item = f'pack::{group_index}::{member_index}'
                self.item_to_pack[item] = pack_id
                count = sum(value == pack_id for value in (self.tags or {}).values())
                effects = pack_effects(pack)
                wallpapers = len(pack_wallpapers(pack))
                cursors = len(pack.get('cursors', {}))
                sounds = len(pack.get('sounds', []))
                music = 1 if pack.get('music') else 0
                self.list.insert(
                    parent, 'end', iid=item, text=pack['name'],
                    values=(
                        'Yes' if pack_enabled(pack) else 'No',
                        f'{"On" if effects["wallpaper"] else "Off"} · {wallpapers}',
                        f'{"On" if effects["cursors"] else "Off"} · {cursors}/15',
                        f'{"On" if effects["sounds"] else "Off"} · {sounds}',
                        f'{"On" if effects["music"] else "Off"} · {music}',
                        count,
                    ),
                )
                first_pack_item = first_pack_item or item
                if pack_id == selected and selected_item is None:
                    selected_item = item
        if selected_item:
            self.list.selection_set(selected_item)
        elif first_pack_item:
            self.list.selection_set(first_pack_item)
        self.show_selected_effects()
        if errors:
            self.status.set('Skipped invalid packs: ' + '; '.join(errors))

    def show_selected_effects(self):
        selection = self.list.selection()
        pack_id = self.item_to_pack.get(selection[0]) if selection else None
        if pack_id is None:
            return
        pack = self.packs[pack_id]
        self.main_pack_enabled.set(pack_enabled(pack))
        effects = pack_effects(pack)
        counts = {
            'wallpaper': str(len(pack_wallpapers(pack))),
            'cursors': f'{len(pack.get("cursors", {}))}/15',
            'sounds': str(len(pack.get('sounds', []))),
            'music': '1' if pack.get('music') else '0',
        }
        names = {'wallpaper': 'Wallpapers', 'cursors': 'Cursor mappings',
                 'sounds': 'Sounds', 'music': 'Music'}
        for name in self.main_effect_vars:
            self.main_effect_vars[name].set(effects[name])
            self.main_effect_labels[name].set(f'{names[name]} ({counts[name]})')

    def toggle_selected_effect(self, name):
        pack_id = self.selected()
        pack = dict(self.packs[pack_id])
        effects = pack_effects(pack)
        effects[name] = self.main_effect_vars[name].get()
        pack['effects'] = effects
        write_json(PACKS_DIR / pack_id / 'pack.json', pack)
        self.packs[pack_id] = pack
        self.reload()
        self.status.set(f'{self.main_effect_labels[name].get()} updated.')

    def toggle_selected_pack(self):
        self.set_packs_enabled(
            [self.selected()],
            self.main_pack_enabled.get(),
        )

    def set_packs_enabled(self, pack_ids, enabled):
        changed = []
        for pack_id in pack_ids:
            pack = self.packs.get(pack_id)
            if pack is None:
                continue
            updated = dict(pack)
            updated['enabled'] = enabled
            write_json(PACKS_DIR / pack_id / 'pack.json', updated)
            changed.append(pack_id)
        self.reload()
        self.present = {
            reader: value for reader, value in self.present.items()
            if pack_enabled(self.packs.get(value[1], {'enabled': False}))
        }
        if self.desktop.active in changed and not enabled:
            if self.tag_controlled and self.present:
                self.apply_present()
            else:
                self.restore()
        state = 'enabled' if enabled else 'disabled'
        self.status.set(f'{len(changed)} pack(s) {state}.')

    def activate(self, pack_id):
        if pack_id not in self.packs:
            raise ValueError(f'Pack not found: {pack_id}')
        if not pack_enabled(self.packs[pack_id]):
            raise ValueError(f'{self.packs[pack_id]["name"]} is disabled.')
        self.desktop.activate(pack_id, self.packs[pack_id])
        self.status.set(f'Active: {self.packs[pack_id]["name"]}')

    def activate_selected(self):
        self.activate(self.selected())
        self.tag_controlled = False

    def restore(self):
        if getattr(self, 'preview_timer', None) is not None:
            self.root.after_cancel(self.preview_timer)
            self.preview_timer = None
        self.desktop.restore()
        self.tag_controlled = False
        self.status.set('Original desktop restored.')

    def save_remove_preference(self):
        self.settings['restore_on_remove'] = self.restore_on_remove.get()
        save_settings(self.settings)

    def save_startup_preference(self):
        enabled = self.start_with_windows.get()
        self.settings['start_with_windows'] = enabled
        save_settings(self.settings)
        set_startup_enabled(enabled)
        state = 'enabled' if enabled else 'disabled'
        self.status.set(f'Login startup {state}.')

    def bind_tag(self):
        if self.tags is None:
            raise ValueError('Fix data/tags.json and restart before binding tags.')
        pack_id = self.selected()
        self.binding = (pack_id, time.monotonic() + 30)
        self.status.set(f'Scan a tag within 30 seconds to bind {self.packs[pack_id]["name"]}.')

    def cancel_binding(self):
        self.binding = None
        self.status.set('Binding cancelled.')

    def unbind(self):
        pack_id = self.selected()
        if self.tags is None:
            raise ValueError('Tag bindings could not be loaded.')
        tags = {uid: value for uid, value in self.tags.items() if value != pack_id}
        save_tags(tags)
        self.tags = tags
        self.present = {
            reader: value for reader, value in self.present.items()
            if value[1] != pack_id
        }
        if self.tag_controlled:
            self.apply_present()
        self.reload()
        self.status.set('Tags unbound from selected pack.')

    def new_pack(self):
        name = simpledialog.askstring('New pack', 'Pack name:', parent=self.root)
        if not name:
            return
        pack_id = simpledialog.askstring('New pack', 'ID (lowercase letters, numbers, underscores):', parent=self.root)
        if not pack_id:
            return
        create_pack(pack_id, name)
        self.reload(selected_pack=pack_id)
        self.edit_pack()

    def edit_pack(self):
        PackEditor(self, self.selected())

    def open_collections(self):
        CollectionManager(self)

    def open_random_wheel(self):
        self.show()
        if self.random_wheel is not None and self.random_wheel.window.winfo_exists():
            self.random_wheel.window.lift()
            self.random_wheel.window.focus_force()
            return
        self.random_wheel = RandomWheel(self)

    def enabled_pack_ids(self, collection=None):
        enabled = [
            pack_id for pack_id, pack in self.packs.items() if pack_enabled(pack)
        ]
        if not collection or collection == ALL_PACKS:
            return enabled
        members = load_collections().get(collection, [])
        return [pack_id for pack_id in members if pack_id in enabled]

    def switch_pack(self, direction):
        candidates = self.enabled_pack_ids()
        if not candidates:
            raise ValueError('There are no enabled packs.')
        if self.desktop.active in candidates:
            index = (candidates.index(self.desktop.active) + direction) % len(candidates)
        else:
            index = 0 if direction > 0 else -1
        self.activate(candidates[index])
        self.tag_controlled = False

    def activate_random(self):
        import random
        candidates = self.enabled_pack_ids(
            self.settings.get('wheel_collection', ALL_PACKS)
        )
        if not candidates:
            raise ValueError('The selected wheel collection has no enabled packs.')
        self.activate(random.SystemRandom().choice(candidates))
        self.tag_controlled = False

    def handle_hotkey(self, action):
        actions = {
            'wheel': self.open_random_wheel,
            'next': lambda: self.switch_pack(1),
            'previous': lambda: self.switch_pack(-1),
            'random': self.activate_random,
        }
        if action in actions:
            actions[action]()

    def preview_selected(self):
        pack_id = self.selected()
        if self.preview_timer is not None:
            self.root.after_cancel(self.preview_timer)
        self.preview_previous = self.desktop.active
        self.desktop.activate(pack_id, self.packs[pack_id], self.settings, play_activation_sound=False)
        seconds = max(1, int(self.settings.get('preview_seconds', 8)))
        self.status.set(f'Previewing {self.packs[pack_id]["name"]} for {seconds} seconds.')
        self.preview_timer = self.root.after(seconds * 1000, self.finish_preview)

    def finish_preview(self):
        self.preview_timer = None
        previous = self.preview_previous
        self.preview_previous = None
        if previous in self.packs and pack_enabled(self.packs[previous]):
            self.desktop.activate(previous, self.packs[previous], self.settings, play_activation_sound=False)
            self.status.set(f'Preview ended. Active: {self.packs[previous]["name"]}')
        else:
            self.restore()

    def export_selected(self):
        selection = self.list.selection()
        if not selection:
            raise ValueError('Select a pack or collection first.')
        item = selection[0]
        collection = self.item_to_collection.get(item)
        if collection is not None:
            name, members = collection
            if not members:
                raise ValueError('This collection has no available packs.')
            safe_name = ''.join(
                character if character.isalnum() else '_'
                for character in name
            ).strip('_') or 'collection'
            destination = filedialog.asksaveasfilename(
                parent=self.root,
                defaultextension='.zip',
                initialfile=f'{safe_name}.zip',
                filetypes=[('DesktopPortal bundle', '*.zip')],
            )
            if destination:
                export_bundle(members, destination, collection=name)
                self.status.set(
                    f'Exported collection {name} with {len(members)} pack(s).'
                )
            return
        pack_id = self.item_to_pack.get(item)
        if pack_id is None:
            raise ValueError('Select a pack or collection first.')
        destination = filedialog.asksaveasfilename(
            parent=self.root, defaultextension='.zip', initialfile=f'{pack_id}.zip',
            filetypes=[('DesktopPortal bundle', '*.zip')],
        )
        if destination:
            export_bundle([pack_id], destination)
            self.status.set(f'Exported {self.packs[pack_id]["name"]}.')

    def import_packs(self):
        source = filedialog.askopenfilename(
            parent=self.root, filetypes=[('DesktopPortal bundle', '*.zip')]
        )
        if not source:
            return
        imported, collection, mapping = import_bundle(source)
        if collection:
            collections = load_collections()
            name = collection
            number = 2
            while name in collections:
                name = f'{collection} {number}'
                number += 1
            collections[name] = [mapping[item] for item in mapping]
            save_collections(collections)
        self.reload(selected_pack=imported[0] if imported else None)
        self.status.set(f'Imported {len(imported)} pack(s).')

    def validate_selected(self):
        pack_id = self.selected()
        issues = validate_pack(pack_id, self.packs[pack_id], self.tags)
        text = '\n'.join(f'• {issue}' for issue in issues) if issues else 'No problems found.'
        messagebox.showinfo('Pack validation', text, parent=self.root)
        self.status.set(f'Validation finished with {len(issues)} issue(s).')

    def clean_selected(self):
        pack_id = self.selected()
        unused = unused_assets(pack_id, self.packs[pack_id])
        if not unused:
            self.status.set('No unused assets found.')
            return
        names = '\n'.join(str(path.relative_to(PACKS_DIR / pack_id)) for path in unused[:12])
        if len(unused) > 12:
            names += f'\n…and {len(unused) - 12} more'
        if messagebox.askyesno('Remove unused assets', f'Remove these files?\n\n{names}', parent=self.root):
            cleanup_assets(pack_id, self.packs[pack_id])
            self.status.set(f'Removed {len(unused)} unused asset(s).')

    def delete_selected(self):
        pack_id = self.selected()
        pack = self.packs[pack_id]
        tag_count = sum(value == pack_id for value in (self.tags or {}).values())
        collections = load_collections()
        collection_count = sum(pack_id in members for members in collections.values())
        details = []
        if tag_count:
            details.append(f'{tag_count} tag binding(s)')
        if collection_count:
            details.append(f'{collection_count} collection membership(s)')
        suffix = '\n\nThis also removes ' + ' and '.join(details) + '.' if details else ''
        if not messagebox.askyesno(
            'Delete pack',
            f'Delete “{pack["name"]}” and all files inside its pack folder?{suffix}\n\nThis cannot be undone.',
            parent=self.root,
        ):
            return
        if self.desktop.active == pack_id:
            self.restore()
        root = (PACKS_DIR / pack_id).resolve()
        if root.parent != PACKS_DIR.resolve() or not root.is_dir():
            raise ValueError(f'Invalid pack folder: {pack_id}')
        if self.tags is not None:
            self.tags = {
                uid: value for uid, value in self.tags.items() if value != pack_id
            }
            save_tags(self.tags)
        changed_collections = {
            name: [member for member in members if member != pack_id]
            for name, members in collections.items()
        }
        save_collections(changed_collections)
        shutil.rmtree(root)
        self.present = {
            reader: value for reader, value in self.present.items()
            if value[1] != pack_id
        }
        self.reload()
        self.status.set(f'Deleted pack: {pack["name"]}.')

    def open_options(self):
        OptionsDialog(self)

    def open_setup_wizard(self):
        if self.setup_prompted or self.settings.get('setup_complete', False):
            return
        self.setup_prompted = True
        SetupWizard(self)

    def open_diagnostics(self):
        DiagnosticsDialog(self)

    def toggle_detection(self):
        self.detection_paused = not self.detection_paused
        if self.detection_paused and self.monitor is not None:
            self.monitor.deleteObserver(self.observer)
            self.monitor = self.observer = None
            self.reader_status.set('NFC: paused')
        elif not self.detection_paused:
            self.ensure_monitor()
            self.refresh_readers()
        self.status.set('NFC detection paused.' if self.detection_paused else 'NFC detection resumed.')

    def apply_present(self):
        if self.present:
            _, pack_id = next(reversed(self.present.values()))
            self.activate(pack_id)
            self.tag_controlled = True
        else:
            self.restore()

    def active_tag(self):
        """Return the most recently added physical tag, ignoring duplicates."""
        for uid, pack_id in reversed(self.present.values()):
            return uid, pack_id
        return None

    def handle_event(self, kind, reader, uid):
        if kind == 'error':
            self.status.set(f'{reader}: {uid}')
            return
        if kind == 'removed':
            previous_active = self.active_tag()
            removed = self.present.pop(reader, None)
            if removed is not None:
                removed_uid, _ = removed
                if not any(uid == removed_uid for uid, _ in self.present.values()):
                    self.suppressed_uids.discard(removed_uid)
            current_active = self.active_tag()
            if self.tag_controlled and previous_active != current_active:
                if current_active is not None:
                    self.apply_present()
                elif self.restore_on_remove.get():
                    self.restore()
                else:
                    self.tag_controlled = False
                    self.status.set('Figurine removed. The current desktop remains active.')
            return
        if self.binding and time.monotonic() < self.binding[1]:
            pack_id = self.binding[0]
            existing = self.tags.get(uid)
            if existing and existing != pack_id:
                old_name = self.packs.get(existing, {}).get('name', existing)
                new_name = self.packs[pack_id]['name']
                if not messagebox.askyesno(
                    'Replace tag binding',
                    f'This tag is bound to {old_name}. Bind it to {new_name} instead?',
                    parent=self.root,
                ):
                    self.binding = None
                    self.status.set('Binding cancelled; existing binding kept.')
                    return
            updated = dict(self.tags)
            updated[uid] = pack_id
            save_tags(updated)
            self.tags = updated
            self.binding = None
            self.suppressed_uids.add(uid)
            self.present[reader] = (uid, pack_id)
            self.reload()
            self.status.set(f'Tag bound to {self.packs[pack_id]["name"]}. Remove and scan again to activate.')
            return
        pack_id = (self.tags or {}).get(uid)
        if pack_id is None:
            return
        if pack_id not in self.packs or not pack_enabled(self.packs[pack_id]):
            return
        if uid in self.suppressed_uids:
            self.present[reader] = (uid, pack_id)
            return
        if any(present_uid == uid for present_uid, _ in self.present.values()):
            self.present[reader] = (uid, pack_id)
            return
        self.present.pop(reader, None)
        self.present[reader] = (uid, pack_id)
        self.apply_present()

    def refresh_readers(self):
        if self.detection_paused:
            self.reader_status.set('NFC: paused')
            if not self.closed:
                self.reader_timer = self.root.after(3000, self.refresh_readers)
            return
        self.ensure_monitor()
        try:
            from smartcard.System import readers
            names = [str(reader) for reader in readers()]
            self.reader_status.set(f'NFC: {len(names)} reader(s) connected' if names else 'NFC: connect a PC/SC reader. Manual activation is available.')
            removed = [name for name in self.present if name not in names]
            for name in removed:
                self.handle_event('removed', name, None)
        except Exception as error:
            self.reader_status.set(f'NFC: {error}')
        if not self.closed:
            self.reader_timer = self.root.after(3000, self.refresh_readers)

    def ensure_monitor(self):
        if not self.monitor_enabled or getattr(self, 'detection_paused', False) or self.monitor is not None:
            return
        try:
            from nfc import start_monitor
            self.monitor, self.observer = start_monitor(self.events)
        except Exception as error:
            self.reader_status.set(
                f'NFC unavailable: {error}. Retrying automatically...'
            )

    def poll(self):
        if self.command_socket is not None:
            while True:
                try:
                    connection, _ = self.command_socket.accept()
                except BlockingIOError:
                    break
                with connection:
                    command = connection.recv(32).decode('ascii', errors='ignore')
                if command == 'show':
                    self.show()
        if self.binding and time.monotonic() >= self.binding[1]:
            self.binding = None
            self.status.set('Tag binding timed out.')
        for _ in range(50):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == 'hotkey':
                self.run(lambda action=event[1]: self.handle_hotkey(action))
            else:
                self.run(lambda event=event: self.handle_event(*event))
        if not self.closed:
            self.poll_id = self.root.after(100, self.poll)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if not self.settings.get('setup_complete', False):
            self.root.after(250, self.open_setup_wizard)

    def hide(self):
        self.root.withdraw()

    def restore_for_system_shutdown(self):
        if self.closed:
            return
        try:
            self.desktop.restore()
            self.activity.append('Original desktop restored for system shutdown.')
        except Exception as error:
            # Keep the recovery snapshot so the next launch can retry.
            self.activity.append(f'System shutdown restoration failed: {error}')

    def quit_app(self, silent=False):
        try:
            self.desktop.restore()
        except Exception as error:
            if not silent:
                messagebox.showerror('Restoration failed', f'{error}\nThe recovery snapshot is preserved. Try Restore desktop again.', parent=self.root)
                return
        self.closed = True
        hooks = getattr(self, 'shutdown_hooks', None)
        if hooks is not None:
            hooks.close()
        if self.monitor is not None:
            self.monitor.deleteObserver(self.observer)
        self.root.after_cancel(self.poll_id)
        if hasattr(self, 'reader_timer'):
            self.root.after_cancel(self.reader_timer)
        if self.command_socket is not None:
            self.command_socket.close()
        self.hotkeys.stop()
        self.tray.stop()
        self.root.destroy()


class SetupWizard:
    def __init__(self, portal):
        self.portal = portal
        self.page = 0
        self.window = tk.Toplevel(portal.root)
        self.window.title('Welcome to DesktopPortal')
        self.window.geometry('560x390')
        self.window.resizable(False, False)
        self.window.transient(portal.root)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.skip)
        self.restore = tk.BooleanVar(value=portal.restore_on_remove.get())
        self.startup = tk.BooleanVar(value=portal.start_with_windows.get())
        self.dark = tk.BooleanVar(value=portal.settings.get('dark_mode', False))
        self.content = ttk.Frame(self.window, padding=(34, 30))
        self.content.pack(fill='both', expand=True)
        navigation = ttk.Frame(self.window, padding=(22, 12))
        navigation.pack(fill='x', side='bottom')
        ttk.Button(navigation, text='Skip setup', command=self.skip).pack(side='left')
        self.next_button = ttk.Button(
            navigation, text='Next', style='Accent.TButton', command=self.next
        )
        self.next_button.pack(side='right')
        self.back_button = ttk.Button(navigation, text='Back', command=self.back)
        self.back_button.pack(side='right', padx=(0, 8))
        self.render()
        self.window.update_idletasks()
        x = portal.root.winfo_rootx() + max(
            0, (portal.root.winfo_width() - self.window.winfo_width()) // 2
        )
        y = portal.root.winfo_rooty() + max(
            0, (portal.root.winfo_height() - self.window.winfo_height()) // 2
        )
        self.window.geometry(f'+{x}+{y}')

    def render(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        self.back_button.configure(state='disabled' if self.page == 0 else 'normal')
        self.next_button.configure(text='Finish' if self.page == 2 else 'Next')
        if self.page == 0:
            ttk.Label(self.content, text='Welcome to DesktopPortal', style='Title.TLabel').pack(anchor='w')
            ttk.Label(
                self.content,
                text=('Create desktop packs with wallpapers, cursor mappings and sounds. '
                      'Activate them manually or bind them to NFC figurines.'),
                wraplength=480,
            ).pack(anchor='w', pady=(18, 0))
        elif self.page == 1:
            ttk.Label(self.content, text='NFC reader', style='Title.TLabel').pack(anchor='w')
            ttk.Label(
                self.content, textvariable=self.portal.reader_status, wraplength=480
            ).pack(anchor='w', pady=(18, 8))
            ttk.Label(
                self.content,
                text='You can use every feature manually even when no reader is connected.',
                wraplength=480,
            ).pack(anchor='w')
        else:
            ttk.Label(self.content, text='Choose your defaults', style='Title.TLabel').pack(anchor='w')
            ttk.Checkbutton(
                self.content,
                text='Restore the original desktop when the last figurine is removed',
                variable=self.restore,
            ).pack(anchor='w', pady=(20, 6))
            ttk.Checkbutton(
                self.content, text='Start DesktopPortal at login', variable=self.startup
            ).pack(anchor='w', pady=6)
            ttk.Checkbutton(
                self.content, text='Use dark theme', variable=self.dark
            ).pack(anchor='w', pady=6)

    def back(self):
        self.page = max(0, self.page - 1)
        self.render()

    def next(self):
        if self.page < 2:
            self.page += 1
            self.render()
            return
        self.finish()

    def finish(self):
        portal = self.portal
        portal.restore_on_remove.set(self.restore.get())
        portal.start_with_windows.set(self.startup.get())
        portal.settings.update(
            restore_on_remove=self.restore.get(),
            start_with_windows=self.startup.get(),
            dark_mode=self.dark.get(),
            setup_complete=True,
        )
        set_startup_enabled(self.startup.get())
        save_settings(portal.settings)
        portal.apply_theme(self.dark.get())
        portal.status.set('Setup complete.')
        self.window.destroy()

    def skip(self):
        self.portal.settings['setup_complete'] = True
        save_settings(self.portal.settings)
        self.window.destroy()


class OptionsDialog:
    def __init__(self, portal):
        self.portal = portal
        self.window = tk.Toplevel(portal.root)
        self.window.title('Options')
        self.window.geometry('520x620')
        self.window.minsize(480, 540)
        self.window.transient(portal.root)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=22)
        frame.pack(fill='both', expand=True)
        self.volume = tk.DoubleVar(value=portal.settings.get('sound_volume', 0.8))
        self.music_volume = tk.DoubleVar(value=portal.settings.get('music_volume', 0.5))
        self.cooldown = tk.DoubleVar(value=portal.settings.get('sound_cooldown', 1.0))
        self.only_change = tk.BooleanVar(value=portal.settings.get('sound_on_change_only', True))
        self.preview = tk.IntVar(value=portal.settings.get('preview_seconds', 8))
        saved_size = portal.settings.get('cursor_size')
        current_size = (
            portal.desktop.backend.get_cursor_size()
            if portal.desktop.backend.supports_cursor_size else 1
        )
        self.cursor_size = tk.IntVar(value=saved_size or current_size)
        self.restore_on_remove = tk.BooleanVar(value=portal.restore_on_remove.get())
        self.start_at_login = tk.BooleanVar(value=portal.start_with_windows.get())
        self.dark_mode = tk.BooleanVar(value=portal.settings.get('dark_mode', False))
        self.hotkeys = {
            name: tk.StringVar(value=portal.settings.get(f'hotkey_{name}', ''))
            for name in ('wheel', 'next', 'previous', 'random')
        }
        notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        general = ttk.Frame(notebook, padding=18)
        shortcuts = ttk.Frame(notebook, padding=18)
        notebook.add(general, text='General')
        notebook.add(shortcuts, text='Hotkeys')
        ttk.Label(general, text='Activation sound volume').pack(anchor='w')
        ttk.Scale(general, from_=0, to=1, variable=self.volume).pack(fill='x', pady=(2, 12))
        ttk.Label(general, text='Background music volume').pack(anchor='w')
        ttk.Scale(general, from_=0, to=1, variable=self.music_volume).pack(fill='x', pady=(2, 12))
        ttk.Label(general, text='Sound cooldown (seconds)').pack(anchor='w')
        ttk.Spinbox(general, from_=0, to=60, increment=0.5, textvariable=self.cooldown).pack(fill='x', pady=(2, 12))
        ttk.Checkbutton(general, text='Play sound only when the active pack changes', variable=self.only_change).pack(anchor='w', pady=(0, 12))
        ttk.Label(general, text='Preview duration (seconds)').pack(anchor='w')
        ttk.Spinbox(general, from_=1, to=60, textvariable=self.preview).pack(fill='x', pady=(2, 16))
        ttk.Label(general, text='Cursor size (1–15)').pack(anchor='w')
        cursor_size = ttk.Spinbox(
            general, from_=1, to=15, textvariable=self.cursor_size,
            state='normal' if portal.desktop.backend.supports_cursor_size else 'disabled',
        )
        cursor_size.pack(fill='x', pady=(2, 4))
        ttk.Label(
            general,
            text=('Windows scales multi-size cursor files best. Single-size custom cursors may look soft.'
                  if portal.desktop.backend.supports_cursor_size
                  else 'Cursor sizing is unavailable on this platform.'),
            wraplength=380,
        ).pack(anchor='w', pady=(0, 12))
        ttk.Label(general, text='Wallpaper transitions: instant (desktop fade is unavailable).').pack(anchor='w')
        ttk.Separator(general).pack(fill='x', pady=(16, 12))
        ttk.Checkbutton(
            general,
            text='Restore the original desktop when the last figurine is removed',
            variable=self.restore_on_remove,
        ).pack(anchor='w')
        ttk.Checkbutton(
            general,
            text='Start DesktopPortal at login',
            variable=self.start_at_login,
        ).pack(anchor='w', pady=(4, 0))
        ttk.Checkbutton(
            general,
            text='Use dark theme',
            variable=self.dark_mode,
        ).pack(anchor='w', pady=(4, 0))
        descriptions = [
            ('Open random wheel', 'wheel'), ('Next enabled pack', 'next'),
            ('Previous enabled pack', 'previous'), ('Activate random pack', 'random'),
        ]
        for label, name in descriptions:
            ttk.Label(shortcuts, text=label).pack(anchor='w')
            ttk.Entry(shortcuts, textvariable=self.hotkeys[name]).pack(
                fill='x', pady=(2, 12)
            )
        ttk.Label(
            shortcuts,
            text='Format: Ctrl+Alt+Space. Leave a field empty to disable it.',
            wraplength=400,
        ).pack(anchor='w', pady=(4, 0))
        if not portal.hotkeys.supported:
            ttk.Label(shortcuts, text='Global hotkeys are currently available on Windows.').pack(anchor='w', pady=(10, 0))
        ttk.Button(frame, text='Save', command=lambda: portal.run(self.save)).pack(fill='x', pady=(14, 0))

    def save(self):
        self.portal.settings.update(
            sound_volume=max(0, min(1, self.volume.get())),
            music_volume=max(0, min(1, self.music_volume.get())),
            sound_cooldown=max(0, self.cooldown.get()),
            sound_on_change_only=self.only_change.get(),
            preview_seconds=max(1, self.preview.get()),
        )
        for name, variable in self.hotkeys.items():
            shortcut = variable.get().strip()
            if shortcut:
                parse_hotkey(shortcut)
            self.portal.settings[f'hotkey_{name}'] = shortcut
        if self.portal.desktop.backend.supports_cursor_size:
            size = max(1, min(15, self.cursor_size.get()))
            self.portal.desktop.backend.set_cursor_size(size)
            self.portal.settings['cursor_size'] = size
        self.portal.restore_on_remove.set(self.restore_on_remove.get())
        self.portal.start_with_windows.set(self.start_at_login.get())
        self.portal.settings['restore_on_remove'] = self.restore_on_remove.get()
        self.portal.settings['start_with_windows'] = self.start_at_login.get()
        self.portal.settings['dark_mode'] = self.dark_mode.get()
        set_startup_enabled(self.start_at_login.get())
        save_settings(self.portal.settings)
        set_music_volume(self.portal.settings['music_volume'])
        errors = self.portal.hotkeys.start(self.portal.hotkey_bindings())
        self.portal.apply_theme(self.dark_mode.get())
        self.portal.status.set(
            'Options saved.' if not errors else 'Options saved. Hotkey: ' + '; '.join(errors)
        )
        self.window.destroy()


class DiagnosticsDialog:
    def __init__(self, portal):
        self.portal = portal
        window = tk.Toplevel(portal.root)
        window.title('Diagnostics')
        window.geometry('720x480')
        window.transient(portal.root)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        active = portal.packs.get(portal.desktop.active, {}).get('name', 'Original desktop')
        summary = (
            f'Platform: {capability_summary(portal.desktop.backend)}\n'
            f'Active: {active}\n'
            f'NFC: {portal.reader_status.get()}\n'
            f'Present tags: {len(portal.present)}\n\nRecent activity:\n'
        )
        text = tk.Text(frame, wrap='word', font=('Consolas', 10))
        text.pack(fill='both', expand=True)
        text.insert('1.0', summary + '\n'.join(portal.activity))
        log_file = Path(__file__).resolve().parent / 'data/background.log'
        if log_file.is_file():
            lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()[-25:]
            text.insert('end', '\n\nBackground log:\n' + '\n'.join(lines))
        text.configure(state='disabled')
        ttk.Button(frame, text='Close', command=window.destroy).pack(anchor='e', pady=(10, 0))


class PackEditor:
    def __init__(self, portal, pack_id):
        self.portal, self.pack_id = portal, pack_id
        self.pack = dict(portal.packs[pack_id])
        self.pack['sounds'] = list(self.pack.get('sounds', []))
        self.pack['music'] = self.pack.get('music')
        self.pack['cursors'] = dict(self.pack.get('cursors', {}))
        self.pack['wallpapers'] = pack_wallpapers(self.pack)
        disabled = self.pack.get('disabled_assets', {})
        self.pack['disabled_assets'] = {
            'wallpapers': list(disabled.get('wallpapers', [])),
            'sounds': list(disabled.get('sounds', [])),
        }
        self.pack.pop('wallpaper', None)
        self.pack['effects'] = pack_effects(self.pack)
        self.window = tk.Toplevel(portal.root)
        self.window.title('Edit pack')
        self.window.geometry('760x690')
        self.window.minsize(680, 610)
        self.window.transient(portal.root)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Pack name').pack(anchor='w')
        self.name = tk.StringVar(value=self.pack['name'])
        ttk.Entry(frame, textvariable=self.name).pack(fill='x', pady=(4, 14))
        ttk.Label(
            frame,
            text='Choose files from anywhere. DesktopPortal copies them into this pack.',
        ).pack(anchor='w', pady=(0, 8))
        self.drop_status = tk.StringVar(
            value='Drop images, audio, cursor files, or folders here'
        )
        self.drop_target = ttk.Label(
            frame, textvariable=self.drop_status, style='Drop.TLabel'
        )
        self.drop_target.pack(fill='x', pady=(0, 12))
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target.drop_target_register(DND_FILES)
            self.drop_target.dnd_bind(
                '<<Drop>>',
                lambda event: portal.run(lambda: self.drop_assets(event.data)),
            )
        except (ImportError, AttributeError):
            self.drop_status.set('Drag and drop unavailable; use the file buttons below')
        self.effect_vars = {
            name: tk.BooleanVar(value=self.pack['effects'][name])
            for name in ('wallpaper', 'cursors', 'sounds', 'music')
        }
        self.effect_labels = {
            name: tk.StringVar() for name in self.effect_vars
        }
        for name, actions in [
            ('wallpaper', [('Add wallpapers', self.wallpaper),
                           ('Select / preview', self.manage_wallpapers),
                           ('Clear', self.clear_wallpapers)]),
            ('cursors', [('Edit mappings', self.cursor_mappings)]),
            ('sounds', [('Add sounds', self.sounds),
                        ('Select / preview', self.manage_sounds),
                        ('Clear', self.clear_sounds),
                        ]),
            ('music', [('Choose file', self.choose_music),
                       ('Clear', self.clear_music),
                       ('Test', self.test_music),
                       ('Stop', stop_music)]),
        ]:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=5)
            ttk.Checkbutton(
                row,
                textvariable=self.effect_labels[name],
                variable=self.effect_vars[name],
            ).pack(side='left', fill='x', expand=True)
            for label, action in actions:
                ttk.Button(
                    row,
                    text=label,
                    command=lambda f=action: portal.run(f),
                ).pack(side='left', padx=(6, 0))
        ttk.Label(
            frame,
            text='One wallpaper is chosen randomly each time the pack activates.',
        ).pack(anchor='w', pady=(10, 4))
        ttk.Button(
            frame,
            text='Save pack',
            command=lambda: portal.run(self.save),
        ).pack(fill='x', pady=(12, 0))
        self.update_info()

    def update_info(self):
        wallpaper_count = len(pack_assets(self.pack, 'wallpapers', True))
        self.effect_labels['wallpaper'].set(
            f'Wallpapers ({wallpaper_count}/{len(self.pack["wallpapers"])} enabled)'
        )
        self.effect_labels['cursors'].set(
            f'Cursor mappings ({len(self.pack["cursors"])}/15)'
        )
        sound_count = len(pack_assets(self.pack, 'sounds', True))
        self.effect_labels['sounds'].set(
            f'Sounds ({sound_count}/{len(self.pack["sounds"])} enabled)'
        )
        music = self.pack.get('music')
        kind = 'Local' if music else 'None'
        self.effect_labels['music'].set(f'Background music ({kind})')

    def copy(self, source, category, replace=None):
        from pathlib import Path
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(f'Asset not found: {source}')
        root = (PACKS_DIR / self.pack_id).resolve()
        if source.is_relative_to(root):
            return source.relative_to(root).as_posix()
        if replace:
            target = (root / replace).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f'Invalid pack asset path: {replace}')
            if target.suffix.lower() != source.suffix.lower():
                target = target.with_suffix(source.suffix.lower())
        else:
            target = root / category / source.name
            index = 1
            while target.exists():
                target = root / category / f'{source.stem}_{index}{source.suffix}'
                index += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target.relative_to(root).as_posix()

    def assign_cursor(self, role, path):
        mappings = self.pack['cursors']
        previous = mappings.get(role)
        relative = self.copy(path, 'cursors', replace=previous)
        mappings[role] = relative
        if previous and previous != relative and previous not in mappings.values():
            root = (PACKS_DIR / self.pack_id).resolve()
            obsolete = (root / previous).resolve()
            if obsolete.is_relative_to(root):
                obsolete.unlink(missing_ok=True)

    def drop_assets(self, raw_paths):
        paths = []
        for value in self.window.tk.splitlist(raw_paths):
            path = Path(value)
            if path.is_dir():
                paths.extend(item for item in path.rglob('*') if item.is_file())
            elif path.is_file():
                paths.append(path)
        counts = {'wallpapers': 0, 'sounds': 0, 'cursors': 0}
        skipped = 0
        for path in paths:
            suffix = path.suffix.casefold()
            if suffix in {'.png', '.jpg', '.jpeg', '.bmp'}:
                self.pack['wallpapers'].append(self.copy(path, 'wallpapers'))
                counts['wallpapers'] += 1
            elif suffix in {'.mp3', '.wav', '.ogg'}:
                self.pack['sounds'].append(self.copy(path, 'sounds'))
                counts['sounds'] += 1
            elif suffix in {'.ani', '.cur'}:
                role = detect_cursor_role(path)
                if role:
                    self.assign_cursor(role, path)
                    counts['cursors'] += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        imported = sum(counts.values())
        if not imported:
            raise ValueError('No supported assets or recognizable cursor names were dropped.')
        self.drop_status.set(
            f'Imported {counts["wallpapers"]} image(s), {counts["cursors"]} cursor(s), '
            f'{counts["sounds"]} sound(s)' + (f'; skipped {skipped}' if skipped else '')
        )
        self.update_info()

    def wallpaper(self):
        paths = filedialog.askopenfilenames(
            parent=self.window,
            filetypes=[('Images', '*.png *.jpg *.jpeg *.bmp')],
        )
        if paths:
            self.pack['wallpapers'].extend(
                self.copy(path, 'wallpapers') for path in paths
            )
            self.update_info()

    def clear_wallpapers(self):
        self.pack['wallpapers'] = []
        self.pack['disabled_assets']['wallpapers'] = []
        self.update_info()

    def manage_wallpapers(self):
        AssetRotationEditor(self, 'wallpapers')

    def cursor_mappings(self):
        CursorEditor(self)

    def sounds(self):
        paths = filedialog.askopenfilenames(parent=self.window, filetypes=[('Audio', '*.mp3 *.wav *.ogg')])
        self.pack['sounds'].extend(self.copy(path, 'sounds') for path in paths)
        self.update_info()

    def clear_sounds(self):
        self.pack['sounds'] = []
        self.pack['disabled_assets']['sounds'] = []
        self.update_info()

    def manage_sounds(self):
        AssetRotationEditor(self, 'sounds')

    def choose_music(self):
        path = filedialog.askopenfilename(
            parent=self.window,
            filetypes=[('Audio', '*.mp3 *.wav *.ogg')],
        )
        if path:
            previous = self.pack.get('music')
            self.pack['music'] = self.copy(path, 'music', replace=previous)
            self.update_info()

    def clear_music(self):
        self.pack['music'] = None
        stop_music()
        self.update_info()

    def test_music(self):
        source = self.pack.get('music')
        if not source:
            raise ValueError('Choose background music first.')
        source = PACKS_DIR / self.pack_id / source
        play_music(source, self.portal.settings.get('music_volume', 0.5))

    def save(self):
        if not self.name.get().strip():
            raise ValueError('Enter a pack name.')
        self.pack['name'] = self.name.get().strip()
        self.pack['format_version'] = 1
        self.pack['effects'] = {
            name: variable.get()
            for name, variable in self.effect_vars.items()
        }
        for category in ('wallpapers', 'sounds'):
            current = set(self.pack[category])
            self.pack['disabled_assets'][category] = [
                path for path in self.pack['disabled_assets'][category]
                if path in current
            ]
        write_json(PACKS_DIR / self.pack_id / 'pack.json', self.pack)
        self.portal.reload()
        self.window.destroy()


class AssetRotationEditor:
    def __init__(self, editor, category):
        self.editor, self.category = editor, category
        self.paths = editor.pack[category]
        title = 'Wallpapers' if category == 'wallpapers' else 'Activation sounds'
        self.window = tk.Toplevel(editor.window)
        self.window.title(f'{title} selection')
        self.window.geometry('760x520')
        self.window.minsize(620, 420)
        self.window.transient(editor.window)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.close)

        outer = ttk.Frame(self.window, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(
            outer,
            text=f'Choose which {title.lower()} can be selected during rotation.',
        ).pack(anchor='w', pady=(0, 10))

        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient='vertical', command=canvas.yview)
        self.rows = ttk.Frame(canvas)
        self.rows.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        self.row_window = canvas.create_window((0, 0), window=self.rows, anchor='nw')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(self.row_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        disabled = set(editor.pack['disabled_assets'][category])
        self.variables = {}
        for path in self.paths:
            row = ttk.Frame(self.rows, padding=(4, 4))
            row.pack(fill='x')
            variable = tk.BooleanVar(value=path not in disabled)
            self.variables[path] = variable
            ttk.Checkbutton(row, text=Path(path).name, variable=variable,
                            command=self.apply).pack(side='left', fill='x', expand=True)
            label = 'Preview' if category == 'wallpapers' else 'Play'
            ttk.Button(row, text=label,
                       command=lambda item=path: editor.portal.run(lambda: self.preview(item))).pack(side='right')

        if not self.paths:
            ttk.Label(self.rows, text=f'No {title.lower()} added yet.').pack(anchor='w', pady=10)

        self.image_label = None
        self.preview_image = None
        if category == 'wallpapers':
            self.image_label = tk.Label(outer, height=150, bd=0)
            self.image_label.pack(fill='x', pady=(12, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=(12, 0))
        ttk.Button(actions, text='Enable all', command=lambda: self.set_all(True)).pack(side='left')
        ttk.Button(actions, text='Disable all', command=lambda: self.set_all(False)).pack(side='left', padx=6)
        if category == 'sounds':
            ttk.Button(actions, text='Stop', command=stop_sound).pack(side='left')
        ttk.Button(actions, text='Done', command=self.close).pack(side='right')

    def apply(self):
        self.editor.pack['disabled_assets'][self.category] = [
            path for path, variable in self.variables.items() if not variable.get()
        ]
        self.editor.update_info()

    def set_all(self, enabled):
        for variable in self.variables.values():
            variable.set(enabled)
        self.apply()

    def preview(self, relative):
        path = PACKS_DIR / self.editor.pack_id / relative
        if self.category == 'sounds':
            play_sound(path, self.editor.portal.settings.get('sound_volume', 0.8))
            return
        image = Image.open(path)
        image.thumbnail((680, 150), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(image, master=self.window)
        self.image_label.configure(image=self.preview_image)

    def close(self):
        self.apply()
        if self.category == 'sounds':
            stop_sound()
        self.window.destroy()
        self.editor.window.grab_set()


class CursorEditor:
    ROLE_NAMES = {
        role: next(
            (name for name, mapped_role in CURSOR_MAPPING.items()
             if mapped_role == role and name != 'Normal'),
            role,
        )
        for role in CURSOR_ROLES
    }

    def __init__(self, editor):
        self.editor = editor
        self.window = tk.Toplevel(editor.window)
        self.window.title('Cursor mappings')
        self.window.geometry('980x600')
        self.window.minsize(820, 520)
        self.window.transient(editor.window)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.close)

        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(
            frame,
            text=('Choose a separate .ani or .cur file for each Windows cursor role. '
                  'Files from outside the pack are copied into it automatically.'),
            wraplength=700,
        ).pack(anchor='w', pady=(0, 10))

        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True)
        self.list = ttk.Treeview(
            body,
            columns=('role', 'file'),
            show='headings',
            selectmode='browse',
            height=15,
        )
        self.list.heading('role', text='Cursor state', anchor='w')
        self.list.heading('file', text='Selected file', anchor='w')
        self.list.column('role', width=210, stretch=False)
        self.list.column('file', width=430)
        self.list.pack(side='left', fill='both', expand=True)
        self.list.bind('<Double-1>', lambda event: self.editor.portal.run(self.choose))
        self.list.bind('<<TreeviewSelect>>', lambda event: self.update_preview())

        preview = ttk.Frame(body, padding=(18, 8, 0, 0))
        preview.pack(side='right', fill='y')
        ttk.Label(preview, text='Preview').pack(anchor='w')
        self.preview = tk.Label(preview, width=180, height=180, bd=0)
        self.preview.pack(pady=(8, 8))
        self.preview_text = tk.StringVar(value='No cursor selected')
        ttk.Label(
            preview, textvariable=self.preview_text,
            wraplength=180, justify='center', anchor='center',
        ).pack(fill='x')
        ttk.Button(
            preview, text='Flip horizontally',
            command=lambda: editor.portal.run(lambda: self.flip('x')),
        ).pack(fill='x', pady=(14, 6))
        ttk.Button(
            preview, text='Flip vertically',
            command=lambda: editor.portal.run(lambda: self.flip('y')),
        ).pack(fill='x')
        self.preview_frames = []
        self.preview_index = 0
        self.preview_job = None

        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        for label, action in [
            ('Choose file', self.choose),
            ('Clear selected', self.clear_selected),
            ('Auto-detect folder', self.auto_detect),
            ('Done', self.close),
        ]:
            ttk.Button(
                actions,
                text=label,
                command=lambda f=action: editor.portal.run(f),
            ).pack(side='left', padx=(0, 7))

        self.refresh()
        self.list.selection_set(CURSOR_ROLES[0])
        self.update_preview()

    def refresh(self):
        selected = self.list.selection()
        for item in self.list.get_children():
            self.list.delete(item)
        mappings = self.editor.pack['cursors']
        for role in CURSOR_ROLES:
            self.list.insert(
                '',
                'end',
                iid=role,
                values=(self.ROLE_NAMES[role], mappings.get(role, 'Not selected')),
            )
        if selected and selected[0] in CURSOR_ROLES:
            self.list.selection_set(selected[0])
        self.editor.update_info()

    def selected_role(self):
        selected = self.list.selection()
        if not selected:
            raise ValueError('Select a cursor state first.')
        return selected[0]

    def choose(self):
        role = self.selected_role()
        path = filedialog.askopenfilename(
            parent=self.window,
            title=f'Choose {self.ROLE_NAMES[role]} cursor',
            filetypes=[('Windows cursors', '*.ani *.cur')],
        )
        if path:
            self.assign(role, path)
            self.refresh()

    def assign(self, role, path):
        self.editor.assign_cursor(role, path)

    def clear_selected(self):
        self.editor.pack['cursors'].pop(self.selected_role(), None)
        self.refresh()

    def cursor_path(self, role):
        relative = self.editor.pack['cursors'].get(role)
        if not relative:
            return None
        root = (PACKS_DIR / self.editor.pack_id).resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        return path

    def flip(self, axis):
        role = self.selected_role()
        path = self.cursor_path(role)
        if path is None:
            raise ValueError('Choose a cursor for this state first.')
        mappings = self.editor.pack['cursors']
        relative = mappings[role]
        if sum(value == relative for value in mappings.values()) > 1:
            root = (PACKS_DIR / self.editor.pack_id).resolve()
            target = path.with_name(f'{path.stem}_{role.lower()}{path.suffix}')
            index = 1
            while target.exists():
                target = path.with_name(f'{path.stem}_{role.lower()}_{index}{path.suffix}')
                index += 1
            shutil.copy2(path, target)
            mappings[role] = target.relative_to(root).as_posix()
            path = target
        flip_cursor(path, axis)
        self.refresh()
        self.list.selection_set(role)
        self.update_preview()

    def update_preview(self):
        if self.preview_job is not None:
            self.window.after_cancel(self.preview_job)
            self.preview_job = None
        self.preview_frames = []
        selection = self.list.selection()
        path = self.cursor_path(selection[0]) if selection else None
        if path is None:
            self.preview.configure(image='', bg='#20242b')
            self.preview_text.set('No cursor selected')
            return
        try:
            frames = preview_frames(path)
            self.preview_frames = [self.make_preview(frame) for frame in frames]
        except Exception as error:
            self.preview.configure(image='', bg='#20242b')
            self.preview_text.set(f'Preview unavailable\n{error}')
            return
        self.preview_index = 0
        self.preview_text.set(
            path.name + (f'\nAnimated · {len(frames)} frames' if len(frames) > 1 else '')
        )
        self.show_preview_frame()

    def make_preview(self, image):
        size = 180
        tile = 12
        canvas = Image.new('RGB', (size, size), '#d9dde3')
        draw = ImageDraw.Draw(canvas)
        for y in range(0, size, tile):
            for x in range(0, size, tile):
                if (x // tile + y // tile) % 2:
                    draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill='#b8bec7')
        cursor = image.copy()
        cursor.thumbnail((150, 150), Image.Resampling.LANCZOS)
        position = ((size - cursor.width) // 2, (size - cursor.height) // 2)
        canvas.paste(cursor, position, cursor)
        return ImageTk.PhotoImage(canvas, master=self.window)

    def show_preview_frame(self):
        if not self.preview_frames:
            return
        image = self.preview_frames[self.preview_index]
        self.preview.configure(image=image, bg='#20242b')
        self.preview_index = (self.preview_index + 1) % len(self.preview_frames)
        if len(self.preview_frames) > 1:
            self.preview_job = self.window.after(100, self.show_preview_frame)

    def auto_detect(self):
        folder = filedialog.askdirectory(parent=self.window)
        if not folder:
            return
        detected = find_cursors(folder)
        if not detected:
            raise ValueError('No recognized cursor role names found in this folder.')
        for role, path in detected.items():
            self.assign(role, path)
        self.refresh()

    def close(self):
        if self.preview_job is not None:
            self.window.after_cancel(self.preview_job)
        self.window.destroy()
        self.editor.window.grab_set()


class CollectionManager:
    def __init__(self, portal):
        self.portal = portal
        self.collections = load_collections()
        self.window = tk.Toplevel(portal.root)
        self.window.title('Collections')
        self.window.geometry('850x440')
        self.window.minsize(760, 380)
        self.window.transient(portal.root)
        self.window.grab_set()

        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(
            frame,
            text='Collections enable or disable several packs together.',
        ).pack(anchor='w', pady=(0, 10))
        self.list = ttk.Treeview(
            frame,
            columns=('packs', 'enabled'),
            show='tree headings',
            selectmode='browse',
            height=10,
        )
        self.list.heading('#0', text='Collection', anchor='w')
        self.list.heading('packs', text='Packs', anchor='w')
        self.list.heading('enabled', text='Enabled packs', anchor='w')
        self.list.column('#0', width=300)
        self.list.column('packs', width=90)
        self.list.column('enabled', width=130)
        self.list.pack(fill='both', expand=True)
        self.list.bind('<Double-1>', lambda event: portal.run(self.edit_members))

        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        for label, action in [
            ('New', self.new),
            ('Edit members', self.edit_members),
            ('Export', self.export),
            ('Enable all packs', lambda: self.set_enabled(True)),
            ('Disable all packs', lambda: self.set_enabled(False)),
            ('Delete', self.delete),
        ]:
            ttk.Button(
                actions,
                text=label,
                command=lambda f=action: portal.run(f),
            ).pack(side='left', padx=(0, 6))
        self.refresh()

    def refresh(self, select=None):
        current = select or (self.list.selection()[0] if self.list.selection() else None)
        for item in self.list.get_children():
            self.list.delete(item)
        for name, members in self.collections.items():
            existing = [pack_id for pack_id in members if pack_id in self.portal.packs]
            enabled = sum(
                pack_enabled(self.portal.packs[pack_id]) for pack_id in existing
            )
            self.list.insert(
                '', 'end', iid=name, text=name,
                values=(len(existing), f'{enabled}/{len(existing)}'),
            )
        if current in self.collections:
            self.list.selection_set(current)
        elif self.collections:
            self.list.selection_set(next(iter(self.collections)))

    def selected(self):
        selection = self.list.selection()
        if not selection:
            raise ValueError('Select a collection first.')
        return selection[0]

    def new(self):
        name = simpledialog.askstring(
            'New collection', 'Collection name:', parent=self.window
        )
        if not name:
            return
        name = name.strip()
        if not name:
            raise ValueError('Enter a collection name.')
        if name in self.collections:
            raise ValueError(f'Collection already exists: {name}')
        self.collections[name] = []
        save_collections(self.collections)
        self.portal.reload()
        self.refresh(name)
        self.edit_members()

    def edit_members(self):
        CollectionMembers(self, self.selected())

    def set_enabled(self, enabled):
        name = self.selected()
        self.portal.set_packs_enabled(self.collections[name], enabled)
        self.refresh(name)

    def export(self):
        name = self.selected()
        members = [item for item in self.collections[name] if item in self.portal.packs]
        if not members:
            raise ValueError('This collection has no available packs.')
        safe_name = ''.join(character if character.isalnum() else '_' for character in name).strip('_')
        destination = filedialog.asksaveasfilename(
            parent=self.window, defaultextension='.zip', initialfile=f'{safe_name}.zip',
            filetypes=[('DesktopPortal bundle', '*.zip')],
        )
        if destination:
            export_bundle(members, destination, collection=name)
            self.portal.status.set(f'Exported collection {name}.')

    def delete(self):
        name = self.selected()
        if not messagebox.askyesno(
            'Delete collection',
            f'Delete the collection "{name}"? Packs will not be deleted.',
            parent=self.window,
        ):
            return
        del self.collections[name]
        save_collections(self.collections)
        self.portal.reload()
        self.refresh()


class CollectionMembers:
    def __init__(self, manager, name):
        self.manager = manager
        self.name = name
        self.pack_ids = list(manager.portal.packs)
        self.window = tk.Toplevel(manager.window)
        self.window.title(f'{name} — packs')
        self.window.geometry('480x500')
        self.window.transient(manager.window)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.close)

        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Select every pack in this collection.').pack(
            anchor='w', pady=(0, 8)
        )
        self.list = tk.Listbox(
            frame,
            selectmode='multiple',
            exportselection=False,
            font=('Segoe UI', 10),
        )
        self.list.pack(fill='both', expand=True)
        members = set(manager.collections[name])
        for index, pack_id in enumerate(self.pack_ids):
            pack = manager.portal.packs[pack_id]
            self.list.insert('end', f'{pack["name"]}  ({pack_id})')
            if pack_id in members:
                self.list.selection_set(index)
        ttk.Button(frame, text='Save members', command=self.save).pack(
            fill='x', pady=(12, 0)
        )

    def save(self):
        self.manager.collections[self.name] = [
            self.pack_ids[index] for index in self.list.curselection()
        ]
        save_collections(self.manager.collections)
        self.manager.portal.reload()
        self.manager.refresh(self.name)
        self.close()

    def close(self):
        self.window.destroy()
        self.manager.window.grab_set()


def notify_running_instance(show=True):
    try:
        with socket.create_connection((IPC_HOST, IPC_PORT), timeout=1) as connection:
            connection.sendall(b'show' if show else b'background')
        return True
    except OSError:
        return False


def create_command_socket():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    server.bind((IPC_HOST, IPC_PORT))
    server.listen(4)
    server.setblocking(False)
    return server


def main(start_hidden=False, on_ready=None):
    # The local command socket is both the single-instance lock and the
    # channel used to show an already-running background instance.
    if notify_running_instance(show=not start_hidden):
        return
    try:
        command_socket = create_command_socket()
    except OSError:
        if notify_running_instance(show=not start_hidden):
            return
        raise
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
    if start_hidden:
        root.withdraw()
    try:
        portal = Portal(
            root,
            command_socket=command_socket,
            start_hidden=start_hidden,
        )
        portal.shutdown_hooks = ShutdownHooks(
            root,
            portal.restore_for_system_shutdown,
            lambda: portal.quit_app(silent=True),
        )
    except Exception as error:
        messagebox.showerror('DesktopPortal could not start', str(error), parent=root)
        if command_socket is not None:
            command_socket.close()
        root.destroy()
        return
    if on_ready is not None:
        root.after_idle(on_ready)
    root.mainloop()


if __name__ == '__main__':
    main(start_hidden='--background' in sys.argv)
