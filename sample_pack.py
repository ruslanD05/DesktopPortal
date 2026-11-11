"""Generate a small demo pack so a fresh install has something to activate.

Every asset is drawn or synthesized here, so the pack needs no downloads and
contains nothing that cannot be redistributed.
"""
import math
import struct
import wave

from PIL import Image, ImageDraw, ImageFilter

from cursor_conversion import Frame, _cur_bytes
from packs import DEFAULT_EFFECTS, PACK_FORMAT_VERSION, PACKS_DIR, write_json

SAMPLE_ID = 'sample_aurora'
SAMPLE_NAME = 'Aurora (sample)'


def _wallpaper(size=(1920, 1080)):
    width, height = size
    column = Image.new('RGB', (1, height))
    top, bottom = (16, 14, 48), (20, 96, 118)
    column.putdata([
        tuple(round(a + (b - a) * y / (height - 1)) for a, b in zip(top, bottom))
        for y in range(height)
    ])
    image = column.resize(size)
    glow = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for index, color in enumerate([(88, 255, 190), (96, 170, 255), (190, 120, 255)]):
        points = [
            (x, height * (0.34 + 0.09 * index)
             + math.sin(x / width * math.tau * (1.1 + 0.35 * index) + index * 1.7)
             * height * 0.09)
            for x in range(0, width + 40, 40)
        ]
        draw.line(points, fill=color + (210,), width=round(height * 0.07))
    glow = glow.filter(ImageFilter.GaussianBlur(height * 0.045))
    image.paste(glow, (0, 0), glow)
    return image


def _cursor(points, fill, hotspot, size=48):
    scale = 4  # Draw large, then shrink for smooth edges.
    image = Image.new('RGBA', (size * scale, size * scale), (0, 0, 0, 0))
    scaled = [(x * scale, y * scale) for x, y in points]
    draw = ImageDraw.Draw(image)
    draw.polygon(scaled, fill=fill)
    draw.line(scaled + scaled[:1], fill=(12, 16, 40, 255), width=2 * scale, joint='curve')
    return _cur_bytes([Frame(image.resize((size, size), Image.LANCZOS), *hotspot)])


def _chime(path, rate=44100):
    notes = [(659.25, 0.0), (880.0, 0.12), (1318.5, 0.24)]
    total = int(rate * 1.1)
    samples = []
    for index in range(total):
        moment = index / rate
        value = sum(
            math.sin(math.tau * pitch * (moment - start))
            * math.exp(-5.0 * (moment - start))
            for pitch, start in notes if moment >= start
        )
        samples.append(int(max(-1.0, min(1.0, value * 0.28)) * 32767))
    with wave.open(str(path), 'wb') as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(struct.pack(f'<{total}h', *samples))


def create_sample_pack(packs_dir=None):
    """Create the demo pack and return its ID, or None when it already exists."""
    root = (packs_dir or PACKS_DIR) / SAMPLE_ID
    if root.exists():
        return None
    for folder in ('wallpapers', 'cursors', 'sounds'):
        (root / folder).mkdir(parents=True)
    _wallpaper().save(root / 'wallpapers/aurora.png')
    arrow = [(3, 2), (3, 38), (13, 29), (20, 44), (27, 41), (20, 27), (33, 27)]
    hand = [(16, 2), (23, 2), (23, 18), (40, 22), (40, 36), (34, 46), (16, 46), (6, 30),
            (11, 26), (16, 31)]
    (root / 'cursors/arrow.cur').write_bytes(_cursor(arrow, (120, 255, 205, 255), (3, 2)))
    (root / 'cursors/hand.cur').write_bytes(_cursor(hand, (150, 190, 255, 255), (19, 2)))
    _chime(root / 'sounds/chime.wav')
    write_json(root / 'pack.json', dict(
        id=SAMPLE_ID,
        format_version=PACK_FORMAT_VERSION,
        name=SAMPLE_NAME,
        wallpapers=['wallpapers/aurora.png'],
        cursors={'Arrow': 'cursors/arrow.cur', 'Hand': 'cursors/hand.cur'},
        sounds=['sounds/chime.wav'],
        disabled_assets={'wallpapers': [], 'sounds': []},
        music=None,
        effects=dict(DEFAULT_EFFECTS),
        enabled=True,
    ))
    return SAMPLE_ID
