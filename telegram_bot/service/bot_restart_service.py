import subprocess
from pathlib import Path

from loguru import logger


class BotRestartService:
    _RESTART_SCRIPT_PATH = Path(__file__).parents[2] / "update-and-restart.sh"

    @classmethod
    def restart(cls) -> None:
        logger.info("Restarting bot...")
        if not cls._RESTART_SCRIPT_PATH.exists():
            raise FileNotFoundError(f"Restart script not found: {cls._RESTART_SCRIPT_PATH}")
        subprocess.Popen([cls._RESTART_SCRIPT_PATH.resolve().as_posix()], start_new_session=True)
