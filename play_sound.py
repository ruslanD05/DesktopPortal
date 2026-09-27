from pathlib import Path

_pygame = None
_sound_channel = None


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


def play_music(source, volume=0.5):
    """Start looping a local audio file."""
    stop_music()
    path = Path(source).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Music not found: {path}')
    pygame = pygame_module()
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    pygame.mixer.music.load(str(path))
    pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
    pygame.mixer.music.play(loops=-1, fade_ms=350)


def stop_music(fade_ms=250):
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
