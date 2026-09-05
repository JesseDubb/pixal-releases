"""Application-owned background tasks with visible failures and bounded cleanup."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)


class TaskOwner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._closing = False

    def start(self, name: str, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task:
        if self._closing or (name in self._tasks and not self._tasks[name].done()):
            coroutine.close()
            raise RuntimeError(f"Cannot start task {name!r}: owner closing or name already active")
        task = asyncio.create_task(coroutine, name=f"pixal:{name}")
        self._tasks[name] = task
        task.add_done_callback(self._finished)
        return task

    @staticmethod
    def _finished(task: asyncio.Task) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            log.error("Background task %s failed", task.get_name(),
                      exc_info=(type(error), error, error.__traceback__))

    async def close(self, timeout: float = 2.0) -> tuple[str, ...]:
        self._closing = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if not tasks:
            return ()
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        names = tuple(sorted(task.get_name() for task in pending))
        if names:
            log.error("Tasks exceeded the shutdown deadline: %s", ", ".join(names))
        return names


TASKS_KEY = web.AppKey("pixal.tasks", TaskOwner)


async def task_lifetime(app: web.Application):
    try:
        yield
    finally:
        await app[TASKS_KEY].close()
