"""Narrow HTTP translation for configuration persistence failures."""
from aiohttp import web

from pixal.config.store import ConfigUnreadableError, ConfigWriteError


@web.middleware
async def config_errors(request: web.Request, handler):
    try:
        return await handler(request)
    except ConfigUnreadableError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=409)
    except ConfigWriteError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=500)
