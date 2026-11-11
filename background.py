"""Windows-startup entry point: run DesktopPortal without showing its window."""
import os
import time
import traceback
from datetime import datetime

from packs import BASE_DIR
from startup import migrate_delayed_startup

LOG_FILE = BASE_DIR / 'data/background.log'
MAX_LOG_BYTES = 256 * 1024


def log(message):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
        lines = LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()
        LOG_FILE.write_text('\n'.join(lines[-200:]) + '\n', encoding='utf-8')
    with LOG_FILE.open('a', encoding='utf-8') as file:
        file.write(f'{datetime.now().isoformat(timespec="seconds")} {message}\n')


if __name__ == '__main__':
    started = time.perf_counter()
    log(f'start requested (pid={os.getpid()})')
    try:
        migrate_delayed_startup()
        from main import main
        main(
            start_hidden=True,
            on_ready=lambda: log(
                f'background ready in {time.perf_counter() - started:.3f}s'
            ),
        )
    except BaseException:
        log('startup failed:\n' + traceback.format_exc())
        raise
    else:
        log('background process exited')
