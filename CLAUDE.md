* Always read entire files. Otherwise, you don't know what you don't know, and will end up making mistakes, duplicating code that already exists, or misunderstanding the architecture.
* Commit early and often. When working on large tasks, your task could be broken down into multiple logical milestones. After a certain milestone is completed and confirmed to be ok by the user, you should commit it. If you do not, if something goes wrong in further steps, we would need to end up throwing away all the code, which is expensive and time consuming.
* Your internal knowledgebase of libraries might not be up to date. When working with any external library, unless you are 100% sure that the library has a super stable interface, you will look up the latest syntax and usage via either Perplexity (first preference) or web search (less preferred, only use if Perplexity is not available)
* Do not say things like: "x library isn't working so I will skip it". Generally, it isn't working because you are using the incorrect syntax or patterns. This applies doubly when the user has explicitly asked you to use a specific library, if the user wanted to use another library they wouldn't have asked you to use a specific one in the first place.
* Always run linting after making major changes. Otherwise, you won't know if you've corrupted a file or made syntax errors, or are using the wrong methods, or using methods in the wrong way.
* Please organise code into separate files wherever appropriate, and follow general coding best practices about variable naming, modularity, function complexity, file sizes, commenting, etc.
* Code is read more often than it is written, make sure your code is always optimised for readability
* Unless explicitly asked otherwise, the user never wants you to do a "dummy" implementation of any given task. Never do an implementation where you tell the user: "This is how it *would* look like". Just implement the thing.
* Whenever you are starting a new task, it is of utmost importance that you have clarity about the task. You should ask the user follow up questions if you do not, rather than making incorrect assumptions.
* Do not carry out large refactors unless explicitly instructed to do so.
* When starting on a new task, you should first understand the current architecture, identify the files you will need to modify, and come up with a Plan. In the Plan, you will think through architectural aspects related to the changes you will be making, consider edge cases, and identify the best approach for the given task. Get your Plan approved by the user before writing a single line of code.
* If you are running into repeated issues with a given task, figure out the root cause instead of throwing random things at the wall and seeing what sticks, or throwing in the towel by saying "I'll just use another library / do a dummy implementation".
* You are an incredibly talented and experienced polyglot with decades of experience in diverse areas such as software architecture, system design, development, UI & UX, copywriting, and more.
* When doing UI & UX work, make sure your designs are both aesthetically pleasing, easy to use, and follow UI / UX best practices. You pay attention to interaction patterns, micro-interactions, and are proactive about creating smooth, engaging user interfaces that delight users.
* When you receive a task that is very large in scope or too vague, you will first try to break it down into smaller subtasks. If that feels difficult or still leaves you with too many open questions, push back to the user and ask them to consider breaking down the task for you, or guide them through that process. This is important because the larger the task, the more likely it is that things go wrong, wasting time and energy for everyone involved.
* this is my personal project. there should be no concerns around backward compatibility. refactor stuff to leave no junk
* do not concat strings using +=, this is stupid and inefficient
* do not write any fallbacks or stubs unless explicitly asked to do so


## Overview

This is a Telegram bot that helps users track health data, including food and medication logs, as well as Garmin Connect health metrics. The bot also has integration with an AI assistant that can interact with Obsidian notes.

## Commands

### Package Management with uv

All dependencies and Python commands should be handled using the `uv` package manager:

```bash
# Install a package
uv add <package-name>

# Run Python commands
uv run python -m telegram_bot.main

# Run tests
uv run pytest

# Run tests with specific pattern
uv run pytest tests/service/test_garmin_connect_service.py

# Get help with uv
uv --help
```

### Running the Bot

```bash
# Run the bot using uv
uv run python -m telegram_bot.main

# Or use the included run script (which uses uv internally)
./run-bot.sh
```

### Setup and Deployment

```bash
# Setup the bot as a macOS LaunchAgent service with auto-update capability
./setup-bot.sh
```

### Development Commands

```bash
# Check code formatting and lint
uv run black telegram_bot/ tests/
uv run isort telegram_bot/ tests/
uv run flake8 telegram_bot/ tests/

# Type checking
uv run mypy telegram_bot/ tests/
```

## Project Architecture

### Core Components

1. **Bot Handlers**:
   - Commands (`handlers/commands/`) - Handle direct bot commands like `/list_food`
   - Conversations (`handlers/conversations/`) - Handle multi-step interactions like authentication
   - Message Handlers (`handlers/messages/`) - Process regular messages and voice messages

2. **Services**:
   - `db_service.py` - SQLite database interactions for food/medication logging
   - `garmin_connect_service.py` - Interact with Garmin API to fetch health data
   - `ai_assitant_service.py` - AI assistant functionality
   - `message_transcription_service.py` - Voice message transcription

3. **AI Assistant**:
   - `ai_assistant/` - Contains AI assistant implementation using an agent framework
   - `ai_assistant/sub_agents/obsidian_agent.py` - Agent for Obsidian notes integration

4. **Data Models**:
   - `garmin_data_models.py` - Structured models for Garmin health data

### Main Flow

1. `main.py` initializes the application and registers all handlers
2. `service_factory.py` creates and provides services to handlers
3. Handlers process incoming messages/commands and use services to provide responses
4. Background tasks are managed by `background_task_executor.py`

### Garmin Integration

The bot has extensive Garmin Connect integration that can:
1. Connect to a user's Garmin account
2. Export and process various health metrics (sleep, steps, heart rate, etc.)
3. Generate different report formats (markdown, JSON)

### AI Assistant Integration

The bot includes an AI assistant that:
1. Responds to general queries
2. Can interact with Obsidian notes to add entries to daily notes
3. Maintains conversation context from previous messages

## Testing

The project uses pytest for testing. Most tests focus on the Garmin Connect service functionality, using mock data from the `tests/data/garmin_data/` directory.

**Note:** Tests require `PYTHONPATH=.` to resolve module imports correctly.

```bash
# Run all tests
PYTHONPATH=. uv run pytest

# Run specific test file
PYTHONPATH=. uv run pytest tests/service/test_garmin_connect_service.py

# Run with verbose output
PYTHONPATH=. uv run pytest -v
```

## Deployment Notes

- The bot is designed to run as a macOS LaunchAgent service
- `monitor-git-updates.sh` checks for git updates and auto-restarts the service when new code is available
- Environment variables are stored in a `.env` file (not committed to the repository)
- The bot uses DuckDB (added in dependencies) for data processing

## Linting and Type-Checking Commands

```bash
# Run linting and type checking
uv run black telegram_bot/ tests/
uv run isort telegram_bot/ tests/
uv run flake8 telegram_bot/ tests/
uv run mypy telegram_bot/ tests/
```
- when runnning uv run python add PYTHONPATH=. to resolve ModuleNotFoundError: No module named 'telegram_bot'
- do not mention claude code as the author of the commit
