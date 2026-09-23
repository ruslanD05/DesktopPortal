"""Desktop effects isolated from portable pack and GUI code."""
import os
import platform
import subprocess
from pathlib import Path


class WindowsBackend:
    name = 'Windows'
    supports_wallpaper = True
    supports_cursors = True
    supports_wallpaper_fade = False
    supports_cursor_size = True

    def get_wallpaper(self):
        from set_wallpaper import get_wallpaper
        return get_wallpaper()

    def set_wallpaper(self, value):
        from set_wallpaper import set_wallpaper
        set_wallpaper(value)

    def snapshot_cursors(self):
        from set_cursors import snapshot_cursors
        return snapshot_cursors()

    def set_cursors(self, cursors):
        from set_cursors import set_cursors
        set_cursors(cursors)

    def restore_cursors(self, snapshot):
        from set_cursors import restore_cursors
        restore_cursors(snapshot)

    def get_cursor_size(self):
        from set_cursors import get_cursor_size
        return get_cursor_size()

    def set_cursor_size(self, size):
        from set_cursors import set_cursor_size
        set_cursor_size(size)


class LinuxBackend:
    name = 'Linux'
    supports_cursors = False
    supports_wallpaper_fade = False
    supports_cursor_size = False

    def __init__(self):
        desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').casefold()
        self.desktop = desktop or 'unknown desktop'
        self.kind = 'gnome' if any(x in desktop for x in ('gnome', 'unity', 'cinnamon')) else (
            'kde' if 'kde' in desktop or 'plasma' in desktop else 'unsupported'
        )
        self.supports_wallpaper = self.kind in {'gnome', 'kde'}

    def _run(self, *args):
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()

    def get_wallpaper(self):
        if self.kind == 'gnome':
            value = self._run('gsettings', 'get', 'org.gnome.desktop.background', 'picture-uri')
            return value.strip("'").removeprefix('file://')
        raise OSError(f'Wallpaper restore is not supported on {self.desktop}.')

    def set_wallpaper(self, value):
        path = Path(value).resolve() if value else None
        if path and not path.is_file():
            raise FileNotFoundError(path)
        uri = path.as_uri() if path else ''
        if self.kind == 'gnome':
            for key in ('picture-uri', 'picture-uri-dark'):
                self._run('gsettings', 'set', 'org.gnome.desktop.background', key, uri)
            return
        if self.kind == 'kde':
            self._run('plasma-apply-wallpaperimage', str(path))
            return
        raise OSError(f'Wallpaper changes are not supported on {self.desktop}.')

    def snapshot_cursors(self):
        return {}

    def set_cursors(self, cursors):
        raise OSError('Per-role Windows cursor packs are unavailable on Linux.')

    def restore_cursors(self, snapshot):
        return None

    def get_cursor_size(self):
        return 1

    def set_cursor_size(self, size):
        raise OSError('System cursor sizing is unavailable on this desktop.')


class UnsupportedBackend(LinuxBackend):
    name = platform.system() or 'Unknown'

    def __init__(self):
        self.desktop = self.name
        self.kind = 'unsupported'
        self.supports_wallpaper = False


def get_backend():
    system = platform.system()
    if system == 'Windows':
        return WindowsBackend()
    if system == 'Linux':
        return LinuxBackend()
    return UnsupportedBackend()


def capability_summary(backend=None):
    backend = backend or get_backend()
    wallpaper = 'wallpaper' if backend.supports_wallpaper else 'no wallpaper control'
    cursors = 'per-role cursors' if backend.supports_cursors else 'no per-role cursors'
    size = 'cursor sizing' if backend.supports_cursor_size else 'no cursor sizing'
    return f'{backend.name}: {wallpaper}, {cursors}, {size}'
