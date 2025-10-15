from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from telegram_bot.service.scheduled_task_service import (
    ScheduledJobDescriptor,
    ScheduledJobRunOutcome,
    ScheduledTaskService,
)


class ScheduledJobsFacade:
    """High-level helper providing read/execute operations for scheduled jobs."""

    def __init__(self, scheduler: ScheduledTaskService) -> None:
        self._scheduler = scheduler

    def list_jobs(self) -> Sequence[ScheduledJobDescriptor]:
        return self._scheduler.list_jobs()

    def get_job(self, job_id: str) -> Optional[ScheduledJobDescriptor]:
        return self._scheduler.get_job_descriptor(job_id)

    async def run_job_now(self, job_id: str) -> ScheduledJobRunOutcome:
        return await self._scheduler.run_job_now(job_id)
