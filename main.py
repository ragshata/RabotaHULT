# -*- coding: utf-8 -*-
import asyncio
import os
import sys

import colorama
from aiogram import Dispatcher, Bot

from tgbot.data.config import BOT_TOKEN, BOT_SCHEDULER, get_admins
from tgbot.database.db_helper import create_dbx
from tgbot.middlewares import register_all_middlwares
from tgbot.routers import register_all_routers
from tgbot.services.api_session import AsyncRequestSession
from tgbot.utils.misc.bot_commands import set_commands
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.services.scheduler_start import build_scheduler, scheduler_start


colorama.init()


# Запуск бота и базовых функций
async def main():
    BOT_SCHEDULER.start()  # Запуск планировщика
    dp = Dispatcher()  # Диспетчер событий
    arSession = AsyncRequestSession()  # Асинхронная сессия
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")  # Образ бота

    register_all_middlwares(dp)  # Мидлвари
    register_all_routers(dp)  # Роутеры

    try:
        # Базовые функции
        await set_commands(bot)
        scheduler = build_scheduler()
        await scheduler_start(scheduler, bot)

        bot_logger.warning("BOT WAS STARTED")
        print(
            colorama.Fore.LIGHTYELLOW_EX
            + f"~~~~~ Bot was started - @{(await bot.get_me()).username} ~~~~~"
        )
        print(colorama.Fore.RESET)

        if len(get_admins()) == 0:
            print("***** ENTER ADMIN ID IN settings.ini *****")

        # Запуск поллинга
        await bot.delete_webhook()
        await bot.get_updates(offset=-1)

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            arSession=arSession,
        )
    finally:
        await arSession.close()
        await bot.session.close()


if __name__ == "__main__":
    # Создаём БД и таблицы
    create_dbx()

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        bot_logger.warning("Bot was stopped")
    finally:
        if sys.platform.startswith("win"):
            os.system("cls")
        else:
            os.system("clear")
