"""Pixal.exe - the thing the Start Menu and the desktop point at.

Deliberately tiny. It exists for two reasons and no others:

  1. An icon. A shortcut can carry a custom icon, but the taskbar and Alt-Tab
     entry belong to whatever process owns the window - so a shortcut to
     pythonw.exe is a python icon no matter what the .lnk says. A real exe with
     pixal-block.ico compiled in is the only way to fix that.
  2. A verb. No arguments means "open Pixal" and hands straight to pixal.vbs,
     which already owns the whole boot discipline - spawn lock, sidecar
     logging, the Chrome app window. --setup means "add or repair ComfyUI and
     models" and runs the setup engine.

It does not reimplement either path. Anything clever belongs in pixal.vbs or
pixal_install.py, where it is already tested.
"""
import os
import subprocess
import sys
from pathlib import Path

APP = Path(getattr(sys, "_MEIPASS", "")).parent if getattr(sys, "frozen", False) \
      else Path(__file__).absolute().parent.parent
if getattr(sys, "frozen", False):
    APP = Path(sys.executable).absolute().parent      # {app}, beside Pixal.exe

CREATE_NO_WINDOW = 0x08000000


def alert(text, title="Pixal"):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        print(text)


def runtime_python(windowed=True):
    """The interpreter the setup engine runs on.

    The installer ships one (install\\runtime) so a machine with no python at
    all still works; anything already on the box is only a fallback, because
    the shipped one is the version this was tested against."""
    name = "pythonw.exe" if windowed else "python.exe"
    shipped = APP / "install" / "runtime" / name
    if shipped.is_file():
        return shipped
    venv = APP / ".venv" / "Scripts" / name
    if venv.is_file():
        return venv
    from shutil import which
    found = which(name) or which("python.exe")
    return Path(found) if found else None


def setup():
    engine = APP / "install" / "pixal_install.py"
    if not engine.is_file():
        alert(f"Pixal Setup is missing:\n\n{engine}\n\nReinstall Pixal.")
        return 1
    py = runtime_python()
    if py is None:
        alert("Could not find a python to run Pixal Setup on.\n\n"
              "Reinstall Pixal - the installer ships one.")
        return 1
    subprocess.Popen([str(py), str(engine)], cwd=str(APP),
                     creationflags=CREATE_NO_WINDOW)
    return 0


def open_app():
    vbs = APP / "pixal.vbs"
    if not vbs.is_file():
        alert(f"Pixal is missing:\n\n{vbs}\n\nReinstall Pixal.")
        return 1
    wscript = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
    try:
        subprocess.Popen([str(wscript), str(vbs)], cwd=str(APP),
                         creationflags=CREATE_NO_WINDOW)
    except Exception as exc:
        alert(f"Could not start Pixal.\n\n{type(exc).__name__}: {exc}")
        return 1
    return 0


def main():
    argv = [a.lower() for a in sys.argv[1:]]
    if "--setup" in argv or "/setup" in argv:
        return setup()
    return open_app()


if __name__ == "__main__":
    sys.exit(main())
