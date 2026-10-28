"""Background job manager: persisted progress events, live fan-out, resume, cancellation."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from sqlalchemy import select

from app.db.models import ResearchEvent, ResearchJob
from app.db.session import session_factory

log = logging.getLogger(__name__)

TERMINAL_EVENTS = {"done", "error", "cancelled"}


class JobManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._approvals: dict[str, asyncio.Event] = {}
        self._approval_payload: dict[str, dict[str, Any]] = {}
        self._user_cancelled: set[str] = set()

    # ---- events -----------------------------------------------------------
    async def emit(self, job_id: str, type_: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = data or {}
        async with session_factory()() as session:
            row = ResearchEvent(job_id=job_id, type=type_, data=payload)
            session.add(row)
            await session.commit()
            event = {"id": row.id, "type": type_, "data": payload}
        for queue in list(self._subscribers.get(job_id, ())):
            queue.put_nowait(event)
        return event

    async def set_status(self, job_id: str, status: str, *, error: str | None = None, **fields: Any) -> None:
        async with session_factory()() as session:
            job = await session.get(ResearchJob, job_id)
            if job is None:
                return
            job.status = status
            if error is not None:
                job.error = error
            for key, value in fields.items():
                setattr(job, key, value)
            await session.commit()
        await self.emit(job_id, "status", {"status": status, **({"error": error} if error else {})})

    async def subscribe(self, job_id: str, after_id: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Replay persisted events after `after_id`, then stream live ones until a terminal event."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(job_id, set()).add(queue)
        try:
            last = after_id
            async with session_factory()() as session:
                rows = (
                    (
                        await session.execute(
                            select(ResearchEvent)
                            .where(ResearchEvent.job_id == job_id, ResearchEvent.id > after_id)
                            .order_by(ResearchEvent.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                job = await session.get(ResearchJob, job_id)
            for row in rows:
                last = row.id
                event = {"id": row.id, "type": row.type, "data": row.data}
                yield event
                if self._is_terminal(event):
                    return
            if job is None or (job.status in ("completed", "failed", "cancelled") and job_id not in self._tasks):
                # Job already finished (or was interrupted by a restart) with no further events coming.
                if (
                    job is not None
                    and job.status == "failed"
                    and not any(self._is_terminal({"type": r.type, "data": r.data}) for r in rows)
                ):
                    yield {"id": last, "type": "error", "data": {"message": job.error or "failed"}}
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {"id": None, "type": "ping", "data": {}}
                    continue
                event_id = int(event["id"] or 0)  # type: ignore[call-overload]
                if event_id <= last:
                    continue
                last = event_id
                yield event
                if self._is_terminal(event):
                    return
        finally:
            self._subscribers.get(job_id, set()).discard(queue)

    @staticmethod
    def _is_terminal(event: dict[str, Any]) -> bool:
        if event["type"] in TERMINAL_EVENTS:
            return True
        return event["type"] == "status" and event["data"].get("status") in ("cancelled",)

    # ---- tasks ------------------------------------------------------------
    def start(self, job_id: str, factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        task = asyncio.create_task(factory(), name=f"research-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))

    def is_running(self, job_id: str) -> bool:
        return job_id in self._tasks

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None:
            return False
        self._user_cancelled.add(job_id)
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except (asyncio.CancelledError, TimeoutError, Exception) as exc:
            log.debug("job %s ended during cancel: %s", job_id, type(exc).__name__)
        return True

    def cancelled_by_user(self, job_id: str) -> bool:
        return job_id in self._user_cancelled

    # ---- plan approval ----------------------------------------------------
    async def wait_for_approval(self, job_id: str) -> dict[str, Any]:
        event = self._approvals.setdefault(job_id, asyncio.Event())
        await event.wait()
        self._approvals.pop(job_id, None)
        return self._approval_payload.pop(job_id, {})

    def approve(self, job_id: str, payload: dict[str, Any]) -> bool:
        event = self._approvals.get(job_id)
        if event is None:
            return False
        self._approval_payload[job_id] = payload
        event.set()
        return True

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
