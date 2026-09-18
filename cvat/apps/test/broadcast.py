# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
Fan-out helper between the writers and the WebSocket consumers.

Annotations are written by the HTTP workers and by RQ workers, each in its own
process. Those processes hold no WebSocket connections, so they cannot push
anything to a browser directly. Instead they publish a tiny invalidation
message - a task id, nothing more - onto the Redis channel layer. Every
consumer subscribed to that task then recomputes and pushes the result.

Publishing the id rather than the payload keeps the write path cheap: the
aggregate is computed once per connected viewer instead of once per write, and
a task nobody is watching costs a single Redis command.
"""

from __future__ import annotations

import logging
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)

CHANGE_MESSAGE_TYPE = "annotations.changed"
_GROUP_TEMPLATE = "test-analytics.task.{task_id}"
_THROTTLE_CACHE_LIMIT = 4096

# Per-process record of the last publish time for a task. Bulk deletes emit one
# post_delete signal per row, so without this a single "clear annotations" call
# would produce thousands of Redis round trips.
_last_published: dict[int, float] = {}


def group_name(task_id: int) -> str:
    return _GROUP_TEMPLATE.format(task_id=task_id)


def publish_task_changed(task_id: int | None, *, force: bool = False) -> None:
    if task_id is None:
        return

    now = time.monotonic()
    if not force:
        throttle = settings.TEST_ANALYTICS_PUBLISH_THROTTLE_SECONDS
        if now - _last_published.get(task_id, 0.0) < throttle:
            return

    if len(_last_published) > _THROTTLE_CACHE_LIMIT:
        _last_published.clear()
    _last_published[task_id] = now

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    try:
        async_to_sync(channel_layer.group_send)(
            group_name(task_id),
            {"type": CHANGE_MESSAGE_TYPE, "task_id": task_id},
        )
    except Exception:  # pragma: no cover - never break an annotation write
        # A broken analytics stream must not roll back the user's annotations.
        logger.warning("Could not publish analytics update for task %s", task_id, exc_info=True)
