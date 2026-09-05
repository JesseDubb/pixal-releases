r"""One verification gate for local work, CI and release preflight.

Use the project's interpreter: .venv\Scripts\python.exe tools/verify.py
Browser/real-engine tests remain explicitly opt-in; this command does not
start the application or publish a release.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verification_commands(*, build: bool = False) -> list[list[str]]:
    web = ["node", "tools/build_web.mjs"]
    if not build:
        web.append("--check")
    javascript = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_*.mjs"))
    if not javascript:
        raise RuntimeError("No JavaScript tests were discovered")
    return [web, [sys.executable, "-m", "pytest", "tests/", "-q"],
            ["node", "--test", *javascript]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="rebuild frontend before verification")
    args = parser.parse_args()
    for command in verification_commands(build=args.build):
        print("Running: " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
