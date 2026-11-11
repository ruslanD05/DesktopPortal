import os
from pathlib import Path
import subprocess

KDE_CONFIG = 'plasma-org.kde.plasma.desktop-appletsrc'



def _run(*args):
        env = None
        if args[0] == 'gsettings':
            schema_dir = Path('/usr/share/glib-2.0/schemas')
            schema_paths = (
                os.environ.get('GSETTINGS_SCHEMA_DIR', ''),
                os.environ.get('XDG_DATA_DIRS', ''),
            )
            if any('/snap/' in value for value in schema_paths) and (schema_dir / 'gschemas.compiled').is_file():
                # Snap terminals can expose older schemas than the host desktop.
                env = os.environ.copy()
                env['GSETTINGS_SCHEMA_DIR'] = str(schema_dir)
        result = subprocess.run(args, capture_output=True, text=True, env=env)
        if result.returncode:
            print('Failed command:', args, flush=True)
            print('Error:', result.stderr.strip(), flush=True)
            result.check_returncode()
        return result.stdout.strip()

def get_wallpaper(kind, desktop):
    if kind == 'gnome':
        value = _run('gsettings', 'get', 'org.gnome.desktop.background', 'picture-uri')
        return value.strip("'").removeprefix('file://')
    if kind == 'kde':
        return _kde_wallpaper(Path.home() / '.config' / KDE_CONFIG)
    raise OSError(f'Wallpaper restore is not supported on {desktop}.')


def _kde_wallpaper(config):
    """Return the first desktop image in Plasma's config, or '' if unknown."""
    try:
        lines = config.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return ''
    in_wallpaper = False
    for line in lines:
        if line.startswith('['):
            in_wallpaper = '[Wallpaper]' in line and line.endswith('[General]')
        elif in_wallpaper and line.startswith('Image='):
            return line.partition('=')[2].strip().removeprefix('file://')
    return ''

def set_wallpaper(kind, desktop, value):
    path = Path(value).resolve() if value else None
    if path and not path.is_file():
        raise FileNotFoundError(path)
    uri = path.as_uri() if path else ''
    if kind == 'gnome':
        for key in ('picture-uri', 'picture-uri-dark'):
            _run('gsettings', 'set', 'org.gnome.desktop.background', key, uri)
        return
    if kind == 'kde':
        # Plasma cannot clear a wallpaper, so an unknown original is left as is.
        if path:
            _run('plasma-apply-wallpaperimage', str(path))
        return
    raise OSError(f'Wallpaper changes are not supported on {desktop}.')