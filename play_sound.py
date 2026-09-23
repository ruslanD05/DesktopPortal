from pathlib import Path
import hashlib
import random
import threading
from urllib.parse import urlparse

from packs import BASE_DIR

_pygame = None
_sound_channel = None
_music_generation = 0
_music_lock = threading.Lock()
MUSIC_CACHE = BASE_DIR / 'data/music-cache'


def pygame_module():
    global _pygame
    if _pygame is None:
        import pygame
        _pygame = pygame
    return _pygame


def play_sound(sound_path, volume=0.8):
    global _sound_channel
    pygame = pygame_module()
    path = Path(sound_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Sound not found: {path}')
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    if _sound_channel is None:
        _sound_channel = pygame.mixer.Channel(1)
    sound = pygame.mixer.Sound(str(path))
    _sound_channel.set_volume(max(0.0, min(1.0, float(volume))))
    _sound_channel.play(sound)


def stop_sound():
    global _sound_channel
    if _pygame is None:
        return
    pygame = _pygame
    if pygame.mixer.get_init() and _sound_channel is not None:
        _sound_channel.stop()


def is_web_music(source):
    try:
        return urlparse(str(source)).scheme.lower() in ('http', 'https')
    except ValueError:
        return False


def _download_youtube(source):
    """Resolve one video (random for a playlist) and cache it as MP3."""
    try:
        import yt_dlp
    except ImportError as error:
        raise RuntimeError('YouTube music requires yt-dlp. Reinstall app dependencies.') from error

    quiet = {'quiet': True, 'no_warnings': True, 'noprogress': True}
    with yt_dlp.YoutubeDL({**quiet, 'extract_flat': 'in_playlist'}) as ydl:
        info = ydl.extract_info(source, download=False)
    entries = [entry for entry in (info.get('entries') or []) if entry]
    selected = random.choice(entries) if entries else info
    video_url = selected.get('webpage_url') or selected.get('url') or source
    key = hashlib.sha256(str(video_url).encode('utf-8')).hexdigest()[:24]
    target = MUSIC_CACHE / f'{key}.mp3'
    if target.is_file():
        return target
    MUSIC_CACHE.mkdir(parents=True, exist_ok=True)
    options = {
        **quiet,
        'format': 'bestaudio/best',
        'noplaylist': True,
        'outtmpl': str(MUSIC_CACHE / f'{key}.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([video_url])
    if not target.is_file():
        raise RuntimeError('YouTube audio conversion did not create an MP3 file.')
    return target


def _start_music(path, volume, generation):
    with _music_lock:
        if generation != _music_generation:
            return
        pygame = pygame_module()
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
        pygame.mixer.music.play(loops=-1, fade_ms=350)


def play_music(source, volume=0.5, on_error=None):
    """Start looping local music, or download/cache YouTube music asynchronously."""
    global _music_generation
    with _music_lock:
        _music_generation += 1
        generation = _music_generation
    stop_music(invalidate=False)
    if is_web_music(source):
        def resolve():
            try:
                path = _download_youtube(str(source))
                _start_music(path, volume, generation)
            except Exception as error:
                if generation == _music_generation and on_error:
                    on_error(str(error))
        threading.Thread(target=resolve, daemon=True, name='YouTubeMusic').start()
        return
    path = Path(source).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Music not found: {path}')
    _start_music(path, volume, generation)


def stop_music(fade_ms=250, invalidate=True):
    global _music_generation
    with _music_lock:
        if invalidate:
            _music_generation += 1
        if _pygame is None:
            return
        pygame = _pygame
        if pygame.mixer.get_init():
            if fade_ms:
                pygame.mixer.music.fadeout(fade_ms)
            else:
                pygame.mixer.music.stop()


def set_music_volume(volume):
    if _pygame is not None and _pygame.mixer.get_init():
        _pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
