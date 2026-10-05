# DesktopPortal

DesktopPortal activates wallpaper, cursors and a random sound from portable packs using NFC or the GUI.

## Run

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

For a new Windows machine, clone the private repository and set up Python first:

```powershell
git clone https://github.com/ruslanD05/DesktopPortal.git
cd DesktopPortal
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe main.py
```

Personal packs and their wallpapers, sounds and cursors are excluded from Git.
Transfer the `packs` folder separately, or export packs on the original PC and
import them in the app. A fresh clone starts without packs. Existing tag and
collection entries do not become usable until their packs are transferred.
Configure **Start DesktopPortal at login** on the new machine so its task points
to that machine's application path.

## Build the Windows application

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_release.ps1
```

The build creates `dist\DesktopPortal\DesktopPortal.exe` and a portable
`dist\DesktopPortal-Windows.zip`. Keep the files inside the application folder
together so packs and settings remain editable. The same executable runs in
the background when Windows starts it with `--background`.

Select a pack and **Activate**, or choose **Bind tag** and scan within 30 seconds. Binding does not activate the pack; remove and rescan the tag. Unknown tags do nothing. Files selected from anywhere are copied into the pack. Wallpaper and sound selection dialogs let each file be previewed and included or excluded from random rotation. Cursor mappings expose all 15 Windows cursor states, show animated previews, mirror individual cursors horizontally or vertically, and can auto-detect a folder.

The first-run wizard checks the NFC reader and sets the initial restore, startup and theme preferences. The pack list supports live name/ID search plus enabled/disabled filtering. Enable the dark theme in **Options**. In the pack editor, drag files or folders onto the drop area to import supported images, audio and recognizable cursor files.

**Random wheel** opens a CS-style animated picker. It can use every enabled pack or only the enabled packs in one collection, remembers that collection, and activates the winner. The tray menu and configurable Windows global hotkeys can open the wheel or switch to the next, previous, or a random pack without NFC.

Each pack can have looping background music from a local MP3/OGG/WAV file. Background-music volume is separate from activation-sound volume in **Options**.

**Preview** applies a pack temporarily without its sound, then returns to the prior pack. **Options** controls sound volume, cooldown, play-on-change behavior, preview duration and the Windows cursor-size scale. Wallpaper transitions remain instant because native desktop wallpaper APIs do not provide a reliable cross-desktop fade.

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
python3 linux_cursor.py apply packs/hollowknight
python3 linux_cursor.py apply "/home/ruslan/Downloads/Hollow Knight" --size 32
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
