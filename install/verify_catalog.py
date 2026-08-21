"""Catalog verifier - every URL and byte count in catalog.json, checked live.

The installer trusts catalog.json blindly: 25 GB of weights behind a size
check, node packs behind a branch name. This script is the other half of that
trust. It walks the same catalog the installer reads and asks the network,
for every entry, "is this still true?" - one honest line per check, non-zero
exit on any red line.

Nothing here downloads a model. Sizes come from response headers (a ranged
GET of the first byte, HEAD where the CDN prefers it), hashes are trusted
from the HuggingFace API that put them in the catalog, and pack refs are
resolved through the GitHub API. A full run moves a few kilobytes.

Stdlib only, like the installer itself - this may run on the same freshly
unzipped embeddable python.

Run it:  python install/verify_catalog.py          (human-readable)
         python install/verify_catalog.py --json   (machine-readable, for CI)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).absolute().parent
CATALOG = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "pixal-installer/1.0"}   # same UA the engine sends

HF = "https://huggingface.co/{repo}/resolve/main/{path}"       # engine line 78
ZIPBALL = "https://codeload.github.com/{repo}/zip/{ref}"
# ^ the generic codeload shape: /zip/{ref} takes a branch, a tag, or a raw
# commit SHA, so this check survives the day packs.*.branch becomes a pin.
# install_pack() today fetches /zip/refs/heads/{branch} - the same zipball
# while branch holds a branch name.

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMEOUT = 30


class Check:
    """One line of the report. ok=False paints the whole run red."""

    def __init__(self, group, target):
        self.group = group
        self.target = target
        self.ok = False
        self.detail = ""

    def line(self):
        mark = "ok  " if self.ok else "FAIL"
        return f"{mark} {self.group:10s} {self.target:52s} {self.detail}"


def _open(url, headers, method=None, attempts=2):
    """Status and headers only; the body is never read. One retry for the
    kind of connection error a second attempt actually fixes - a verifier
    that cries wolf on wifi jitter teaches people to ignore it."""
    last = None
    for _ in range(attempts):
        try:
            req = Request(url, headers={**UA, **headers}, method=method)
            r = urlopen(req, timeout=TIMEOUT)
            status, hdrs = r.status, r.headers
            r.close()
            return status, hdrs
        except HTTPError as e:
            return e.code, e.headers
        except (URLError, OSError) as e:
            last = e
    raise last


def ranged_size(url):
    """Remote size without the content. A ranged GET of the first byte: 206
    carries the total in Content-Range, a 200 (range ignored) carries it in
    Content-Length - the body that follows is never read. HEAD is the
    fallback for servers that reject ranges outright."""
    status, hdrs = _open(url, {"Range": "bytes=0-0"})
    if status == 206 and hdrs.get("Content-Range"):
        m = re.match(r"bytes \d+-\d+/(\d+)", hdrs["Content-Range"])
        if m:
            return status, int(m.group(1))
    if status == 200 and hdrs.get("Content-Length") is not None:
        return status, int(hdrs["Content-Length"])
    if status in (200, 206):
        return status, None               # answered, but said nothing about size
    status, hdrs = _open(url, {}, method="HEAD")
    if status == 200 and hdrs.get("Content-Length") is not None:
        return status, int(hdrs["Content-Length"])
    return status, None


def check_url_size(group, target, url, want_bytes, sha):
    """The shared shape of every file check: answers, right size, real hash."""
    c = Check(group, target)
    try:
        status, size = ranged_size(url)
    except (URLError, OSError) as e:
        c.detail = f"connection: {e}"
        return c
    if status not in (200, 206):
        c.detail = f"HTTP {status} on ranged GET"
    elif size != want_bytes:
        c.detail = f"size drift: catalog {want_bytes}, remote {size}"
    elif not SHA256_RE.match(sha or ""):
        c.detail = "sha256 missing or not 64 hex"
    else:
        c.ok = True
        c.detail = f"{status}, {size} bytes, sha256 {sha[:12]}…"
    return c


def main():
    ap = argparse.ArgumentParser(
        description="Verify install/catalog.json against the live network.")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable results")
    args = ap.parse_args()

    checks = []

    # -- lane files: URL answers, size matches, sha256 present and 64 hex -- #
    for lane in CATALOG["lanes"]:
        for f in lane["files"]:
            url = HF.format(repo=f["repo"], path=f["path"])
            checks.append(check_url_size(
                lane["id"], f["path"].rsplit("/", 1)[-1],
                url, f["bytes"], f.get("sha256")))

    # -- ComfyUI release asset: resolves at the recorded size -------------- #
    cu = CATALOG["comfyui"]
    checks.append(check_url_size(
        "comfyui", cu["asset"],
        cu["url"].format(tag=cu["pin"], asset=cu["asset"]),
        cu["asset_bytes"], cu.get("asset_sha256")))

    # -- packs: ref resolves via the API, zipball answers 200 -------------- #
    for name, spec in CATALOG["packs"].items():
        ref = spec["branch"]

        c = Check("packs", f"{name} ref")
        checks.append(c)
        try:
            status, _ = _open(
                f"https://api.github.com/repos/{spec['repo']}/commits/{ref}", {})
            if status == 200:
                c.ok, c.detail = True, "resolves via github api"
            else:
                c.detail = f"github api HTTP {status} for ref {ref!r}"
        except (URLError, OSError) as e:
            c.detail = f"github api: {e}"

        c = Check("packs", f"{name} zipball")
        checks.append(c)
        try:
            status, _ = _open(ZIPBALL.format(repo=spec["repo"], ref=ref), {})
            if status == 200:
                c.ok = True
                c.detail = f"200 from codeload /zip/{ref[:12]}"
            else:
                c.detail = f"codeload HTTP {status}"
        except (URLError, OSError) as e:
            c.detail = f"codeload: {e}"

    # manual lane: no remote URLs by definition (Civitai, login-gated) -
    # there is nothing to check, and the report says so rather than imply it.
    notes = [f"note manual     {m['id']:52s} no remote URLs, skipped"
             for m in CATALOG.get("manual", [])]

    failed = [c for c in checks if not c.ok]
    if args.json:
        print(json.dumps({
            "ok": not failed,
            "checks": [{"group": c.group, "target": c.target,
                        "ok": c.ok, "detail": c.detail} for c in checks],
            "skipped": [m["id"] for m in CATALOG.get("manual", [])],
            "summary": {"total": len(checks), "failed": len(failed)},
        }, indent=2))
    else:
        for c in checks:
            print(c.line())
        for n in notes:
            print(n)
        print(f"\n{len(checks) - len(failed)}/{len(checks)} checks green"
              + (f" - {len(failed)} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
