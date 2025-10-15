from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.life_context.models import LifeContextFormattedResponse, LifeContextMetric, LifeContextRequest
from telegram_bot.service.life_context.service import LifeContextService
from telegram_bot.utils import escape_markdown_v1

SELECT_METRICS, CUSTOM_METRICS, SELECT_PERIOD, CUSTOM_START, CUSTOM_END, SELECT_FORMAT = range(6)

# Maximum date range allowed for exports (days)
MAX_EXPORT_RANGE_DAYS = 120

_METRIC_PRESETS: dict[str, Iterable[LifeContextMetric]] = {
    "all": LifeContextMetric.all_metrics(),
    "daily": (
        LifeContextMetric.NOTES,
        LifeContextMetric.GARMIN,
        LifeContextMetric.CALENDAR,
        LifeContextMetric.PERSISTENT_MEMORY,
    ),
    "notes": (
        LifeContextMetric.NOTES,
        LifeContextMetric.PERSISTENT_MEMORY,
    ),
    "insights": (
        LifeContextMetric.GARMIN,
        LifeContextMetric.CORRELATIONS,
        LifeContextMetric.VARIANCE,
    ),
}


class LifeContextExportHandler(PrivateHandler):
    def __init__(self, life_context_service: LifeContextService, tz: ZoneInfo) -> None:
        super().__init__()
        self._life_context_service = life_context_service
        self._tz = tz

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        assert update.message is not None
        assert context.user_data is not None
        self._initialise_defaults(context)
        await update.message.reply_text(
            "📊 *Life context export*\n\n"
            "I'll prepare a downloadable report with your selected metrics.\n"
            "Default: *all metrics* for the last *7 days* as Markdown.\n"
            "Choose a quick preset or pick exactly what you need:",
            reply_markup=self._metric_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return SELECT_METRICS

    def _initialise_defaults(self, context: CallbackContext) -> None:
        assert context.user_data is not None
        start, end = self._default_range()
        context.user_data["metrics"] = set(LifeContextMetric.all_metrics())
        context.user_data["metrics_label"] = "All metrics"
        context.user_data["start_date"] = start
        context.user_data["end_date"] = end
        context.user_data["format"] = "markdown"

    def _metric_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("✅ All metrics", callback_data="metrics_all")],
            [InlineKeyboardButton("🗂 Daily snapshot", callback_data="metrics_daily")],
            [InlineKeyboardButton("📝 Notes focus", callback_data="metrics_notes")],
            [InlineKeyboardButton("📈 Insights only", callback_data="metrics_insights")],
            [InlineKeyboardButton("🎛 Custom selection", callback_data="metrics_custom")],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def select_metrics(self, update: Update, context: CallbackContext) -> int:
        assert update.callback_query is not None
        assert context.user_data is not None
        query = update.callback_query
        assert query.data is not None
        await query.answer()

        selection = query.data.replace("metrics_", "")
        if selection == "custom":
            await query.edit_message_text(
                "Type the metrics you want separated by commas (e.g. `notes, garmin, calendar`).\n\n"
                "Available: notes, garmin, calendar, correlations, variance, persistent_memory, all",
                parse_mode=ParseMode.MARKDOWN,
            )
            return CUSTOM_METRICS

        metrics = self._resolve_preset(selection)
        if metrics is None:
            await query.edit_message_text("Unknown selection, please try again.")
            return SELECT_METRICS

        context.user_data["metrics"] = metrics
        context.user_data["metrics_label"] = self._preset_label(selection)

        await query.edit_message_text(
            f"Great! We'll use *{context.user_data['metrics_label']}*." "\nNow pick a period:",
            reply_markup=self._period_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return SELECT_PERIOD

    def _resolve_preset(self, selection: str) -> set[LifeContextMetric] | None:
        preset = _METRIC_PRESETS.get(selection)
        if preset is None:
            return None
        return {metric if isinstance(metric, LifeContextMetric) else LifeContextMetric(metric) for metric in preset}

    def _preset_label(self, selection: str) -> str:
        labels = {
            "all": "All metrics",
            "daily": "Daily snapshot",
            "notes": "Notes focus",
            "insights": "Insights only",
            "custom": "Custom selection",
        }
        return labels.get(selection, selection.capitalize())

    async def receive_custom_metrics(self, update: Update, context: CallbackContext) -> int:
        assert update.message is not None
        assert context.user_data is not None
        choices = self._parse_metric_input(update.message.text)
        if choices is None:
            await update.message.reply_text(
                "Couldn't understand that. Please list metrics separated by commas (e.g. `notes, garmin`).\n"
                "Valid options: notes, garmin, calendar, correlations, variance, persistent_memory, all",
                parse_mode=ParseMode.MARKDOWN,
            )
            return CUSTOM_METRICS

        context.user_data["metrics"] = choices
        context.user_data["metrics_label"] = self._format_metric_list(sorted(m.value for m in choices))

        await update.message.reply_text(
            "Nice! Now choose the time period to export:", reply_markup=self._period_keyboard()
        )
        return SELECT_PERIOD

    def _parse_metric_input(self, raw: str | None) -> set[LifeContextMetric] | None:
        if not raw:
            return None
        cleaned = raw.strip().lower()
        if cleaned == "all":
            return set(LifeContextMetric.all_metrics())

        separators = "," if "," in cleaned else None
        parts = [part.strip() for part in cleaned.split(separators)] if separators else cleaned.split()
        metrics: set[LifeContextMetric] = set()
        valid_names = {metric.value: metric for metric in LifeContextMetric}
        for part in parts:
            if not part:
                continue
            metric = valid_names.get(part)
            if metric is None:
                return None
            metrics.add(metric)
        return metrics or None

    def _period_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("Last 7 days", callback_data="period_7")],
            [InlineKeyboardButton("Last 14 days", callback_data="period_14")],
            [InlineKeyboardButton("Last 30 days", callback_data="period_30")],
            [InlineKeyboardButton("This month", callback_data="period_month")],
            [InlineKeyboardButton("Custom range", callback_data="period_custom")],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def select_period(self, update: Update, context: CallbackContext) -> int:
        assert update.callback_query is not None
        assert context.user_data is not None
        query = update.callback_query
        assert query.data is not None
        await query.answer()

        selection = query.data.replace("period_", "")
        if selection == "custom":
            await query.edit_message_text(
                "Send the start date (YYYY-MM-DD). You can also type `today` or `yesterday`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return CUSTOM_START

        start, end = self._resolve_period(selection)
        context.user_data["start_date"] = start
        context.user_data["end_date"] = end

        await query.edit_message_text(
            f"Period set to *{self._period_label(selection, start, end)}*.\nSelect export format:",
            reply_markup=self._format_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return SELECT_FORMAT

    def _resolve_period(self, selection: str) -> tuple[date, date]:
        today = self._today()
        if selection == "month":
            start = today.replace(day=1)
            return start, today
        try:
            days = int(selection)
        except ValueError:
            logger.warning("Unknown period selection: %s", selection)
            return self._default_range()
        end = today
        start = end - timedelta(days=days - 1)
        return start, end

    def _period_label(self, selection: str, start: date, end: date) -> str:
        labels = {
            "7": "last 7 days",
            "14": "last 14 days",
            "30": "last 30 days",
            "month": "this month",
            "custom": f"{start.isoformat()} → {end.isoformat()}",
        }
        return labels.get(selection, f"{start.isoformat()} → {end.isoformat()}")

    async def receive_custom_start(self, update: Update, context: CallbackContext) -> int:
        assert update.message is not None
        assert context.user_data is not None
        parsed = self._parse_date_input(update.message.text)
        if parsed is None:
            await update.message.reply_text(
                "Couldn't parse that date. Please enter start date in YYYY-MM-DD (or type `today`).",
                parse_mode=ParseMode.MARKDOWN,
            )
            return CUSTOM_START

        context.user_data["start_date"] = parsed
        await update.message.reply_text("Great. Now send the end date (YYYY-MM-DD). You can also type `today`.")
        return CUSTOM_END

    async def receive_custom_end(self, update: Update, context: CallbackContext) -> int:
        assert update.message is not None
        assert context.user_data is not None
        parsed = self._parse_date_input(update.message.text)
        if parsed is None:
            await update.message.reply_text(
                "Couldn't parse that date. Please enter end date in YYYY-MM-DD (or type `today`).",
                parse_mode=ParseMode.MARKDOWN,
            )
            return CUSTOM_END

        start = context.user_data.get("start_date")
        if not isinstance(start, date):
            start = self._today()
            context.user_data["start_date"] = start

        if parsed < start:
            await update.message.reply_text("End date must be on or after start date. Try again.")
            return CUSTOM_END
        if (parsed - start).days > MAX_EXPORT_RANGE_DAYS:
            await update.message.reply_text(
                f"Range too long (max {MAX_EXPORT_RANGE_DAYS} days). Please choose a closer end date."
            )
            return CUSTOM_END

        context.user_data["end_date"] = parsed
        await update.message.reply_text(
            f"We'll export from {start.isoformat()} to {parsed.isoformat()}. Choose the format:",
            reply_markup=self._format_keyboard(),
        )
        return SELECT_FORMAT

    def _format_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("Markdown (.md)", callback_data="format_markdown")],
            [InlineKeyboardButton("JSON (.json)", callback_data="format_json")],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def select_format(self, update: Update, context: CallbackContext) -> int:
        assert update.callback_query is not None
        assert context.user_data is not None
        query = update.callback_query
        assert query.data is not None
        await query.answer()

        selection = query.data.replace("format_", "")
        context.user_data["format"] = selection

        await query.edit_message_text("Generating your export…")
        await self._generate_and_send_export(update, context)
        context.user_data.clear()
        return ConversationHandler.END

    async def _generate_and_send_export(self, update: Update, context: CallbackContext) -> None:
        assert update.effective_chat is not None
        assert context.user_data is not None
        metrics: set[LifeContextMetric] = context.user_data.get("metrics", set(LifeContextMetric.all_metrics()))
        start: date = context.user_data.get("start_date", self._default_range()[0])
        end: date = context.user_data.get("end_date", self._default_range()[1])
        export_format: str = context.user_data.get("format", "markdown")

        request = LifeContextRequest(
            start_date=start,
            end_date=end,
            metrics=frozenset(metrics),
        )

        try:
            response = await self._life_context_service.build_context(request)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to build life context: %s", exc)
            await self._notify_failure(update, context, f"⚠️ Export failed: {exc}")
            return

        if response.error:
            await self._notify_failure(update, context, f"⚠️ Export error: {response.error}")
            return

        if export_format == "json":
            content = self._build_json_payload(response, metrics)
            suffix = ".json"
        else:
            content = self._build_markdown_document(response, metrics)
            suffix = ".md"

        filename = self._build_filename(export_format, start, end)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, delete=False) as tmp_file:
            tmp_file.write(content)
            temp_path = Path(tmp_file.name)

        try:
            with temp_path.open("rb") as file:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=file,
                    filename=filename,
                )

            summary_markdown = self._export_summary(metrics, start, end, export_format, markdown_safe=True)
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=summary_markdown,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as exc:  # pragma: no cover - network interaction
                logger.error("Failed to send markdown summary for life context export: %s", exc)
                summary_plain = self._export_summary(metrics, start, end, export_format, markdown_safe=False)
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=summary_plain,
                    )
                except Exception as fallback_exc:  # pragma: no cover - network interaction
                    logger.exception("Failed to send plain text summary for life context export: %s", fallback_exc)
        except Exception as exc:  # pragma: no cover - network interaction
            logger.exception("Failed to send life context export: %s", exc)
            await self._notify_failure(update, context, f"⚠️ Could not send export: {exc}")
        finally:
            temp_path.unlink(missing_ok=True)

    async def _notify_failure(self, update: Update, context: CallbackContext, message: str) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(message)
        elif update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message)

    def _build_markdown_document(self, response: LifeContextFormattedResponse, metrics: set[LifeContextMetric]) -> str:
        start = response.bundle.start_date.isoformat()
        end = response.bundle.end_date.isoformat()
        header = [
            "# Life Context Export",
            f"- Date range: {start} → {end}",
            f"- Metrics: {self._format_metric_list(sorted(metric.value for metric in metrics))}",
            "",
        ]
        if response.rendered_markdown:
            body = [response.rendered_markdown]
        else:
            body = []
            for metric_name, section in response.sections.items():
                body.append(f"## {metric_name.replace('_', ' ').title()}")
                markdown = section.get("markdown") if isinstance(section, dict) else None
                if markdown:
                    body.append(str(markdown))
                else:
                    data = section.get("data") if isinstance(section, dict) else None
                    if data is not None:
                        body.append("```json")
                        body.append(json.dumps(data, indent=2, ensure_ascii=False))
                        body.append("```")
                body.append("")
        return "\n".join(header + body).strip() + "\n"

    def _build_json_payload(self, response: LifeContextFormattedResponse, metrics: set[LifeContextMetric]) -> str:
        payload = {
            "date_range": {
                "start_date": response.bundle.start_date.isoformat(),
                "end_date": response.bundle.end_date.isoformat(),
            },
            "selected_metrics": sorted(metric.value for metric in metrics),
            "sections": response.sections,
            "rendered_markdown": response.rendered_markdown,
            "error": response.error,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _build_filename(self, export_format: str, start: date, end: date) -> str:
        base = f"life_context_{start.isoformat()}_{end.isoformat()}"
        return base + (".json" if export_format == "json" else ".md")

    def _export_summary(
        self,
        metrics: set[LifeContextMetric],
        start: date,
        end: date,
        export_format: str,
        *,
        markdown_safe: bool = True,
    ) -> str:
        metric_text = self._format_metric_list(sorted(metric.value for metric in metrics))
        if markdown_safe:
            metric_text = escape_markdown_v1(metric_text)
            start_text = escape_markdown_v1(start.isoformat())
            end_text = escape_markdown_v1(end.isoformat())
        else:
            start_text = start.isoformat()
            end_text = end.isoformat()
        format_label = "Markdown" if export_format == "markdown" else "JSON"
        return (
            "✅ Export ready!\n"
            f"• Range: {start_text} → {end_text}\n"
            f"• Metrics: {metric_text}\n"
            f"• Format: {format_label}"
        )

    def _parse_date_input(self, raw: str | None) -> date | None:
        if not raw:
            return None
        text = raw.strip().lower()
        if text == "today":
            return self._today()
        if text == "yesterday":
            return self._today() - timedelta(days=1)
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    def _default_range(self) -> tuple[date, date]:
        end = self._today()
        start = end - timedelta(days=6)
        return start, end

    def _today(self) -> date:
        return datetime.now(self._tz).date()

    def _format_metric_list(self, metrics: Iterable[str]) -> str:
        return ", ".join(metrics)

    async def cancel(self, update: Update, context: CallbackContext) -> int:
        assert update.message is not None
        assert context.user_data is not None
        context.user_data.clear()
        await update.message.reply_text("Export cancelled. Come back anytime with /export_context.")
        return ConversationHandler.END


def get_life_context_export_handler(life_context_service: LifeContextService, tz: ZoneInfo) -> ConversationHandler:
    handler = LifeContextExportHandler(life_context_service, tz)
    return ConversationHandler(
        entry_points=[CommandHandler("export_context", handler.handle)],
        states={
            SELECT_METRICS: [CallbackQueryHandler(handler.select_metrics, pattern=r"^metrics_")],
            CUSTOM_METRICS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_custom_metrics)],
            SELECT_PERIOD: [CallbackQueryHandler(handler.select_period, pattern=r"^period_")],
            CUSTOM_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_custom_start)],
            CUSTOM_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_custom_end)],
            SELECT_FORMAT: [CallbackQueryHandler(handler.select_format, pattern=r"^format_")],
        },
        fallbacks=[CommandHandler("cancel", handler.cancel)],
        name="life_context_export",
        persistent=False,
    )
