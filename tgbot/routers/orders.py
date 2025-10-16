# -*- coding: utf-8 -*-
import sqlite3
import datetime
import urllib.parse
from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from tgbot.data.config import PATH_DATABASE
from tgbot.services.tz import TZ
from tgbot.utils.const_functions import format_display

router = Router()
PAGE_SIZE = 5


# ================= Вспомогательные =================
def get_worker(user_id: int) -> dict | None:
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM workers WHERE telegram_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def has_time_conflict(worker_id: int, new_start: int, fmt: str) -> bool:
    """Проверка пересечения смен"""
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        shifts = cur.execute(
            """
            SELECT s.*, o.start_time, o.format 
            FROM shifts s JOIN orders o ON s.order_id=o.id
            WHERE s.worker_id=? AND s.status IN ('accepted','arrived')
            """,
            (worker_id,),
        ).fetchall()

        def duration(fmt):
            return (
                4 * 3600
                if fmt == "hour"
                else (8 * 3600 if fmt == "shift8" else 12 * 3600)
            )

        for sh in shifts:
            old_start = sh["start_time"]
            old_dur = duration(sh["format"])
            new_dur = duration(fmt)
            if not (
                new_start + new_dur <= old_start or old_start + old_dur <= new_start
            ):
                return True
        return False


def get_orders(user_id: int, page: int = 0):
    """Получаем список заказов, исключая просроченные и полные по местам."""
    now_ts = int(datetime.datetime.now(TZ).timestamp())

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Пропущенные (на 48ч)
        cur.execute(
            """
            SELECT order_id FROM skipped_orders
            WHERE worker_id = ? AND skipped_at > strftime('%s','now') - 48*3600
            """,
            (user_id,),
        )
        skipped = {row["order_id"] for row in cur.fetchall()}

        # Только актуальные заказы:
        # - статус = 'created'
        # - старт как минимум через 1 час
        # - есть свободные места
        cur.execute(
            """
            SELECT * FROM orders
            WHERE status = 'created'
              AND start_time > ?
              AND places_taken < places_total
            ORDER BY start_time ASC
            """,
            (now_ts + 3600,),
        )

        all_orders = [dict(row) for row in cur.fetchall()]

        # Исключаем пропущенные
        filtered = [o for o in all_orders if o["id"] not in skipped]

        # Пагинация
        start, end = page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE
        return filtered[start:end], len(filtered)


def orders_keyboard(orders: list[dict], page: int, total: int):
    kb = []
    for o in orders:
        kb.append(
            [
                InlineKeyboardButton(
                    text=order_button_text(o),
                    callback_data=f"order_card:{o['id']}:{page}",
                )
            ]
        )

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"orders_page:{page-1}")
        )
    if (page + 1) * PAGE_SIZE < total:
        nav.append(
            InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"orders_page:{page+1}")
        )
    nav.append(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"orders_page:{page}")
    )
    kb.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=kb)


def order_button_text(o: dict) -> str:
    dt = datetime.datetime.fromtimestamp(o["start_time"], TZ)
    date_str = dt.strftime("%d.%m %H:%M")
    people = f"👥 {o['places_taken']}/{o['places_total']}"
    desc = o.get("description", "")
    district = o.get("district", "")
    # формат: дата/время | люди | описание | район
    return f"🗓 {date_str} | {people} | {desc} | {district}"


def order_card_keyboard(order: dict, page: int):
    query = f"Екатеринбург {order['address']} {order['district']}"
    map_url = "https://yandex.ru/maps/?text=" + urllib.parse.quote(query)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Берусь", callback_data=f"take_order:{order['id']}:{page}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Пропустить",
                    callback_data=f"skip_order:{order['id']}:{page}",
                )
            ],
            [InlineKeyboardButton(text="🗺 Открыть адрес в картах", url=map_url)],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад к ленте", callback_data=f"orders_page:{page}"
                )
            ],
        ]
    )


def format_order_card(o: dict):
    dt = datetime.datetime.fromtimestamp(o["start_time"], TZ)
    start_str = dt.strftime("%d.%m %H:%M")

    if o["format"] == "hour":
        rate = "💰 400 ₽/час (минимум 4 часа)"
    elif o["format"] == "shift8":
        rate = "💰 3500 ₽ за 8 часов"
    else:
        rate = "💰 4800 ₽ за 12 часов"

    return (
        f"📋 <b>{o['description']}</b>\n\n"
        f"📍 Адрес: {o['address']} ({o['district']})\n"
        f"⏰ Старт: {start_str}\n"
        f"⚙️ Формат:{format_display(o['format'])}\n"
        f"👥 Места: {o['places_taken']}/{o['places_total']}\n"
        f"🌍 Гражданство: {o['citizenship_required']}\n"
        f"{rate}\n"
        f"ℹ️ Особенности: {o.get('features','-')}"
    )


# ================= Хэндлеры =================
@router.message(F.text == "📦 Новые заказы")
async def show_orders(message: types.Message):
    page = 0
    orders, total = get_orders(message.from_user.id, page)
    if not orders:
        await message.answer("❗️ Нет доступных заказов.")
        return
    await message.answer(
        "📦 Доступные заказы:\n\nВыберите нужный заказ 👇",
        reply_markup=orders_keyboard(orders, page, total),
    )


@router.callback_query(F.data.startswith("orders_page:"))
async def paginate_orders(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    orders, total = get_orders(callback.from_user.id, page)

    if not orders:
        await callback.answer("Нет заказов на этой странице.", show_alert=True)
        return

    text = "📦 Доступные заказы:\n\nВыберите нужный заказ 👇"
    kb = orders_keyboard(orders, page, total)

    try:
        # Проверяем, изменилось ли что-то реально
        if callback.message.text == text and callback.message.reply_markup == kb:
            await callback.answer("⚠️ Уже эта страница", show_alert=False)
            return

        await callback.message.edit_text(text, reply_markup=kb)

    except TelegramBadRequest as e:
        # Обрабатываем только «message is not modified»
        if "message is not modified" in str(e):
            await callback.answer("⚠️ Без изменений", show_alert=False)
        else:
            # Если другая ошибка — пробрасываем дальше
            raise


@router.callback_query(F.data.startswith("order_card:"))
async def show_order_card(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) == 3:
        order_id, page = map(int, parts[1:])
    else:
        order_id = int(parts[1])
        page = 0  # по умолчанию первая страница

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        order = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    if not order or order["status"] != "created":
        await callback.answer(
            "Заказ недоступен или отменён. Обновите ленту.", show_alert=True
        )
        return

    order = dict(order)  # превратили Row в dict
    await callback.message.edit_text(
        format_order_card(order),
        reply_markup=order_card_keyboard(order, page),
        parse_mode="HTML",
    )


# === Пропустить ===
@router.callback_query(F.data.startswith("skip_order:"))
async def skip_order(callback: CallbackQuery):
    _, order_id, page = callback.data.split(":")
    order_id, page = int(order_id), int(page)
    user_id = callback.from_user.id
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "INSERT INTO skipped_orders (worker_id, order_id, skipped_at) VALUES (?, ?, strftime('%s','now'))",
            (user_id, order_id),
        )
        con.commit()
    await callback.answer("🚫 Заказ скрыт на 48 часов.", show_alert=True)
    orders, total = get_orders(user_id, page)
    if orders:
        await callback.message.edit_text(
            "📦 Доступные заказы:\n\nВыберите нужный заказ 👇",
            reply_markup=orders_keyboard(orders, page, total),
        )
    else:
        await callback.message.edit_text("❗️ Нет доступных заказов.")


# === Берусь ===
@router.callback_query(F.data.startswith("take_order:"))
async def take_order(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) == 3:
        _, order_id_str, page_str = parts
    elif len(parts) == 2:
        _, order_id_str = parts
        page_str = "0"  # если в callback не передали страницу, берём 0
    else:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    try:
        order_id = int(order_id_str)
        page = int(page_str)
    except ValueError:
        await callback.answer("Некорректный идентификатор заказа.", show_alert=True)
        return

    user_id = callback.from_user.id

    # получаем работника и приводим к dict (если это sqlite3.Row)
    worker = get_worker(user_id)
    if not worker:
        await callback.answer("❗️ Вы не зарегистрированы.", show_alert=True)
        return
    if not isinstance(worker, dict):
        worker = dict(worker)

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        order = cur.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            await callback.answer("❌ Заказ не найден.", show_alert=True)
            return
        order = dict(order)

        # базовые проверки
        if order["status"] != "created":
            await callback.answer("❌ Заказ недоступен или отменён.", show_alert=True)
            return
        if order["places_taken"] >= order["places_total"]:
            await callback.answer(
                "❌ Места заняты. Посмотрите другие заказы в меню “📦 Новые заказы”.",
                show_alert=True,
            )
            return

        # === Проверка гражданства ===
        worker_cit = worker.get("citizenship")
        order_cit = order.get("citizenship_required")

        # Иностранец может брать только "Иностранец" и "Любое"
        if worker_cit == "Иностранец" and order_cit not in ("Иностранец", "Любое"):
            await callback.answer(
                "❌ Этот заказ доступен только гражданам РФ.", show_alert=True
            )
            return
        # Гражданин РФ может брать любые заказы — без ограничений

        # дублирование
        already = cur.execute(
            "SELECT id FROM shifts WHERE worker_id=? AND order_id=? AND status IN ('accepted','arrived')",
            (worker["id"], order_id),
        ).fetchone()
        if already:
            await callback.answer(
                "Вы уже записаны на этот заказ. Проверьте “📅 Мои смены”.\n"
                "Если хотите отказаться, откройте карточку смены и нажмите “❌ Отказаться” (учтите правила рейтинга).",
                show_alert=True,
            )
            return

        # пересечение по времени
        if has_time_conflict(worker["id"], order["start_time"], order["format"]):
            await callback.answer(
                "❌ Эта смена пересекается с уже принятой. Завершите или отмените другую запись.",
                show_alert=True,
            )
            return

        # блокировки / ограничения
        blocked_until = worker.get("blocked_until")
        if blocked_until:
            try:
                if int(blocked_until) > int(datetime.datetime.now(TZ).timestamp()):
                    await callback.answer(
                        "⛔️ Ваш профиль временно ограничен. Обратитесь в поддержку.",
                        show_alert=True,
                    )
                    return
            except Exception:
                # если в БД неожиданное значение — не падаем
                pass

        # все ок — создаём запись и обновляем X/Y (атомарно)
        cur.execute(
            "INSERT INTO shifts (order_id, worker_id, status, start_time) VALUES (?, ?, 'accepted', ?)",
            (order_id, worker["id"], order["start_time"]),
        )
        cur.execute(
            "UPDATE orders SET places_taken = places_taken + 1 WHERE id=?",
            (order_id,),
        )
        con.commit()

    # Подтверждение пользователю
    await callback.answer(
        "✅ Запись подтверждена. Напоминание придёт за 2 часа до начала смены.",
        show_alert=True,
    )

    # Перечитываем заказ для актуальной X/Y и перерисовываем карточку
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        fresh = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    if fresh:
        fresh = dict(fresh)
        await callback.message.edit_text(
            format_order_card(fresh),
            reply_markup=order_card_keyboard(fresh, page),
            parse_mode="HTML",
        )
