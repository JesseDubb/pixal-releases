"""Per-application event fan-out and replay state. No import-time resources."""
import asyncio
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from aiohttp import web

_current = ContextVar("pixal.event_publisher", default=None)


@contextmanager
def scope(consumer, owner):
    token = _current.set((consumer, owner))
    try:
        yield
    finally:
        _current.reset(token)


def current(consumer):
    value = _current.get()
    return value[1] if value is not None and value[0] is consumer else None


class EventPublisher:
    def __init__(self, *, clock):
        self.clock = clock
        self.subs = set()
        self.event_log = deque(maxlen=4000)
        self.event_seq = 0
        self.last_poll = 0.0
        self.shutting_down = asyncio.Event()

    def broadcast(self, *, after_record, **event):
        event["ts"] = self.clock()
        self.event_seq += 1
        event["seq"] = self.event_seq
        self.event_log.append(event)
        # Hub's lane persistence runs after recording and before fan-out.
        after_record(event)
        dead = []
        for q in self.subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subs.discard(q)


EVENTS_KEY = web.AppKey("pixal.events", EventPublisher)
