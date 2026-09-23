"""Optional cross-platform system tray integration."""
import threading


class TrayIcon:
    def __init__(self, portal):
        self.portal = portal
        self.icon = None
        self.thread = None

    def start(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return False
        image = Image.new('RGBA', (64, 64), '#6d4aff')
        draw = ImageDraw.Draw(image)
        draw.ellipse((15, 10, 49, 44), fill='white')
        draw.rectangle((28, 40, 36, 56), fill='white')

        def call(action):
            return lambda icon, item: self.portal.root.after(0, action)

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._active_label(), None, enabled=False),
            pystray.MenuItem('Open DesktopPortal', call(self.portal.show), default=True),
            pystray.MenuItem('Random theme wheel', call(self.portal.open_random_wheel)),
            pystray.MenuItem(
                lambda item: 'Resume NFC detection' if self.portal.detection_paused else 'Pause NFC detection',
                call(self.portal.toggle_detection),
            ),
            pystray.MenuItem('Restore desktop', call(lambda: self.portal.run(self.portal.restore))),
            pystray.MenuItem('Quit', call(self.portal.quit_app)),
        )
        self.icon = pystray.Icon('DesktopPortal', image, 'DesktopPortal', menu)
        self.thread = threading.Thread(target=self.icon.run, daemon=True)
        self.thread.start()
        return True

    def _active_label(self):
        pack = self.portal.packs.get(self.portal.desktop.active, {})
        return 'Active: ' + pack.get('name', 'Original desktop')

    def stop(self):
        if self.icon is not None:
            self.icon.stop()
            self.icon = None
