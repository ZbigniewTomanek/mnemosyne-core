import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Coroutine, Literal, Optional, Union

import aiocron
from loguru import logger

from telegram_bot.service.background_task_executor import BackgroundTaskExecutor, TaskResult

TargetFunction = Callable[..., Any]
AsyncScheduledCoroutine = Callable[..., Coroutine[Any, Any, None]]
GenericCallback = Callable[[TaskResult[Any]], Union[None, Awaitable[None]]]


@dataclass(frozen=True)
class ScheduledJobDescriptor:
    job_id: str
    display_name: str
    schedule: str
    description: Optional[str] = None
    job_type: Literal["async", "background"] = "async"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduledJobRunOutcome:
    job_id: str
    display_name: str
    success: bool
    message: str


@dataclass
class _ScheduledJobEntry:
    descriptor: ScheduledJobDescriptor
    cron_handle: aiocron.Cron
    runner: Callable[[], Awaitable[ScheduledJobRunOutcome]]


class ScheduledTaskService:
    """
    Manages and executes scheduled tasks (cron jobs) using aiocron.
    Can schedule lightweight async tasks directly or submit tasks (sync or async)
    to a BackgroundTaskExecutor.
    """

    def __init__(self, background_task_executor: Optional[BackgroundTaskExecutor] = None):
        """
        Initializes the ScheduledTaskService.

        Args:
            background_task_executor: Optional BackgroundTaskExecutor to offload/manage tasks.
        """
        self._cron_jobs: list[aiocron.Cron] = []
        self._job_entries: dict[str, _ScheduledJobEntry] = {}
        self._background_task_executor = background_task_executor
        self._is_running = False
        logger.info("ScheduledTaskService initialized.")

    def add_job(
        self,
        cron_expression: str,
        func: AsyncScheduledCoroutine,
        args: tuple = (),
        kwargs: Optional[dict[str, Any]] = None,
        *,
        job_id: str,
        display_name: str,
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Adds a new lightweight asynchronous job to be scheduled and run directly by aiocron.

        Args:
            cron_expression: The cron expression (e.g., "*/5 * * * *" for every 5 minutes).
                             Supports seconds: "*/30 * * * * *" for every 30 seconds.
            func: The asynchronous function (coroutine) to execute.
            args: Positional arguments to pass to the function.
            kwargs: Keyword arguments to pass to the function.
            job_id: Unique identifier for the job (used for lookup and manual runs).
            display_name: Human readable name shown in UIs.
            description: Optional longer description for the job tile.
            metadata: Optional free-form metadata for consumers.
        """
        if not inspect.iscoroutinefunction(func):
            logger.error(
                f"Function {func.__name__} for 'add_job' must be an async function. "
                f"For sync functions, use 'add_job_to_background_executor'."
            )
            return
        if kwargs is None:
            kwargs = {}

        if job_id in self._job_entries:
            logger.error(f"Duplicate scheduled job_id detected: {job_id}")
            raise ValueError(f"Scheduled job with id '{job_id}' already exists")

        info_metadata = {
            "function_name": func.__name__,
            "args": args,
            "kwargs": kwargs,
        }
        if metadata:
            info_metadata.update(metadata)

        descriptor = ScheduledJobDescriptor(
            job_id=job_id,
            display_name=display_name,
            schedule=cron_expression,
            description=description,
            job_type="async",
            metadata=info_metadata,
        )

        async def run_job() -> ScheduledJobRunOutcome:
            logger.info(f"Manually executing scheduled async task {func.__name__} with args: {args}, kwargs: {kwargs}")
            try:
                await func(*args, **kwargs)
                message = f"Scheduled async task {func.__name__} completed successfully."
                logger.info(message)
                return ScheduledJobRunOutcome(job_id=job_id, display_name=display_name, success=True, message=message)
            except Exception as e:
                logger.exception(f"Error executing scheduled async task {func.__name__}: {e}")
                return ScheduledJobRunOutcome(
                    job_id=job_id,
                    display_name=display_name,
                    success=False,
                    message=str(e),
                )

        async def job_wrapper():
            await run_job()

        cron_job = aiocron.crontab(cron_expression, func=job_wrapper, start=True)
        self._cron_jobs.append(cron_job)
        self._job_entries[job_id] = _ScheduledJobEntry(
            descriptor=descriptor,
            cron_handle=cron_job,
            runner=run_job,
        )
        logger.info(
            f"Added direct async scheduled job: '{func.__name__}' with schedule '{cron_expression}' and id '{job_id}'"
        )

    def add_job_to_background_executor(
        self,
        cron_expression: str,
        target_fn: TargetFunction,
        target_args: tuple = (),
        target_kwargs: Optional[dict[str, Any]] = None,
        callback_fn: Optional[GenericCallback] = None,
        *,
        job_id: str,
        display_name: str,
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Adds a new job that, when triggered by cron, enqueues a task
        into the BackgroundTaskExecutor. The target_fn can be synchronous
        (will run in process pool) or asynchronous (will be awaited by executor's async workers).

        Args:
            cron_expression: The cron expression.
            target_fn: The sync or async function to be executed by the BackgroundTaskExecutor.
            target_args: Positional arguments for target_fn.
            target_kwargs: Keyword arguments for target_fn.
            callback_fn: Optional callback (sync or async) to handle the TaskResult.
                         Signature: (task_result: TaskResult) -> None or Awaitable[None]
        """
        if self._background_task_executor is None:
            logger.error("BackgroundTaskExecutor not provided. Cannot add job to background executor.")
            return
        if target_kwargs is None:
            target_kwargs = {}

        if job_id in self._job_entries:
            logger.error(f"Duplicate scheduled job_id detected: {job_id}")
            raise ValueError(f"Scheduled job with id '{job_id}' already exists")

        info_metadata = {
            "function_name": target_fn.__name__,
            "args": target_args,
            "kwargs": target_kwargs,
            "callback": getattr(callback_fn, "__name__", None),
        }
        if metadata:
            info_metadata.update(metadata)

        descriptor = ScheduledJobDescriptor(
            job_id=job_id,
            display_name=display_name,
            schedule=cron_expression,
            description=description,
            job_type="background",
            metadata=info_metadata,
        )

        async def _enqueue(source: str) -> ScheduledJobRunOutcome:
            logger.info(f"{source.capitalize()} trigger for {target_fn.__name__}. Enqueuing to BackgroundTaskExecutor.")
            try:
                await self._background_task_executor.add_task(
                    target_fn=target_fn,
                    target_args=target_args,
                    target_kwargs=target_kwargs,
                    callback_fn=callback_fn,
                )
                message = (
                    f"Task {target_fn.__name__} "
                    f"(async: {inspect.iscoroutinefunction(target_fn)}) enqueued successfully."
                )
                logger.info(message)
                return ScheduledJobRunOutcome(
                    job_id=job_id,
                    display_name=display_name,
                    success=True,
                    message=message,
                )
            except Exception as e:
                logger.exception(f"Error enqueuing task {target_fn.__name__} from {source}: {e}")
                return ScheduledJobRunOutcome(
                    job_id=job_id,
                    display_name=display_name,
                    success=False,
                    message=str(e),
                )

        async def run_job() -> ScheduledJobRunOutcome:
            return await _enqueue("manual")

        async def enqueue_task_wrapper():
            await _enqueue("cron")

        cron_job = aiocron.crontab(cron_expression, func=enqueue_task_wrapper, start=True)
        self._cron_jobs.append(cron_job)
        self._job_entries[job_id] = _ScheduledJobEntry(
            descriptor=descriptor,
            cron_handle=cron_job,
            runner=run_job,
        )
        logger.info(
            f"Added BackgroundTaskExecutor job: '{target_fn.__name__}' "
            f"(async: {inspect.iscoroutinefunction(target_fn)}) with schedule '{cron_expression}' and id '{job_id}'"
        )

    def list_jobs(self) -> list[ScheduledJobDescriptor]:
        """Return descriptors for all registered jobs sorted by display name."""
        return sorted((entry.descriptor for entry in self._job_entries.values()), key=lambda d: d.display_name)

    def get_job_descriptor(self, job_id: str) -> Optional[ScheduledJobDescriptor]:
        entry = self._job_entries.get(job_id)
        return entry.descriptor if entry else None

    async def run_job_now(self, job_id: str) -> ScheduledJobRunOutcome:
        """Execute the scheduled job immediately."""
        entry = self._job_entries.get(job_id)
        if entry is None:
            raise KeyError(f"Scheduled job with id '{job_id}' not found")
        return await entry.runner()

    async def start(self) -> None:
        """
        Ensures the ScheduledTaskService is marked as running.
        aiocron jobs typically start upon creation if `start=True` (default when func is provided).
        This method is idempotent.
        """
        if self._is_running:
            logger.info("ScheduledTaskService is already running.")
            return

        if not self._job_entries:
            logger.info("No scheduled jobs to start.")
            self._is_running = True
            logger.info("ScheduledTaskService started (no jobs registered).")
            return

        job_count = len(self._job_entries)
        logger.info(f"ScheduledTaskService starting with {job_count} jobs (jobs auto-start via aiocron).")
        self._is_running = True
        logger.info("ScheduledTaskService is now active.")

    async def stop(self) -> None:
        """
        Stops all registered cron jobs by calling their `stop()` or `cancel()` method.
        This method is idempotent.
        """
        if not self._is_running:
            logger.info("ScheduledTaskService is not running or already stopped.")
            return

        logger.info(f"Stopping {len(self._cron_jobs)} scheduled jobs...")
        for job in self._cron_jobs:
            try:
                job.stop()
                logger.debug(f"Stopped job: {job}")
            except AttributeError:
                logger.warning(f"Job {job} does not have a stop method, trying cancel().")
                if hasattr(job, "cancel"):
                    job.cancel()
                    logger.debug(f"Cancelled job: {job}")
                else:
                    logger.error(f"Could not stop or cancel job: {job}")
            except Exception as e:
                logger.exception(f"Error stopping/cancelling job {job}: {e}")

        self._cron_jobs.clear()
        self._job_entries.clear()
        self._is_running = False
        logger.info("ScheduledTaskService stopped and all jobs cancelled/cleared.")
