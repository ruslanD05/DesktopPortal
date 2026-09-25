import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch
import queue
import socket

import desktop
import cursor_images
import cursor_roles
import hotkeys
import main
import packs
import pack_tools
import startup
from random_wheel import ALL_PACKS, RandomWheel


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state.json'
        self.original = {'Arrow': ('old.cur', 2), 'Help': None}
        for name, value in [('STATE_FILE', self.state), ('get_wallpaper', Mock(return_value='old.png')),
                            ('snapshot_cursors', Mock(return_value=self.original)),
                            ('restore_cursors', Mock()), ('set_wallpaper', Mock()),
                            ('set_cursors', Mock()), ('stop_sound', Mock()), ('play_sound', Mock()),
                            ('stop_music', Mock()), ('play_music', Mock()),
                            ('asset', Mock(side_effect=lambda pid, path: Path(path)))]:
            patcher = patch.object(desktop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        backend = Mock(supports_cursors=True)
        patcher = patch.object(desktop, '_BACKEND', backend)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = desktop.Desktop()

    def test_switch_and_restore_preserves_first_snapshot(self):
        self.app.activate('one', {'wallpaper': 'one.png', 'cursors': {'Arrow': 'one.cur'}})
        self.app.activate('two', {'wallpaper': 'two.png', 'cursors': {'Arrow': 'two.cur'}})
        self.assertEqual(self.app.original['wallpaper'], 'old.png')
        self.assertTrue(self.state.exists())
        self.assertEqual(
            desktop.set_wallpaper.call_args_list,
            [call(Path('one.png')), call(Path('two.png'))],
        )
        self.assertEqual(
            desktop.set_cursors.call_args_list,
            [call({'Arrow': Path('one.cur')}), call({'Arrow': Path('two.cur')})],
        )
        desktop.restore_cursors.assert_not_called()
        self.app.restore()
        desktop.restore_cursors.assert_called_with(self.original)
        desktop.set_wallpaper.assert_called_with('old.png')
        self.assertFalse(self.state.exists())

    def test_failed_activation_restores(self):
        desktop.set_cursors.side_effect = OSError('Bad cursor')
        with self.assertRaisesRegex(OSError, 'Bad cursor'):
            self.app.activate('one', {'cursors': {'Arrow': 'one.cur'}})
        self.assertIsNone(self.app.active)
        desktop.set_wallpaper.assert_called_with('old.png')
        self.assertFalse(self.state.exists())

    def test_failed_restore_keeps_recovery_file_and_tries_wallpaper(self):
        self.app.activate('one', {})
        desktop.restore_cursors.side_effect = OSError('reload failed')
        with self.assertRaises(OSError):
            self.app.restore()
        self.assertTrue(self.state.exists())
        desktop.set_wallpaper.assert_called_with('old.png')

    def test_restart_can_recover(self):
        self.app.activate('one', {})
        recovered = desktop.Desktop()
        recovered.restore()
        self.assertFalse(self.state.exists())
        desktop.set_wallpaper.assert_called_with('old.png')

    def test_random_wallpaper_is_selected_from_pack(self):
        with patch.object(desktop.random, 'choice', return_value=Path('second.png')):
            self.app.activate('one', {'wallpapers': ['first.png', 'second.png']})
        desktop.set_wallpaper.assert_any_call(Path('second.png'))

    def test_disabled_effects_are_not_applied(self):
        pack = {
            'wallpapers': ['new.png'],
            'cursors': {'Arrow': 'new.cur'},
            'sounds': ['new.mp3'],
            'effects': {'wallpaper': False, 'cursors': False, 'sounds': False},
        }
        self.app.activate('one', pack)
        # One call restores the original; disabled wallpaper adds no second call.
        self.assertEqual(desktop.set_wallpaper.call_args_list, [call('old.png')])
        desktop.set_cursors.assert_not_called()
        desktop.play_sound.assert_not_called()

    def test_pack_music_loops_and_stops_on_pack_change(self):
        error_handler = Mock()
        self.app.on_music_error = error_handler
        self.app.settings = {'music_volume': 0.35}
        self.app.activate('one', {'music': 'theme.mp3'})
        desktop.play_music.assert_called_once_with(
            Path('theme.mp3'), 0.35, error_handler,
        )
        self.app.activate('two', {})
        self.assertGreaterEqual(desktop.stop_music.call_count, 1)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.portal = main.Portal.__new__(main.Portal)
        p = self.portal
        p.tags = {'one': 'a', 'two': 'b'}
        p.packs = {'a': {'name': 'A'}, 'b': {'name': 'B'}}
        p.present = {}
        p.suppressed_uids = set()
        p.binding = None
        p.tag_controlled = False
        p.restore_on_remove = Mock()
        p.restore_on_remove.get.return_value = True
        p.desktop = Mock()
        p.status = Mock()
        p.reload = Mock()

    @patch('nfc.start_monitor')
    def test_nfc_monitor_can_retry_after_startup(self, start_monitor):
        p = self.portal
        p.monitor_enabled = True
        p.monitor = None
        p.observer = None
        p.events = queue.Queue()
        p.reader_status = Mock()
        start_monitor.return_value = ('monitor', 'observer')
        p.ensure_monitor()
        self.assertEqual((p.monitor, p.observer), ('monitor', 'observer'))
        start_monitor.assert_called_once_with(p.events)

    def test_unknown_tag_has_no_effect(self):
        self.portal.handle_event('added', 'reader', 'unknown')
        self.portal.desktop.activate.assert_not_called()

    def test_disabled_pack_does_not_trigger(self):
        self.portal.packs['a']['enabled'] = False
        self.portal.handle_event('added', 'reader', 'one')
        self.portal.desktop.activate.assert_not_called()
        self.assertEqual(self.portal.present, {})

    def test_two_readers_fall_back_then_restore(self):
        p = self.portal
        p.handle_event('added', 'r1', 'one')
        p.handle_event('added', 'r2', 'two')
        p.desktop.activate.assert_called_with('b', p.packs['b'])
        p.handle_event('removed', 'r2', None)
        p.desktop.activate.assert_called_with('a', p.packs['a'])
        p.handle_event('removed', 'r1', None)
        p.desktop.restore.assert_called_once()

    def test_duplicate_added_event_activates_only_once(self):
        p = self.portal
        p.handle_event('added', 'r1', 'one')
        p.handle_event('added', 'r1', 'one')
        p.desktop.activate.assert_called_once_with('a', p.packs['a'])

    def test_same_uid_from_two_reader_interfaces_activates_only_once(self):
        p = self.portal
        p.handle_event('added', 'r1', 'one')
        p.handle_event('added', 'r2', 'one')
        p.desktop.activate.assert_called_once_with('a', p.packs['a'])
        p.handle_event('removed', 'r2', None)
        p.desktop.activate.assert_called_once()
        p.desktop.restore.assert_not_called()
        p.handle_event('removed', 'r1', None)
        p.desktop.restore.assert_called_once()

    def test_manual_activation_survives_tag_removal(self):
        p = self.portal
        p.handle_event('added', 'r1', 'one')
        p.selected = Mock(return_value='b')
        p.activate_selected()
        p.handle_event('removed', 'r1', None)
        p.desktop.restore.assert_not_called()

    def test_last_tag_can_leave_current_desktop_active(self):
        p = self.portal
        p.restore_on_remove.get.return_value = False
        p.handle_event('added', 'r1', 'one')
        p.handle_event('removed', 'r1', None)
        p.desktop.restore.assert_not_called()
        self.assertFalse(p.tag_controlled)

    def test_restore_preference_does_not_disable_reader_fallback(self):
        p = self.portal
        p.restore_on_remove.get.return_value = False
        p.handle_event('added', 'r1', 'one')
        p.handle_event('added', 'r2', 'two')
        p.handle_event('removed', 'r2', None)
        p.desktop.activate.assert_called_with('a', p.packs['a'])

    @patch('main.save_tags')
    def test_binding_is_one_shot_and_does_not_activate(self, save):
        p = self.portal
        p.binding = ('b', float('inf'))
        p.handle_event('added', 'r1', 'new')
        self.assertEqual(p.tags['new'], 'b')
        self.assertIsNone(p.binding)
        self.assertIn('new', p.suppressed_uids)
        p.desktop.activate.assert_not_called()
        save.assert_called_once()

        # Duplicate insertion callbacks after binding stay silent until removal.
        p.handle_event('added', 'r1', 'new')
        p.desktop.activate.assert_not_called()
        p.handle_event('removed', 'r1', None)
        p.handle_event('added', 'r1', 'new')
        p.desktop.activate.assert_called_once_with('b', p.packs['b'])

    @patch('main.save_tags')
    def test_expired_binding_does_not_save(self, save):
        self.portal.binding = ('b', 0)
        self.portal.handle_event('added', 'r1', 'unknown')
        save.assert_not_called()


class PackTests(unittest.TestCase):
    @patch('main.messagebox.askyesno', return_value=True)
    @patch('main.save_collections')
    @patch('main.save_tags')
    @patch('main.load_collections', return_value={'Group': ['demo', 'other']})
    def test_delete_pack_removes_files_tags_and_membership(
        self, load_collections, save_tags, save_collections, confirm
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'packs'
            folder = root / 'demo'
            folder.mkdir(parents=True)
            (folder / 'asset.png').touch()
            portal = main.Portal.__new__(main.Portal)
            portal.selected = Mock(return_value='demo')
            portal.packs = {'demo': {'name': 'Demo'}}
            portal.tags = {'one': 'demo', 'two': 'other'}
            portal.present = {'reader': ('one', 'demo')}
            portal.desktop = Mock(active=None)
            portal.root = Mock()
            portal.reload = Mock()
            portal.status = Mock()
            with patch.object(main, 'PACKS_DIR', root):
                portal.delete_selected()
            self.assertFalse(folder.exists())
            save_tags.assert_called_once_with({'two': 'other'})
            save_collections.assert_called_once_with({'Group': ['other']})
            self.assertEqual(portal.present, {})

    def test_bundle_round_trip_renames_existing_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            target = root / 'target'
            (source / 'demo').mkdir(parents=True)
            (target / 'demo').mkdir(parents=True)
            packs.write_json(source / 'demo/pack.json', {
                'id': 'demo', 'name': 'Demo', 'wallpapers': [],
                'cursors': {}, 'sounds': [],
            })
            bundle = root / 'demo.zip'
            pack_tools.export_bundle(['demo'], bundle, packs_dir=source)
            imported, _, mapping = pack_tools.import_bundle(bundle, packs_dir=target)
            self.assertEqual(imported, ['demo_2'])
            self.assertEqual(mapping, {'demo': 'demo_2'})
            manifest = packs.json.loads((target / 'demo_2/pack.json').read_text())
            self.assertEqual(manifest['id'], 'demo_2')

    def test_cleanup_only_removes_unreferenced_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'demo'
            folder.mkdir()
            keep = folder / 'wallpapers/keep.png'
            unused = folder / 'wallpapers/old.png'
            keep.parent.mkdir()
            keep.touch()
            unused.touch()
            removed = pack_tools.cleanup_assets(
                'demo', {'wallpapers': ['wallpapers/keep.png']}, packs_dir=root
            )
            self.assertEqual(removed, [unused])
            self.assertTrue(keep.exists())

    def test_local_music_is_packaged_but_youtube_url_is_not_an_asset(self):
        local = {'music': 'music/theme.mp3'}
        remote = {'music': 'https://www.youtube.com/watch?v=example'}
        self.assertIn('music/theme.mp3', pack_tools.referenced_assets(local))
        self.assertEqual(pack_tools.referenced_assets(remote), set())

    def test_validation_reports_missing_and_unknown_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'demo').mkdir()
            issues = pack_tools.validate_pack(
                'demo', {'wallpapers': ['missing.png'], 'cursors': {'Other': 'x.cur'}},
                packs_dir=root,
            )
            self.assertTrue(any('Unknown cursor roles' in issue for issue in issues))
            self.assertTrue(any('Missing asset' in issue for issue in issues))

    def test_startup_setting_defaults_off(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'settings.json'
            with patch.object(packs, 'SETTINGS_FILE', missing):
                self.assertFalse(packs.load_settings()['start_with_windows'])

    def test_pack_groups_are_collapsible_collections_plus_uncollected(self):
        pack_map = {'a': {}, 'b': {}, 'c': {}}
        collections = {'Mane Six': ['a', 'b']}
        self.assertEqual(
            packs.group_packs(pack_map, collections),
            [('Mane Six', ['a', 'b']), ('Uncollected', ['c'])],
        )

    def test_pack_is_enabled_by_default(self):
        self.assertTrue(packs.pack_enabled({}))
        self.assertFalse(packs.pack_enabled({'enabled': False}))

    def test_collections_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'collections.json'
            value = {'Mane Six': ['applejack', 'fluttershy', 'twilight_sparkle']}
            with patch.object(packs, 'COLLECTIONS_FILE', path):
                packs.save_collections(value)
                self.assertEqual(packs.load_collections(), value)

    def test_legacy_wallpaper_becomes_single_item_list(self):
        self.assertEqual(
            packs.pack_wallpapers({'wallpaper': 'wallpaper.png'}),
            ['wallpaper.png'],
        )

    def test_asset_cannot_escape_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pack').mkdir()
            (root / 'outside.wav').touch()
            with patch.object(packs, 'PACKS_DIR', root):
                with self.assertRaises(ValueError):
                    packs.asset('pack', '../outside.wav')

    def test_malformed_pack_does_not_hide_good_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'good').mkdir()
            (root / 'bad').mkdir()
            (root / 'good/pack.json').write_text('{"name": "Good"}')
            (root / 'bad/pack.json').write_text('{bad')
            with patch.object(packs, 'PACKS_DIR', root):
                loaded, errors = packs.load_packs()
            self.assertEqual(list(loaded), ['good'])
            self.assertEqual(len(errors), 1)

    def test_external_editor_asset_is_copied_into_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            pack_root = directory / 'packs'
            (pack_root / 'demo').mkdir(parents=True)
            external = directory / 'outside' / 'cursor.ani'
            external.parent.mkdir()
            external.write_bytes(b'cursor data')
            editor = main.PackEditor.__new__(main.PackEditor)
            editor.pack_id = 'demo'
            with patch.object(main, 'PACKS_DIR', pack_root):
                relative = editor.copy(external, 'cursors')
            copied = pack_root / 'demo' / relative
            self.assertEqual(relative, 'cursors/cursor.ani')
            self.assertEqual(copied.read_bytes(), b'cursor data')
            self.assertNotEqual(copied.resolve(), external.resolve())

    def test_pack_local_asset_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            pack_root = Path(directory) / 'packs'
            local = pack_root / 'demo' / 'custom' / 'cursor.ani'
            local.parent.mkdir(parents=True)
            local.touch()
            editor = main.PackEditor.__new__(main.PackEditor)
            editor.pack_id = 'demo'
            with patch.object(main, 'PACKS_DIR', pack_root):
                relative = editor.copy(local, 'cursors')
            self.assertEqual(relative, 'custom/cursor.ani')

    def test_replacing_cursor_overwrites_assigned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            pack_root = directory / 'packs'
            assigned = pack_root / 'demo' / 'cursors' / 'arrow.ani'
            assigned.parent.mkdir(parents=True)
            assigned.write_bytes(b'old cursor')
            external = directory / 'new-arrow.ani'
            external.write_bytes(b'new cursor')
            editor = main.PackEditor.__new__(main.PackEditor)
            editor.pack_id = 'demo'
            with patch.object(main, 'PACKS_DIR', pack_root):
                relative = editor.copy(
                    external, 'cursors', replace='cursors/arrow.ani'
                )
            self.assertEqual(relative, 'cursors/arrow.ani')
            self.assertEqual(assigned.read_bytes(), b'new cursor')
            self.assertEqual(
                [path.name for path in assigned.parent.iterdir()],
                ['arrow.ani'],
            )

    def test_dropped_folder_imports_supported_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            pack_root = directory / 'packs'
            (pack_root / 'demo').mkdir(parents=True)
            dropped = directory / 'drop'
            dropped.mkdir()
            for name in ('wallpaper.png', 'hello.mp3', 'Demo -Normal Select-.ani'):
                (dropped / name).write_bytes(name.encode())
            editor = main.PackEditor.__new__(main.PackEditor)
            editor.pack_id = 'demo'
            editor.pack = {'wallpapers': [], 'sounds': [], 'cursors': {}}
            editor.window = Mock()
            editor.window.tk.splitlist.return_value = [str(dropped)]
            editor.drop_status = Mock()
            editor.update_info = Mock()
            with patch.object(main, 'PACKS_DIR', pack_root):
                editor.drop_assets(str(dropped))
            self.assertEqual(len(editor.pack['wallpapers']), 1)
            self.assertEqual(len(editor.pack['sounds']), 1)
            self.assertIn('Arrow', editor.pack['cursors'])


class CursorDiscoveryTests(unittest.TestCase):
    def test_normal_alias_maps_to_arrow(self):
        with tempfile.TemporaryDirectory() as directory:
            cursor = Path(directory) / 'Applejack -Normal-.ani'
            cursor.touch()
            self.assertEqual(cursor_roles.find_cursors(directory)['Arrow'], cursor.resolve())


class HotkeyTests(unittest.TestCase):
    def test_parses_global_shortcut(self):
        modifiers, key = hotkeys.parse_hotkey('Ctrl+Alt+Space')
        self.assertEqual(key, 0x20)
        self.assertTrue(modifiers & 0x0001)
        self.assertTrue(modifiers & 0x0002)

    def test_rejects_shortcut_without_modifier(self):
        with self.assertRaises(ValueError):
            hotkeys.parse_hotkey('R')


class RandomWheelTests(unittest.TestCase):
    def test_collection_scope_excludes_disabled_packs(self):
        wheel = RandomWheel.__new__(RandomWheel)
        wheel.portal = Mock()
        wheel.portal.packs = {
            'one': {'enabled': True},
            'two': {'enabled': False},
            'three': {'enabled': True},
        }
        wheel.collections = {'Chosen': ['one', 'two']}
        wheel.scope = Mock()
        wheel.scope.get.return_value = 'Chosen'
        self.assertEqual(wheel.candidates(), ['one'])
        wheel.scope.get.return_value = ALL_PACKS
        self.assertEqual(wheel.candidates(), ['one', 'three'])


class CursorImageTests(unittest.TestCase):
    @staticmethod
    def cursor_bytes(hotspot=(0, 0)):
        from io import BytesIO
        from PIL import Image
        image = Image.new('RGBA', (2, 2))
        image.putdata([
            (255, 0, 0, 255), (0, 255, 0, 255),
            (0, 0, 255, 255), (255, 255, 0, 255),
        ])
        output = BytesIO()
        image.save(output, format='PNG')
        payload = output.getvalue()
        import struct
        return (struct.pack('<HHH', 0, 2, 1)
                + struct.pack('<BBBBHHII', 2, 2, 0, 0, hotspot[0], hotspot[1],
                              len(payload), 22)
                + payload)

    def test_horizontal_flip_mirrors_pixels_and_hotspot(self):
        import struct
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.cur'
            path.write_bytes(self.cursor_bytes((0, 1)))
            cursor_images.flip_cursor(path, 'x')
            self.assertEqual(struct.unpack_from('<HH', path.read_bytes(), 10), (1, 1))
            image = cursor_images.preview_frames(path)[0]
            self.assertEqual(image.getpixel((0, 0)), (0, 255, 0, 255))
            self.assertEqual(image.getpixel((1, 0)), (255, 0, 0, 255))

    def test_vertical_flip_mirrors_pixels_and_hotspot(self):
        import struct
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.cur'
            path.write_bytes(self.cursor_bytes((1, 0)))
            cursor_images.flip_cursor(path, 'y')
            self.assertEqual(struct.unpack_from('<HH', path.read_bytes(), 10), (1, 1))
            image = cursor_images.preview_frames(path)[0]
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
            self.assertEqual(image.getpixel((0, 1)), (255, 0, 0, 255))

    def test_ani_flip_keeps_all_frames(self):
        import struct
        icon = self.cursor_bytes((0, 0))
        chunks = b''.join(
            b'icon' + struct.pack('<I', len(icon)) + icon + (b'\0' if len(icon) & 1 else b'')
            for _ in range(2)
        )
        body = b'ACON' + b'LIST' + struct.pack('<I', len(chunks) + 4) + b'fram' + chunks
        ani = b'RIFF' + struct.pack('<I', len(body)) + body
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.ani'
            path.write_bytes(ani)
            cursor_images.flip_cursor(path, 'x')
            self.assertEqual(len(cursor_images.preview_frames(path)), 2)


class StartupTests(unittest.TestCase):
    def test_existing_instance_notification_uses_local_socket(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((main.IPC_HOST, 0))
        server.listen(1)
        port = server.getsockname()[1]
        self.addCleanup(server.close)
        with patch.object(main, 'IPC_PORT', port):
            self.assertTrue(main.notify_running_instance())
        connection, _ = server.accept()
        with connection:
            self.assertEqual(connection.recv(32), b'show')

    @patch('main.notify_running_instance', return_value=True)
    def test_duplicate_background_launch_does_not_show_gui(self, notify):
        main.main(start_hidden=True)
        notify.assert_called_once_with(show=False)

    def test_startup_command_uses_windowed_python_and_absolute_script(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / 'Python Folder' / 'python.exe'
            python.parent.mkdir()
            python.touch()
            python.with_name('pythonw.exe').touch()
            with patch.object(startup.sys, 'executable', str(python)):
                command = startup.startup_command()
        self.assertIn('pythonw.exe', command)
        self.assertIn(str(packs.BASE_DIR / 'background.py'), command)

    @patch('startup._set_registry_startup')
    @patch('startup._set_scheduled_task')
    @patch('startup.platform.system', return_value='Windows')
    def test_startup_uses_immediate_task_and_removes_old_launchers(
        self, system, set_task, set_registry
    ):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / 'DesktopPortal.cmd'
            legacy = Path(directory) / 'DesktopPortal.vbs'
            launcher.touch()
            legacy.touch()
            with patch.object(startup, 'STARTUP_FILE', launcher), \
                    patch.object(startup, 'LEGACY_STARTUP_FILE', legacy):
                startup.set_startup_enabled(True)
                self.assertFalse(launcher.exists())
                self.assertFalse(legacy.exists())
                startup.set_startup_enabled(False)
        self.assertEqual(
            set_task.call_args_list,
            [call(True), call(False)],
        )
        self.assertEqual(set_registry.call_args_list, [call(False), call(False)])

    def test_logon_task_has_no_delay_and_uses_windowed_python(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / 'python.exe'
            python.touch()
            python.with_name('pythonw.exe').touch()
            with patch.object(startup.sys, 'executable', str(python)), \
                    patch('startup._target_user_sid', return_value='S-1-5-21-test'):
                xml = startup._task_xml()
        self.assertIn('LogonTrigger', xml)
        self.assertNotIn('<Delay>', xml)
        self.assertIn('pythonw.exe', xml)

    def test_hiding_window_keeps_portal_alive(self):
        portal = main.Portal.__new__(main.Portal)
        portal.root = Mock()
        portal.hide()
        portal.root.withdraw.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
