import ctypes
from pathlib import Path


SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def set_wallpaper(image_path):
    path = Path(image_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Wallpaper not found: {path}")

    result = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER,
        0,
        str(path),
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )

    if not result:
        raise ctypes.WinError()



set_wallpaper("C:\\Users\\rusla\\Desktop\\DesktopPortal\\MLP_Wallpaper\\AppleJack.png")