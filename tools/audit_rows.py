# Read-only browser audit of the Settings workspace: minimum row heights,
# bounded controls, label/rail overlap, shared card/group spacing and Escape.
# Explicitly invoke with the user-approved browser-testing workflow. POST/PUT/
# PATCH/DELETE requests are blocked; this must never change the live config.
# Usage: python tools/audit_rows.py [--url URL] [--shots DIR] [--width 1440] [--json]
import argparse
import asyncio
import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9224
TOKENS = (ROOT / "web" / "src" / "lib" / "design-tokens.js").read_text(encoding="utf-8")


def table(name, source=TOKENS):
    body = re.search(r"export const %s = \{(.*?)\};" % name, source, re.S).group(1)
    return {k: int(v) for k, v in re.findall(r"^\s*(\w+):\s*(\d+),", body, re.M)}


HEIGHT = table("HEIGHT")
SETTINGS = table("SETTINGS", (ROOT / "web/src/lib/settings-layout.js").read_text(encoding="utf-8"))

# Runs in the page; reads only labels, geometry and computed styles.
MEASURE = r"""
(() => {
  const rect = (el) => el.getBoundingClientRect();
  const text = (el) => (el?.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
  const panel = document.querySelector(".px-settings");
  const body = panel?.querySelector(".px-settings-body");
  const out = { tab: text(panel?.querySelector('.px-settings-tabs [aria-selected="true"]')),
    rows: [], rails: [], gaps: [], overflow: [], frame: rect(panel).height };
  const controls = (el) => {
    const cs = getComputedStyle(el);
    if (["BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)
        || el.getAttribute("role") === "switch" || parseFloat(cs.borderTopWidth) > 0)
      return [el];
    return [...el.children].flatMap(controls);
  };
  for (const row of panel.querySelectorAll("[data-set-row]")) {
    const rr = rect(row), label = text(row.querySelector(".px-setting-name"));
    const rail = row.querySelector("[data-set-rail]");
    const lr = rect(row.querySelector(".px-setting-label")), ar = rect(rail);
    const stacked = ar.top >= lr.bottom - 1;
    out.rows.push({ label, h: rr.height });
    if (!stacked && lr.right > ar.left + 1) out.overflow.push(label + ": label overlaps control");
    if (row.scrollWidth > row.clientWidth + 1) out.overflow.push(label + ": row overflows");
    for (const control of controls(rail)) {
      const cr = rect(control);
      if (!cr.width || !cr.height) continue;
      out.rails.push({ label, tag: control.tagName, role: control.getAttribute("role") || "",
        h: cr.height, w: cr.width, above: cr.top - ar.top, below: ar.bottom - cr.bottom });
      if (cr.left < rr.left - 1 || cr.right > rr.right + 1)
        out.overflow.push(label + ": control escapes row");
    }
  }
  const gaps = (el, kind) => {
    const children = [...el.children].filter((child) => rect(child).height > 0);
    children.slice(1).forEach((child, i) =>
      out.gaps.push({ kind, value: rect(child).top - rect(children[i]).bottom }));
  };
  if (!body.classList.contains("px-settings-about")) {
    gaps(body, "group");
    panel.querySelectorAll(".px-settings-group").forEach((el) => gaps(el, "heading"));
    panel.querySelectorAll(".px-settings-group-body").forEach((el) => gaps(el, "card"));
    panel.querySelectorAll(".px-set-rows").forEach((el) => gaps(el, "row"));
  }
  if (body.scrollWidth > body.clientWidth + 1) out.overflow.push("body overflows horizontally");
  return JSON.stringify(out);
})()
"""


def judge(tabs):
    """Rows may wrap. Controls stay bounded, centered within their rail."""
    bad, heights = [], {}
    gap_targets = {"group": SETTINGS["groupGap"], "heading": SETTINGS["cardGap"],
                   "card": SETTINGS["cardGap"], "row": 0}
    for tab in tabs:
        name = tab["tab"] or "?"
        for row in tab["rows"]:
            if row["h"] + 0.5 < SETTINGS["row"]:
                bad.append("%s / %s: row %.1f is below the %dpx minimum" %
                           (name, row["label"], row["h"], SETTINGS["row"]))
        seen = set()
        for control in tab["rails"]:
            h = control["h"]
            seen.add(round(h, 2))
            toggle = control["role"] == "switch" or (round(control["w"]) == 42 and round(h) == 16)
            expected = (HEIGHT["rail"], HEIGHT["row"]) if control["tag"] == "INPUT" else (HEIGHT["rail"],)
            if not toggle and all(abs(h - value) > 0.5 for value in expected):
                bad.append("%s / %s: %s is %.1fpx tall" % (name, control["label"], control["tag"], h))
            if abs(control["above"] - control["below"]) > 1:
                bad.append("%s / %s: control is not centered in its rail" % (name, control["label"]))
        for gap in tab["gaps"]:
            if abs(gap["value"] - gap_targets[gap["kind"]]) > 1:
                bad.append("%s: %s gap %.1f, expected %d" %
                           (name, gap["kind"], gap["value"], gap_targets[gap["kind"]]))
        bad.extend("%s: %s" % (name, problem) for problem in tab["overflow"])
        heights[name] = sorted(seen)
    if tabs and max(t["frame"] for t in tabs) - min(t["frame"] for t in tabs) > 1:
        bad.append("The workspace frame changes height between tabs")
    return bad, heights


async def run(url, shots=None, width=1440):
    prof = tempfile.mkdtemp(prefix="pixal-audit-")
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as s:
            ws_url = None
            for _ in range(60):
                try:
                    async with s.get(f"http://127.0.0.1:{PORT}/json") as r:
                        for t in await r.json():
                            if t.get("type") == "page":
                                ws_url = t["webSocketDebuggerUrl"]
                                break
                except Exception:
                    pass
                if ws_url:
                    break
                await asyncio.sleep(0.25)
            if not ws_url:
                raise RuntimeError("no CDP target - is Chrome at %s?" % CHROME)
            async with s.ws_connect(ws_url, max_msg_size=64 * 2 ** 20) as ws:
                mid = 0
                pending = {}

                async def receive():
                    nonlocal mid
                    async for m in ws:
                        if m.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(m.data)
                        if d.get("method") == "Fetch.requestPaused":
                            event = d["params"]
                            allowed = event["request"]["method"] in ("GET", "HEAD", "OPTIONS")
                            mid += 1
                            await ws.send_json({"id": mid,
                                "method": "Fetch.continueRequest" if allowed else "Fetch.failRequest",
                                "params": {"requestId": event["requestId"],
                                           **({} if allowed else {"errorReason": "BlockedByClient"})}})
                        future = pending.get(d.get("id"))
                        if future and not future.done():
                            future.set_result(d)

                reader = asyncio.create_task(receive())

                async def cmd(method, **params):
                    nonlocal mid
                    mid += 1
                    request_id = mid
                    future = asyncio.get_running_loop().create_future()
                    pending[request_id] = future
                    try:
                        await ws.send_json({"id": request_id, "method": method, "params": params})
                        d = await asyncio.wait_for(future, 30)
                        if "error" in d:
                            raise RuntimeError("%s: %s" % (method, d["error"]))
                        return d.get("result", {})
                    finally:
                        pending.pop(request_id, None)

                async def js(expr):
                    res = await cmd("Runtime.evaluate", expression=expr, awaitPromise=True,
                                    returnByValue=True)
                    if res.get("exceptionDetails"):
                        raise RuntimeError("Browser evaluation failed: %s" % res["exceptionDetails"].get("text"))
                    return res.get("result", {}).get("value")

                await cmd("Emulation.setDeviceMetricsOverride", width=width, height=900,
                          deviceScaleFactor=1, mobile=False)
                await cmd("Network.enable")
                await cmd("Fetch.enable", patterns=[{"urlPattern": "*", "requestStage": "Request"}])
                await cmd("Network.setCacheDisabled", cacheDisabled=True)
                await cmd("Page.enable")
                await cmd("Page.navigate", url=url)
                await asyncio.sleep(5)          # SSE keeps load pending; just settle
                await js("navigator.serviceWorker ? navigator.serviceWorker.getRegistrations()"
                         ".then(rs => Promise.all(rs.map(r => r.unregister()))) : null")
                await cmd("Page.reload", ignoreCache=True)
                await asyncio.sleep(5)
                opened = await js('(() => { const b = document.querySelector(\'button[aria-label="settings"]\');'
                                  ' if (!b) return false; b.click(); return true; })()')
                if not opened:
                    raise RuntimeError("no settings button in the rail - did the app render?")
                await asyncio.sleep(2)          # the eleven fetches land, ghosts swap
                count = await js('document.querySelectorAll(\'.px-settings-tabs [role="tab"]\').length')
                tabs = []
                for i in range(int(count or 0)):
                    await js('document.querySelectorAll(\'.px-settings-tabs [role="tab"]\')[%d].click()' % i)
                    await asyncio.sleep(1.2)
                    t = json.loads(await js(MEASURE))
                    if shots:
                        # One PNG per tab, at 2x so a 1px hairline is visible in the
                        # file - the screenshot pass is the last step before a commit,
                        # not a follow-up (docs/2026-09-04-spacing-and-optical-balance.md §6).
                        await cmd("Emulation.setDeviceMetricsOverride", width=width, height=900,
                                  deviceScaleFactor=2, mobile=False)
                        await asyncio.sleep(0.4)
                        png = await cmd("Page.captureScreenshot", format="png")
                        out = Path(shots) / ("settings-%d-%s.png" % (i + 1, re.sub(r"\W+", "", t["tab"] or "tab").lower()))
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(base64.b64decode(png["data"]))
                        t["shot"] = str(out)
                        await cmd("Emulation.setDeviceMetricsOverride", width=width, height=900,
                                  deviceScaleFactor=1, mobile=False)
                    tabs.append(t)
                # An actual keyboard event, not a direct call to the close handler.
                await cmd("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape",
                          windowsVirtualKeyCode=27)
                await cmd("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape",
                          windowsVirtualKeyCode=27)
                await asyncio.sleep(0.3)
                if await js('!!document.querySelector(".px-settings")'):
                    raise RuntimeError("Escape did not close Settings")
                reader.cancel()
                return tabs
    finally:
        proc.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8190/")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--width", type=int, default=1440, help="viewport width for responsive checks")
    ap.add_argument("--shots", metavar="DIR", help="also save one PNG per tab into DIR")
    a = ap.parse_args()
    try:
        tabs = asyncio.run(run(a.url, a.shots, a.width))
    except Exception as ex:                      # noqa: BLE001 - report, do not trace
        print(json.dumps({"error": str(ex)}) if a.json else "could not measure: %s" % ex)
        return 2
    measured = sum(len(t["rows"]) for t in tabs)
    bad, heights = judge(tabs)
    if measured == 0:
        bad = ["no [data-set-row] in the served bundle - run web\\build.bat, then measure again"]
    if a.json:
        print(json.dumps({"measured": measured, "tabs": [t["tab"] for t in tabs],
                          "rail_heights": heights, "violations": bad}))
    else:
        print("%d rows across %d tabs" % (measured, len(tabs)))
        for tab, hs in heights.items():
            print("  %-8s rail heights: %s" % (tab, ", ".join("%g" % h for h in hs) or "-"))
        for t in tabs:
            if t.get("shot"):
                print("  shot     %s" % t["shot"])
        if bad:
            print("\n%d violation(s):" % len(bad))
            for line in bad:
                print("  - " + line)
        else:
            print("\nclean: rows breathe, rails fit, card rhythm holds, Escape closes Settings")
    return 1 if bad else (0 if measured else 2)


if __name__ == "__main__":
    sys.exit(main())
