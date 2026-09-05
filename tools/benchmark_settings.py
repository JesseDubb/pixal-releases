"""Opt-in synthetic settings benchmark; never touches the running studio.

Compare the old and extracted handlers using the same atomic config store and
the same temporary model tree. Measures save + next catalog read, without HTTP
transport, engine requests or real weights. Requires the private baseline commit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


async def measure(handler, catalog, entries, samples):
    times = []
    for i in range(samples):
        async def body():
            return {"still": {"film_grain": bool(i % 2)}}
        start = time.perf_counter()
        response = await handler(SimpleNamespace(json=body))
        assert response.status == 200
        assert len(catalog()) == entries
        times.append((time.perf_counter() - start) * 1000)
    ordered = sorted(times)
    return {"samples": samples, "median_ms": round(statistics.median(times), 3),
            "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=11)
    args = parser.parse_args()
    if not 1 <= args.models <= 10000 or not 3 <= args.samples <= 100:
        parser.error("Use 1..10000 models and 3..100 samples")
    sys.path.insert(0, str(ROOT))
    from tools.capture_settings_contracts import BASELINE, baseline_handler

    with tempfile.TemporaryDirectory(prefix="pixal-settings-benchmark-") as temporary:
        root = Path(temporary)
        data, engine = root / "data", root / "ComfyUI"
        data.mkdir()
        models = engine / "models"
        weights = models / "diffusion_models"
        weights.mkdir(parents=True)
        for name in ("input", "output"):
            (engine / name).mkdir()
        for i in range(args.models):
            (weights / f"synthetic-{i:05}.safetensors").touch()
        with patch.dict(os.environ, {"PIXAL_DATA_DIR": str(data), "PIXAL_COMFY_DIR": str(engine),
                                      "MOONSHOT_API_KEY": ""}):
            import server
            assert server.DATA_DIR == data and server.CDIR == engine
            server.save_config(server._config_defaults())
            namespace = dict(vars(server))
            exec(baseline_handler(), namespace)
            results = {}
            with patch.object(server, "model_roots", return_value=[models]):
                for name, handler in (("baseline", namespace["settings_post"]),
                                      ("extracted", server.settings_post)):
                    server._CATALOG.update(at=0, data=None)
                    assert len(server.model_catalog()) == args.models  # warm, outside timing
                    results[name] = asyncio.run(measure(handler, server.model_catalog,
                                                        args.models, args.samples))
            print(json.dumps({"baseline_commit": BASELINE, "synthetic_model_files": args.models,
                              "operation": "atomic settings save + warm catalog read",
                              "results": results}, indent=2))


if __name__ == "__main__":
    main()
