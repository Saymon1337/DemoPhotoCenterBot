import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, OWNER_ID
from database.db import init_db
from database.queries import add_or_update_user

# Импортируем наши роутеры
from handlers import admin, client, booking
from services.scheduler import setup_scheduler

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # 1. Инициализируем БД
    logger.info("Инициализация базы данных...")
    await init_db()

    # 2. Назначаем владельца
    await add_or_update_user(
        tg_id=OWNER_ID,
        username="owner",
        full_name="Владелец фотоцентра",
        default_role="owner"
    )

    # 3. Бот и диспетчер
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # 4. Регистрация роутеров (admin идет ПЕРВЫМ для приоритета FSM-ввода!)
    dp.include_router(admin.router)
    dp.include_router(client.router)
    dp.include_router(booking.router)

    # 5. Шедулер (отчет за смену)
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик сменных отчетов запущен.")

    # 6. Запуск бота
    logger.info("Бот фотоцентра запущен 24/7!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")