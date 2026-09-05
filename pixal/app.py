"""Construct HTTP applications without starting engines or reading user data.

The desktop currently supplies legacy handlers through server.create_app().
That adapter still shares legacy globals; this factory itself has no such state.
New features should receive their own narrowly scoped dependencies.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from aiohttp import web

from pixal.http.routes import Handler, register_routes
from pixal.lifecycle import TASKS_KEY, TaskOwner, task_lifetime
from pixal.paths import RuntimePaths

Hook = Callable[[web.Application], Awaitable[None]]
PATHS_KEY = web.AppKey("pixal.paths", RuntimePaths)


@dataclass(frozen=True)
class LifecycleHooks:
    startup: tuple[Hook, ...] = ()
    shutdown: tuple[Hook, ...] = ()
    cleanup: tuple[Hook, ...] = ()


def create_app(*, paths: RuntimePaths, handlers: Mapping[str, Handler],
               client_max_size: int, middlewares: tuple = (),
               lifecycle: LifecycleHooks = LifecycleHooks()) -> web.Application:
    app = web.Application(middlewares=middlewares, client_max_size=client_max_size)
    app[PATHS_KEY] = paths
    app[TASKS_KEY] = TaskOwner()
    app.cleanup_ctx.append(task_lifetime)
    register_routes(app, paths, handlers)
    app.on_startup.extend(lifecycle.startup)
    app.on_shutdown.extend(lifecycle.shutdown)
    app.on_cleanup.extend(lifecycle.cleanup)
    return app
