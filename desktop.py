"""Windowed executable entry point with a useful error dialog and persistent log."""
import ctypes
import os
from pathlib import Path
import sys
import traceback


def run():
    folder = Path(os.environ.get('PLANEPLANE_HOME') or Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PlanePlane')
    folder.mkdir(parents=True,exist_ok=True)
    log_path=folder/'game.log'
    log=log_path.open('w',encoding='utf-8',buffering=1)
    if sys.stdout is None:
        sys.stdout=log
    if sys.stderr is None:
        sys.stderr=log
    try:
        from main import main
        main()
    except KeyboardInterrupt:
        return 0
    except BaseException as error:
        if isinstance(error,SystemExit) and error.code in (None,0):
            return 0
        traceback.print_exc(file=log)
        message=f'{error}\n\nDetails were saved to:\n{log_path}'
        # Automated/headless runs report via exit code and log, without blocking on a dialog.
        if '--headless' not in sys.argv and '--frames' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,message,'Plane² could not start',0x10)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(run())
