"""Read and apply Windows desktop wallpapers."""
import ctypes
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL('user32', use_last_error=True)
spi = user32.SystemParametersInfoW
spi.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
spi.restype = wintypes.BOOL


def get_wallpaper():
    buffer = ctypes.create_unicode_buffer(32768)
    if not spi(0x0073, len(buffer), buffer, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def set_wallpaper(image_path):
    path = str(Path(image_path).resolve()) if image_path else ''
    if path and not Path(path).is_file():
        raise FileNotFoundError(f'Wallpaper not found: {path}')
    if not spi(20, 0, ctypes.c_wchar_p(path), 3):
        raise ctypes.WinError(ctypes.get_last_error())
