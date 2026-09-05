"""Build Pixal-Setup-<version>-win-x64.exe with Inno Setup.

    .venv\\Scripts\\python.exe install\\build_installer.py

A normal Windows installer, because that is what people recognise: a small
wizard, a progress bar, Add/Remove Programs, a real uninstaller, no admin
prompt. Inno Setup does all of that and is the boring standard choice.

What gets staged into the package:

  the committed tree      `git archive HEAD` - never the working tree, so an
                          uncommitted config.json (live API key, access key)
                          cannot ride along. Hard-fails if one appears.
  install\\runtime         python.org's embeddable build, so the target machine
                          needs nothing preinstalled and no console flashes
                          while something bootstraps.
  Pixal.exe               a small launcher whose only jobs are owning the icon
                          and choosing between "open Pixal" and "--setup".

ComfyUI, the node packs and ~60 GB of weights are NOT in here. They are
downloaded afterwards by the setup engine, which resumes and can be re-run.
An installer that sits for an hour is not an installer.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).absolute().parent
PIXAL = HERE.parent
BUILD = HERE / "_build"
STAGE = BUILD / "stage"
ICON = PIXAL / "web" / "icons" / "pixal-block.ico"
SECRETS = ("config.json", "history.jsonl", "_lora_titles.json")


def is_secret_path(path):
    """Include config backups and interrupted atomic writes, not just the primary file."""
    name = Path(path).name
    return (name in SECRETS or name.startswith("config.json.")
            or name.startswith(".config.json."))

# Committed but internal - planning briefs, working docs, the marketing site,
# brand experiments. No secrets in them, but an installer anyone can unzip is a
# publication, and these were never written for one.
#
# THIS IS THE ONE PRUNE LIST. `release.py` imports it for the public source zip
# and the tree it publishes to pixal-releases, so the installer and the public
# repo cannot disagree about what "internal" means. It lives HERE rather than in
# release.py because release.py is itself pruned: a stranger who clones the
# published source still has this file and can still build the installer.
#
# It used to be two lists, and they drifted (found 2026-09-02, cutting 1.2.0b).
# release.py's copy grew RELEASING.md, release.py, MORNING.md, DESIGN.md,
# PORTING.md and the agent-skill folders; this one never did - so every 1.1.x
# installer shipped Pixal's release runbook and the Netlify site id inside it.
# Nothing looked wrong, because the public source tree was correct.
#
# If you add a working note to the repo root, add it HERE, or the next release
# publishes it - twice.
INTERNAL = ("briefs", "docs", "site", "brand", ".github",
            "SOL_PLAN.md", "PRODUCT_NOTES.md", "pixal-dm-ssot.md",
            "scratch_prompt.txt", "PACKAGING.md", "MORNING.md",
            # Names the Netlify site id in prose; release.py carries it in code.
            "RELEASING.md", "release.py",
            "DESIGN.md", "PORTING.md",
            # Superseded landing-page drafts (v2/v3/v4). They sit outside the
            # deployed `site/` folder so nothing serves them, but they still
            # advertise a 1.0.0b download link, and they rode both publications
            # as dead weight until 1.2.0b.
            "site-archive",
            # Installed agent skills (transitions.dev) are third-party docs for
            # the tooling, not Pixal - they go to neither publication.
            ".agents", ".claude", "skills-lock.json")

PY_VER = "3.12.10"
PY_ZIP = f"python-{PY_VER}-embed-amd64.zip"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/{PY_ZIP}"

ISCC = next((p for p in (
    Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
) if p.is_file()), None)


def run(cmd, cwd=PIXAL):
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=cwd)


def version():
    src = (PIXAL / "server.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'PIXAL_VERSION\s*=\s*["\']([^"\']+)["\']', src)
    if not m:
        sys.exit("could not read PIXAL_VERSION from server.py")
    return m.group(1)


def stage_tree():
    """The committed tree, and nothing that is merely lying around."""
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    tar = BUILD / "tree.zip"
    if tar.exists():
        tar.unlink()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=PIXAL,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("\n  Uncommitted - will NOT be in the installer:")
        for line in dirty.splitlines()[:12]:
            print("   ", line)
        print()
    run(["git", "archive", "HEAD", "-o", str(tar)])
    with zipfile.ZipFile(tar) as z:
        names = z.namelist()
        leaked = [n for n in names if is_secret_path(n)]
        if leaked:
            sys.exit(f"REFUSING TO BUILD - secrets in the package: {leaked}")
        z.extractall(STAGE)
    tar.unlink()
    kept = len(names)
    for entry in INTERNAL:
        victim = STAGE / entry
        if victim.is_dir():
            kept -= sum(1 for p in victim.rglob("*") if p.is_file())
            shutil.rmtree(victim)
        elif victim.is_file():
            kept -= 1
            victim.unlink()
    print(f"  tree: {kept} files, no secrets, internal docs pruned")


def stage_runtime():
    """python.org's embeddable build, with site-packages switched on.

    The shipped ._pth deliberately disables `import site`, which also disables
    pip - and the setup engine has to be able to pip install four packages. One
    uncommented line is the documented way to turn it back on."""
    cache = BUILD / PY_ZIP
    if not cache.is_file():
        print(f"  downloading {PY_ZIP}")
        BUILD.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PY_URL, timeout=120) as r, \
                open(cache, "wb") as f:
            shutil.copyfileobj(r, f)
    rt = STAGE / "install" / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache) as z:
        z.extractall(rt)
    for pth in rt.glob("python*._pth"):
        text = pth.read_text(encoding="utf-8")
        lines = text.splitlines()
        for entry in (r"..\..", "import site"):
            if entry not in lines:
                lines.append(entry)
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not (rt / "pythonw.exe").is_file():
        sys.exit("embeddable python has no pythonw.exe - wrong archive?")
    print(f"  runtime: python {PY_VER} embeddable, site enabled")


def gen_wizard_art():
    """The wizard's left panel and header mark, from the brand renders.

    Inno wants BMP at fixed sizes and one file per DPI step, which is a silly
    thing to keep ten of in the repo - so they are generated, and install/wizard
    is gitignored. Stock Inno artwork is a cardboard box and a CD, which is the
    single loudest tell that nobody looked at the installer."""
    from PIL import Image, ImageEnhance, ImageFilter
    art = HERE / "wizard"
    art.mkdir(parents=True, exist_ok=True)

    def retro(im):
        """Grade + a light unsharp, applied at FINAL size, full 24-bit color.

        This used to Floyd-Steinberg down to 64 colors; on a scaled display
        the wizard draws the @150/@175 panel large enough that the grain read
        as banding, not texture (Jesse, 2026-08-20: "why does this look so
        terrible?"). Inno's constraint is BMP at fixed sizes - not bit depth -
        so the render ships at full color. The unsharp answers the original
        worry (a photo shrunk this far goes muddy) without costing gradients."""
        im = ImageEnhance.Color(im).enhance(1.12)
        im = ImageEnhance.Contrast(im).enhance(1.06)
        return im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))

    def fit(src, w, h, dest, pad=False, treat=False):
        """pad=False crops to fill; pad=True scales the whole image in and fills
        the rest with its own background tone.

        The wizard panel is 164x314 - very nearly 1:2 - and the source art is
        roughly 3:4, so cropping to fill throws away a third of the width and
        takes the subject's arms with it. Scaling the whole frame in and padding
        keeps the composition; sampling the pad colour from the image's own
        corners means the seam does not read as a letterbox."""
        im = Image.open(src).convert("RGB")
        sw, sh = im.size
        if not pad:
            want = w / h
            if sw / sh > want:                   # too wide - take the middle
                nw = int(sh * want)
                im = im.crop(((sw - nw) // 2, 0, (sw + nw) // 2, sh))
            else:                                # too tall - bias up
                nh = int(sw / want)
                top = int((sh - nh) * 0.30)
                im = im.crop((0, top, sw, top + nh))
            im = im.resize((w, h), Image.LANCZOS)
            if treat:
                im = retro(im)
            im.save(dest, "BMP")
            return
        scale = min(w / sw, h / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        small = im.resize((nw, nh), Image.LANCZOS)
        top_strip = im.crop((0, 0, sw, max(1, sh // 24))).resize((1, 1), Image.LANCZOS)
        bot_strip = im.crop((0, sh - max(1, sh // 24), sw, sh)).resize((1, 1), Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), top_strip.getpixel((0, 0)))
        y = (h - nh) // 2
        if y + nh < h:                           # bottom band matches the floor
            canvas.paste(Image.new("RGB", (w, h - (y + nh)),
                                   bot_strip.getpixel((0, 0))), (0, y + nh))
        canvas.paste(small, ((w - nw) // 2, y))
        canvas.save(dest, "BMP")

    panel = PIXAL / "brand" / "installer-panel.png"
    mark = PIXAL / "web" / "icons" / "block-512.png"
    if not panel.is_file() or not mark.is_file():
        print("  wizard art: brand art missing, falling back to Inno defaults")
        return False
    # Big left panel (Welcome and Finish): the render, edge to edge, cropped to
    # fill - never padded. Header thumbnail on the interior pages: solid white.
    # Inno insists on drawing a small image there (omitting the setting gets
    # its cardboard-box default), and the chartreuse tile fought the header
    # band (Jesse, 2026-08-19: remove it or make the square white) - white is
    # the only way to have nothing there.
    for w, h, sfx in ((164,314,""), (192,386,"@125"), (246,459,"@150"),
                      (273,556,"@175"), (328,628,"@200")):
        fit(panel, w, h, art / f"wizard{sfx}.bmp", treat=True)
    for w, h, sfx in ((55,58,""), (64,68,"@125"), (83,80,"@150"),
                      (92,97,"@175"), (110,116,"@200")):
        Image.new("RGB", (w, h), (255, 255, 255)).save(
            art / f"wizard-small{sfx}.bmp", "BMP")
    print(f"  wizard art: panel from {panel.name}, header mark blanked white")
    return True


def gen_components():
    """Turn catalog.json into the wizard's Select Components page.

    Generated rather than hand-written so the page and the catalog cannot drift:
    a lane added to the catalog appears as a checkbox with the right size, and
    one removed stops being offered. Also emits LaneIds() so the [Code] section
    can ask which boxes are ticked without a second copy of the id list."""
    cat = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    out = [";  GENERATED by build_installer.py from catalog.json - do not edit",
           "", "[Types]",
           'Name: "full";        Description: "Everything (recommended)"',
           'Name: "compact";     Description: "Just the recommended lanes"',
           'Name: "custom";      Description: "Choose what to download"; Flags: iscustom',
           "", "[Components]"]
    ids = []
    for lane in cat["lanes"]:
        lid = lane["id"]
        ids.append(lid)
        size = sum(f["bytes"] for f in lane.get("files", []))
        gb = size / (1 << 30)
        desc = lane["name"].replace('"', "'")
        if gb >= 0.05:
            desc = f"{desc}  ({gb:.1f} GB)"
        types = "full custom"
        if lane.get("recommended"):
            types = "full compact custom"
        # Models can live on another drive and may already exist. The engine's
        # destination-aware preflight owns their space check, not Inno's app disk.
        out.append(f'Name: "{lid}"; Description: "{desc}"; Types: {types}')
    out += ["", "[Code]",
            "{ Lane ids, in catalog order. Generated - see build_installer.py }",
            "function LaneIds: TArrayOfString;", "begin",
            "  Result := [" + ", ".join(f"'{i}'" for i in ids) + "];",
            "end;", ""]
    out += ["function ResolveLaneSelection(Selection: String): String;",
            "var Pass: Integer;", "begin",
            f"  for Pass := 1 to {len(ids)} do begin"]
    for lane in cat["lanes"]:
        for dependency in lane.get("requires", []):
            if dependency not in ids:
                raise ValueError(f"Unknown lane prerequisite: {dependency}")
            out += [f"    if (Pos(',{lane['id']},', ',' + Selection + ',') > 0) and",
                    f"       (Pos(',{dependency},', ',' + Selection + ',') = 0) then",
                    f"      Selection := Selection + ',{dependency}';"]
    out += ["  end;", "  Result := Selection;", "end;", ""]
    dest = BUILD / "components.iss"
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"  components: {len(ids)} lanes -> {dest.name}")


def stage_launcher():
    """Pixal.exe - small, windowless, carries the icon."""
    out = BUILD / "launcher"
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole",
           "--name", "Pixal",
           "--distpath", str(out), "--workpath", str(BUILD / "lwork"),
           "--specpath", str(BUILD), "--noconfirm", "--clean"]
    if ICON.is_file():
        cmd += ["--icon", str(ICON)]
    cmd.append(str(HERE / "pixal_launch.py"))
    run(cmd)
    exe = out / "Pixal.exe"
    if not exe.is_file():
        sys.exit("launcher build produced no Pixal.exe")
    shutil.copy2(exe, STAGE / "Pixal.exe")
    print(f"  launcher: Pixal.exe {exe.stat().st_size / 1e6:.1f} MB")


def compile_setup(ver):
    if ISCC is None:
        sys.exit("Inno Setup not found. winget install JRSoftware.InnoSetup")
    run([str(ISCC), f"/DMyVersion={ver}", f"/DMyStage={STAGE}",
         str(HERE / "pixal.iss")], cwd=HERE)


def main():
    ver = version()
    print(f"Building Pixal-Setup-{ver}-win-x64.exe (Inno Setup)")
    stage_tree()
    stage_runtime()
    gen_wizard_art()
    gen_components()
    stage_launcher()
    compile_setup(ver)
    out = PIXAL / f"Pixal-Setup-{ver}-win-x64.exe"
    if not out.is_file():
        sys.exit("ISCC produced no installer")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"\n  {out}")
    print(f"  {out.stat().st_size / 1e6:.1f} MB")
    print(f"  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
