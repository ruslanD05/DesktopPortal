"""Restore desktop effects when the operating system ends the session."""
import ctypes
import signal
import sys


class ShutdownHooks:
    WM_QUERYENDSESSION = 0x0011
    GWL_WNDPROC = -4

    def __init__(self, root, restore, exit_app):
        self.root = root
        self.restore = restore
        self.exit_app = exit_app
        self.previous_signals = {}
        self.old_window_proc = None
        self.window_proc = None
        self.hwnd = None
        self._exit_scheduled = False
        self._install_signals()
        if sys.platform == 'win32':
            try:
                self._install_windows_session_hook()
            except OSError:
                # Signal handling and next-launch recovery remain available.
                self.old_window_proc = None
                self.window_proc = None
                self.hwnd = None

    def _install_signals(self):
        for name in ('SIGTERM', 'SIGINT'):
            value = getattr(signal, name, None)
            if value is None:
                continue
            try:
                self.previous_signals[value] = signal.getsignal(value)
                signal.signal(value, self._handle_signal)
            except (OSError, ValueError):
                pass

    def _handle_signal(self, signum, frame):
        if self._exit_scheduled:
            return
        self._exit_scheduled = True
        try:
            self.root.after_idle(self.exit_app)
        except Exception:
            self.restore()

    def _install_windows_session_hook(self):
        user32 = ctypes.windll.user32
        pointer_type = ctypes.c_ssize_t
        callback_type = ctypes.WINFUNCTYPE(
            pointer_type, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_size_t, pointer_type,
        )
        set_window_proc = user32.SetWindowLongPtrW
        set_window_proc.argtypes = [ctypes.c_void_p, ctypes.c_int, pointer_type]
        set_window_proc.restype = pointer_type
        user32.CallWindowProcW.argtypes = [
            pointer_type, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_size_t, pointer_type,
        ]
        user32.CallWindowProcW.restype = pointer_type
        self.hwnd = self.root.winfo_id()

        def window_proc(hwnd, message, wparam, lparam):
            if message == self.WM_QUERYENDSESSION:
                # Windows gives applications a short synchronous window here.
                self.restore()
            return user32.CallWindowProcW(
                self.old_window_proc, hwnd, message, wparam, lparam
            )

        self.window_proc = callback_type(window_proc)
        address = ctypes.cast(self.window_proc, ctypes.c_void_p).value
        self.old_window_proc = set_window_proc(
            self.hwnd, self.GWL_WNDPROC, address
        )
        if not self.old_window_proc:
            raise ctypes.WinError()

    def close(self):
        for value, previous in self.previous_signals.items():
            try:
                signal.signal(value, previous)
            except (OSError, ValueError):
                pass
        self.previous_signals.clear()
        if self.old_window_proc and self.hwnd and sys.platform == 'win32':
            try:
                ctypes.windll.user32.SetWindowLongPtrW(
                    self.hwnd, self.GWL_WNDPROC, self.old_window_proc
                )
            except Exception:
                pass
        self.old_window_proc = None
        self.window_proc = None
