# Copyright (C) 2026 Muhammad Saeed
#
# SPDX-License-Identifier: MIT

"""
WebSocket endpoint that streams class-distribution snapshots.

    ws(s)://<host>/ws/test/class-distribution/<task_id>/[?job_id=<id>]

Authentication rides on the existing CVAT session cookie, which the browser
attaches to a same-origin WebSocket handshake automatically. No token has to be
put in the URL, so the credential never reaches an access log.

Server frames
    ``snapshot``   full payload, identical to the REST response
    ``heartbeat``  application-level keepalive
    ``pong``       answer to a client ``ping``
    ``error``      ``code`` plus a human-readable ``detail``

Client frames
    ``ping``       liveness probe
    ``refresh``    ask for a snapshot now
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from .analytics import collect_class_distribution
from .broadcast import group_name
from .permissions import get_task_or_404, user_can_view_task

logger = logging.getLogger(__name__)

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_BAD_REQUEST = 4400


class ClassDistributionConsumer(AsyncWebsocketConsumer):
    task_id: int
    job_id: int | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._group: str | None = None
        self._dirty = False
        self._refresh_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # -- lifecycle -------------------------------------------------------

    async def connect(self) -> None:
        # Accept first, then validate. Closing before accepting makes the
        # browser report a bare handshake failure with no close code, which
        # leaves the client unable to tell "not allowed" from "server down" -
        # and those two need very different retry behaviour.
        await self.accept()

        try:
            self.task_id = int(self.scope["url_route"]["kwargs"]["task_id"])
        except (KeyError, TypeError, ValueError):
            await self._fail(CLOSE_BAD_REQUEST, "bad_request", "Malformed task id")
            return

        query = parse_qs(self.scope.get("query_string", b"").decode("utf-8", "ignore"))
        raw_job_id = (query.get("job_id") or [None])[0]
        if raw_job_id is not None:
            try:
                self.job_id = int(raw_job_id)
            except ValueError:
                await self._fail(CLOSE_BAD_REQUEST, "bad_request", "Malformed job id")
                return

        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self._fail(CLOSE_UNAUTHENTICATED, "unauthenticated", "Sign in to CVAT first")
            return

        task = await self._load_task()
        if task is None:
            await self._fail(CLOSE_NOT_FOUND, "not_found", f"Task {self.task_id} does not exist")
            return

        if not await self._check_permission(user, task):
            await self._fail(CLOSE_FORBIDDEN, "forbidden", "You cannot view this task")
            return

        self._group = group_name(self.task_id)
        await self.channel_layer.group_add(self._group, self.channel_name)

        await self._send_snapshot()
        self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def disconnect(self, code) -> None:
        for task in (self._heartbeat_task, self._refresh_task):
            if task is not None and not task.done():
                task.cancel()

        if self._group is not None and self.channel_layer is not None:
            await self.channel_layer.group_discard(self._group, self.channel_name)
            self._group = None

    # -- inbound ---------------------------------------------------------

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        if not text_data:
            return

        try:
            message = json.loads(text_data)
        except json.JSONDecodeError:
            await self._send({"type": "error", "code": "bad_request", "detail": "Invalid JSON"})
            return

        action = message.get("type")
        if action == "ping":
            await self._send({"type": "pong"})
        elif action == "refresh":
            await self._send_snapshot()

    async def annotations_changed(self, event: dict) -> None:
        """Channel-layer handler for ``broadcast.CHANGE_MESSAGE_TYPE``."""
        self._dirty = True
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._debounced_refresh())

    # -- outbound --------------------------------------------------------

    async def _debounced_refresh(self) -> None:
        """
        Collapse a burst of writes into one recomputation.

        Drawing ten boxes produces ten invalidations within a second. Without
        this, each one would trigger a full aggregate and a frame on the wire.
        """
        try:
            while self._dirty:
                self._dirty = False
                await asyncio.sleep(settings.TEST_ANALYTICS_DEBOUNCE_SECONDS)
                await self._send_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover
            logger.exception("Analytics refresh failed for task %s", self.task_id)

    async def _send_snapshot(self) -> None:
        try:
            payload = await self._compute()
        except Exception:
            logger.exception("Could not compute analytics for task %s", self.task_id)
            await self._send(
                {
                    "type": "error",
                    "code": "compute_failed",
                    "detail": "Statistics are temporarily unavailable",
                }
            )
            return

        await self._send({"type": "snapshot", "payload": payload})

    async def _heartbeat(self) -> None:
        interval = settings.TEST_ANALYTICS_HEARTBEAT_SECONDS
        try:
            while True:
                await asyncio.sleep(interval)
                await self._send({"type": "heartbeat"})
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover
            logger.debug("Heartbeat stopped for task %s", self.task_id, exc_info=True)

    async def _send(self, message: dict) -> None:
        try:
            await self.send(text_data=json.dumps(message))
        except Exception:
            # The peer vanished between the check and the write. Nothing to do.
            logger.debug("Dropped a frame for task %s", self.task_id, exc_info=True)

    async def _fail(self, close_code: int, code: str, detail: str) -> None:
        await self._send({"type": "error", "code": code, "detail": detail})
        await self.close(code=close_code)

    # -- database --------------------------------------------------------

    @database_sync_to_async
    def _load_task(self):
        from rest_framework.exceptions import NotFound

        try:
            return get_task_or_404(self.task_id)
        except NotFound:
            return None

    @database_sync_to_async
    def _check_permission(self, user, task) -> bool:
        return user_can_view_task(user, task)

    @database_sync_to_async
    def _compute(self) -> dict:
        task = get_task_or_404(self.task_id)
        return collect_class_distribution(task, job_id=self.job_id)
