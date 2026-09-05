"""Read-only options parity harness; never contacts or controls a live service."""
import json
import os
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def capture():
    def forbidden(*args, **kwargs):
        raise PermissionError("10.14 read-only harness: resource action forbidden")

    # Legacy Hub construction creates chats. Suppress directory creation and
    # reject file mutations (its best-effort chat writes already catch OSError).
    with ExitStack() as stack:
        stack.enter_context(patch("pathlib.Path.mkdir", return_value=None))
        stack.enter_context(patch("tempfile.gettempdir", return_value=os.environ["TEMP"]))
        for target in ("pathlib.Path.write_text", "pathlib.Path.write_bytes",
                       "pathlib.Path.replace", "pathlib.Path.rename", "pathlib.Path.unlink",
                       "subprocess.Popen", "subprocess.run", "socket.socket.connect",
                       "socket.socket.connect_ex", "aiohttp.ClientSession",
                       "asyncio.create_task", "threading.Thread.start"):
            stack.enter_context(patch(target, side_effect=forbidden))
        import server
        server.apply_comfy_root(server.load_config()["comfy_root"])
        return json.dumps(server.HUB.options(), sort_keys=True)


if __name__ == "__main__":
    destination = (ROOT / sys.argv[1]).resolve()
    allowed = (ROOT / "briefs/10.14-options-baseline.json").resolve()
    if destination != allowed:
        raise SystemExit("Only the brief's baseline file may be written")

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            writing = (flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing and (not isinstance(path, (str, bytes)) or Path(os.fsdecode(path)).resolve() != allowed):
                raise PermissionError("10.14 harness: write forbidden")
        if event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "subprocess.Popen", "os.kill", "os.system", "socket.connect"):
            raise PermissionError("10.14 harness: mutation/network/process forbidden")

    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    result = capture()
    if "--compare" in sys.argv:
        baseline = json.loads(destination.read_text(encoding="utf-8"))
        current = json.loads(result)
        differences = []
        def compare(a, b, path="$", normalize=False):
            if isinstance(a, dict) and isinstance(b, dict):
                for key in sorted(a.keys() | b.keys()):
                    if normalize and key in ("is_new", "mtime", "mtime_ns"):
                        continue
                    if key not in a or key not in b:
                        differences.append(path + "." + key)
                    else:
                        compare(a[key], b[key], path + "." + key, normalize)
            elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                for i, (left, right) in enumerate(zip(a, b)):
                    compare(left, right, f"{path}[{i}]", normalize)
            elif a != b:
                differences.append(path)
        compare(baseline, current)
        print(f"Raw differing paths: {len(differences)}")
        print("\n".join(differences[:30]))
        differences.clear()
        compare(baseline, current, normalize=True)
        print(f"Differences excluding is_new and mtimes: {len(differences)}")
        print("\n".join(differences[:30]))
        if differences:
            raise SystemExit(1)
    else:
        if destination.exists():
            raise SystemExit("Baseline already exists; use --compare")
        destination.write_text(result + "\n", encoding="utf-8")
        print(f"Captured {len(result)} characters")

