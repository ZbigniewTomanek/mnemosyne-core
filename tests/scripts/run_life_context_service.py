import asyncio
from argparse import ArgumentParser
from datetime import datetime, timedelta

from telegram_bot.config import BotSettings
from telegram_bot.service.life_context import LifeContextRequest
from telegram_bot.service_factory import ServiceFactory


async def main() -> None:
    arg_parser = ArgumentParser(description="Run the Life Context Service to fetch and format life context data.")
    arg_parser.add_argument(
        "end_date",
        default=datetime.now().strftime("%Y-%m-%d"),
        type=str,
        help="Start date for the context (YYYY-MM-DD)",
    )
    arg_parser.add_argument("lookback_days", type=int, help="Number of days to look back from the end date")
    args = arg_parser.parse_args()

    bot_settings = BotSettings()

    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    start_date = end_date - timedelta(days=args.lookback_days)

    service_factory = ServiceFactory(bot_settings)
    result = await service_factory.life_context_service.build_context(
        request=LifeContextRequest(
            start_date=start_date,
            end_date=end_date,
        )
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
