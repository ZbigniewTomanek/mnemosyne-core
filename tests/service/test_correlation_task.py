from datetime import UTC, datetime
from uuid import uuid4

import pytest

from telegram_bot.config import CorrelationEngineConfig
from telegram_bot.scheduled_tasks.correlation_engine_task import CorrelationEngineTask
from telegram_bot.service.correlation_engine.models import CorrelationRunSummary


class StubScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(
        self,
        cron_expression,
        func,
        args=(),
        kwargs=None,
        *,
        job_id: str,
        display_name: str,
        description: str | None = None,
        metadata: dict | None = None,
    ):  # noqa: D401 - test stub
        self.jobs.append(
            {
                "cron": cron_expression,
                "func": func,
                "args": args,
                "kwargs": kwargs or {},
                "job_id": job_id,
                "display_name": display_name,
                "description": description,
                "metadata": metadata or {},
            }
        )


class StubJobRunner:
    def __init__(self):
        self.calls = 0

    async def run(self):
        self.calls += 1
        now = datetime.now(UTC)
        return CorrelationRunSummary(
            run_id=str(uuid4()),
            started_at=now,
            completed_at=now,
            user_id=12345,
            window_days=7,
            results=[],
            discarded_events=[],
            telemetry={},
        )


class StubBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})


@pytest.mark.asyncio
async def test_correlation_task_registers_job_when_enabled():
    config = CorrelationEngineConfig(enabled=True, cron="*/15 * * * *")
    runner = StubJobRunner()
    scheduler = StubScheduler()
    bot = StubBot()
    user_id = 12345

    task = CorrelationEngineTask(config=config, job_runner=runner, bot=bot, user_id=user_id)
    task.register_with_scheduler(scheduler)

    assert scheduler.jobs, "Job should be registered when enabled"
    job_info = scheduler.jobs[0]
    assert job_info["cron"] == "*/15 * * * *"
    func = job_info["func"]
    await func(*job_info["args"], **job_info["kwargs"])
    assert runner.calls == 1
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]["chat_id"] == user_id
    assert "✅" in bot.sent_messages[0]["text"]


def test_correlation_task_skips_when_disabled():
    config = CorrelationEngineConfig(enabled=False)
    runner = StubJobRunner()
    scheduler = StubScheduler()
    bot = StubBot()
    user_id = 12345

    task = CorrelationEngineTask(config=config, job_runner=runner, bot=bot, user_id=user_id)
    task.register_with_scheduler(scheduler)

    assert not scheduler.jobs
