import ctypes.util
from io import BytesIO
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from PIL import Image

from cursor_conversion import Frame, _chunk, _cur_bytes, convert_cursor, read_cursor


@unittest.skipUnless(ctypes.util.find_library('Xcursor'), 'Requires libXcursor')
class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def frame(self, size, color=(220, 100, 40, 255), delay=0):
        image = Image.new('RGBA', (size, size), color)
        image.putpixel((0, 0), (0, 0, 0, 0))
        return Frame(image, 2, 3, delay)

    def test_static_multisize_round_trip_preserves_images_and_hotspots(self):
        frames = [self.frame(16), self.frame(32)]
        source = self.root / 'original.cur'
        source.write_bytes(_cur_bytes(frames))
        linux = convert_cursor(source, self.root / 'linux.xcursor')
        windows = convert_cursor(linux, self.root / 'restored.cur')
        kind, tracks = read_cursor(windows)
        self.assertEqual(kind, 'cur')
        self.assertEqual(set(tracks), {16, 32})
        for frame in frames:
            result = tracks[frame.image.width][0]
            self.assertEqual((result.xhot, result.yhot), (frame.xhot, frame.yhot))
            self.assertEqual(result.image.tobytes(), frame.image.tobytes())

    def test_ani_sequence_repeats_and_variable_rates_are_preserved(self):
        icons = [_cur_bytes([self.frame(16, color)]) for color in
                 [(255, 0, 0, 255), (0, 255, 0, 255)]]
        header = struct.pack('<9I', 36, 2, 3, 0, 0, 0, 0, 6, 3)
        ani = _chunk(b'RIFF', b'ACON' + _chunk(b'anih', header)
                     + _chunk(b'seq ', struct.pack('<3I', 1, 0, 1))
                     + _chunk(b'rate', struct.pack('<3I', 3, 6, 9))
                     + _chunk(b'LIST', b'fram' + b''.join(_chunk(b'icon', icon) for icon in icons)))
        source = self.root / 'source.ani'
        source.write_bytes(ani)
        linux = convert_cursor(source, self.root / 'cursor.xcursor')
        restored = convert_cursor(linux, self.root / 'restored.ani')
        for path in (source, linux, restored):
            _, tracks = read_cursor(path)
            frames = tracks[16]
            self.assertEqual([frame.delay for frame in frames], [50, 100, 150])
            self.assertEqual([frame.image.getpixel((1, 1)) for frame in frames],
                             [(0, 255, 0, 255), (255, 0, 0, 255), (0, 255, 0, 255)])
            self.assertEqual([(frame.xhot, frame.yhot) for frame in frames], [(2, 3)] * 3)

    def test_png_backed_cur_and_partial_alpha(self):
        image = self.frame(16, (200, 80, 20, 128)).image
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        png = buffer.getvalue()
        source = self.root / 'png.cur'
        source.write_bytes(struct.pack('<HHHBBBBHHII', 0, 2, 1, 16, 16, 0, 0, 2, 3, len(png), 22) + png)
        linux = convert_cursor(source, self.root / 'cursor.xcursor')
        _, tracks = read_cursor(linux)
        result = tracks[16][0].image.getpixel((1, 1))
        for actual, expected in zip(result, (200, 80, 20, 128)):
            self.assertLessEqual(abs(actual - expected), 1)

    @unittest.skipUnless(shutil.which('xcursorgen'), 'Requires independent Xcursor writer')
    def test_independent_xcursorgen_file_converts_to_ani(self):
        self.frame(24).image.save(self.root / 'first.png')
        self.frame(24, (10, 20, 30, 255)).image.save(self.root / 'second.png')
        config = self.root / 'cursor.conf'
        config.write_text('24 4 5 first.png 100\n24 6 7 second.png 150\n', encoding='ascii')
        source = self.root / 'external-cursor'
        subprocess.run(['xcursorgen', str(config), str(source)], cwd=self.root, check=True, capture_output=True)
        output = convert_cursor(source, self.root)
        self.assertEqual(output.suffix, '.ani')
        _, tracks = read_cursor(output)
        self.assertEqual([(f.xhot, f.yhot, f.delay) for f in tracks[24]], [(4, 5, 100), (6, 7, 150)])

    def test_size_selection_and_overwrite_refusal(self):
        source = self.root / 'source.cur'
        source.write_bytes(_cur_bytes([self.frame(16), self.frame(32)]))
        output = convert_cursor(source, self.root, size=16)
        self.assertEqual(set(read_cursor(output)[1]), {16})
        before = output.read_bytes()
        with self.assertRaises(FileExistsError):
            convert_cursor(source, self.root, size=16)
        self.assertEqual(output.read_bytes(), before)
        with self.assertRaises(ValueError):
            convert_cursor(source, self.root / 'missing.xcursor', size=48)
        self.assertFalse((self.root / 'missing.xcursor').exists())

    def test_wrong_extension_does_not_create_output(self):
        source = self.root / 'source.cur'
        source.write_bytes(_cur_bytes([self.frame(16)]))
        with self.assertRaisesRegex(ValueError, 'xcursor'):
            convert_cursor(source, self.root / 'wrong.ani')
        self.assertFalse((self.root / 'wrong.ani').exists())


class MalformedCursorTests(unittest.TestCase):
    def test_truncated_inputs_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'broken'
            for data in (b'', b'\0\0\2\0', b'RIFF\0\0\0\0ACON',
                         struct.pack('<HHHBBBBHHII', 0, 2, 1, 16, 16, 0, 0, 0, 0, 1, 22) + b'x'):
                source.write_bytes(data)
                with self.subTest(data=data), self.assertRaises(ValueError):
                    read_cursor(source)

    def test_invalid_hotspot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hotspot'):
            _cur_bytes([Frame(Image.new('RGBA', (16, 16)), 16, 0)])


if __name__ == '__main__':
    unittest.main()
