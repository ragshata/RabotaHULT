# -*- coding: utf-8 -*-
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo
from aiogram import Bot

from tgbot.services.scheduler_tasks import (
    job_notify_on_start,
    job_send_pre_start_reminders,
    job_mark_no_shows_and_penalize,
    job_autoping_after_end,
    job_send_30min_reminders,
)


# создаём готовый шедулер с TZ Екатеринбурга
def build_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=ZoneInfo("Asia/Yekaterinburg"))


async def scheduler_start(scheduler: AsyncIOScheduler, bot: Bot):
    # каждые 5 минут — напоминания до старта
    scheduler.add_job(
        func=job_send_pre_start_reminders,
        trigger="interval",
        minutes=5,
        args=(bot,),
        id="pre_start_reminders",
        replace_existing=True,
    )
    # каждые 5 минут — напоминания до старта
    scheduler.add_job(
        func=job_send_30min_reminders,
        trigger="interval",
        minutes=5,
        args=(bot,),
        id="no_show_mark",
        replace_existing=True,
    )

    # каждые 5 минут — напоминания о старте
    scheduler.add_job(
        func=job_notify_on_start,
        trigger="interval",
        minutes=5,
        args=(bot,),
        id="no_show_mark",
        replace_existing=True,
    )

    # каждые 5 минут — отметка «неявка» спустя 15 минут от старта
    scheduler.add_job(
        func=job_mark_no_shows_and_penalize,
        trigger="interval",
        minutes=5,
        args=(bot,),
        id="no_show_mark",
        replace_existing=True,
    )

    # каждые 5 минут — автопинг через 30 минут после планового окончания
    scheduler.add_job(
        func=job_autoping_after_end,
        trigger="interval",
        minutes=5,
        args=(bot,),
        id="autoping_after_end",
        replace_existing=True,
    )

    scheduler.start()
