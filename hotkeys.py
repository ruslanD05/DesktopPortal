"""System-wide DesktopPortal hotkeys."""
import sys
import threading


MODIFIERS = {
    'alt': 0x0001,
    'ctrl': 0x0002,
    'control': 0x0002,
    'shift': 0x0004,
    'win': 0x0008,
    'windows': 0x0008,
}
SPECIAL_KEYS = {
    'space': 0x20,
    'left': 0x25,
    'up': 0x26,
    'right': 0x27,
    'down': 0x28,
    'home': 0x24,
    'end': 0x23,
    'pageup': 0x21,
    'pagedown': 0x22,
}


def parse_hotkey(value):
    parts = [part.strip().lower() for part in str(value).split('+') if part.strip()]
    if len(parts) < 2:
        raise ValueError('Use a shortcut such as Ctrl+Alt+Space.')
    modifiers = 0x4000  # MOD_NOREPEAT
    for part in parts[:-1]:
        if part not in MODIFIERS:
            raise ValueError(f'Unknown shortcut modifier: {part}')
        modifiers |= MODIFIERS[part]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        virtual_key = ord(key.upper())
    elif key in SPECIAL_KEYS:
        virtual_key = SPECIAL_KEYS[key]
    elif key.startswith('f') and key[1:].isdigit() and 1 <= int(key[1:]) <= 11:
        virtual_key = 0x6F + int(key[1:])
    else:
        raise ValueError(f'Unknown shortcut key: {key}')
    return modifiers, virtual_key


class HotkeyManager:
    def __init__(self, events):
        self.events = events
        self.thread = None
        self.thread_id = None
        self.bindings = {}
        self.errors = []
        self.ready = threading.Event()

    @property
    def supported(self):
        return sys.platform == 'win32'

    def start(self, bindings):
        self.stop()
        self.bindings = {
            action: shortcut.strip()
            for action, shortcut in bindings.items() if shortcut.strip()
        }
        self.errors = []
        if not self.supported or not self.bindings:
            return []
        self.ready.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='Hotkeys')
        self.thread.start()
        self.ready.wait(2)
        return list(self.errors)

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        registered = []
        for hotkey_id, (action, shortcut) in enumerate(self.bindings.items(), 1):
            try:
                modifiers, key = parse_hotkey(shortcut)
            except ValueError as error:
                self.errors.append(f'{action}: {error}')
                continue
            if user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                registered.append(hotkey_id)
            else:
                self.errors.append(f'{shortcut} is already in use.')
        self.ready.set()
        message = wintypes.MSG()
        while registered and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312 and message.wParam in registered:
                action = list(self.bindings)[message.wParam - 1]
                self.events.put(('hotkey', action, ''))
        for hotkey_id in registered:
            user32.UnregisterHotKey(None, hotkey_id)
        self.thread_id = None

    def stop(self):
        if self.thread_id is not None and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.thread = None
        self.thread_id = None

