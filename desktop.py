"""Apply packs while keeping a recoverable snapshot of the original desktop."""
import json
import random
import time
from packs import (BASE_DIR, PACKS_DIR, asset, write_json, pack_effects,
                   pack_wallpapers)
from cursor_roles import find_cursors
from platform_backend import get_backend
from play_sound import play_music, play_sound, stop_music, stop_sound

STATE_FILE = BASE_DIR / 'data/desktop-state.json'
_BACKEND = get_backend()


# Module wrappers retain a small, mockable surface for tests.
get_wallpaper = _BACKEND.get_wallpaper
set_wallpaper = _BACKEND.set_wallpaper
snapshot_cursors = _BACKEND.snapshot_cursors
set_cursors = _BACKEND.set_cursors
restore_cursors = _BACKEND.restore_cursors


class Desktop:
    def __init__(self, backend=None):
        self.backend = backend or _BACKEND
        self.original = json.loads(STATE_FILE.read_text(encoding='utf-8')) if STATE_FILE.exists() else None
        self.active = None
        self.active_music = None
        self.last_sound_at = 0.0
        self.settings = {}
        self.on_music_error = None

    def restore_effects(self):
        # Try both so one failure does not prevent restoring the other effect.
        errors = []
        for action, value in ((restore_cursors, self.original['cursors']),
                              (set_wallpaper, self.original['wallpaper'])):
            try:
                action(value)
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise OSError('; '.join(errors))

    def restore(self):
        stop_sound()
        stop_music()
        if self.original is not None:
            self.restore_effects()
            STATE_FILE.unlink(missing_ok=True)
            self.original = None
        self.active = None
        self.active_music = None

    def activate(self, pack_id, pack, settings=None, play_activation_sound=True):
        settings = settings or self.settings
        effects = pack_effects(pack)
        wallpapers = (
            [asset(pack_id, path) for path in pack_wallpapers(pack)]
            if effects['wallpaper'] else []
        )
        cursor_supported = self.backend.supports_cursors
        explicit_cursors = {
            role: asset(pack_id, path)
            for role, path in pack.get('cursors', {}).items()
        } if effects['cursors'] and cursor_supported else {}
        folder = PACKS_DIR / pack_id / 'cursors'
        cursors = (
            find_cursors(folder)
            if effects['cursors'] and cursor_supported and folder.is_dir() else {}
        )
        cursors.update(explicit_cursors)
        sounds = (
            [asset(pack_id, path) for path in pack.get('sounds', [])]
            if effects['sounds'] else []
        )
        music = pack.get('music') if effects['music'] else None
        if music and not str(music).lower().startswith(('http://', 'https://')):
            music = asset(pack_id, music)
        if self.original is None:
            self.original = dict(wallpaper=get_wallpaper(), cursors=snapshot_cursors())
            try:
                write_json(STATE_FILE, self.original)
            except Exception:
                self.original = None
                raise
        try:
            stop_sound()
            if wallpapers:
                set_wallpaper(random.choice(wallpapers))
            else:
                set_wallpaper(self.original['wallpaper'])
            if cursors:
                set_cursors(cursors)
            else:
                restore_cursors(self.original['cursors'])
            cooldown = float(settings.get('sound_cooldown', 0))
            changed = self.active != pack_id
            sound_allowed = not settings.get('sound_on_change_only', False) or changed
            now = time.monotonic()
            if sounds and play_activation_sound and sound_allowed and now - self.last_sound_at >= cooldown:
                play_sound(random.choice(sounds), settings.get('sound_volume', 0.8))
                self.last_sound_at = now
            if changed or music != self.active_music:
                if music:
                    play_music(
                        music, settings.get('music_volume', 0.5),
                        self.on_music_error,
                    )
                else:
                    stop_music()
                self.active_music = music
            self.active = pack_id
        except Exception:
            self.restore()
            raise
