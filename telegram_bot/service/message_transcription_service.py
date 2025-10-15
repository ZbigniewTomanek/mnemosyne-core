# telegram_bot/service/message_transcription_service.py
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel
from faster_whisper.transcribe import Segment, TranscriptionInfo
from loguru import logger

from telegram_bot.config import WhisperSettings
from telegram_bot.service.background_task_executor import BackgroundTaskExecutor, TaskResult


@dataclass
class TranscriptionResult:
    duration: timedelta
    segments: list[Segment]  # Use List from typing for clarity
    info: TranscriptionInfo


# 1. Define the transcription logic as a top-level function.
# This function will be executed in a separate process.
def _execute_transcription_task(audio_file_path_str: str, whisper_settings_dict: dict[str, Any]) -> TranscriptionResult:
    """
    Performs audio transcription in a worker process.
    Initializes its own WhisperModel instance.
    """
    # If using loguru, ensure it's configured for multiprocessing (e.g., enqueue=True for relevant sinks)
    # or use print() for debugging in worker processes if logging is problematic.
    logger.info(f"[Worker] Initializing WhisperModel. Settings: {whisper_settings_dict.get('model_size', 'N/A')}")
    whisper_settings = WhisperSettings(**whisper_settings_dict)

    model = WhisperModel(
        model_size_or_path=whisper_settings.model_size,
        device=whisper_settings.device,
        compute_type=whisper_settings.compute_type,
        cpu_threads=whisper_settings.cpu_threads,
        num_workers=whisper_settings.num_workers,
        download_root=whisper_settings.download_root.as_posix(),
        local_files_only=whisper_settings.local_files_only,
    )

    logger.info(f"[Worker] Starting transcription for: {audio_file_path_str}")
    start_time = datetime.now()

    segment_iterator, info_obj = model.transcribe(audio_file_path_str, beam_size=5)  # beam_size is an example parameter

    processed_segments: list[Segment] = []
    for segment in segment_iterator:
        logger.debug(f"[Worker] Segment: [{segment.start:.2f}s -> {segment.end:.2f}s]")
        processed_segments.append(segment)

    duration = datetime.now() - start_time
    logger.info(
        f"[Worker] Transcription finished in {duration.total_seconds():.2f}s. Found {len(processed_segments)} segments."
    )

    del model

    return TranscriptionResult(
        duration=duration,
        segments=processed_segments,
        info=info_obj,
    )


class MessageTranscriptionService:
    def __init__(self, background_task_executor: BackgroundTaskExecutor, whisper_settings: WhisperSettings) -> None:
        self.background_task_executor = background_task_executor
        self.whisper_settings = whisper_settings
        logger.info(
            f"MessageTranscriptionService initialized. Whisper model "
            f"'{self.whisper_settings.model_size}' will be loaded in worker processes."
        )

    async def transcribe_message(self, tmp_audio_file: Path, callback: Callable[[TaskResult], Awaitable[None]]) -> None:
        settings_dict = json.loads(self.whisper_settings.model_dump_json())
        logger.debug(f"Adding transcription task to queue for audio file: '{tmp_audio_file}'")

        await self.background_task_executor.add_task(
            target_fn=_execute_transcription_task,
            target_args=(str(tmp_audio_file), settings_dict),
            callback_fn=callback,
        )
