from pathlib import Path


CURSOR_ROLES = [
    'Arrow', 'Help', 'AppStarting', 'Wait', 'Crosshair', 'IBeam', 'NWPen',
    'No', 'SizeNS', 'SizeWE', 'SizeNWSE', 'SizeNESW', 'SizeAll', 'UpArrow',
    'Hand',
]

CURSOR_MAPPING = {
    'Normal Select': 'Arrow', 'Normal': 'Arrow', 'Help Select': 'Help',
    'Working in Background': 'AppStarting', 'Busy': 'Wait',
    'Precision Select': 'Crosshair', 'Text Select': 'IBeam',
    'Handwriting': 'NWPen', 'Unavailable': 'No', 'Vertical Resize': 'SizeNS',
    'Horizontal Resize': 'SizeWE', 'Diagonal 1': 'SizeNWSE',
    'Diagonal 2': 'SizeNESW', 'Move': 'SizeAll',
    'Alternate Select': 'UpArrow', 'Link Select': 'Hand',
}


def find_cursors(cursor_dir):
    cursor_dir = Path(cursor_dir)
    if not cursor_dir.exists():
        raise FileNotFoundError(f'Cursor directory not found: {cursor_dir.resolve()}')
    cursors = {}
    # Match longer names first so "Normal Select" wins over "Normal".
    names = sorted(CURSOR_MAPPING, key=len, reverse=True)
    for path in cursor_dir.iterdir():
        if path.suffix.lower() not in {'.ani', '.cur'}:
            continue
        for name in names:
            if name.lower() in path.stem.lower():
                cursors[CURSOR_MAPPING[name]] = path.resolve()
                break
    return cursors


def detect_cursor_role(path):
    """Infer one cursor role from a .ani/.cur filename."""
    stem = Path(path).stem.casefold()
    for name in sorted(CURSOR_MAPPING, key=len, reverse=True):
        if name.casefold() in stem:
            return CURSOR_MAPPING[name]
    return None
