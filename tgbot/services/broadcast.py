# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
import asyncio
import urllib
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from tgbot.data.config import PATH_DATABASE, get_admins


def _order_card(order: dict) -> str:
    """Формируем красивую карточку заказа для рассылки"""
    start_dt = dt.datetime.fromtimestamp(order["start_time"])
    start_str = start_dt.strftime("%d.%m %H:%M")

    fmt_map = {"hour": "Почасовая", "shift8": "Смена (8ч)", "day12": "День (12ч)"}
    fmt = fmt_map.get(order["format"], order["format"])

    return (
        f"📢 Новый заказ!\n\n"
        f"📝 {order['description']}\n"
        f"📍 Адрес: {order['address']} ({order['district']})\n"
        f"⏰ Старт: {start_str}\n"
        f"⚙️ Формат: {fmt}\n"
        f"👥 Места: {order['places_taken']}/{order['places_total']}\n"
        f"🌍 Гражданство: {order['citizenship_required']}\n"
        f"ℹ️ Особенности: {order['features'] or '-'}"
    )


async def _send_to_worker(
    bot: Bot, worker: dict, order: dict, kb: InlineKeyboardMarkup
):
    """Отправляем заказ одному пользователю, возвращаем (True/False, error_msg)"""
    try:
        await bot.send_message(
            worker["telegram_id"], _order_card(order), reply_markup=kb
        )
        return True, None
    except Exception as e:
        return False, str(e)



async def _send_to_worker(
    bot: Bot, worker: dict, order: dict, kb: InlineKeyboardMarkup
):
    try:
        text = (
            f"📋 Новый заказ #{order['id']}\n\n"
            f"📝 {order['description']}\n"
            f"📍 {order['address']} ({order['district']})\n"
            f"⏰ {dt.datetime.fromtimestamp(order['start_time']).strftime('%d.%m %H:%M')}\n"
            f"👥 {order['places_taken']}/{order['places_total']} мест\n"
            f"🌍 {order['citizenship_required']}\n"
            f"ℹ️ {order['features'] or '-'}"
        )
        await bot.send_message(worker["telegram_id"], text, reply_markup=kb)
        return True, None
    except Exception as e:
        return False, str(e)


async def broadcast_order(bot: Bot, order_id: int, rate_limit: int = 10):
    """
    Рассылка заказа по всем активным пользователям с ограничением скорости.
    Итог отправляется админу: сколько доставлено, сколько ошибок + примеры ошибок.
    """
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        order = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return
        order = dict(order)

        # Кнопки под заказом (унифицированные как в order_card_keyboard)
        query = f"Екатеринбург {order['address']} {order['district']}"
        map_url = "https://yandex.ru/maps/?text=" + urllib.parse.quote(query)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Берусь", callback_data=f"take_order:{order['id']}:0"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Пропустить",
                        callback_data=f"skip_order:{order['id']}:0",
                    )
                ],
                [InlineKeyboardButton(text="🗺 Открыть адрес в картах", url=map_url)],
            ]
        )

        # Достаём всех работников
        workers = con.execute("SELECT * FROM workers WHERE status='active'").fetchall()

    success = 0
    failed = 0
    errors = []
    tasks = []

    for i, w in enumerate(workers, start=1):
        # фильтр по гражданству
        if order["citizenship_required"] == "РФ" and w["citizenship"] != "РФ":
            continue
        if order["citizenship_required"] == "Иностранец" and w["citizenship"] == "РФ":
            continue

        tasks.append(_send_to_worker(bot, dict(w), order, kb))

        # каждые `rate_limit` сообщений ждём 1 секунду
        if i % rate_limit == 0:
            results = await asyncio.gather(*tasks)
            for ok, err in results:
                if ok:
                    success += 1
                else:
                    failed += 1
                    errors.append(err)
            tasks.clear()
            await asyncio.sleep(1)

    # добиваем хвост
    if tasks:
        results = await asyncio.gather(*tasks)
        for ok, err in results:
            if ok:
                success += 1
            else:
                failed += 1
                errors.append(err)

    # Формируем отчёт
    admins = get_admins()
    report = (
        f"📊 Рассылка завершена\n"
        f"✅ Успешно доставлено: {success}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего обработано: {success + failed}"
    )
    if errors:
        report += "\n\nПримеры ошибок:\n"
        for idx, err in enumerate(errors[:5], start=1):
            report += f"{idx}. {err}\n"

    for admin_id in admins:
        try:
            await bot.send_message(admin_id, report)
        except:
            pass
