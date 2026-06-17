"""HITL polling helper for application-layer wait loops."""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from iris_core.hitl.models import HITLStatus
from iris_core.hitl.queue import HITLQueue


class HITLPoller:
    """
    Helper for applications that need to poll for HITL resolution.
    Handles the polling loop, timeout, and retry logic.
    """

    def __init__(self, review_id: str, queue: Optional[HITLQueue] = None):
        self.review_id = review_id
        self._queue = queue or HITLQueue()

    def wait(
        self,
        timeout: int = 300,
        poll_interval: int = 5,
        on_status_change: Optional[Callable[[HITLStatus], None]] = None,
    ) -> HITLStatus:
        deadline = time.time() + timeout
        last_status: Optional[HITLStatus] = None
        while time.time() < deadline:
            review = self._queue.get(self.review_id)
            if review is None:
                time.sleep(poll_interval)
                continue
            if review.status != last_status:
                if on_status_change:
                    on_status_change(review.status)
                last_status = review.status
            if review.status in (
                HITLStatus.APPROVED,
                HITLStatus.REJECTED,
                HITLStatus.TIMED_OUT,
                HITLStatus.ESCALATED,
            ):
                return review.status
            if self._queue.is_expired(review):
                resolved = self._queue.apply_timeout_policy(review)
                return resolved.status
            time.sleep(poll_interval)
        return HITLStatus.TIMED_OUT

    async def wait_async(
        self,
        timeout: int = 300,
        poll_interval: int = 5,
        on_status_change: Optional[Callable[[HITLStatus], None]] = None,
    ) -> HITLStatus:
        deadline = time.time() + timeout
        last_status: Optional[HITLStatus] = None
        while time.time() < deadline:
            review = self._queue.get(self.review_id)
            if review is None:
                await asyncio.sleep(poll_interval)
                continue
            if review.status != last_status:
                if on_status_change:
                    on_status_change(review.status)
                last_status = review.status
            if review.status in (
                HITLStatus.APPROVED,
                HITLStatus.REJECTED,
                HITLStatus.TIMED_OUT,
                HITLStatus.ESCALATED,
            ):
                return review.status
            if self._queue.is_expired(review):
                resolved = self._queue.apply_timeout_policy(review)
                return resolved.status
            await asyncio.sleep(poll_interval)
        return HITLStatus.TIMED_OUT
