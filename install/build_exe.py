"""Build Pixal-Setup-<version>-win-x64.exe - the one-file installer.

The EXE is the installer engine plus the committed Pixal tree, and nothing
else. Models, ComfyUI and the node packs are still downloaded on the target
machine, because baking 60 GB of weights into a binary is not a thing.

    .venv\\Scripts\\python.exe install\\build_exe.py

Two rules this script exists to enforce:

1. The payload is `git archive HEAD` and never the working tree. Uncommitted
   files are how config.json - which holds a live API key and the access key -
   would end up inside something handed to a friend. PACKAGING.md has the
   2026-08-14 note about this; a one-file EXE makes the mistake invisible
   rather than merely bad, so the check is a hard failure here.
2. The version comes from PIXAL_VERSION in server.py, so a stale download in
   someone's Downloads folder can always identify itself.
"""
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).absolute().parent
PIXAL = HERE.parent
BUILD = HERE / "_build"
PAYLOAD = BUILD / "pixal-tree.zip"
ICON = PIXAL / "web" / "icons" / "pixal-block.ico"
SECRETS = ("config.json", "history.jsonl", "_lora_titles.json")


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, cwd=PIXAL, **kw)


def version():
    src = (PIXAL / "server.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'PIXAL_VERSION\s*=\s*["\']([^"\']+)["\']', src)
    if not m:
        sys.exit("could not read PIXAL_VERSION from server.py")
    return m.group(1)


def build_payload():
    BUILD.mkdir(parents=True, exist_ok=True)
    if PAYLOAD.exists():
        PAYLOAD.unlink()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=PIXAL,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("\n  Uncommitted changes - they will NOT be in the EXE:")
        for line in dirty.splitlines()[:12]:
            print("   ", line)
        print("  (the payload is `git archive HEAD`, by design)\n")
    run(["git", "archive", "HEAD", "-o", str(PAYLOAD)])

    with zipfile.ZipFile(PAYLOAD) as z:
        names = z.namelist()
    leaked = [n for n in names if Path(n).name in SECRETS]
    if leaked:
        sys.exit(f"REFUSING TO BUILD - secrets in the payload: {leaked}")
    if "install/pixal_install.py" not in names:
        sys.exit("payload has no install/pixal_install.py - wrong tree?")
    print(f"  payload: {len(names)} files, "
          f"{PAYLOAD.stat().st_size / 1e6:.1f} MB, no secrets")


def main():
    ver = version()
    name = f"Pixal-Setup-{ver}-win-x64"
    print(f"Building {name}.exe")
    build_payload()

    # --noconsole because a console window behind the UI is the single loudest
    # "this is somebody's script" tell. It is only safe because every run now
    # writes install/_work/install-<date>.log, and because the three ways this
    # can fail before there is a UI - no port, no window, no browser - all end
    # in a MessageBox rather than silence.
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole",
           "--name", name,
           "--distpath", str(BUILD / "dist"),
           "--workpath", str(BUILD / "work"),
           "--specpath", str(BUILD),
           "--add-data", f"{PAYLOAD};.",
           "--collect-all", "webview",           # WebView2 loader + its DLLs
           "--noconfirm", "--clean",
           str(HERE / "pixal_install.py")]
    if ICON.is_file():
        cmd[3:3] = ["--icon", str(ICON)]
    run(cmd)

    exe = BUILD / "dist" / f"{name}.exe"
    if not exe.is_file():
        sys.exit("PyInstaller produced no exe")
    out = PIXAL / exe.name
    shutil.copy2(exe, out)
    import hashlib
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"\n  {out}")
    print(f"  {out.stat().st_size / 1e6:.1f} MB")
    print(f"  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
