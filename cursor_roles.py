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

LINUX_CURSOR_ROLES = {
    'left_ptr': 'Arrow', 'default': 'Arrow', 'arrow': 'Arrow',
    'question_arrow': 'Help', 'help': 'Help',
    'left_ptr_watch': 'AppStarting', 'progress': 'AppStarting',
    'watch': 'Wait', 'wait': 'Wait', 'crosshair': 'Crosshair',
    'xterm': 'IBeam', 'text': 'IBeam', 'pencil': 'NWPen',
    'not-allowed': 'No', 'crossed_circle': 'No',
    'ns-resize': 'SizeNS', 'sb_v_double_arrow': 'SizeNS',
    'ew-resize': 'SizeWE', 'sb_h_double_arrow': 'SizeWE',
    'nwse-resize': 'SizeNWSE', 'size_fdiag': 'SizeNWSE',
    'nesw-resize': 'SizeNESW', 'size_bdiag': 'SizeNESW',
    'fleur': 'SizeAll', 'move': 'SizeAll', 'all-scroll': 'SizeAll',
    'up_arrow': 'UpArrow', 'hand2': 'Hand', 'pointer': 'Hand',
}


def is_cursor_file(path):
    path = Path(path)
    if not path.is_file():
        return False
    if path.suffix.lower() in {'.ani', '.cur', '.xcursor'}:
        return True
    with path.open('rb') as source:
        return source.read(4) == b'Xcur'

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
    paths = sorted(cursor_dir.rglob('*'), key=lambda path: (
        len(path.relative_to(cursor_dir).parts), str(path).casefold(),
    ))
    for path in paths:
        if not is_cursor_file(path):
            continue
        role = detect_cursor_role(path)
        if role:
            # Prefer files nearest the selected folder when nested names repeat.
            cursors.setdefault(role, path.resolve())
    return cursors


def detect_cursor_role(path):
    """Infer a cursor role from common Windows or Linux cursor names."""
    if Path(path).stem.casefold() in LINUX_CURSOR_ROLES:
        return LINUX_CURSOR_ROLES[Path(path).stem.casefold()]
    stem = _normalize_name(Path(path).stem)
    for alias, role in _NORMALIZED_ALIASES:
        if alias in stem:
            return role
    return None
