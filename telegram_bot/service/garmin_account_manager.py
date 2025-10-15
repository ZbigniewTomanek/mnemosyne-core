from pathlib import Path
from typing import Optional

from garminconnect import Garmin, GarminConnectAuthenticationError
from garth.exc import GarthHTTPError
from loguru import logger


class GarminAccountManager:
    """Manages Garmin account associations and tokens for Telegram users."""

    def __init__(self, token_store_dir: Path):
        """
        Initialize the GarminAccountManager.

        Args:
            token_store_dir: Directory path to store Garmin Connect tokens.
                             Each Telegram user will have their own subdirectory.
        """
        self.token_store_dir = token_store_dir
        self.token_store_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized GarminAccountManager with token_store_dir: {token_store_dir}")

    def get_user_token_path(self, telegram_user_id: int) -> Path:
        """
        Returns the path to a user's token directory.

        Args:
            telegram_user_id: The Telegram user ID to get token path for.

        Returns:
            Path to the user's token directory.
        """
        return self.token_store_dir / str(telegram_user_id)

    def is_authenticated(self, telegram_user_id: int) -> bool:
        """
        Check if a Telegram user has a valid Garmin Connect token.

        Args:
            telegram_user_id: The Telegram user ID to check.

        Returns:
            True if the user has authentication tokens, False otherwise.
        """
        user_token_path = self.get_user_token_path(telegram_user_id)
        # Check if directory exists and contains token files
        is_auth = user_token_path.exists() and any(user_token_path.iterdir())
        logger.debug(f"User {telegram_user_id} authentication status: {is_auth}")
        return is_auth

    def create_client(self, telegram_user_id: int) -> Optional[Garmin]:
        """
        Create a Garmin client for the specified Telegram user.

        Args:
            telegram_user_id: The Telegram user ID to create client for.

        Returns:
            A configured Garmin client instance if authentication is successful,
            None otherwise.
        """
        if not self.is_authenticated(telegram_user_id):
            logger.warning(f"User {telegram_user_id} is not authenticated with Garmin Connect")
            return None

        user_token_path = self.get_user_token_path(telegram_user_id)
        logger.debug(f"Creating Garmin client for user {telegram_user_id} using token path: {user_token_path}")

        try:
            # Use the existing login function with the user's token path
            garmin = Garmin()
            garmin.login(user_token_path.as_posix())
            logger.info(f"Successfully created Garmin client for user {telegram_user_id}")
            return garmin
        except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError) as e:
            logger.error(f"Failed to create Garmin client for user {telegram_user_id}: {str(e)}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error creating Garmin client for user {telegram_user_id}: {str(e)}")
            return None
