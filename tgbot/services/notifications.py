# -*- coding: utf-8 -*-
from aiogram import Bot


async def notify_recorded(bot: Bot, worker_id: int, order_id: int):
    await bot.send_message(
        worker_id,
        f"✅ Вы записаны на заказ №{order_id}. Напоминание придёт за 2 часа до начала.",
    )


async def notify_payment(bot: Bot, worker_id: int, order_id: int, amount: int):
    await bot.send_message(worker_id, f"Начислено: {amount} ₽. Проверьте “💰 Баланс”.")


async def notify_cancel_by_admin(bot: Bot, worker_id: int, reason: str):
    await bot.send_message(
        worker_id,
        f"Вы сняты с заказа (причина: {reason}). Это не влияет на ваш рейтинг.",
    )


async def notify_unpaid(bot: Bot, worker_id: int, order_id: int):
    await bot.send_message(
        worker_id,
        "Работа приостановлена: заказ закрыт из-за неоплаты. Это не влияет на ваш рейтинг.",
    )
