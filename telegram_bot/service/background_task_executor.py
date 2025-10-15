import asyncio
import inspect
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Generic, Optional, TypeVar, Union

from loguru import logger

T = TypeVar("T")


@dataclass
class TaskResult(Generic[T]):
    result: Optional[T] = None
    exception: Optional[Exception] = None
    was_async: bool = False
    task_name: Optional[str] = None


@dataclass
class TaskJob(Generic[T]):
    target_fn: Callable[..., Union[T, Awaitable[T]]]
    target_args: tuple[Any, ...] = field(default_factory=tuple)
    target_kwargs: dict[str, Any] = field(default_factory=dict)
    callback_fn: Optional[Callable[[TaskResult[T]], Union[None, Awaitable[None]]]] = None


class BackgroundTaskExecutor:
    """
    Manages a queue and worker pool for executing generic background tasks.
    CPU-bound tasks are run in a ProcessPoolExecutor, and their results (or exceptions)
    are passed to an asyncio callback function.
    """

    def __init__(self, num_async_workers: int = 2, num_cpu_workers: int = 1):
        """
        Initializes the BackgroundTaskExecutor.

        Args:
            num_async_workers: Number of asyncio tasks pulling from the queue to dispatch jobs.
            num_cpu_workers: Number of worker processes in the ProcessPoolExecutor
                             for CPU-bound tasks. This is the primary concurrency limit
                             for the actual heavy computation.
        """
        self._queue: asyncio.Queue[TaskJob[Any]] = asyncio.Queue()
        self._num_async_workers = num_async_workers

        # Ensure num_cpu_workers is at least 1
        if num_cpu_workers < 1:
            logger.warning(f"num_cpu_workers was {num_cpu_workers}, defaulting to 1.")
            num_cpu_workers = 1

        self._process_pool = ProcessPoolExecutor(max_workers=num_cpu_workers)
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._is_running = False

        logger.info(
            f"BackgroundTaskExecutor initialized with {num_async_workers} async workers "
            f"and {num_cpu_workers} CPU workers. Now supports async target functions."
        )

    async def _worker(self, worker_id: int) -> None:
        """
        An asyncio worker task that pulls jobs from the queue,
        executes them (sync via process pool or async directly), and then calls the callback.
        """
        logger.info(f"Async worker {worker_id} started for BackgroundTaskExecutor.")
        loop = asyncio.get_running_loop()

        while self._is_running:
            try:
                # Wait for a job with a timeout to allow checking self._is_running
                job: TaskJob[Any] = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue  # Check self._is_running again
            except asyncio.CancelledError:
                logger.info(f"Async worker {worker_id} received cancellation during queue.get().")
                break  # Exit if cancelled

            if not job:  # Should not happen if queue is managed properly, but as a safeguard
                self._queue.task_done()
                continue

            task_name = job.target_fn.__name__
            logger.info(f"Async worker {worker_id} picked up job for target: {task_name}")

            task_run_result: Any = None
            task_exception: Optional[Exception] = None
            is_async_target = inspect.iscoroutinefunction(job.target_fn)

            try:
                if is_async_target:
                    logger.debug(f"Executing async target function {task_name} in worker {worker_id}.")
                    # Directly await the async function
                    task_run_result = await job.target_fn(*job.target_args, **job.target_kwargs)
                else:
                    logger.debug(f"Executing sync target function {task_name} in process pool via worker {worker_id}.")
                    # Execute the CPU-bound/sync target function in the process pool
                    # run_in_executor doesn't support kwargs directly, so we use functools.partial
                    if job.target_kwargs:
                        partial_fn = partial(job.target_fn, *job.target_args, **job.target_kwargs)
                        task_run_result = await loop.run_in_executor(self._process_pool, partial_fn)
                    else:
                        task_run_result = await loop.run_in_executor(
                            self._process_pool, job.target_fn, *job.target_args
                        )
                logger.debug(
                    f"Target function {task_name} (async: {is_async_target}) "
                    f"completed successfully for worker {worker_id}."
                )
            except Exception as e:
                logger.exception(
                    f"Exception in target_fn {task_name} (async: {is_async_target}, worker {worker_id}): {e}"
                )
                task_exception = e

            final_task_result = TaskResult(
                result=task_run_result, exception=task_exception, was_async=is_async_target, task_name=task_name
            )

            if job.callback_fn:
                try:
                    logger.debug(f"Executing callback for {task_name} (worker {worker_id}).")
                    callback_result = job.callback_fn(final_task_result)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                except Exception as ce:
                    logger.exception(
                        f"Exception in callback_fn {getattr(job.callback_fn, '__name__', 'callback')} "
                        f"for target {task_name} (worker {worker_id}): {ce}"
                    )

            self._queue.task_done()
            logger.info(f"Async worker {worker_id} finished job for target: {task_name} (async: {is_async_target})")

        logger.info(f"Async worker {worker_id} for BackgroundTaskExecutor stopped.")

    async def add_task(
        self,
        target_fn: Callable[..., Union[T, Awaitable[T]]],
        target_args: tuple[Any, ...] = (),
        target_kwargs: Optional[dict[str, Any]] = None,
        callback_fn: Optional[Callable[[TaskResult[T]], Union[None, Awaitable[None]]]] = None,
    ) -> None:
        """
        Adds a new task to the processing queue.

        Args:
            target_fn: The sync or async function to execute.
            target_args: Positional arguments for target_fn.
            target_kwargs: Keyword arguments for target_fn.
            callback_fn: The sync or async function to call with the TaskResult.
                         Signature: def/async def my_callback(
                             task_result: TaskResult[T]
                         ) -> None/Awaitable[None]
        """
        if not self._is_running:
            raise RuntimeError("BackgroundTaskExecutor is not running. Please start it before adding tasks.")

        job: TaskJob[T] = TaskJob(
            target_fn=target_fn,
            target_args=target_args,
            target_kwargs=target_kwargs if target_kwargs is not None else {},
            callback_fn=callback_fn,
        )
        await self._queue.put(job)
        is_async_target = inspect.iscoroutinefunction(target_fn)
        logger.info(
            f"Added task for target {target_fn.__name__} (async: {is_async_target}) to "
            f"BackgroundTaskExecutor queue. Queue size: {self._queue.qsize()}"
        )

    async def start_workers(self) -> None:
        """
        Starts the asyncio worker tasks.
        """
        if self._is_running:
            logger.info("Workers are already running.")
            return

        self._is_running = True
        self._worker_tasks.clear()  # Clear any old tasks if restart is attempted (though not typical)
        for i in range(self._num_async_workers):
            task = asyncio.create_task(self._worker(i))
            self._worker_tasks.append(task)
        logger.info(f"Started {self._num_async_workers} async workers for BackgroundTaskExecutor.")

    async def stop_workers(self, wait_for_queue: bool = True) -> None:
        """
        Stops the asyncio worker tasks and shuts down the process pool.

        Args:
            wait_for_queue: If True, waits for all items currently in the queue
                            to be processed before stopping workers.
        """
        if not self._is_running:
            logger.info("Workers are not running.")
            return

        logger.info("Stopping BackgroundTaskExecutor workers...")

        if wait_for_queue and not self._queue.empty():
            logger.info(f"Waiting for {self._queue.qsize()} items in queue to be processed...")
            await self._queue.join()  # Wait for all queue items to be processed

        self._is_running = False  # Signal workers to stop

        # Wait for worker tasks to complete
        if self._worker_tasks:
            logger.info("Cancelling and gathering worker tasks...")
            for task in self._worker_tasks:
                task.cancel()
            # Wait for all tasks to acknowledge cancellation and finish
            results = await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, asyncio.CancelledError):
                    logger.debug(f"Worker task {i} cancelled successfully.")
                elif isinstance(result, Exception):
                    logger.error(f"Worker task {i} raised an exception during shutdown: {result}")
            self._worker_tasks.clear()
            logger.info("All async worker tasks have been stopped.")

        # Shutdown the process pool
        logger.info("Shutting down process pool...")
        self._process_pool.shutdown(wait=True)  # wait=True ensures all child processes finish
        logger.info("Process pool shut down.")
        logger.info("BackgroundTaskExecutor workers stopped.")
