"""Handlers for statistics commands."""

from telegram import Update
from telegram.ext import ContextTypes

from .state import get_user_stats


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display aggregated per-user statistics."""

    stats = get_user_stats(context.user_data)
    total_sprints = len(stats.sprint_results)
    best_score = best_total = 0
    if stats.sprint_results:
        best = max(stats.sprint_results, key=lambda r: r.score)
        best_score = best.score
        best_total = best.total

    lines = ["📊 Ваша статистика:"]
    lines.append(f"Спринтов сыграно: {total_sprints}")
    if total_sprints:
        lines.append(f"Лучший результат: {best_score} из {best_total}")
    lines.append(f"Карточек к повторению: {len(stats.to_repeat)}")
    if stats.to_repeat:
        sample = list(sorted(stats.to_repeat))[:10]
        lines.append("\n".join(["К повторению:"] + sample))

    await update.effective_message.reply_text("\n".join(lines))
