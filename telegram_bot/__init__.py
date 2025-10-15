from pathlib import Path

from dotenv import load_dotenv

env_file_path = Path(__file__).parent.parent / ".env"
if not env_file_path.exists():
    raise FileNotFoundError(f".env file not found at {env_file_path}!")
load_dotenv(env_file_path)
