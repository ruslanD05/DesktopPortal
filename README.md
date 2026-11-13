# DesktopPortal

> **Beta.** Windows is the main platform. Linux support is experimental.

Make themed packs of wallpapers, cursors, sounds and background music, then
switch between them from the app, a tray menu, global hotkeys or a random
"theme wheel". An NFC reader is optional: tap a tag to switch packs.

![DesktopPortal main window](docs/screenshot.png)

## Install (Windows)

1. Download `DesktopPortal.exe` from the
   [Releases](https://github.com/ruslanD05/DesktopPortal/releases) page.
2. Put it in a folder of its own that you can write to, such as
   `Documents\DesktopPortal`. The app creates its `packs` and `data` folders
   next to the executable, so do not keep it on the Desktop or in
   `Program Files`.
3. Run `DesktopPortal.exe`. The build is unsigned, so Windows SmartScreen may
   warn you; choose **More info** > **Run anyway**. The first start takes a
   few seconds.

There is no installer, no Python to install and nothing to extract. Nothing is
written outside that folder, apart from the optional login task described under
[Options](#options). To update, quit the app and replace `DesktopPortal.exe`
with the newer one; your `packs` and `data` folders are kept.

**Uninstall:** turn off **Start DesktopPortal at login** in **Options**, choose
**More > Quit DesktopPortal** (this puts your original wallpaper and cursors
back), then delete the folder.

## First-time setup

The first launch opens a three-step wizard. You can skip it; everything in it
can be changed later in **Options**.

1. **Welcome** explains what packs are.
2. **NFC reader** shows whether a reader was found. A reader is optional: every
   feature also works from the window, the tray menu and hotkeys.
3. **Choose your defaults** has three checkboxes, all off to begin with:
   - **Restore the original desktop when the last figurine is removed**
   - **Start DesktopPortal at login**
   - **Use dark theme**

The first launch also creates a small **Aurora (sample)** pack so you can try
the app straight away; delete it whenever you like.

## Quick start

1. Select **Aurora (sample)** and click **Activate**. Your wallpaper and
   cursors change and a chime plays.
2. Click **More > Restore original desktop** to go back. Quitting the app does
   the same.
3. Click **New pack**, give it a name and an ID, then **Edit pack** to add
   wallpapers, cursors, sounds and music. You can drag files or folders onto
   the drop area. Files are copied into the pack.
4. With an NFC reader: select a pack, click **Bind tag** and place a tag or
   figurine on the reader within 30 seconds. Binding does not activate the
   pack. Lift the tag and place it again to activate it.

Closing the window with **X** only hides it; DesktopPortal keeps running in the
tray so tags and hotkeys still work. Use **More > Quit DesktopPortal** to exit.

To share packs, use **More > Export selected…** and **Import**. Only share
packs whose assets you have the right to redistribute.

## Options

Open **Options** at the top right of the main window. Changes apply when you
click **Save**.

### General

| Option | Default | What it does |
| --- | --- | --- |
| Activation sound volume | 80% | Volume of the sound played when a pack activates. |
| Background music volume | 50% | Volume of a pack's looping music. |
| Sound cooldown (seconds) | 1.0 | Minimum time between two activation sounds. |
| Play sound only when the active pack changes | On | Skips the sound when the pack that is already active is activated again. |
| Preview duration (seconds) | 8 | How long **Preview** shows a pack before returning to the previous one. |
| Cursor size (1–15) | Your Windows size | Pointer size while DesktopPortal is running. Quitting puts your own size back. |
| Restore the original desktop when the last figurine is removed | Off | See below. |
| Start DesktopPortal at login | Off | Starts the app hidden in the tray when you sign in to Windows. |
| Use dark theme | Off | Dark colors for the DesktopPortal windows. |

**Figurine removal.** By default a pack stays active after you lift its
figurine from the reader, so you can take the figurine away and keep the theme.
Turn on **Restore the original desktop when the last figurine is removed** to
make the theme disappear instead: your own wallpaper and cursors come back as
soon as no bound tag is left on a reader. With two readers, removing one
figurine switches to the pack of the figurine that is still present, whichever
way this option is set. Packs activated by hand, hotkey or the wheel are not
affected by removing a tag.

**Start at login** registers a Windows Task Scheduler task for your user that
points at the current location of the app. If you move the folder, turn the
option off and on again.

### Hotkeys

Global shortcuts work while the app is running, even when its window is hidden.
Use the form `Ctrl+Alt+Space`; clear a field to disable that shortcut.

| Action | Default |
| --- | --- |
| Open random wheel | `Ctrl+Alt+Space` |
| Next enabled pack | `Ctrl+Alt+Right` |
| Previous enabled pack | `Ctrl+Alt+Left` |
| Activate random pack | `Ctrl+Alt+R` |

## Works offline

DesktopPortal never connects to the internet. There are no accounts, no
telemetry, no update checks and no downloads; packs are plain folders on your
disk and music must be a local file. The only socket it opens is on
`127.0.0.1`, used so a second launch can bring the running app to the front.

## Reporting bugs

Open **More > Diagnostics…**, click **Copy for bug report**, and paste the
result into a new
[issue](https://github.com/ruslanD05/DesktopPortal/issues/new/choose). The
report shows the app version, platform, NFC reader state and recent activity.

## Run from source

```powershell
git clone https://github.com/ruslanD05/DesktopPortal.git
cd DesktopPortal
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Packs (`packs/`) and personal data (`data/`) are excluded from Git. To move
your setup to another PC, export packs there and import them, and re-enable
**Start DesktopPortal at login** so it points to the new location.

## Build the Windows application

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_release.ps1
```

The build creates a single self-contained `dist\DesktopPortal.exe`; that one
file is the release. It contains no packs or settings. The same executable runs
in the background when Windows starts it with `--background`. The version shown
in Diagnostics comes from `version.py`.

## Using DesktopPortal

Select a pack and **Activate**, or choose **Bind tag** and scan within 30 seconds. Binding does not activate the pack; remove and rescan the tag. Unknown tags do nothing. Files selected from anywhere are copied into the pack. Wallpaper and sound selection dialogs let each file be previewed and included or excluded from random rotation. Cursor mappings expose all 15 Windows cursor states, show animated previews, mirror individual cursors horizontally or vertically, and can auto-detect a folder.

The pack list supports live name/ID search plus enabled/disabled filtering. Enable the dark theme in **Options**. In the pack editor, drag files or folders onto the drop area to import supported images, audio and recognizable cursor files.

**Random wheel** opens a CS-style animated picker. It can use every enabled pack or only the enabled packs in one collection, remembers that collection, and activates the winner. The tray menu and configurable Windows global hotkeys can open the wheel or switch to the next, previous, or a random pack without NFC.

Each pack can have looping background music from a local MP3/OGG/WAV file. Background-music volume is separate from activation-sound volume in **Options**.

**Preview** applies a pack temporarily without its sound, then returns to the prior pack. **Options** controls sound volume, cooldown, play-on-change behavior, preview duration and the Windows cursor-size scale. A custom cursor size applies while DesktopPortal is running; quitting puts your own size back. Wallpaper transitions remain instant because native desktop wallpaper APIs do not provide a reliable cross-desktop fade.

**Export** creates a versioned ZIP containing the selected pack and its assets. **Import** safely renames a pack when its ID already exists. Collections can be exported as one bundle. **Validate** reports missing files, unsupported formats and cursor roles. **Clean assets** previews and removes files no longer referenced by a pack.

Disable a pack to prevent manual and NFC activation. Collections appear as collapsible rows and can enable or disable all their packs together. A pack may appear in multiple collections.

**Delete selected pack** is available under **More**. It confirms before removing the pack folder, tag bindings and collection memberships.

Enable **Start DesktopPortal at login** to register an immediate Task Scheduler logon trigger. It launches `pythonw.exe` directly without a terminal or Windows' delayed startup-app queue. Closing the GUI hides it while the listener and tray icon continue running. Launch `main.py` again or use the tray to reopen it. The tray also pauses NFC detection, restores the desktop and quits. **Diagnostics** shows platform capabilities, reader state, present tags, recent activity and the background log.

If PC/SC or the reader is unavailable at sign-in, DesktopPortal retries every three seconds. A snapshot in `data/desktop-state.json` allows the original wallpaper and cursors to be restored after a crash.

During Windows shutdown/logoff or Linux termination, DesktopPortal restores the original wallpaper and cursors before exiting. After an abrupt power loss or crash, the background process automatically restores the saved snapshot on its next launch.

## Linux foundation

Pack, collection, NFC, sound, tray and GUI code is portable. GNOME, Cinnamon and Unity wallpaper changes use `gsettings`; KDE uses `plasma-apply-wallpaperimage`. Per-role `.ani`/`.cur` cursor mapping is a Windows feature and is skipped on Linux. Linux startup uses `~/.config/autostart/DesktopPortal.desktop`.

## Standalone cursor converter

### Apply cursors on Ubuntu/GNOME

The standalone Linux activation script accepts a saved pack folder or an
extracted cursor folder, converts its assets, and installs an Xcursor theme:

```bash
python3 linux_cursor.py apply packs/my_pack
python3 linux_cursor.py apply ~/Downloads/MyCursors --size 32
python3 linux_cursor.py status
python3 linux_cursor.py restore
```

Run it as your desktop user, without sudo. Generated themes live in `~/.icons`.
Unmapped Linux cursor shapes inherit your original theme. The first apply saves
the original theme and pixel size in `data/linux-cursor-state.json`; subsequent
applies preserve that first snapshot. Restore removes it only after both settings
are restored successfully. These commands change only cursor settings. This
script is separate from the GUI's Activate/Restore flow for now. Some running
applications may need to be reopened to pick up a new theme.

Cursor conversion also runs automatically when editing a pack or importing a
DesktopPortal bundle. Selecting or dropping a cursor, or using **Auto-detect
folder**, detects CUR, ANI or Xcursor by content and prepares a file for the
current OS only when needed. Source files are retained in the pack via
`cursor_sources`; `cursors` maps roles to the prepared files. Conversion results
are reused until the source changes. Linux cursor names such as `left_ptr`,
`watch`, and `xterm` are recognized, including extensionless files. Converting
assets does not yet enable Linux cursor activation.

On Ubuntu, open the converter window with:

```bash
python3 cursor_converter.py
```

Choose a Windows `.cur`/`.ani` file or a Linux Xcursor file (often extensionless),
then an output folder and click **Convert**. The tool detects the direction from
file contents and writes `.xcursor`, `.cur`, or `.ani` as appropriate. Existing
files are never overwritten. It does not install themes or change your cursor.

The same conversion is available from the terminal:

```bash
python3 cursor_converter.py "input.ani" /path/to/output-folder
python3 cursor_converter.py /usr/share/icons/DMZ-White/cursors/left_ptr output.cur
python3 cursor_converter.py /path/to/animated-xcursor output.ani --size 32
```

Conversion requires Pillow (already in `requirements.txt`). The native Xcursor
library is used when available, with a portable reader/writer for Windows.
Images, hotspots and compatible
size variants are retained. Windows animation timing is rounded to 1/60-second
ticks; Xcursor uses milliseconds. Premultiplied Linux transparency can introduce
small color-rounding differences. If sizes have different animation timing,
select one size in the standalone tool. Automatic import selects the largest
compatible size when size variants cannot share one Windows animation timeline.
Windows output is limited to images up to 256 pixels. ANI files
with raw bitmap frames or embedded ICO frames without hotspots are unsupported.

## Checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
