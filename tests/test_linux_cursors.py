import configparser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from cursor_conversion import Frame, _cur_bytes, read_cursor
from linux_backend import cursors
import linux_cursor


class LinuxCursorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'pack'
        self.source.mkdir()
        self.arrow = self.source / 'Arrow.cur'
        self.original_bytes = _cur_bytes([Frame(Image.new('RGBA', (24, 24), 'red'), 2, 3)])
        self.arrow.write_bytes(self.original_bytes)
        self.state = self.root / 'state.json'
        self.themes = self.root / 'icons'
        self.original = {'theme': "'Yaru'", 'size': '24'}

    def test_build_installs_theme_and_aliases_without_touching_source(self):
        name = cursors.build_theme({'Arrow': self.arrow}, 'Yaru', self.themes)
        theme = self.themes / name
        config = configparser.ConfigParser()
        config.read(theme / 'index.theme')
        self.assertEqual(config['Icon Theme']['Inherits'], 'Yaru')
        for alias in cursors.THEME_NAMES['Arrow']:
            frame = read_cursor(theme / 'cursors' / alias)[1][24][0]
            self.assertEqual((frame.xhot, frame.yhot), (2, 3))
        self.assertEqual(self.arrow.read_bytes(), self.original_bytes)
        self.assertEqual(cursors.build_theme({'Arrow': self.arrow}, 'Yaru', self.themes), name)

    @patch('linux_cursor.apply_theme')
    @patch('linux_cursor.snapshot_cursors')
    def test_apply_preserves_first_snapshot_across_switches(self, snapshot, apply):
        snapshot.side_effect = [self.original, {'theme': "'DesktopPortal-test'", 'size': '32'}]
        first, count = linux_cursor.apply_cursors(self.source, 32, self.state, self.themes)
        self.assertEqual(count, 1)
        self.arrow.write_bytes(_cur_bytes([Frame(Image.new('RGBA', (24, 24), 'blue'), 2, 3)]))
        second, _ = linux_cursor.apply_cursors(self.source, 48, self.state, self.themes)
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(self.state.read_text()), self.original)
        self.assertEqual(apply.call_args_list[0].args, (first, 32))
        self.assertEqual(apply.call_args_list[1].args, (second, 48))

    @patch('linux_cursor.restore_cursors')
    @patch('linux_cursor.apply_theme', side_effect=OSError('setting failed'))
    @patch('linux_cursor.snapshot_cursors')
    def test_apply_failure_rolls_back_and_keeps_recovery(self, snapshot, apply, restore):
        snapshot.return_value = self.original
        with self.assertRaisesRegex(OSError, 'Recovery snapshot kept'):
            linux_cursor.apply_cursors(self.source, 32, self.state, self.themes)
        restore.assert_called_once_with(self.original)
        self.assertEqual(json.loads(self.state.read_text()), self.original)

    @patch('linux_cursor.restore_cursors')
    def test_failed_restore_keeps_snapshot_and_success_removes_it(self, restore):
        self.state.write_text(json.dumps(self.original))
        restore.side_effect = OSError('restore failed')
        with self.assertRaises(OSError):
            linux_cursor.restore_original(self.state)
        self.assertTrue(self.state.exists())
        restore.side_effect = None
        self.assertEqual(linux_cursor.restore_original(self.state), 'Yaru')
        self.assertFalse(self.state.exists())

    @patch('linux_backend.cursors._run')
    def test_settings_commands_preserve_gvariant_values(self, run):
        cursors.apply_theme('DesktopPortal-example', 32)
        self.assertEqual(run.call_args_list[0].args,
                         ('gsettings', 'set', cursors.SCHEMA, 'cursor-size', '32'))
        self.assertEqual(run.call_args_list[1].args,
                         ('gsettings', 'set', cursors.SCHEMA, 'cursor-theme', '"DesktopPortal-example"'))
        run.reset_mock()
        cursors.restore_cursors(self.original)
        self.assertEqual(run.call_args_list[0].args[-1], "'Yaru'")
        self.assertEqual(run.call_args_list[1].args[-1], '24')

    def test_manifest_cannot_read_outside_pack(self):
        (self.source / 'pack.json').write_text(json.dumps({'cursors': {'Arrow': '../outside.cur'}}))
        with self.assertRaisesRegex(ValueError, 'invalid cursor asset'):
            linux_cursor.load_cursor_mapping(self.source)

    def test_empty_folder_does_not_create_recovery_snapshot(self):
        self.arrow.unlink()
        with patch('linux_cursor.snapshot_cursors', return_value=self.original):
            with self.assertRaisesRegex(ValueError, 'No recognized'):
                linux_cursor.apply_cursors(self.source, state_file=self.state, themes_dir=self.themes)
        self.assertFalse(self.state.exists())


if __name__ == '__main__':
    unittest.main()
