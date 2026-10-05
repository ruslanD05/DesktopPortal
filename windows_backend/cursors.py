"""Apply and restore Windows cursor schemes and pointer sizes."""
import ctypes
from ctypes import wintypes
import winreg
from pathlib import Path
from cursor_roles import CURSOR_MAPPING, CURSOR_ROLES, find_cursors


CURSOR_REGISTRY_PATH = r"Control Panel\Cursors"
ACCESSIBILITY_REGISTRY_PATH = r"Software\Microsoft\Accessibility"


# Windows API constant:
# Reloads the system cursors from the current cursor scheme.
SPI_SETCURSORS = 0x0057


# Define the Windows function properly instead of relying on
# ctypes to guess argument/return types.
user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.SystemParametersInfoW.argtypes = [
    ctypes.c_uint,     # uiAction
    ctypes.c_uint,     # uiParam
    ctypes.c_void_p,   # pvParam
    ctypes.c_uint,     # fWinIni
]

user32.SystemParametersInfoW.restype = wintypes.BOOL


def reload_cursors():
    """Tell Windows to reload the cursor scheme from the registry."""

    ctypes.set_last_error(0)

    success = user32.SystemParametersInfoW(
        SPI_SETCURSORS,
        0,
        0,
        0
    )

    if not success:
        error = ctypes.get_last_error()

        if error:
            raise ctypes.WinError(error)

        raise OSError("Windows failed to reload cursors.")


def get_cursor_size():
    """Return the Windows accessibility pointer-size step, from 1 to 15."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ACCESSIBILITY_REGISTRY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, 'CursorSize')
            return max(1, min(15, int(value)))
    except (FileNotFoundError, OSError, ValueError):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CURSOR_REGISTRY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, 'CursorBaseSize')
                return max(1, min(15, round((int(value) - 32) / 16) + 1))
        except (FileNotFoundError, OSError, ValueError):
            return 1


def set_cursor_size(size):
    """Set the Windows accessibility pointer-size step and reload cursors."""
    size = int(size)
    if not 1 <= size <= 15:
        raise ValueError('Cursor size must be between 1 and 15.')
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, ACCESSIBILITY_REGISTRY_PATH, 0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, 'CursorSize', 0, winreg.REG_DWORD, size)
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, CURSOR_REGISTRY_PATH, 0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(
            key, 'CursorBaseSize', 0, winreg.REG_DWORD, 32 + (size - 1) * 16
        )
    reload_cursors()


def snapshot_cursors():
    """Keep value types and absent entries for exact restoration."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CURSOR_REGISTRY_PATH) as key:
        snapshot = {}
        for role in CURSOR_ROLES:
            try:
                snapshot[role] = winreg.QueryValueEx(key, role)
            except FileNotFoundError:
                snapshot[role] = None
        return snapshot


def restore_cursors(snapshot):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CURSOR_REGISTRY_PATH,
                        0, winreg.KEY_SET_VALUE) as key:
        for role, entry in snapshot.items():
            if entry is None:
                try:
                    winreg.DeleteValue(key, role)
                except FileNotFoundError:
                    pass
            else:
                value, value_type = entry
                winreg.SetValueEx(key, role, 0, value_type, value)
    reload_cursors()


def set_cursors(cursors):
    """Validate paths, apply them, and roll back if Windows rejects them."""
    paths = {}
    for role, path in cursors.items():
        if role not in CURSOR_ROLES:
            raise ValueError(f"Unknown cursor role: {role}")
        if path is None or str(path) == "":
            paths[role] = ""
            continue
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Cursor file not found: {path}")
        paths[role] = str(path)

    original = snapshot_cursors()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CURSOR_REGISTRY_PATH,
                            0, winreg.KEY_SET_VALUE) as key:
            for role, path in paths.items():
                winreg.SetValueEx(key, role, 0, winreg.REG_SZ, path)
        reload_cursors()
    except BaseException:
        restore_cursors(original)
        raise


def get_current_cursors():
    """Read the currently configured Windows cursor paths."""

    cursors = {}

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        CURSOR_REGISTRY_PATH
    ) as key:

        for role in CURSOR_ROLES:
            try:
                value, _ = winreg.QueryValueEx(key, role)
                cursors[role] = value

            except FileNotFoundError:
                cursors[role] = ""

    return cursors


if __name__ == "__main__":
    twilight = find_cursors(
        Path(__file__).resolve().parent.parent / "packs/twilight_sparkle/cursors"
    )
    print(f"Found {len(twilight)}/{len(CURSOR_ROLES)} Twilight cursors.")
    if set(twilight) != set(CURSOR_ROLES):
        raise SystemExit("Not all cursor roles were found. Aborting.")

    input("Press Enter to apply Twilight...")
    original = snapshot_cursors()
    try:
        set_cursors(twilight)
        input("Twilight is applied. Press Enter to restore original cursors...")
    finally:
        restore_cursors(original)
        if snapshot_cursors() != original:
            raise RuntimeError("Restored cursor registry does not match the original.")
        print("Original cursor registry restored exactly; Windows reload succeeded.")
