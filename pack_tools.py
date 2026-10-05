"""Validation, portable bundles, and safe asset cleanup."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from cursor_roles import CURSOR_ROLES
from cursor_assets import prepare_pack_cursors
from cursor_conversion import cursor_format
from packs import (PACKS_DIR, pack_assets, pack_effects, pack_music,
                   pack_wallpapers, write_json)

PACK_FORMAT_VERSION = 1
BUNDLE_FORMAT = 'desktopportal-bundle'


def referenced_assets(pack):
    assets = (set(pack_wallpapers(pack)) | set(pack.get('cursors', {}).values())
              | set(pack.get('cursor_sources', {}).values())
              | set(pack.get('sounds', [])))
    music = pack.get('music')
    if music:
        assets.add(music)
    return assets


def validate_pack(pack_id, pack, tags=None, packs_dir=None):
    root = ((packs_dir or PACKS_DIR) / pack_id).resolve()
    issues = []
    if pack.get('format_version', PACK_FORMAT_VERSION) > PACK_FORMAT_VERSION:
        issues.append('Pack uses a newer format version.')
    try:
        pack_effects(pack)
        pack_assets(pack, 'wallpapers', enabled_only=True)
        pack_assets(pack, 'sounds', enabled_only=True)
    except ValueError as error:
        issues.append(str(error))
    try:
        music = pack_music(pack)
    except ValueError as error:
        issues.append(str(error))
        music = None
    unknown = sorted(set(pack.get('cursors', {})) - set(CURSOR_ROLES))
    if unknown:
        issues.append('Unknown cursor roles: ' + ', '.join(unknown))
    allowed = {
        **{path: {'.png', '.jpg', '.jpeg', '.bmp'} for path in pack_wallpapers(pack)},
        **{path: None for path in (*pack.get('cursors', {}).values(),
                                  *pack.get('cursor_sources', {}).values())},
        **{path: {'.mp3', '.wav', '.ogg'} for path in pack.get('sounds', [])},
    }
    if music:
        allowed[music] = {'.mp3', '.wav', '.ogg'}
    for relative, extensions in allowed.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            issues.append(f'Asset escapes pack folder: {relative}')
        elif not path.is_file():
            issues.append(f'Missing asset: {relative}')
        elif extensions is None:
            try:
                cursor_format(path)
            except ValueError:
                issues.append(f'Unsupported cursor type: {relative}')
        elif path.suffix.lower() not in extensions:
            issues.append(f'Unsupported asset type: {relative}')
    if tags is not None:
        count = sum(value == pack_id for value in tags.values())
        if count == 0:
            issues.append('No NFC tag is bound to this pack.')
    return issues


def unused_assets(pack_id, pack, packs_dir=None):
    root = ((packs_dir or PACKS_DIR) / pack_id).resolve()
    referenced = {(root / item).resolve() for item in referenced_assets(pack)}
    return sorted(
        path for path in root.rglob('*')
        if path.is_file() and path.name != 'pack.json' and path.resolve() not in referenced
    )


def cleanup_assets(pack_id, pack, packs_dir=None):
    root = ((packs_dir or PACKS_DIR) / pack_id).resolve()
    removed = unused_assets(pack_id, pack, packs_dir)
    for path in removed:
        path.unlink()
    for folder in sorted((p for p in root.rglob('*') if p.is_dir()), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    return removed


def export_bundle(pack_ids, destination, collection=None, packs_dir=None):
    packs_dir = packs_dir or PACKS_DIR
    manifest = {
        'format': BUNDLE_FORMAT,
        'format_version': PACK_FORMAT_VERSION,
        'packs': list(pack_ids),
    }
    if collection:
        manifest['collection'] = collection
    destination = Path(destination)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('bundle.json', json.dumps(manifest, indent=2))
        for pack_id in pack_ids:
            root = packs_dir / pack_id
            if not (root / 'pack.json').is_file():
                raise ValueError(f'Pack not found: {pack_id}')
            for path in root.rglob('*'):
                if path.is_file():
                    archive.write(path, Path('packs') / pack_id / path.relative_to(root))
    return destination


def _safe_members(archive):
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or '..' in path.parts or info.is_dir():
            if path.is_absolute() or '..' in path.parts:
                raise ValueError(f'Unsafe bundle path: {info.filename}')
            continue
        yield info


def import_bundle(source, packs_dir=None):
    packs_dir = packs_dir or PACKS_DIR
    with zipfile.ZipFile(source) as archive:
        members = list(_safe_members(archive))
        try:
            manifest = json.loads(archive.read('bundle.json'))
        except (KeyError, json.JSONDecodeError) as error:
            raise ValueError('This is not a valid DesktopPortal bundle.') from error
        if manifest.get('format') != BUNDLE_FORMAT or manifest.get('format_version', 0) > PACK_FORMAT_VERSION:
            raise ValueError('Unsupported DesktopPortal bundle version.')
        with tempfile.TemporaryDirectory() as temporary:
            archive.extractall(temporary, members=members)
            extracted = Path(temporary) / 'packs'
            imported, mapping = [], {}
            for original in manifest.get('packs', []):
                source_root = extracted / original
                if not (source_root / 'pack.json').is_file():
                    raise ValueError(f'Bundle is missing pack: {original}')
                candidate, number = original, 2
                while (packs_dir / candidate).exists():
                    candidate = f'{original}_{number}'
                    number += 1
                pack = json.loads((source_root / 'pack.json').read_text(encoding='utf-8'))
                prepare_pack_cursors(pack, source_root)
                pack['id'] = candidate
                pack['format_version'] = PACK_FORMAT_VERSION
                write_json(source_root / 'pack.json', pack)
                shutil.copytree(source_root, packs_dir / candidate)
                imported.append(candidate)
                mapping[original] = candidate
    collection = manifest.get('collection')
    return imported, collection, mapping
