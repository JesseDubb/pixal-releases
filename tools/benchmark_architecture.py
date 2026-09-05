"""Synthetic foundation measurements; no live settings, engines or downloads.

Not a render/startup benchmark. Report medians and p95 across small repeated
samples on temporary storage. Import timing means a fresh Python interpreter
with a warm filesystem, not desktop readiness or engine/model loading.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pixal.app import create_app
from pixal.config.rules import default_config
from pixal.config.store import ConfigStore
from pixal.http.routes import HANDLER_NAMES
from pixal.paths import RuntimePaths


def measure(operation, samples=9, iterations=40):
    values = []
    for _ in range(samples):
        started = time.perf_counter()
        for _ in range(iterations):
            operation()
        values.append((time.perf_counter() - started) * 1000 / iterations)
    return summarize(values)


def summarize(values):
    ordered = sorted(values)
    return {"median_ms": round(statistics.median(values), 4),
            "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 4),
            "samples": len(values)}


def defaults():
    return default_config(kimi_url="https://api.moonshot.ai/v1/chat/completions", kimi_model="kimi-k3",
                          api_key="", image_mode="model", image_vsr_mode="VSR Ultra", video_mode="VSR High")


def legacy_loader(path):
    # Only the reviewed configuration function, not an import of the old server.
    source = subprocess.check_output(["git", "show", "5ab6aae:server.py"], cwd=ROOT).decode("utf-8")
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == "load_config")
    namespace = {"CONFIG": path, "json": json, "os": SimpleNamespace(environ={}),
                 "KIMI_URL": "https://api.moonshot.ai/v1/chat/completions", "KIMI_MODEL": "kimi-k3",
                 "UPSCALE_IMAGE_DEFAULT_MODE": "model", "UPSCALE_IMAGE_DEFAULT_VSR_MODE": "VSR Ultra",
                 "UPSCALE_VIDEO_DEFAULT_MODE": "VSR High"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<baseline config>", "exec"), namespace)
    return namespace["load_config"]


async def run():
    with tempfile.TemporaryDirectory(prefix="pixal-benchmark-") as tmp:
        root = Path(tmp)
        path = root / "config.json"
        store = ConfigStore(path)
        store.save(defaults())
        result = {"environment": {"platform": platform.platform(), "python": platform.python_version(),
                                   "aiohttp": importlib.metadata.version("aiohttp"),
                                   "logical_cpus": os.cpu_count()},
                  "scope": "Synthetic configuration and HTTP construction; no engine/model readiness or render timing",
                  "baseline_config_ref": "5ab6aae",
                  "config_read_baseline": measure(legacy_loader(path)),
                  "config_read_extracted": measure(lambda: store.load(defaults)),
                  "config_atomic_save": measure(lambda: store.save(defaults()), iterations=3)}
        async def handler(request):
            raise AssertionError("Benchmark construction must not handle requests")
        handlers = dict.fromkeys(HANDLER_NAMES, handler)
        paths = RuntimePaths(ROOT, root, root / "engine")
        result["http_construction"] = measure(lambda: create_app(
            paths=paths, handlers=handlers, client_max_size=1024), iterations=10)
        env = {**os.environ, "PIXAL_DATA_DIR": str(root), "PIXAL_COMFY_DIR": str(root / "engine"),
               "MOONSHOT_API_KEY": ""}
        code = "import time; t=time.perf_counter(); import server; print((time.perf_counter()-t)*1000)"
        imports = []
        for _ in range(5):
            response = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env,
                                      capture_output=True, text=True, check=True, timeout=30)
            imports.append(float(response.stdout.strip().splitlines()[-1]))
        result["fresh_interpreter_import_warm_filesystem"] = summarize(imports)
        result["import_cache_note"] = "Existing bytecode is read if current; stale bytecode triggers compilation. Not a startup budget."
        result["bundle_bytes"] = (ROOT / "web/app.js").stat().st_size
        result["server_lines"] = len((ROOT / "server.py").read_text(encoding="utf-8").splitlines())
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
