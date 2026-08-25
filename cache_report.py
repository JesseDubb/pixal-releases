# cache_report.py - brief 9.33: what did ComfyUI NOT have to run?
# Reads history.jsonl, prints per-template observed / hit-rate / most-common
# ran set, then the 10 most recent jobs one line each. No arguments, no deps
# beyond stdlib. "Unobserved" means the sensor never saw an execution_cached
# frame for that job (or the job predates the sensor) - never a miss.
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "history.jsonl"


def load_entries(path):
    """Every parseable ledger line, oldest first. A blank or truncated line
    (sidecar killed mid-write) is skipped, never fatal."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def job_line(entry):
    """One glanceable line: when, which job, what template, what the cache
    did - or why we do not know."""
    ts = time.strftime("%m-%d %H:%M", time.localtime(entry.get("ts") or 0))
    cache = entry.get("cache")
    if cache is None:
        state = "pre-sensor (no cache data)"
    elif not cache.get("observed"):
        state = "no execution_cached frame"
    else:
        ran = ", ".join(cache.get("ran") or []) or "none"
        state = f"{cache.get('hit', 0)}/{cache.get('total', 0)} skipped (ran: {ran})"
    return (f"  {ts}  {str(entry.get('id', '?')):8}  "
            f"{str(entry.get('template', '?')):16}  {state}")


def report(entries):
    """The whole report as a list of lines - pure, so tests feed injected
    entries instead of a ledger file."""
    with_cache = [e for e in entries if "cache" in e]
    observed = [e for e in with_cache if e["cache"].get("observed")]
    lines = [f"{len(entries)} ledger jobs: {len(observed)} observed, "
             f"{len(with_cache) - len(observed)} no execution_cached frame, "
             f"{len(entries) - len(with_cache)} pre-sensor", "",
             "per template:"]
    by_template = defaultdict(list)
    for e in entries:
        by_template[str(e.get("template", "?"))].append(e)
    for template in sorted(by_template):
        es = by_template[template]
        obs = [e for e in es if e.get("cache", {}).get("observed")]
        if obs:
            hits = sum(e["cache"].get("hit", 0) for e in obs)
            total = sum(e["cache"].get("total", 0) for e in obs)
            rate = (f"{100.0 * hits / total:.0f}% ({hits}/{total} nodes)"
                    if total else "-")
            ran_sets = Counter(tuple(e["cache"].get("ran") or []) for e in obs)
            common = ", ".join(ran_sets.most_common(1)[0][0]) or "none"
        else:
            rate, common = "-", "-"
        lines.append(f"  {template:16}  observed {len(obs)}/{len(es):<5} "
                     f"hit-rate {rate:22}  most-common ran: {common}")
    lines += ["", "recent jobs:"]
    lines += [job_line(e) for e in entries[-10:]]
    return lines


def main(path=LEDGER):
    entries = load_entries(path)
    if not entries:
        print(f"cache report: no ledger entries at {path}")
        return 0
    print("\n".join(report(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
