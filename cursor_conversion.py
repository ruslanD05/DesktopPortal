"""Convert CUR/ANI and Xcursor files without changing desktop settings."""
import ctypes
from ctypes.util import find_library
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import struct
import tempfile

from PIL import Image


@dataclass
class Frame:
    image: Image.Image
    xhot: int
    yhot: int
    delay: int = 0  # Milliseconds; ANI rates are rounded to/from 1/60 second.


def _validate(frame):
    width, height = frame.image.size
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError('Cursor dimensions must be between 1 and 4096 pixels.')
    if not (0 <= frame.xhot < width and 0 <= frame.yhot < height):
        raise ValueError('Cursor hotspot is outside its image.')
    if not 0 <= frame.delay <= 0xffffffff:
        raise ValueError('Invalid cursor frame delay.')


def _read_cur(data):
    if len(data) < 6:
        raise ValueError('Truncated Windows cursor.')
    reserved, kind, count = struct.unpack_from('<HHH', data)
    if reserved or kind != 2 or not count or len(data) < 6 + 16 * count:
        raise ValueError('Expected a CUR file with cursor hotspots.')
    frames = {}
    depths = {}
    for index in range(count):
        w, h, colors, reserved, xhot, yhot, size, offset = struct.unpack_from(
            '<BBBBHHII', data, 6 + index * 16
        )
        if offset < 6 + 16 * count or not size or offset + size > len(data):
            raise ValueError('Truncated Windows cursor image.')
        payload = data[offset:offset + size]
        png = payload.startswith(b'\x89PNG\r\n\x1a\n')
        depth = 32 if png else struct.unpack_from('<H', payload, 14)[0]
        # Pillow's ICO decoder handles PNG, DIB and legacy transparency masks.
        ico = (struct.pack('<HHH', 0, 1, 1)
               + struct.pack('<BBBBHHII', w, h, colors, 0, 1, depth, size, 22)
               + payload)
        with Image.open(BytesIO(ico)) as image:
            rgba = image.convert('RGBA')
        if rgba.size != (w or 256, h or 256):
            raise ValueError('Cursor directory and image dimensions differ.')
        # Some old 32-bit DIBs use only the AND mask and leave alpha all zero.
        if not png and depth == 32 and not rgba.getchannel('A').getbbox():
            stride = ((rgba.width + 31) // 32) * 4
            mask_size = stride * rgba.height
            if len(payload) < 40 + rgba.width * rgba.height * 4 + mask_size:
                raise ValueError('Truncated cursor transparency mask.')
            mask = Image.frombytes('1', rgba.size, payload[-mask_size:], 'raw', '1;I', stride, -1)
            rgba.putalpha(mask.convert('L'))
        frame = Frame(rgba, xhot, yhot)
        _validate(frame)
        nominal = max(rgba.size)
        if nominal not in frames or depth > depths[nominal]:
            frames[nominal] = [frame]
            depths[nominal] = depth
    return frames


def _chunks(data):
    position = 0
    while position < len(data):
        if position + 8 > len(data):
            raise ValueError('Truncated ANI chunk header.')
        name, size = struct.unpack_from('<4sI', data, position)
        start = position + 8
        end = start + size
        if end + (size & 1) > len(data):
            raise ValueError('Truncated ANI chunk.')
        yield name, data[start:end]
        position = end + (size & 1)


def _read_ani(data):
    if len(data) < 12 or data[8:12] != b'ACON':
        raise ValueError('Expected an ANI cursor.')
    size = struct.unpack_from('<I', data, 4)[0]
    if size + 8 != len(data):
        raise ValueError('Invalid ANI RIFF length.')
    header, rate, sequence, icons = None, None, None, []
    for name, payload in _chunks(data[12:]):
        if name == b'anih':
            if len(payload) != 36:
                raise ValueError('Invalid ANI header.')
            header = struct.unpack('<9I', payload)
        elif name in (b'rate', b'seq '):
            if len(payload) % 4:
                raise ValueError('Invalid ANI rate or sequence chunk.')
            values = struct.unpack(f'<{len(payload) // 4}I', payload)
            if name == b'rate':
                rate = values
            else:
                sequence = values
        elif name == b'LIST' and payload[:4] == b'fram':
            icons.extend(_read_cur(icon) for tag, icon in _chunks(payload[4:]) if tag == b'icon')
    if header is None or header[0] != 36 or not header[8] & 1:
        raise ValueError('Only ANI files containing CUR frames are supported.')
    _, count, steps, _, _, _, _, default_rate, flags = header
    if not count or not steps or count != len(icons):
        raise ValueError('ANI frame count does not match its header.')
    if flags & 2:
        if sequence is None or len(sequence) != steps:
            raise ValueError('ANI sequence is missing or has the wrong length.')
    else:
        if steps != count:
            raise ValueError('ANI needs a sequence for repeated frames.')
        sequence = tuple(range(count))
    rate = rate if rate is not None else (default_rate,) * steps
    if len(rate) != steps or any(index >= count for index in sequence):
        raise ValueError('Invalid ANI sequence or rate length.')
    sizes = set(icons[0])
    if any(set(icon) != sizes for icon in icons):
        raise ValueError('ANI frames must contain the same cursor sizes.')
    return {
        nominal: [Frame(icons[index][nominal][0].image,
                        icons[index][nominal][0].xhot,
                        icons[index][nominal][0].yhot,
                        max(1, round(ticks * 1000 / 60)))
                  for index, ticks in zip(sequence, rate)]
        for nominal in sorted(sizes)
    }


class _XImage(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in
                ('version', 'size', 'width', 'height', 'xhot', 'yhot', 'delay')]
    _fields_.append(('pixels', ctypes.POINTER(ctypes.c_uint32)))


class _XImages(ctypes.Structure):
    _fields_ = [('nimage', ctypes.c_int),
                ('images', ctypes.POINTER(ctypes.POINTER(_XImage))),
                ('name', ctypes.c_char_p)]


def _xcursor():
    library = find_library('Xcursor')
    if not library:
        raise OSError('Xcursor library unavailable. On Ubuntu, install libxcursor1.')
    lib = ctypes.CDLL(library)
    signatures = {
        'XcursorFilenameLoadAllImages': ([ctypes.c_char_p], ctypes.POINTER(_XImages)),
        'XcursorFilenameSaveImages': ([ctypes.c_char_p, ctypes.POINTER(_XImages)], ctypes.c_int),
        'XcursorImagesCreate': ([ctypes.c_int], ctypes.POINTER(_XImages)),
        'XcursorImagesDestroy': ([ctypes.POINTER(_XImages)], None),
        'XcursorImageCreate': ([ctypes.c_int, ctypes.c_int], ctypes.POINTER(_XImage)),
    }
    for name, (args, result) in signatures.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
    return lib


def _read_xcursor(path):
    if not find_library('Xcursor'):
        return _read_xcursor_portable(Path(path).read_bytes())
    lib = _xcursor()
    images = lib.XcursorFilenameLoadAllImages(os.fsencode(path))
    if not images:
        raise ValueError('Invalid or empty Xcursor file.')
    tracks = {}
    try:
        for index in range(images.contents.nimage):
            item = images.contents.images[index].contents
            if not item.size or not (0 < item.width <= 4096 and 0 < item.height <= 4096):
                raise ValueError('Invalid Xcursor image dimensions.')
            rgba = bytearray()
            for pixel in item.pixels[:item.width * item.height]:
                alpha = pixel >> 24
                # Xcursor stores premultiplied ARGB; Pillow uses straight RGBA.
                rgba.extend(min(255, round(channel * 255 / alpha)) if alpha else 0
                            for channel in ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255))
                rgba.append(alpha)
            frame = Frame(Image.frombytes('RGBA', (item.width, item.height), bytes(rgba)),
                          item.xhot, item.yhot, item.delay)
            _validate(frame)
            tracks.setdefault(item.size, []).append(frame)
    finally:
        lib.XcursorImagesDestroy(images)
    if not tracks:
        raise ValueError('Xcursor contains no images.')
    return tracks


def _read_xcursor_portable(data):
    """Read Xcursor images on Windows, where libXcursor is unavailable."""
    if len(data) < 16:
        raise ValueError('Truncated Xcursor header.')
    magic, header, version, count = struct.unpack_from('<4sIII', data)
    if magic != b'Xcur' or header < 16 or header + count * 12 > len(data):
        raise ValueError('Invalid Xcursor header.')
    tracks = {}
    for index in range(count):
        kind, nominal, offset = struct.unpack_from('<III', data, header + index * 12)
        if kind != 0xfffd0002:
            continue
        if offset < header + count * 12 or offset + 36 > len(data):
            raise ValueError('Invalid Xcursor image offset.')
        length, chunk_kind, chunk_size, chunk_version, width, height, xhot, yhot, delay = struct.unpack_from('<9I', data, offset)
        if (length < 36 or chunk_kind != kind or chunk_size != nominal or not nominal
                or not (0 < width <= 4096 and 0 < height <= 4096)
                or offset + length + width * height * 4 > len(data)):
            raise ValueError('Invalid Xcursor image chunk.')
        pixels = data[offset + length:offset + length + width * height * 4]
        rgba = bytearray()
        for (pixel,) in struct.iter_unpack('<I', pixels):
            alpha = pixel >> 24
            rgba.extend(min(255, round(channel * 255 / alpha)) if alpha else 0
                        for channel in ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255))
            rgba.append(alpha)
        frame = Frame(Image.frombytes('RGBA', (width, height), bytes(rgba)), xhot, yhot, delay)
        _validate(frame)
        tracks.setdefault(nominal, []).append(frame)
    if not tracks:
        raise ValueError('Xcursor contains no images.')
    return tracks


def cursor_format(path):
    """Detect cursor format from its header, including extensionless Xcursor files."""
    with Path(path).open('rb') as source:
        header = source.read(12)
    if header[:4] == b'Xcur':
        return 'xcursor'
    if header[:4] == b'RIFF' and header[8:12] == b'ACON':
        return 'ani'
    if header[:4] == b'\0\0\2\0':
        return 'cur'
    raise ValueError(f'Not a CUR, ANI or Xcursor file: {Path(path).name}')


def read_cursor(path):
    """Return (format, {nominal_size: playback_frames}), detecting file contents."""
    path = Path(path)
    data = path.read_bytes()
    try:
        if data[:4] == b'Xcur':
            return 'xcursor', _read_xcursor(path)
        if data[:4] == b'RIFF':
            return 'ani', _read_ani(data)
        return 'cur', _read_cur(data)
    except (struct.error, IndexError) as error:
        raise ValueError('Truncated cursor file.') from error


def _cur_bytes(frames):
    payloads, entries = [], []
    offset = 6 + 16 * len(frames)
    for frame in frames:
        _validate(frame)
        width, height = frame.image.size
        if max(width, height) > 256:
            raise ValueError('Windows CUR/ANI supports images up to 256 pixels. Choose a smaller size.')
        image = frame.image.convert('RGBA')
        stride = ((width + 31) // 32) * 4
        mask = bytearray(stride * height)
        alpha = image.getchannel('A')
        for y in range(height):
            for x in range(width):
                if alpha.getpixel((x, y)) == 0:
                    mask[(height - 1 - y) * stride + x // 8] |= 0x80 >> (x % 8)
        pixels = image.tobytes('raw', 'BGRA', 0, -1)
        payload = (struct.pack('<IiiHHIIiiII', 40, width, height * 2, 1, 32,
                               0, len(pixels) + len(mask), 0, 0, 0, 0)
                   + pixels + mask)
        entries.append(struct.pack('<BBBBHHII', width % 256, height % 256, 0, 0,
                                   frame.xhot, frame.yhot, len(payload), offset))
        payloads.append(payload)
        offset += len(payload)
    return struct.pack('<HHH', 0, 2, len(frames)) + b''.join(entries + payloads)


def _chunk(name, payload):
    return name + struct.pack('<I', len(payload)) + payload + b'\0' * (len(payload) % 2)


def _windows_bytes(tracks):
    sequences = list(tracks.values())
    count = len(sequences[0])
    if any(len(frames) != count or [f.delay for f in frames] != [f.delay for f in sequences[0]]
           for frames in sequences):
        raise ValueError('Sizes have different animation timing. Select one size to convert.')
    icons = [_cur_bytes([frames[index] for frames in sequences]) for index in range(count)]
    if count == 1:
        return '.cur', icons[0]
    rates = [max(1, round(frame.delay * 60 / 1000)) for frame in sequences[0]]
    header = struct.pack('<9I', 36, count, count, 0, 0, 0, 0, rates[0], 1)
    payload = (b'ACON' + _chunk(b'anih', header)
               + _chunk(b'rate', struct.pack(f'<{count}I', *rates))
               + _chunk(b'LIST', b'fram' + b''.join(_chunk(b'icon', icon) for icon in icons)))
    return '.ani', _chunk(b'RIFF', payload)


def _write_xcursor(path, tracks):
    if not find_library('Xcursor'):
        _write_xcursor_portable(path, tracks)
        return
    lib = _xcursor()
    images = lib.XcursorImagesCreate(sum(map(len, tracks.values())))
    if not images:
        raise MemoryError('Cannot allocate Xcursor images.')
    try:
        for nominal, frames in sorted(tracks.items()):
            for frame in frames:
                _validate(frame)
                image = frame.image.convert('RGBA')
                item = lib.XcursorImageCreate(*image.size)
                if not item:
                    raise MemoryError('Cannot allocate Xcursor frame.')
                images.contents.images[images.contents.nimage] = item
                images.contents.nimage += 1
                item.contents.size = nominal
                item.contents.xhot, item.contents.yhot = frame.xhot, frame.yhot
                item.contents.delay = frame.delay
                for index, (r, g, b, a) in enumerate(image.getdata()):
                    item.contents.pixels[index] = ((a << 24) | (round(r * a / 255) << 16)
                                                  | (round(g * a / 255) << 8) | round(b * a / 255))
        if not lib.XcursorFilenameSaveImages(os.fsencode(path), images):
            raise OSError('Failed to write Xcursor file.')
    finally:
        lib.XcursorImagesDestroy(images)


def _write_xcursor_portable(path, tracks):
    entries, chunks = [], []
    offset = 16 + sum(map(len, tracks.values())) * 12
    for nominal, frames in sorted(tracks.items()):
        for frame in frames:
            _validate(frame)
            image = frame.image.convert('RGBA')
            pixels = bytearray()
            for r, g, b, a in image.getdata():
                pixels.extend(struct.pack('<I', (a << 24) | (round(r * a / 255) << 16)
                                          | (round(g * a / 255) << 8) | round(b * a / 255)))
            chunk = struct.pack('<9I', 36, 0xfffd0002, nominal, 1,
                                image.width, image.height, frame.xhot, frame.yhot, frame.delay) + pixels
            entries.append(struct.pack('<III', 0xfffd0002, nominal, offset))
            chunks.append(chunk)
            offset += len(chunk)
    Path(path).write_bytes(struct.pack('<4sIII', b'Xcur', 16, 0x10000, len(entries))
                           + b''.join(entries + chunks))


def flip_xcursor(path, axis):
    from PIL import ImageOps
    _, tracks = read_cursor(path)
    for frames in tracks.values():
        for frame in frames:
            if axis == 'x':
                frame.image = ImageOps.mirror(frame.image)
                frame.xhot = frame.image.width - 1 - frame.xhot
            else:
                frame.image = ImageOps.flip(frame.image)
                frame.yhot = frame.image.height - 1 - frame.yhot
    path = Path(path)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        staged = Path(directory) / 'flipped.xcursor'
        _write_xcursor(staged, tracks)
        staged.replace(path)


def convert_cursor(source, destination, size=None):
    """Convert to the other platform. Refuse overwrites and return the output path."""
    kind, tracks = read_cursor(source)
    if size is not None:
        if size not in tracks:
            raise ValueError(f'Size {size} is unavailable; choose from {sorted(tracks)}.')
        tracks = {size: tracks[size]}
    if kind == 'xcursor':
        suffix, data = _windows_bytes(tracks)
    else:
        suffix, data = '.xcursor', None
    destination = Path(destination)
    if destination.is_dir():
        destination = destination / (Path(source).stem + suffix)
    elif destination.suffix.lower() != suffix:
        raise ValueError(f'This cursor requires a {suffix} output file.')
    # Complete encoding before creating the destination; failed conversions leave no file.
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary) / ('cursor' + suffix)
        if data is None:
            _write_xcursor(staged, tracks)
            data = staged.read_bytes()
        with destination.open('xb') as output:
            try:
                output.write(data)
            except BaseException:
                destination.unlink()
                raise
    return destination
