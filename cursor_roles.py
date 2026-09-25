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

# Windows registry identifiers are common in downloaded cursor packs, while
# the display names above are more common in hand-labeled folders. Matching
# ignores separators, so e.g. ``Working_in_Background`` and
# ``Working+in.Background`` resolve to the same alias.
CURSOR_ALIASES = {
    **CURSOR_MAPPING,
    'Arrow': 'Arrow',
    'Help': 'Help',
    'AppStarting': 'AppStarting',
    'Working Background': 'AppStarting',
    'Background Working': 'AppStarting',
    'Wait': 'Wait',
    'Crosshair': 'Crosshair',
    'Cross Hair': 'Crosshair',
    'IBeam': 'IBeam',
    'I Beam': 'IBeam',
    'NWPen': 'NWPen',
    'No': 'No',
    'SizeNS': 'SizeNS',
    'Size NS': 'SizeNS',
    'SizeWE': 'SizeWE',
    'Size WE': 'SizeWE',
    'SizeNWSE': 'SizeNWSE',
    'Size NWSE': 'SizeNWSE',
    'Diagonal Resize 1': 'SizeNWSE',
    'SizeNESW': 'SizeNESW',
    'Size NESW': 'SizeNESW',
    'Diagonal Resize 2': 'SizeNESW',
    'SizeAll': 'SizeAll',
    'UpArrow': 'UpArrow',
    'Up Arrow': 'UpArrow',
    'Hand': 'Hand',
}


def _normalize_name(value):
    """Ignore spaces and punctuation when matching cursor filenames."""
    return ''.join(character for character in value.casefold() if character.isalnum())


_NORMALIZED_ALIASES = sorted(
    ((_normalize_name(name), role) for name, role in CURSOR_ALIASES.items()),
    key=lambda entry: len(entry[0]),
    reverse=True,
)


def find_cursors(cursor_dir):
    cursor_dir = Path(cursor_dir)
    if not cursor_dir.exists():
        raise FileNotFoundError(f'Cursor directory not found: {cursor_dir.resolve()}')
    cursors = {}
    for path in cursor_dir.iterdir():
        if path.suffix.lower() not in {'.ani', '.cur'}:
            continue
        stem = _normalize_name(path.stem)
        # Match longer aliases first, so "Normal Select" wins over "Normal".
        for alias, role in _NORMALIZED_ALIASES:
            if alias in stem:
                cursors[role] = path.resolve()
                break
    return cursors


def detect_cursor_role(path):
    """Infer one cursor role from a .ani/.cur filename."""
    stem = _normalize_name(Path(path).stem)
    for alias, role in _NORMALIZED_ALIASES:
        if alias in stem:
            return role
    return None
