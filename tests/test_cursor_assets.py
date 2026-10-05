import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from cursor_assets import native_cursor, prepare_pack_cursors
from cursor_conversion import Frame, _cur_bytes, convert_cursor, read_cursor
from cursor_roles import detect_cursor_role, find_cursors
import cursor_images
import main
import pack_tools
import packs


class CursorAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack_root = self.root / 'packs' / 'demo'
        self.pack_root.mkdir(parents=True)
        self.source = self.pack_root / 'Arrow.cur'
        self.original = _cur_bytes([Frame(Image.new('RGBA', (24, 24), 'red'), 3, 4)])
        self.source.write_bytes(self.original)

    def test_auto_conversion_retains_source_and_reuses_output(self):
        pack = {'cursors': {'Arrow': 'Arrow.cur'}}
        prepare_pack_cursors(pack, self.pack_root, 'linux')
        self.assertEqual(pack['cursor_sources'], {'Arrow': 'Arrow.cur'})
        output = self.pack_root / pack['cursors']['Arrow']
        self.assertEqual(read_cursor(output)[0], 'xcursor')
        modified = output.stat().st_mtime_ns
        prepare_pack_cursors(pack, self.pack_root, 'linux')
        self.assertEqual(output.stat().st_mtime_ns, modified)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(pack_tools.unused_assets('demo', pack, self.root / 'packs'), [])
        prepare_pack_cursors(pack, self.pack_root, 'win32')
        self.assertEqual(pack['cursors'], {'Arrow': 'Arrow.cur'})

    def test_source_changes_regenerate_the_native_file(self):
        first = native_cursor(self.source, self.pack_root, 'linux')
        self.source.write_bytes(_cur_bytes([Frame(Image.new('RGBA', (24, 24), 'blue'), 3, 4)]))
        second = native_cursor(self.source, self.pack_root, 'linux')
        self.assertNotEqual(first, second)
        self.assertEqual(read_cursor(self.pack_root / second)[1][24][0].image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_windows_import_without_native_linux_library(self):
        linux = convert_cursor(self.source, self.pack_root / 'left_ptr.xcursor')
        with patch('cursor_conversion.find_library', return_value=None):
            converted = native_cursor(linux, self.pack_root, 'win32')
        frame = read_cursor(self.pack_root / converted)[1][24][0]
        self.assertEqual((frame.xhot, frame.yhot), (3, 4))
        self.assertEqual(frame.image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_portable_xcursor_writer_matches_native_reader(self):
        with patch('cursor_conversion.find_library', return_value=None):
            linux = convert_cursor(self.source, self.pack_root / 'portable.xcursor')
            portable = read_cursor(linux)[1][24][0]
        native = read_cursor(linux)[1][24][0]
        self.assertEqual(native.image.tobytes(), portable.image.tobytes())
        self.assertEqual((native.xhot, native.yhot), (3, 4))

    def test_bundle_import_prepares_native_mapping_before_copying(self):
        pack = {'id': 'demo', 'name': 'Demo', 'cursors': {'Arrow': 'Arrow.cur'}}
        packs.write_json(self.pack_root / 'pack.json', pack)
        bundle = self.root / 'bundle.zip'
        pack_tools.export_bundle(['demo'], bundle, packs_dir=self.root / 'packs')
        destination = self.root / 'imported'
        with patch('cursor_assets.sys.platform', 'linux'):
            imported, _, _ = pack_tools.import_bundle(bundle, packs_dir=destination)
        saved = json.loads((destination / imported[0] / 'pack.json').read_text())
        self.assertEqual(saved['cursor_sources']['Arrow'], 'Arrow.cur')
        self.assertEqual(read_cursor(destination / imported[0] / saved['cursors']['Arrow'])[0], 'xcursor')
        self.assertEqual((destination / imported[0] / 'Arrow.cur').read_bytes(), self.original)
        self.assertEqual(pack_tools.validate_pack(imported[0], saved, packs_dir=destination), [])

    def test_pack_edit_assigns_and_converts_in_one_step(self):
        editor = main.PackEditor.__new__(main.PackEditor)
        editor.pack_id = 'demo'
        editor.pack = {'cursors': {}}
        with patch.object(main, 'PACKS_DIR', self.root / 'packs'), patch('cursor_assets.sys.platform', 'linux'):
            editor.assign_cursor('Arrow', self.source)
        self.assertEqual(editor.pack['cursor_sources']['Arrow'], 'Arrow.cur')
        self.assertEqual(read_cursor(self.pack_root / editor.pack['cursors']['Arrow'])[0], 'xcursor')

    def test_extensionless_linux_roles_and_preview(self):
        linux = convert_cursor(self.source, self.pack_root / 'left_ptr.xcursor')
        extensionless = self.pack_root / 'left_ptr'
        linux.rename(extensionless)
        self.source.unlink()
        self.assertEqual(detect_cursor_role(extensionless), 'Arrow')
        self.assertEqual(find_cursors(self.pack_root)['Arrow'], extensionless)
        self.assertEqual(len(cursor_images.preview_frames(extensionless)), 1)
        cursor_images.flip_cursor(extensionless, 'x')
        frame = read_cursor(extensionless)[1][24][0]
        self.assertEqual((frame.xhot, frame.yhot), (20, 4))

    def test_invalid_cursor_does_not_change_mapping(self):
        editor = main.PackEditor.__new__(main.PackEditor)
        editor.pack_id = 'demo'
        editor.pack = {'cursors': {'Arrow': 'Arrow.cur'}}
        bad = self.pack_root / 'bad.ani'
        bad.write_bytes(b'not a cursor')
        with patch.object(main, 'PACKS_DIR', self.root / 'packs'), self.assertRaises(ValueError):
            editor.assign_cursor('Arrow', bad)
        self.assertEqual(editor.pack['cursors'], {'Arrow': 'Arrow.cur'})

    def test_folder_detection_finds_nested_roles_and_prefers_top_level(self):
        nested = self.pack_root / 'Hollow Knight'
        nested.mkdir()
        (nested / 'Arrow.ani').write_bytes(self.original)
        (nested / 'IBeam.ani').write_bytes(self.original)
        (nested / 'Person.cur').write_bytes(self.original)
        (nested / 'Pin.cur').write_bytes(self.original)
        (self.pack_root / 'invalid.cur').mkdir()
        detected = find_cursors(self.pack_root)
        self.assertEqual(detected, {'Arrow': self.source, 'IBeam': nested / 'IBeam.ani'})


if __name__ == '__main__':
    unittest.main()
