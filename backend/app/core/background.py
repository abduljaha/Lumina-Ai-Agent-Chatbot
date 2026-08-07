"""Fire-and-forget background task tracking.

asyncio only holds a weak reference to tasks created via
`ensure_future`/`create_task` - without something else pinning a strong
reference, the task can be garbage-collected mid-flight before it
completes. `track()` is the documented workaround: hold a strong reference
in a module-level set until the task finishes, then let it go.
"""
from __future__ import annotations

import asyncio
from typing import Coroutine

_tasks: set[asyncio.Task] = set()


def track(coro: Coroutine) -> asyncio.Task:
    """Schedule `coro` to run without blocking the caller, and keep it alive."""
    task = asyncio.ensure_future(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task
