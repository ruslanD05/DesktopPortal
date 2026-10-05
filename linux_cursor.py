"""Apply a cursor folder or DesktopPortal pack on GNOME, with explicit restore."""
import argparse
import json
import os
from pathlib import Path
import sys

from cursor_roles import find_cursors
from linux_backend.cursors import (apply_theme, build_theme, restore_cursors,
                                   snapshot_cursors, theme_name)
from packs import BASE_DIR, write_json

STATE_FILE = BASE_DIR / 'data/linux-cursor-state.json'


def load_cursor_mapping(folder):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError(f'Cursor folder not found: {folder}')
    manifest = folder / 'pack.json'
    if not manifest.is_file():
        return find_cursors(folder)
    pack = json.loads(manifest.read_text(encoding='utf-8'))
    mapping = {}
    for role, relative in pack.get('cursors', {}).items():
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError(f'Missing or invalid cursor asset: {relative}')
        mapping[role] = path
    return mapping or find_cursors(folder / 'cursors')


def apply_cursors(folder, size=None, state_file=None, themes_dir=None):
    state_file = Path(state_file) if state_file is not None else STATE_FILE
    if size is not None and not 1 <= size <= 256:
        raise ValueError('Linux cursor size must be between 1 and 256 pixels.')
    mapping = load_cursor_mapping(folder)
    previous = snapshot_cursors()
    original = (json.loads(state_file.read_text(encoding='utf-8'))
                if state_file.exists() else previous)
    fallback = theme_name(original)
    name = build_theme(mapping, fallback, themes_dir)
    if not state_file.exists():
        write_json(state_file, original)
    try:
        apply_theme(name, size)
    except Exception as error:
        try:
            restore_cursors(previous)
        except Exception as restore_error:
            raise OSError(f'Cursor activation failed: {error}; rollback failed: {restore_error}. '
                          f'Recovery snapshot kept at {state_file}') from error
        raise OSError(f'Cursor activation failed: {error}. Recovery snapshot kept at {state_file}') from error
    return name, len(mapping)


def restore_original(state_file=None):
    state_file = Path(state_file) if state_file is not None else STATE_FILE
    if not state_file.is_file():
        raise ValueError('There is no saved cursor theme to restore.')
    original = json.loads(state_file.read_text(encoding='utf-8'))
    restore_cursors(original)
    state_file.unlink()
    return theme_name(original)


def main():
    parser = argparse.ArgumentParser(description='Apply and restore GNOME cursor themes.')
    actions = parser.add_subparsers(dest='action', required=True)
    apply = actions.add_parser('apply', help='Convert, install and apply a cursor folder or pack')
    apply.add_argument('folder', type=Path)
    apply.add_argument('--size', type=int, help='Cursor size in pixels; otherwise keep the current size')
    actions.add_parser('restore', help='Restore the original cursor theme and size')
    actions.add_parser('status', help='Show the current theme and recovery snapshot')
    args = parser.parse_args()
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').casefold()
    if sys.platform != 'linux' or not any(name in desktop for name in ('gnome', 'unity')):
        parser.exit(1, 'This script currently supports Ubuntu/GNOME sessions.\n')
    try:
        if args.action == 'apply':
            name, count = apply_cursors(args.folder, args.size)
            print(f'Applied {count} cursor roles: {name}')
            print('Restore with: python3 linux_cursor.py restore')
        elif args.action == 'restore':
            print(f'Restored cursor theme: {restore_original()}')
        else:
            snapshot = snapshot_cursors()
            print(f'Theme: {theme_name(snapshot)}; size: {snapshot["size"]} pixels')
            print(f'Recovery snapshot: {STATE_FILE if STATE_FILE.exists() else "none"}')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
