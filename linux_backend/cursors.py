"""Build and apply GNOME Xcursor themes from DesktopPortal cursor mappings."""
import ast
import configparser
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from cursor_conversion import convert_cursor, cursor_format, read_cursor
from cursor_roles import CURSOR_ROLES
from linux_backend.wallpaper import _run

SCHEMA = 'org.gnome.desktop.interface'
THEME_NAMES = {
    'Arrow': ('left_ptr', 'default', 'arrow', 'top_left_arrow'),
    'Help': ('question_arrow', 'help', 'whats_this'),
    'AppStarting': ('left_ptr_watch', 'progress', 'half-busy'),
    'Wait': ('watch', 'wait'),
    'Crosshair': ('crosshair', 'cross', 'tcross'),
    'IBeam': ('xterm', 'text', 'ibeam'),
    'NWPen': ('pencil',),
    'No': ('crossed_circle', 'not-allowed', 'forbidden', 'no-drop'),
    'SizeNS': ('sb_v_double_arrow', 'ns-resize', 'n-resize', 's-resize', 'size_ver', 'row-resize'),
    'SizeWE': ('sb_h_double_arrow', 'ew-resize', 'e-resize', 'w-resize', 'size_hor', 'col-resize'),
    'SizeNWSE': ('size_fdiag', 'nwse-resize', 'nw-resize', 'se-resize'),
    'SizeNESW': ('size_bdiag', 'nesw-resize', 'ne-resize', 'sw-resize'),
    'SizeAll': ('fleur', 'move', 'all-scroll', 'all-resize', 'size_all'),
    'UpArrow': ('up_arrow', 'center_ptr'),
    'Hand': ('hand2', 'pointer', 'pointing_hand', 'hand'),
}


def snapshot_cursors():
    """Keep GVariant values verbatim so restoration preserves theme and size."""
    return {
        'theme': _run('gsettings', 'get', SCHEMA, 'cursor-theme'),
        'size': _run('gsettings', 'get', SCHEMA, 'cursor-size'),
    }


def theme_name(snapshot):
    try:
        name = ast.literal_eval(snapshot['theme'])
        size = int(snapshot['size'])
    except (KeyError, TypeError, ValueError, SyntaxError) as error:
        raise ValueError('Invalid Linux cursor snapshot.') from error
    if not isinstance(name, str) or not isinstance(snapshot['size'], str) or size <= 0:
        raise ValueError('Invalid Linux cursor snapshot.')
    return name


def restore_cursors(snapshot):
    theme_name(snapshot)
    errors = []
    for key, value in (('cursor-theme', snapshot['theme']), ('cursor-size', snapshot['size'])):
        try:
            _run('gsettings', 'set', SCHEMA, key, value)
        except Exception as error:
            errors.append(str(error))
    if errors:
        raise OSError('; '.join(errors))


def build_theme(cursors, inherited_theme, themes_dir=None):
    """Install an immutable theme; unmapped shapes inherit the original theme."""
    if not cursors:
        raise ValueError('No recognized cursor roles were found.')
    if set(cursors) - set(CURSOR_ROLES):
        raise ValueError('The pack contains unsupported cursor roles.')
    digest = hashlib.sha256(inherited_theme.encode('utf-8'))
    sources = {}
    for role, source in sorted(cursors.items()):
        source = Path(source).resolve()
        cursor_format(source)
        sources[role] = source
        digest.update(role.encode('ascii') + b'\0' + source.read_bytes())
    name = 'DesktopPortal-' + digest.hexdigest()[:24]
    themes_dir = Path(themes_dir) if themes_dir is not None else Path.home() / '.icons'
    destination = themes_dir / name
    if destination.is_dir():
        return name
    themes_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.desktopportal-', dir=themes_dir) as directory:
        staged = Path(directory) / name
        output = staged / 'cursors'
        output.mkdir(parents=True)
        for role, source in sources.items():
            primary, *aliases = THEME_NAMES[role]
            target = output / primary
            if cursor_format(source) == 'xcursor':
                read_cursor(source)  # Validate before installing a native file.
                shutil.copy2(source, target)
            else:
                converted = convert_cursor(source, output / (primary + '.xcursor'))
                converted.rename(target)
            for alias in aliases:
                # Copies also work when this directory is on a non-POSIX volume.
                shutil.copy2(target, output / alias)
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config['Icon Theme'] = {'Name': name, 'Inherits': inherited_theme or 'Adwaita'}
        with (staged / 'index.theme').open('w', encoding='utf-8') as stream:
            config.write(stream)
        staged.rename(destination)
    return name


def apply_theme(name, size=None):
    if size is not None:
        if not isinstance(size, int) or not 1 <= size <= 256:
            raise ValueError('Linux cursor size must be between 1 and 256 pixels.')
        _run('gsettings', 'set', SCHEMA, 'cursor-size', str(size))
    _run('gsettings', 'set', SCHEMA, 'cursor-theme', json.dumps(name))
