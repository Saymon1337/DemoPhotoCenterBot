from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from config import OWNER_ID, TIMEZONE
from database.queries import get_shift_statistics

async def send_daily_shift_report(bot: Bot):
    """Отправка ежедневного отчета Владельцу ровно в 19:00 по Москве."""
    now_msk = datetime.now(pytz.timezone(TIMEZONE))
    today_str = now_msk.strftime("%Y-%m-%d")
    
    summary, by_staff = await get_shift_statistics(today_str)
    
    total_orders = summary['total_orders'] or 0
    completed = summary['completed_orders'] or 0
    rejected = summary['rejected_orders'] or 0
    revenue = summary['total_revenue'] or 0.0
    
    lines = [
        f"🔔 **ИТОГИ СМЕНЫ В 19:00 (МСК) — {now_msk.strftime('%d.%m.%Y')}**\n",
        f"• Всего заказов за день: **{total_orders}**",
        f"• Успешно выполнено: **{completed}**",
        f"• Отклонено: **{rejected}**",
        f"• Итоговая выручка: **{revenue:.1f} ₽**\n",
        "👨‍💻 **Эффективность персонала:**"
    ]
    
    if by_staff:
        for st in by_staff:
            lines.append(f"• {st['staff_name']}: {st['count']} заказов ({st['revenue']:.1f} ₽)")
    else:
        lines.append("• Выполненных заказов нет.")
        
    try:
        await bot.send_message(OWNER_ID, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка отправки автоотчета владельцу: {e}")

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    # Запуск каждый день ровно в 19:00 по МСК
    scheduler.add_job(
        send_daily_shift_report,
        trigger="cron",
        hour=19,
        minute=0,
        args=[bot]
    )
    return scheduler