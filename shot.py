# shot.py <url> <out.png> [width height] - CDP screenshot with real mobile emulation
# (headless Chrome's --window-size is DPI-mangled on this box; CDP override is exact)
import asyncio, base64, json, subprocess, sys, time
import aiohttp

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9223

async def main():
    url, out = sys.argv[1], sys.argv[2]
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 390
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 844
    prof = out + ".prof"
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                             f"--remote-debugging-port={PORT}",
                             f"--user-data-dir={prof}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as s:
            ws_url = None
            for _ in range(40):
                try:
                    async with s.get(f"http://127.0.0.1:{PORT}/json") as r:
                        for t in await r.json():
                            if t.get("type") == "page":
                                ws_url = t["webSocketDebuggerUrl"]; break
                except Exception:
                    pass
                if ws_url: break
                await asyncio.sleep(0.25)
            if not ws_url:
                print("no CDP target"); return 1
            async with s.ws_connect(ws_url, max_msg_size=64*2**20) as ws:
                mid = 0
                async def cmd(method, **params):
                    nonlocal mid
                    mid += 1
                    await ws.send_json({"id": mid, "method": method, "params": params})
                    async for m in ws:
                        d = json.loads(m.data)
                        if d.get("id") == mid:
                            return d.get("result", {})
                await cmd("Emulation.setDeviceMetricsOverride",
                          width=w, height=h, deviceScaleFactor=2, mobile=True)
                await cmd("Page.enable")
                await cmd("Page.navigate", url=url)
                await asyncio.sleep(7)          # SSE keeps load pending; just settle
                typing = sys.argv[5] if len(sys.argv) > 5 else None
                if typing:
                    await cmd("Runtime.evaluate",
                              expression="document.querySelector('textarea').focus()")
                    for ch in typing:
                        await cmd("Input.insertText", text=ch)
                        await asyncio.sleep(0.12)
                    await asyncio.sleep(1)
                shot = await cmd("Page.captureScreenshot", format="png")
                with open(out, "wb") as f:
                    f.write(base64.b64decode(shot["data"]))
                print("wrote", out)
    finally:
        proc.kill()
    return 0

sys.exit(asyncio.run(main()))
