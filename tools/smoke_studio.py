"""Opt-in, local studio smoke tests. Never included in the normal test gate.

Requires an explicitly approved idle desktop. Uses a separate chat, real HTTP
handlers and installed models. No settings changes, downloads, automatic POST
retries, deletion, process killing or release actions. Outputs remain in history.
Run one step at a time and inspect its result. `restore` returns to the original
chat only if the test chat is still selected; it never overrides a user's switch.
Reports live under ignored logs/. An interrupted submission must be reconciled
with `wait`, not submitted again. This is a development harness, not a job API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = "http://127.0.0.1:8190"
ENGINE = "http://127.0.0.1:8188"
SCENE = ("Architecture smoke test. Product photograph of a blue ceramic teapot "
         "on a pale oak table beside a small green plant, soft daylight from a "
         "window on the left, neutral plaster wall, crisp glaze and wood texture.")


def request(path, body=None, *, engine=False, timeout=30):
    url = (ENGINE if engine else STUDIO) + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    # Intentionally no retry. A timeout does not prove a POST was rejected.
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    if isinstance(result, dict) and result.get("ok") is False:
        raise RuntimeError(result.get("error", "request failed"))
    return result


def queue_is_idle(queue):
    return (isinstance(queue, dict) and queue.get("queue_running") == []
            and queue.get("queue_pending") == [])


def check_idle():
    if not queue_is_idle(request("/queue", engine=True)):
        raise RuntimeError("ComfyUI is busy; no action taken")
    lane = request("/api/lane")["lane"]
    if any(row.get("role") == "job" and not row["job"].get("done") for row in lane):
        raise RuntimeError("Pixal has unfinished work; no action taken")


def owned_events(events, cid, job_ids):
    # Discover ids first: later events may omit cid, but must match a known job.
    ids = set(job_ids) | {e["job_id"] for e in events
                          if e.get("cid") == cid and e.get("job_id")}
    return [e for e in events if e.get("cid") == cid
            or (e.get("job_id") and e["job_id"] in ids)], ids


def config_hash():
    return hashlib.sha256((ROOT / "config.json").read_bytes()).hexdigest()


def preference_hash(data):
    """Compare preferences without persisting their values in the report.

    Engine boot duration is measured and saved by the normal startup path.
    Ignore only that explicit telemetry key, not arbitrary changed settings.
    Canonical JSON also distinguishes data changes from line-ending changes.
    """
    value = json.loads(data)
    value.pop("comfy_boot_seconds", None)
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def save(path, state):
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def selected(state):
    if request("/api/chats")["active"] != state["chat"]:
        raise RuntimeError("The active chat changed; leaving it untouched")


def result_job(state, name):
    job = state["steps"].get(name, {}).get("result")
    if not job or job.get("error") or not job.get("images"):
        raise RuntimeError(f"{name} must finish successfully first")
    return job["job_id"]


def wait_job(path, state, name, timeout=1800):
    step = state["steps"][name]
    deadline = time.monotonic() + timeout
    last_note = 0
    while time.monotonic() < deadline:
        selected(state)
        poll = request(f"/api/poll?since={step['seq']}")
        if poll.get("resync") and step["seq"]:
            step["replay_gap"] = True
        events, ids = owned_events(poll["events"], step["cid"], step["jobs"])
        step["seq"], step["jobs"] = poll["seq"], sorted(ids)
        # Preview bytes are large and unnecessary for protocol evidence.
        step["events"].extend(e for e in events if e.get("type") != "preview")
        lane = request("/api/lane")["lane"]
        matches = [r["job"] for r in lane if r.get("role") == "job"
                   and r["job"]["job_id"] in ids]
        if len(matches) > 1:
            save(path, state)
            raise RuntimeError("Multiple jobs for one request; inspect before continuing")
        if matches and matches[0].get("done"):
            step["result"] = matches[0]
            step["finished"] = time.time()
            save(path, state)
            print(json.dumps(step["result"], ensure_ascii=True), flush=True)
            if matches[0].get("error") or not matches[0].get("images"):
                raise RuntimeError("Render failed or produced no media")
            return
        errors = [e.get("message") for e in events if e.get("type") == "error"]
        if errors:
            save(path, state)
            raise RuntimeError("; ".join(str(e) for e in errors))
        if time.monotonic() - last_note >= 20:
            hints = [{k: e[k] for k in ("type", "note", "value", "max") if k in e}
                     for e in events if e.get("type") in ("thinking", "progress")]
            print(f"{name}: jobs={sorted(ids)} latest={hints[-1:]}", flush=True)
            save(path, state)
            last_note = time.monotonic()
        time.sleep(2)
    save(path, state)
    raise TimeoutError("Still unresolved; inspect/wait. Do not resubmit or interrupt blindly.")


def render(path, state, name, model):
    if name in state["steps"]:
        raise RuntimeError("Step already attempted; use wait to reconcile, not resubmit")
    selected(state)
    check_idle()
    cid = "smoke-" + uuid.uuid4().hex[:12]
    if name == "image":
        if not model:
            raise RuntimeError("Choose an installed image model with --model")
        route, body = "/api/chat", {"text": SCENE, "opts": {
            "prompt_enhance": False, "model": model, "style": "realism",
            "quality": "fast", "aspect": "1:1", "mp": 1, "seed": 904131,
            "character": None, "refs": [], "loras": []}}
    elif name in ("reroll", "recovery"):
        route, body = "/api/reroll", {"id": result_job(state, "image"), "lock_seed": True}
    elif name == "edit":
        route, body = "/api/edit", {"id": result_job(state, "image"),
            "instruction": "Change only the blue teapot to warm terracotta orange. "
                           "Keep the plant, table, lighting and composition unchanged.",
            "seed": 904132, "megapixels": 1}
    elif name == "video":
        route, body = "/api/animate", {"id": result_job(state, "image"),
            "engine": "h3", "model": "fl2va", "seconds": 5, "shots": 1,
            "resolution": "standard", "speed": "turbo8",
            "script": "A slow, gentle camera push toward the blue ceramic teapot. "
                      "The teapot and plant stay still on the oak table. "
                      "Soft daylight remains steady. Quiet room ambience."}
    elif name == "upscale":
        route, body = "/api/upscale", {"id": result_job(state, "image"), "mode": "vsr"}
    else:
        raise ValueError(name)
    body["cid"] = cid
    step = {"cid": cid, "seq": request("/api/poll?since=0")["seq"],
            "jobs": [], "events": [], "started": time.time(),
            "request": {"path": route, "body": body}, "dispatch": "uncertain"}
    state["steps"][name] = step
    save(path, state)  # Receipt BEFORE sending: never automatically repeat a POST.
    step["response"] = request(route, body)
    step["dispatch"] = "acknowledged"
    save(path, state)
    wait_job(path, state, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("begin", "image", "reroll", "recovery", "edit", "video",
                                          "upscale", "wait", "restore"))
    parser.add_argument("--execute", action="store_true", help="approved live studio work")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--step", choices=("image", "reroll", "recovery", "edit", "video", "upscale"))
    args = parser.parse_args()
    if not args.execute:
        parser.error("Live work requires --execute and an approved idle session")
    path = args.report.resolve()
    if not path.is_relative_to((ROOT / "logs").resolve()):
        parser.error("Reports must stay in this checkout's private logs directory")
    if args.action == "begin":
        if path.exists():
            parser.error("Report already exists; refusing to overwrite it")
        check_idle()
        state = {"started": time.time(), "original_chat": request("/api/chats")["active"],
                 "config_sha256": config_hash(), "steps": {},
                 "preferences_sha256": preference_hash((ROOT / "config.json").read_bytes())}
        path.parent.mkdir(parents=True, exist_ok=True)
        save(path, state)
        state["chat"] = request("/api/chats", {"action": "new"})["active"]
        save(path, state)
        print(f"Created separate test chat; report: {path}")
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    if args.action == "restore":
        selected(state)
        check_idle()
        request("/api/chats", {"action": "select", "id": state["original_chat"]})
        state["restored"] = time.time()
        state["config_unchanged"] = config_hash() == state["config_sha256"]
        state["preferences_unchanged"] = (
            preference_hash((ROOT / "config.json").read_bytes()) == state["preferences_sha256"]
            if state.get("preferences_sha256") else None)
        save(path, state)
        print(f"Original chat restored. Configuration bytes unchanged: {state['config_unchanged']}. "
              f"Preferences unchanged: {state['preferences_unchanged']} "
              "(None means this older report needs a manual comparison).")
    elif args.action == "wait":
        if not args.step:
            parser.error("wait requires --step")
        wait_job(path, state, args.step)
    else:
        render(path, state, args.action, args.model)


if __name__ == "__main__":
    main()
