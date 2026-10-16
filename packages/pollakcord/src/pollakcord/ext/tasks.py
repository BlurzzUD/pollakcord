from __future__ import annotations

import asyncio
import copy
import inspect
import math
from datetime import datetime, timedelta, timezone
from types import MethodType


class Loop:
    def __init__(self, callback, *, seconds: float = 0, minutes: float = 0, hours: float = 0, count: int | None = None) -> None:
        if not inspect.iscoroutinefunction(callback):
            raise TypeError("Task loops require async functions")
        self.coro = callback
        self.count = count
        if count is not None and (type(count) is not int or count < 1):
            raise ValueError("count must be a positive integer or None")
        self.change_interval(seconds=seconds, minutes=minutes, hours=hours)
        self._task: asyncio.Task | None = None
        self._before = None
        self._after = None
        self._error = None
        self._stop = False
        self._failed = False
        self.current_loop = 0
        self.next_iteration: datetime | None = None

    def __get__(self, instance, owner):
        if instance is None:
            return self
        key = "__pollak_loop_" + self.coro.__name__
        if key not in instance.__dict__:
            bound = copy.copy(self)
            bound.coro = MethodType(self.coro, instance)
            bound._before = MethodType(self._before, instance) if self._before else None
            bound._after = MethodType(self._after, instance) if self._after else None
            bound._error = MethodType(self._error, instance) if self._error else None
            bound._task = None
            instance.__dict__[key] = bound
        return instance.__dict__[key]

    def change_interval(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        interval = seconds + minutes * 60 + hours * 3600
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("Task intervals must be nonnegative finite numbers")
        self.seconds, self.minutes, self.hours = seconds, minutes, hours
        self._interval = interval

    def start(self, *args, **kwargs) -> asyncio.Task:
        if self.is_running():
            raise RuntimeError("This task loop is already running")
        self._stop = False
        self._failed = False
        self.current_loop = 0
        self._task = asyncio.create_task(self._run(args, kwargs))
        return self._task

    async def _run(self, args, kwargs) -> None:
        try:
            if self._before:
                await self._before()
            while not self._stop:
                started = asyncio.get_running_loop().time()
                await self.coro(*args, **kwargs)
                self.current_loop += 1
                if self._stop or self.count is not None and self.current_loop >= self.count:
                    break
                delay = max(0, self._interval - (asyncio.get_running_loop().time() - started))
                self.next_iteration = datetime.now(timezone.utc) + timedelta(seconds=delay)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._failed = True
            if self._error:
                await self._error(error)
            else:
                raise
        finally:
            self.next_iteration = None
            if self._after:
                await self._after()

    async def __call__(self, *args, **kwargs):
        return await self.coro(*args, **kwargs)

    def before_loop(self, callback):
        self._before = callback
        return callback

    def after_loop(self, callback):
        self._after = callback
        return callback

    def error(self, callback):
        self._error = callback
        return callback

    def get_task(self) -> asyncio.Task | None:
        return self._task

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def failed(self) -> bool:
        return self._failed

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()

    def stop(self) -> None:
        self._stop = True


def loop(*, seconds: float = 0, minutes: float = 0, hours: float = 0, count: int | None = None):
    def decorator(callback):
        return Loop(callback, seconds=seconds, minutes=minutes, hours=hours, count=count)
    return decorator
