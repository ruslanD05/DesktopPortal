"""Preview and mirror Windows CUR/ANI cursor files."""
from io import BytesIO
from pathlib import Path
import struct

from PIL import Image, ImageOps


def _chunks(data):
    position = 0
    while position + 8 <= len(data):
        chunk_id = data[position:position + 4]
        size = struct.unpack_from('<I', data, position + 4)[0]
        start = position + 8
        end = start + size
        if end > len(data):
            raise ValueError('Damaged animated cursor.')
        yield chunk_id, data[start:end]
        position = end + (size & 1)


def _icon_chunks(data):
    for chunk_id, payload in _chunks(data):
        if chunk_id == b'icon':
            yield payload
        elif (chunk_id in (b'RIFF', b'LIST') and len(payload) >= 4
              and payload[:4] in (b'ACON', b'fram')):
            yield from _icon_chunks(payload[4:])


def _preview_icon(data):
    if len(data) >= 22 and data[:4] == b'\0\0\x02\0':
        count = struct.unpack_from('<H', data, 4)[0]
        choices = []
        for index in range(count):
            offset = 6 + index * 16
            if offset + 16 > len(data):
                break
            width = data[offset] or 256
            height = data[offset + 1] or 256
            size, image_offset = struct.unpack_from('<II', data, offset + 8)
            if image_offset + size <= len(data):
                choices.append((width * height, data[image_offset:image_offset + size]))
        if choices:
            payload = max(choices, key=lambda item: item[0])[1]
            if payload.startswith(b'\x89PNG\r\n\x1a\n'):
                with Image.open(BytesIO(payload)) as image:
                    return image.convert('RGBA').copy()
    with Image.open(BytesIO(data)) as image:
        return image.convert('RGBA').copy()


def preview_frames(path):
    """Return independent RGBA frames suitable for a GUI preview."""
    data = Path(path).read_bytes()
    if data[:4] == b'RIFF' and data[8:12] == b'ACON':
        frames = [_preview_icon(item) for item in _icon_chunks(data[12:])]
        if not frames:
            raise ValueError('Animated cursor contains no frames.')
        return frames
    return [_preview_icon(data)]


def _mirror_image(image, horizontal):
    mirrored = ImageOps.mirror(image) if horizontal else ImageOps.flip(image)
    output = BytesIO()
    mirrored.convert('RGBA').save(output, format='PNG')
    return output.getvalue()


def _mirror_icon(data, horizontal):
    if len(data) < 6:
        raise ValueError('Damaged cursor file.')
    reserved, kind, count = struct.unpack_from('<HHH', data)
    if reserved or kind not in (1, 2) or not count or len(data) < 6 + count * 16:
        raise ValueError('Unsupported cursor file.')

    entries = []
    for index in range(count):
        offset = 6 + index * 16
        width_byte, height_byte, colors, entry_reserved = struct.unpack_from(
            '<BBBB', data, offset
        )
        first, second, size, image_offset = struct.unpack_from('<HHII', data, offset + 4)
        if image_offset + size > len(data):
            raise ValueError('Damaged cursor image.')
        width = width_byte or 256
        height = height_byte or 256
        source = data[image_offset:image_offset + size]
        single = (struct.pack('<HHH', 0, kind, 1)
                  + struct.pack('<BBBBHHII', width_byte, height_byte, colors,
                                entry_reserved, first, second, len(source), 22)
                  + source)
        image = _mirror_image(_preview_icon(single), horizontal)
        if kind == 2:
            if horizontal:
                first = max(0, min(width - 1, width - 1 - first))
            else:
                second = max(0, min(height - 1, height - 1 - second))
        entries.append((width_byte, height_byte, colors, entry_reserved,
                        first, second, image))

    header_size = 6 + 16 * len(entries)
    output = bytearray(struct.pack('<HHH', 0, kind, len(entries)))
    image_offset = header_size
    for width, height, colors, entry_reserved, first, second, image in entries:
        output.extend(struct.pack(
            '<BBBBHHII', width, height, colors, entry_reserved,
            first, second, len(image), image_offset,
        ))
        image_offset += len(image)
    for entry in entries:
        output.extend(entry[-1])
    return bytes(output)


def _mirror_chunks(data, horizontal):
    output = bytearray()
    for chunk_id, payload in _chunks(data):
        if chunk_id == b'icon':
            payload = _mirror_icon(payload, horizontal)
        elif (chunk_id in (b'RIFF', b'LIST') and len(payload) >= 4
              and payload[:4] in (b'ACON', b'fram')):
            payload = payload[:4] + _mirror_chunks(payload[4:], horizontal)
        output.extend(chunk_id)
        output.extend(struct.pack('<I', len(payload)))
        output.extend(payload)
        if len(payload) & 1:
            output.append(0)
    return bytes(output)


def flip_cursor(path, axis):
    """Mirror a CUR or every frame of an ANI in place, preserving hotspots."""
    if axis not in ('x', 'y'):
        raise ValueError("Cursor flip axis must be 'x' or 'y'.")
    path = Path(path)
    data = path.read_bytes()
    horizontal = axis == 'x'
    if data[:4] == b'RIFF' and data[8:12] == b'ACON':
        result = b'RIFF' + struct.pack('<I', 0) + b'ACON'
        result += _mirror_chunks(data[12:], horizontal)
        result = result[:4] + struct.pack('<I', len(result) - 8) + result[8:]
    else:
        result = _mirror_icon(data, horizontal)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(result)
    temporary.replace(path)
