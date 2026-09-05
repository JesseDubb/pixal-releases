"""Opt-in Chromium comparison audit, isolated from the running studio.

Usage: .venv/Scripts/python.exe tools/audit_image_compare.py --image path/to/still.png
Uses a COPY of the supplied image; no live API, config, models or chats change.
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SHOTS = ROOT / "logs" / "compare-audit"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


async def run(source):
    SHOTS.mkdir(exist_ok=True)
    subprocess.run(["node", str(ROOT / "node_modules/esbuild/bin/esbuild"),
        "tools/fixtures/compare_fixture.jsx", "--bundle", "--format=esm",
        "--outfile=logs/compare_fixture.js", "--jsx=automatic"], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix="pixal-compare-") as temp:
        scratch = Path(temp)
        engine = scratch / "ComfyUI"
        output = engine / "output"
        output.mkdir(parents=True)
        (scratch / "data").mkdir()
        os.environ["PIXAL_DATA_DIR"] = str(scratch / "data")
        os.environ["PIXAL_COMFY_DIR"] = str(engine)
        os.environ["MOONSHOT_API_KEY"] = ""
        import server

        original = output / ("original" + source.suffix)
        shutil.copy2(source, original)
        events = []
        hub = object.__new__(server.Hub)
        hub.broadcast = lambda **e: events.append(e)
        job = {"id": "compare-audit", "job_id": "compare-audit", "template": "h3_ref_still",
               "seen": set(), "images": [], "info": {}, "seed": 915501, "count": 1,
               "scene": "Post-processing comparison", "done": True, "elapsed": 1.0}
        with patch.object(server, "load_config", return_value={"still": {
            "de_shine": True, "film_grain": True, "film_grain_amount": 2.0}}):
            hub.add_image(job, {"filename": original.name, "subfolder": "", "type": "output"})
        pair = job["images"][0]
        assert pair.get("original"), "real delivery did not preserve the pair"
        legacy = {"filename": original.name, "subfolder": "", "type": "output", "media": "image"}
        missing = {**pair, "original": {**legacy, "filename": "missing.png"}}
        images = [pair, legacy, missing]
        serial_job = {k: v for k, v in job.items() if k != "seen"}
        requests = []

        async def handler(req):
            requests.append((req.method, req.path))
            if req.method not in ("GET", "HEAD"):
                return web.Response(status=405)
            if req.path == "/":
                return web.Response(text='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>@font-face{font-family:Geist;src:url(/fonts/geist-variable-latin.woff2)}body{margin:0}</style><div id="app"></div><script type="module" src="/fixture.js"></script>', content_type="text/html")
            if req.path == "/fixture.js":
                return web.FileResponse(ROOT / "logs" / "compare_fixture.js")
            if req.path == "/fixture":
                return web.json_response({"images": images})
            if req.path == "/api/lane":
                return web.json_response({"lane": [{"role": "job", "job": serial_job}]})
            if req.path == "/api/history":
                return web.json_response({"history": []})
            if req.path.startswith("/fonts/"):
                return web.FileResponse(ROOT / "web" / "fonts" / Path(req.path).name)
            name = req.query.get("filename")
            if name and Path(name).name == name and (output / name).is_file():
                return web.FileResponse(output / name)
            if name:
                return web.Response(status=404)
            return web.json_response({})

        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = f"http://127.0.0.1:{runner.addresses[0][1]}"
        profile = scratch / "chrome"
        proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
            "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            port_file = profile / "DevToolsActivePort"
            for _ in range(80):
                if port_file.exists():
                    break
                await asyncio.sleep(.1)
            port = int(port_file.read_text().splitlines()[0])
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{port}/json") as response:
                    targets = await response.json()
                async with session.ws_connect(next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page"), max_msg_size=64*2**20) as ws:
                    pending, errors, mid = {}, [], 0

                    async def receive():
                        async for message in ws:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = json.loads(message.data)
                            if data.get("method") == "Runtime.exceptionThrown":
                                errors.append(data["params"])
                            future = pending.get(data.get("id"))
                            if future and not future.done():
                                future.set_result(data)

                    reader = asyncio.create_task(receive())

                    async def cmd(method, **params):
                        nonlocal mid
                        mid += 1
                        index = mid
                        future = asyncio.get_running_loop().create_future()
                        pending[index] = future
                        await ws.send_json({"id": index, "method": method, "params": params})
                        try:
                            data = await asyncio.wait_for(future, 20)
                            if "error" in data:
                                raise RuntimeError(data["error"])
                            return data.get("result", {})
                        finally:
                            pending.pop(index, None)

                    async def js(expression):
                        data = await cmd("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
                        if data.get("exceptionDetails"):
                            raise RuntimeError(data["exceptionDetails"])
                        return data.get("result", {}).get("value")

                    async def wait(expression):
                        for _ in range(80):
                            if await js(expression):
                                return
                            await asyncio.sleep(.1)
                        raise RuntimeError("Browser condition timed out: " + expression + str(errors))

                    async def screenshot(name):
                        shot = await cmd("Page.captureScreenshot", format="png")
                        (SHOTS / name).write_bytes(base64.b64decode(shot["data"]))

                    await cmd("Runtime.enable")
                    await cmd("Page.enable")
                    await cmd("Emulation.setDeviceMetricsOverride", width=1440, height=1000, deviceScaleFactor=1, mobile=False)
                    await cmd("Page.navigate", url=url)
                    await wait('!!document.querySelector("button[aria-label^=Compare]")')
                    await js('document.querySelector("button[aria-label^=Compare]").click()')
                    await wait('!!document.querySelector(".px-post-compare input[type=range]")')
                    box = await js('document.querySelector(".px-compare-viewport").getBoundingClientRect().toJSON()')
                    x, y = box["x"] + box["width"]*.28, box["y"] + box["height"]*.5
                    await cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
                    position = await js('parseFloat(document.querySelector(".px-compare-viewport").style.getPropertyValue("--wipe"))')
                    assert abs(position-28) < .2, position
                    await screenshot("desktop-wipe.png")
                    await cmd("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=-450)
                    await asyncio.sleep(.2)
                    transforms = await js('[...document.querySelectorAll(".px-compare-viewport img")].map(e=>e.style.transform)')
                    assert len(set(transforms)) == 1 and "scale(1)" not in transforms[0], transforms
                    await js("window.compareFixture.open(0)")
                    await asyncio.sleep(.1)
                    await js('document.querySelector(".px-post-compare input[type=range]").focus()')
                    await cmd("Input.dispatchKeyEvent", type="keyDown", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
                    await cmd("Input.dispatchKeyEvent", type="keyUp", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
                    assert await js('!!document.querySelector(".px-post-compare")'), "slider key navigated gallery"
                    assert await js("window.compareFixture.index()") == 0, "slider key changed image"
                    await screenshot("zoomed-wipe.png")
                    downloads = scratch / "downloads"
                    downloads.mkdir()
                    await cmd("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(downloads))
                    for label, expected in (("Save original", original), ("Save processed", output / pair["filename"])):
                        selector = f'[aria-label="{label}"]'
                        await js(f'document.querySelector({json.dumps(selector)}).click()')
                        for _ in range(60):
                            if (downloads / expected.name).exists():
                                break
                            await asyncio.sleep(.1)
                        assert (downloads / expected.name).read_bytes() == expected.read_bytes(), label
                    await cmd("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
                    await wait('!document.querySelector(".px-post-compare")')
                    await js("window.compareFixture.open(1)")
                    await asyncio.sleep(.1)
                    assert not await js('!!document.querySelector(".px-post-compare")'), "legacy original invented"
                    await js("window.compareFixture.open(2)")
                    await wait('document.querySelector(".px-post-compare [role=status]")?.textContent.includes("unavailable")')
                    assert not await js('!!document.querySelector("a[aria-label$=original]")')
                    await js("window.compareFixture.open(0)")
                    await cmd("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
                    await cmd("Emulation.setTouchEmulationEnabled", enabled=True)
                    await wait('!!document.querySelector(".px-post-compare input[type=range]")')
                    await asyncio.sleep(.2)
                    box = await js('document.querySelector(".px-compare-viewport").getBoundingClientRect().toJSON()')
                    await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x":box["x"]+box["width"]*.25,"y":box["y"]+80}])
                    await cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x":box["x"]+box["width"]*.8,"y":box["y"]+80}])
                    await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                    await asyncio.sleep(.1)
                    position = await js('parseFloat(document.querySelector(".px-compare-viewport").style.getPropertyValue("--wipe"))')
                    assert abs(position-80) < 1, position
                    await screenshot("mobile-wipe.png")
                    await cmd("Page.reload")
                    await wait('!!document.querySelector("button[aria-label^=Compare]")')
                    await js('document.querySelector("button[aria-label^=Compare]").click()')
                    await wait('!!document.querySelector(".px-post-compare input[type=range]")')
                    assert not errors, errors
                    assert all(method in ("GET", "HEAD") for method, _ in requests), requests
                    print(json.dumps({"ok": True, "checks": ["real delivery", "live card", "hover mask", "shared zoom", "keyboard", "both byte-exact downloads", "Escape", "legacy", "missing original", "touch", "reload"], "screenshots": str(SHOTS)}), flush=True)
                    reader.cancel()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.image.resolve(strict=True)))
