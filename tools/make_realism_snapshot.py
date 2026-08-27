"""One-shot: capture today's default build_realism graph as the 9.57 snapshot.

Run with `py -3 tools/make_realism_snapshot.py` from the repo root, against
PRE-CHANGE server.py. The snapshot pins "no negative -> byte-identical graph"
for the test suite; it is data, regenerated never - if the builder's default
graph ever legitimately changes, this file is regenerated the same way.
"""
import json
import sys
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("pixal_server", ROOT / "server.py")
server = module_from_spec(spec)
sys.modules["pixal_server"] = server
spec.loader.exec_module(server)

ENTRY = {"rel": "Krea 2\\phone test.safetensors", "kind": "diffusion_models",
         "family": "krea2", "variant": "any", "supported": True}

with ExitStack() as stack:
    stack.enter_context(patch.object(server, "resolve_model_entry", return_value=ENTRY))
    stack.enter_context(patch.object(server, "_catalog_has", return_value=True))
    stack.enter_context(patch.object(server, "_catalog_resolve",
                                     side_effect=lambda kind, rel: rel))
    stack.enter_context(patch.object(server, "resolve_lora", side_effect=lambda name: name))
    graph, cap, _info = server.build_realism("a portrait", 1, model=ENTRY["rel"])

out = ROOT / "tests" / "snapshots" / "realism_default.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"caption": cap, "graph": graph},
                          ensure_ascii=False, indent=1, sort_keys=True) + "\n",
               encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size} bytes)")
