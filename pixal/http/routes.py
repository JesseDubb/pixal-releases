"""The ordered public HTTP surface. Handlers are supplied at composition time."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import NamedTuple

import gzip

from aiohttp import web

from pixal.paths import RuntimePaths

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class RouteSpec(NamedTuple):
    method: str
    path: str
    handler: str


# Preserve specific routes before dynamic catch-alls.
ROUTES = (
    RouteSpec("GET", "/", "index"),
    RouteSpec("GET", "/manifest.webmanifest", "manifest"),
    RouteSpec("GET", "/sw.js", "service_worker"),
    RouteSpec("STATIC", "/icons", "icons"),
    RouteSpec("GET", "/api/events", "events"),
    RouteSpec("POST", "/api/chat", "chat"),
    RouteSpec("GET", "/api/lane", "lane_get"),
    RouteSpec("GET", "/api/chats", "chats_get"),
    RouteSpec("POST", "/api/chats", "chats_post"),
    RouteSpec("POST", "/api/reroll", "reroll"),
    RouteSpec("POST", "/api/stop", "stop"),
    RouteSpec("POST", "/api/comfy/free", "comfy_free"),
    RouteSpec("POST", "/api/comfy/restart", "restart_comfy"),
    RouteSpec("POST", "/api/sidecar/restart", "restart_sidecar"),
    RouteSpec("POST", "/api/llm/free", "free_chat_model"),
    RouteSpec("POST", "/api/ram/free", "ram_free"),
    RouteSpec("POST", "/api/desktop/reset", "desktop_reset"),
    RouteSpec("GET", "/api/vram/table", "vram_table"),
    RouteSpec("GET", "/api/history", "history"),
    RouteSpec("POST", "/api/history/delete", "history_delete"),
    RouteSpec("GET", "/api/options", "options"),
    RouteSpec("GET", "/api/h3/canvas", "h3_canvas"),
    RouteSpec("GET", "/api/quant_alternatives", "quant_alternatives"),
    RouteSpec("POST", "/api/quant_fetch", "quant_fetch"),
    RouteSpec("POST", "/api/upload", "upload"),
    RouteSpec("POST", "/api/dlss5/dll", "dlss5_dll"),
    RouteSpec("POST", "/api/input-ref-type", "input_ref_type_post"),
    RouteSpec("GET", "/api/setup", "setup_get"),
    RouteSpec("POST", "/api/setup", "setup_post"),
    RouteSpec("GET", "/api/settings", "settings_get"),
    RouteSpec("POST", "/api/settings", "settings_post"),
    RouteSpec("POST", "/api/settings/test", "settings_test"),
    RouteSpec("POST", "/api/settings/rescan", "settings_rescan"),
    RouteSpec("GET", "/api/update-check", "update_check_get"),
    RouteSpec("POST", "/api/update/download", "update_download_post"),
    RouteSpec("POST", "/api/update/cancel", "update_cancel_post"),
    RouteSpec("POST", "/api/update/launch", "update_launch_post"),
    RouteSpec("POST", "/api/animate", "animate"),
    RouteSpec("POST", "/api/animate/brief", "animate_brief"),
    RouteSpec("POST", "/api/edit", "edit"),
    RouteSpec("POST", "/api/input/stage", "input_stage"),
    RouteSpec("POST", "/api/upscale", "upscale"),
    RouteSpec("POST", "/api/review", "review"),
    RouteSpec("POST", "/api/trailer", "trailer"),
    RouteSpec("POST", "/api/styles", "styles_post"),
    RouteSpec("POST", "/api/styles/from-image", "style_from_image"),
    RouteSpec("GET", "/api/styles/sampler", "style_sampler"),
    RouteSpec("POST", "/api/sampler/combos/star", "sampler_combo_star"),
    RouteSpec("POST", "/api/sampler/combos/forget", "sampler_combo_forget"),
    RouteSpec("DELETE", "/api/styles/{style_id}", "styles_delete"),
    RouteSpec("POST", "/api/characters", "characters_post"),
    RouteSpec("POST", "/api/characters/preview", "characters_preview"),
    RouteSpec("DELETE", "/api/characters/{character_id}", "characters_delete"),
    RouteSpec("GET", "/api/characters/{character_id}", "characters_get_one"),
    RouteSpec("GET", "/api/characters/{character_id}/ref-thumb", "character_ref_thumb"),
    RouteSpec("GET", "/api/status", "status"),
    RouteSpec("GET", "/api/poll", "events_poll"),
    RouteSpec("GET", "/api/image", "image"),
    RouteSpec("GET", "/api/thumb", "output_thumbnail"),
    RouteSpec("GET", "/api/input-thumb", "input_thumbnail"),
    RouteSpec("GET", "/api/comfy/compat", "comfy_compat"),
    RouteSpec("GET", "/api/comfy/manager/status", "manager_status"),
    RouteSpec("GET", "/api/comfy/{tail:.*}", "comfy_asset"),
    RouteSpec("STATIC", "/vendor", "vendor"),
    RouteSpec("STATIC", "/fonts", "fonts"),
    RouteSpec("GET", "/app.js", "_bundle"),
)
HANDLER_NAMES = frozenset(route.handler for route in ROUTES
                          if route.method != "STATIC" and route.handler != "_bundle")


def register_routes(app: web.Application, paths: RuntimePaths,
                    handlers: Mapping[str, Handler]) -> None:
    missing = HANDLER_NAMES - handlers.keys()
    if missing:
        raise ValueError(f"Missing HTTP handlers: {', '.join(sorted(missing))}")

    # The bundle compressed once per file version and held here: 868 KB on
    # the wire became ~250 KB, which is nothing on a LAN and the whole first
    # paint through a tunnel. Revalidation stays (ETag, no max-age): a cached
    # bundle behind a new sidecar is the "screenshot contradicts the code"
    # failure, so the browser must always ask.
    packed: dict = {}

    async def bundle(request: web.Request) -> web.StreamResponse:
        source = paths.web_dir / "app.js"
        if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
            return web.FileResponse(source, headers={
                "Content-Type": "application/javascript",
                "Cache-Control": "no-cache", "Vary": "Accept-Encoding"})
        try:
            stat = source.stat()
        except OSError:
            return web.FileResponse(source)   # let aiohttp answer the miss
        key = (stat.st_mtime_ns, stat.st_size)
        if packed.get("key") != key:
            packed["key"] = key
            packed["body"] = gzip.compress(source.read_bytes(), compresslevel=6)
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}-gz"'
        headers = {"Content-Type": "application/javascript",
                   "Cache-Control": "no-cache", "Vary": "Accept-Encoding",
                   "ETag": etag}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        headers["Content-Encoding"] = "gzip"
        return web.Response(body=packed["body"], headers=headers)

    for route in ROUTES:
        if route.method == "STATIC":
            app.router.add_static(route.path, paths.web_dir / route.handler)
        elif route.method == "GET":
            app.router.add_get(route.path, bundle if route.handler == "_bundle" else handlers[route.handler])
        else:
            app.router.add_route(route.method, route.path, handlers[route.handler])
