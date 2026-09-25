"""Current-user Windows login startup integration."""
import os
import platform
import shlex
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

if platform.system() == 'Windows':
    import winreg
else:
    winreg = None

from packs import BASE_DIR

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'DesktopPortal'
TASK_NAME = 'DesktopPortal'
PROFILE_LIST_KEY = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
STARTUP_APPROVED_RUN = (
    r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
)
STARTUP_APPROVED_FOLDER = (
    r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'
)
if platform.system() == 'Windows':
    STARTUP_DIRECTORY = (
        Path(os.environ['APPDATA'])
        / 'Microsoft/Windows/Start Menu/Programs/Startup'
    )
    STARTUP_FILE = STARTUP_DIRECTORY / 'DesktopPortal.cmd'
    LEGACY_STARTUP_FILE = STARTUP_DIRECTORY / 'DesktopPortal.vbs'
else:
    STARTUP_DIRECTORY = STARTUP_FILE = LEGACY_STARTUP_FILE = None
LINUX_AUTOSTART_FILE = Path.home() / '.config/autostart/DesktopPortal.desktop'


def startup_command():
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        return subprocess.list2cmdline([str(executable), '--background'])
    if executable.name.lower() == 'python.exe':
        windowed = executable.with_name('pythonw.exe')
        if windowed.is_file():
            executable = windowed
    return subprocess.list2cmdline(
        [str(executable), str(BASE_DIR / 'background.py')]
    )


def startup_parts():
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        return executable, ['--background']
    if executable.name.lower() == 'python.exe':
        windowed = executable.with_name('pythonw.exe')
        if windowed.is_file():
            executable = windowed
    return executable, [str(BASE_DIR / 'background.py')]


def _task_result(*arguments, check=False):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(
        ['schtasks.exe', *arguments], check=check, capture_output=True,
        text=True, creationflags=flags,
    )


def _scheduled_task_enabled():
    if platform.system() != 'Windows':
        return False
    return _task_result('/Query', '/TN', TASK_NAME).returncode == 0


def _task_xml():
    executable, arguments = startup_parts()
    sid = _target_user_sid()
    user = sid or os.environ.get('USERNAME', '')
    argument_text = subprocess.list2cmdline(arguments)
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Start DesktopPortal immediately at user logon.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>4</Priority></Settings>
  <Actions Context="Author"><Exec><Command>{escape(str(executable))}</Command><Arguments>{escape(argument_text)}</Arguments><WorkingDirectory>{escape(str(BASE_DIR))}</WorkingDirectory></Exec></Actions>
</Task>'''


def _set_scheduled_task(enabled):
    if enabled:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.xml', encoding='utf-16', delete=False
        ) as file:
            file.write(_task_xml())
            task_file = Path(file.name)
        try:
            result = _task_result(
                '/Create', '/TN', TASK_NAME, '/XML', str(task_file), '/F'
            )
            if result.returncode:
                raise OSError(result.stderr.strip() or result.stdout.strip())
        finally:
            task_file.unlink(missing_ok=True)
    else:
        _task_result('/Delete', '/TN', TASK_NAME, '/F')


def startup_enabled():
    if platform.system() != 'Windows':
        return LINUX_AUTOSTART_FILE.is_file()
    if _scheduled_task_enabled():
        return True
    registry_enabled = False
    try:
        hive, path = _user_key(RUN_KEY)
        with winreg.OpenKey(hive, path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        registry_enabled = True
    except FileNotFoundError:
        pass
    return registry_enabled


def _target_profile():
    value = os.environ.get('USERPROFILE')
    if value:
        return Path(value).resolve()
    return Path(os.environ['APPDATA']).resolve().parents[1]


def _target_user_sid():
    target = str(_target_profile()).casefold()
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PROFILE_LIST_KEY) as profiles:
        index = 0
        while True:
            try:
                sid = winreg.EnumKey(profiles, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(profiles, sid) as profile:
                    path, _ = winreg.QueryValueEx(profile, 'ProfileImagePath')
            except OSError:
                continue
            if str(Path(winreg.ExpandEnvironmentStrings(path)).resolve()).casefold() == target:
                return sid
    return None


def _user_key(relative_path):
    sid = _target_user_sid()
    if sid:
        return winreg.HKEY_USERS, f'{sid}\\{relative_path}'
    return winreg.HKEY_CURRENT_USER, relative_path


def _delete_value(relative_path, name):
    hive, path = _user_key(relative_path)
    try:
        with winreg.OpenKey(
            hive, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        ) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _remove_legacy_registry_entry():
    _delete_value(RUN_KEY, VALUE_NAME)


def _set_registry_startup(enabled):
    if platform.system() != 'Windows':
        return
    hive, path = _user_key(RUN_KEY)
    if enabled:
        with winreg.CreateKeyEx(
            hive, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        ) as key:
            winreg.SetValueEx(
                key, VALUE_NAME, 0, winreg.REG_SZ, startup_command()
            )
        # A previous Task Manager disable action overrides Run/Startup items.
        _delete_value(STARTUP_APPROVED_RUN, VALUE_NAME)
        _delete_value(STARTUP_APPROVED_FOLDER, STARTUP_FILE.name)
    else:
        _remove_legacy_registry_entry()


def set_startup_enabled(enabled):
    if platform.system() != 'Windows':
        if enabled:
            LINUX_AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
            command = startup_command()
            LINUX_AUTOSTART_FILE.write_text(
                '[Desktop Entry]\nType=Application\nName=DesktopPortal\n'
                f'Exec={shlex.join([command]) if " " not in command else command}\n'
                'Terminal=false\nX-GNOME-Autostart-enabled=true\n',
                encoding='utf-8',
            )
        else:
            LINUX_AUTOSTART_FILE.unlink(missing_ok=True)
        return
    _set_scheduled_task(enabled)
    # Remove the older Windows Run entry, which Windows can delay for minutes.
    _set_registry_startup(False)
    # Older fallback launchers caused a terminal window and duplicate starts.
    # The Run entry invokes pythonw directly and needs neither.
    STARTUP_FILE.unlink(missing_ok=True)
    LEGACY_STARTUP_FILE.unlink(missing_ok=True)


def migrate_delayed_startup():
    """Replace an existing Run entry with the immediate logon task once."""
    if platform.system() != 'Windows' or _scheduled_task_enabled():
        return False
    try:
        hive, path = _user_key(RUN_KEY)
        with winreg.OpenKey(hive, path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    set_startup_enabled(True)
    return True
