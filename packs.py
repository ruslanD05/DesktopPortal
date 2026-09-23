"""Local pack manifests and tag bindings; no desktop effects or NFC here."""
import json
import re
import sys
from pathlib import Path

BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, 'frozen', False)
    else Path(__file__).resolve().parent
)
PACKS_DIR = BASE_DIR / 'packs'
TAGS_FILE = BASE_DIR / 'data/tags.json'
SETTINGS_FILE = BASE_DIR / 'data/settings.json'
COLLECTIONS_FILE = BASE_DIR / 'data/collections.json'
PACK_FORMAT_VERSION = 1
DEFAULT_SETTINGS = {
    'restore_on_remove': True,
    'start_with_windows': False,
    'sound_volume': 0.8,
    'sound_cooldown': 1.0,
    'sound_on_change_only': True,
    'music_volume': 0.5,
    'preview_seconds': 8,
    'cursor_size': None,
    'dark_mode': False,
    'setup_complete': False,
    'hotkey_wheel': 'Ctrl+Alt+Space',
    'hotkey_next': 'Ctrl+Alt+Right',
    'hotkey_previous': 'Ctrl+Alt+Left',
    'hotkey_random': 'Ctrl+Alt+R',
    'wheel_collection': 'All enabled packs',
}
DEFAULT_EFFECTS = {
    'wallpaper': True, 'cursors': True, 'sounds': True, 'music': True,
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=4), encoding='utf-8')
    temporary.replace(path)


def load_tags():
    tags = json.loads(TAGS_FILE.read_text(encoding='utf-8')) if TAGS_FILE.exists() else {}
    if not isinstance(tags, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()):
        raise ValueError('tags.json must map UIDs to pack IDs.')
    return {uid.lower(): pack for uid, pack in tags.items()}


def save_tags(tags):
    write_json(TAGS_FILE, tags)


def load_settings():
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    settings = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
    if not isinstance(settings, dict):
        raise ValueError('settings.json must contain an object.')
    result = dict(DEFAULT_SETTINGS)
    for name in ('restore_on_remove', 'start_with_windows', 'sound_on_change_only',
                 'dark_mode', 'setup_complete'):
        if name in settings:
            if not isinstance(settings[name], bool):
                raise ValueError(f'{name} must be true or false.')
            result[name] = settings[name]
    for name in ('sound_volume', 'music_volume', 'sound_cooldown', 'preview_seconds'):
        if name in settings:
            if not isinstance(settings[name], (int, float)) or settings[name] < 0:
                raise ValueError(f'{name} must be a non-negative number.')
            result[name] = settings[name]
    if 'cursor_size' in settings:
        value = settings['cursor_size']
        if value is not None and (not isinstance(value, int) or not 1 <= value <= 15):
            raise ValueError('cursor_size must be between 1 and 15.')
        result['cursor_size'] = value
    for name in ('hotkey_wheel', 'hotkey_next', 'hotkey_previous',
                 'hotkey_random', 'wheel_collection'):
        if name in settings:
            if not isinstance(settings[name], str):
                raise ValueError(f'{name} must be text.')
            result[name] = settings[name].strip()
    result['sound_volume'] = min(1.0, float(result['sound_volume']))
    result['music_volume'] = min(1.0, float(result['music_volume']))
    return result


def save_settings(settings):
    write_json(SETTINGS_FILE, settings)


def pack_wallpapers(pack):
    """Return the new wallpaper list, with legacy single-wallpaper support."""
    if 'wallpapers' in pack:
        wallpapers = pack['wallpapers']
        if not isinstance(wallpapers, list) or not all(
            isinstance(path, str) for path in wallpapers
        ):
            raise ValueError('wallpapers must be a list of file paths.')
        return list(wallpapers)
    wallpaper = pack.get('wallpaper')
    if wallpaper is not None and not isinstance(wallpaper, str):
        raise ValueError('wallpaper must be a file path or null.')
    return [wallpaper] if wallpaper else []


def pack_effects(pack):
    effects = pack.get('effects', {})
    if not isinstance(effects, dict):
        raise ValueError('effects must contain checkbox values.')
    result = dict(DEFAULT_EFFECTS)
    for name in result:
        if name in effects:
            if not isinstance(effects[name], bool):
                raise ValueError(f'effects.{name} must be true or false.')
            result[name] = effects[name]
    return result


def pack_enabled(pack):
    enabled = pack.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ValueError('enabled must be true or false.')
    return enabled


def load_collections():
    if not COLLECTIONS_FILE.exists():
        return {}
    collections = json.loads(COLLECTIONS_FILE.read_text(encoding='utf-8'))
    if not isinstance(collections, dict):
        raise ValueError('collections.json must contain an object.')
    for name, members in collections.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Collection names must be non-empty text.')
        if not isinstance(members, list) or not all(
            isinstance(pack_id, str) for pack_id in members
        ):
            raise ValueError(f'Collection {name} must contain pack IDs.')
    return collections


def save_collections(collections):
    write_json(COLLECTIONS_FILE, collections)


def group_packs(packs, collections):
    """Return collection rows plus packs that do not belong to a collection."""
    groups = []
    collected = set()
    for name, members in collections.items():
        existing = [pack_id for pack_id in members if pack_id in packs]
        groups.append((name, existing))
        collected.update(existing)
    uncollected = [pack_id for pack_id in packs if pack_id not in collected]
    if uncollected:
        groups.append(('Uncollected', uncollected))
    return groups


def asset(pack_id, relative):
    root = (PACKS_DIR / pack_id).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Missing or invalid pack asset: {relative}')
    return path


def load_packs():
    packs, errors = {}, []
    PACKS_DIR.mkdir(exist_ok=True)
    for folder in sorted(PACKS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        try:
            pack = json.loads((folder / 'pack.json').read_text(encoding='utf-8'))
            if not isinstance(pack, dict) or not isinstance(pack.get('name'), str):
                raise ValueError('Pack needs a name.')
            if pack.get('format_version', PACK_FORMAT_VERSION) > PACK_FORMAT_VERSION:
                raise ValueError('Pack uses a newer unsupported format version.')
            if not isinstance(pack.get('cursors', {}), dict) or not isinstance(pack.get('sounds', []), list):
                raise ValueError('Invalid cursors or sounds manifest.')
            music = pack.get('music')
            if music is not None and not isinstance(music, str):
                raise ValueError('music must be a file path, URL, or null.')
            pack_wallpapers(pack)
            pack_effects(pack)
            pack_enabled(pack)
            packs[folder.name] = pack
        except (OSError, ValueError) as error:
            errors.append(f'{folder.name}: {error}')
    return packs, errors


def create_pack(pack_id, name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', pack_id):
        raise ValueError('Use lowercase letters, numbers, underscores or hyphens for the ID.')
    if not name.strip():
        raise ValueError('Enter a pack name.')
    (PACKS_DIR / pack_id).mkdir()
    pack = dict(
        id=pack_id,
        format_version=PACK_FORMAT_VERSION,
        name=name.strip(),
        wallpapers=[],
        cursors={},
        sounds=[],
        music=None,
        effects=dict(DEFAULT_EFFECTS),
        enabled=True,
    )
    write_json(PACKS_DIR / pack_id / 'pack.json', pack)
    return pack
