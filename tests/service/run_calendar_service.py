import asyncio

from telegram_bot.service.calendar_service.calendar_service import CalendarConfig, CalendarService
from telegram_bot.service.calendar_service.exceptions import CalendarBackendError
from telegram_bot.service.calendar_service.models import CalendarEventsResult


async def main() -> None:
    calendar_service = CalendarService(config=CalendarConfig())
    try:
        events: CalendarEventsResult = await calendar_service.get_today_events()
        print(events.model_dump_json())
    except CalendarBackendError as e:
        # Print error in a predictable JSON form for manual runs
        print({"error": str(e)})


if __name__ == "__main__":
    asyncio.run(main())
