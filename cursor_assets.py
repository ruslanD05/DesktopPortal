"""Prepare native cursor assets while retaining the portable source files."""
import hashlib
from pathlib import Path
import sys

from cursor_conversion import convert_cursor, cursor_format, read_cursor


def native_cursor(source, root, target_platform=None):
    root = Path(root).resolve()
    source = Path(source).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError(f'Missing or invalid cursor asset: {source.name}')
    target_platform = target_platform or sys.platform
    kind = cursor_format(source)
    if target_platform == 'win32':
        native = kind in {'ani', 'cur'}
        platform_folder = 'windows'
    elif target_platform.startswith('linux'):
        native = kind == 'xcursor'
        platform_folder = 'linux'
    else:
        return source.relative_to(root).as_posix()
    if native:
        return source.relative_to(root).as_posix()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    folder = root / 'cursors' / 'converted' / platform_folder / digest
    size = None
    if target_platform == 'win32':
        _, tracks = read_cursor(source)
        compatible = {nominal: frames for nominal, frames in tracks.items()
                      if all(max(frame.image.size) <= 256 for frame in frames)}
        if not compatible:
            raise ValueError('This Linux cursor has no size compatible with Windows (maximum 256 pixels).')
        sequences = list(compatible.values())
        if len(compatible) != len(tracks) or any(
            [frame.delay for frame in frames] != [frame.delay for frame in sequences[0]]
            for frames in sequences
        ):
            size = max(compatible)
        count = len(tracks[size] if size else sequences[0])
        suffix = '.ani' if count > 1 else '.cur'
    else:
        suffix = '.xcursor'
    destination = folder / ('cursor' + suffix)
    if not destination.resolve().is_relative_to(root):
        raise ValueError('Converted cursor path escapes the pack folder.')
    if not destination.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        convert_cursor(source, destination, size=size)
    return destination.relative_to(root).as_posix()


def prepare_pack_cursors(pack, root, target_platform=None):
    """Update native mappings after import/edit; preserve originals in the manifest."""
    root = Path(root).resolve()
    sources, prepared = {}, {}
    for role, relative in pack.get('cursors', {}).items():
        source_relative = pack.get('cursor_sources', {}).get(role, relative)
        source = (root / source_relative).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f'Cursor asset escapes pack folder: {source_relative}')
        sources[role] = source_relative
        prepared[role] = (native_cursor(source, root, target_platform)
                          if source.is_file() else relative)
    pack['cursor_sources'] = sources
    pack['cursors'] = prepared
