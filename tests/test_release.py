import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import background
import main
import pack_tools
import packs
import sample_pack
from linux_backend import wallpaper as linux_wallpaper


class SamplePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.packs_dir = Path(self.temp.name)

    def test_sample_pack_is_valid_and_self_contained(self):
        pack_id = sample_pack.create_sample_pack(self.packs_dir)
        pack = json.loads((self.packs_dir / pack_id / 'pack.json').read_text())
        self.assertEqual(pack_tools.validate_pack(pack_id, pack, packs_dir=self.packs_dir), [])
        self.assertEqual(pack_tools.unused_assets(pack_id, pack, self.packs_dir), [])

    def test_sample_pack_is_not_recreated(self):
        sample_pack.create_sample_pack(self.packs_dir)
        self.assertIsNone(sample_pack.create_sample_pack(self.packs_dir))


class CursorSizeTests(unittest.TestCase):
    def setUp(self):
        self.portal = main.Portal.__new__(main.Portal)
        self.portal.settings = dict(packs.DEFAULT_SETTINGS)
        self.portal.desktop = Mock()
        self.backend = self.portal.desktop.backend
        self.backend.supports_cursor_size = True
        self.backend.get_cursor_size.return_value = 2
        patcher = patch.object(main, 'save_settings')
        self.save = patcher.start()
        self.addCleanup(patcher.stop)

    def test_original_size_is_remembered_once_and_restored(self):
        self.portal.apply_cursor_size(5)
        self.backend.get_cursor_size.return_value = 5
        self.portal.apply_cursor_size(7)
        self.assertEqual(self.portal.settings['original_cursor_size'], 2)
        self.portal.restore_cursor_size()
        self.backend.set_cursor_size.assert_called_with(2)
        self.assertIsNone(self.portal.settings['original_cursor_size'])

    def test_restore_without_custom_size_changes_nothing(self):
        self.portal.restore_cursor_size()
        self.backend.set_cursor_size.assert_not_called()


class KdeWallpaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'appletsrc'

    def test_reads_desktop_image_from_plasma_config(self):
        self.config.write_text(
            '[Containments][1][General]\nImage=file:///wrong.png\n\n'
            '[Containments][1][Wallpaper][org.kde.image][General]\n'
            'Image=file:///home/user/Pictures/a b.png\n',
            encoding='utf-8',
        )
        self.assertEqual(
            linux_wallpaper._kde_wallpaper(self.config), '/home/user/Pictures/a b.png'
        )

    def test_missing_config_is_unknown_not_an_error(self):
        self.assertEqual(linux_wallpaper._kde_wallpaper(self.config), '')

    @patch.object(linux_wallpaper, '_run')
    def test_unknown_original_is_left_alone_on_restore(self, run):
        linux_wallpaper.set_wallpaper('kde', 'kde', '')
        run.assert_not_called()


class BackgroundLogTests(unittest.TestCase):
    def test_log_is_trimmed_when_it_grows_too_large(self):
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / 'background.log'
            log_file.write_text('line\n' * 1000, encoding='utf-8')
            with patch.object(background, 'LOG_FILE', log_file), \
                    patch.object(background, 'MAX_LOG_BYTES', 100):
                background.log('newest')
            lines = log_file.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 201)
            self.assertTrue(lines[-1].endswith('newest'))


if __name__ == '__main__':
    unittest.main()
