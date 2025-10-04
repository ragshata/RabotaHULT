# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, types, Bot
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from tgbot.data.config import PATH_DATABASE
from tgbot.utils.misc.bot_filters import IsAdmin

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ====== Вспомогательные ======
def fmt_order_row(o: dict) -> str:
    start = dt.datetime.fromtimestamp(o["start_time"]).strftime("%d.%m %H:%M")
    return (
        f"#{o['id']} | {start} | {o['client_name']} | {o['address']} ({o['district']}) | "
        f"{o['format']} | {o['places_taken']}/{o['places_total']} | {o['status']}"
    )


# ====== 1. Список заказов ======
@router.message(F.text == "/admin")
async def admin_menu_entry(message: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Заказы", callback_data="admin_orders")],
            [InlineKeyboardButton(text="👷 Рабочие", callback_data="admin_workers")],
            [InlineKeyboardButton(text="💰 Выплаты", callback_data="admin_payouts")],
        ]
    )
    await message.answer("Админ-панель:", reply_markup=kb)


# ====== Список заказов ======
@router.message(F.text == "📦 Заказы")
async def show_orders(message: types.Message):
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM orders ORDER BY start_time DESC LIMIT 10"
        ).fetchall()

    if not rows:
        await message.answer("❗️ Заказы не найдены.")
        return

    kb = []
    for o in rows:
        o = dict(o)
        start = dt.datetime.fromtimestamp(o["start_time"]).strftime("%d.%m %H:%M")
        text = f"#{o['id']} | {start} | {o['client_name']}"
        kb.append(
            [InlineKeyboardButton(text=text, callback_data=f"admin_order:{o['id']}")]
        )

    await message.answer(
        "📦 Последние заказы:\nВыберите нужный для просмотра 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
    )


# ====== Карточка заказа ======
@router.callback_query(F.data.startswith("admin_order:"))
async def show_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        o = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        workers = con.execute(
            """
            SELECT w.name, w.phone, s.status 
            FROM shifts s 
            JOIN workers w ON s.worker_id=w.id 
            WHERE s.order_id=?
            """,
            (order_id,),
        ).fetchall()

    if not o:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return

    o = dict(o)
    start = dt.datetime.fromtimestamp(o["start_time"]).strftime("%d.%m %H:%M")

    # Перевод формата
    format_map = {
        "hour": "⏱ Почасовая",
        "shift8": "🕗 Смена (8ч)",
        "day12": "📅 День (12ч)",
    }
    fmt = format_map.get(o["format"], o["format"])

    # Перевод статуса
    status_map = {
        "created": "🟢 Открыт",
        "started": "🔵 В работе",
        "done": "✅ Завершён",
        "cancelled": "❌ Отменён",
    }
    status = status_map.get(o["status"], o["status"])

    text = (
        f"📦 <b>Заказ #{o['id']}</b>\n\n"
        f"👤 <b>Клиент:</b> {o['client_name']} ({o['client_phone']})\n"
        f"📝 <b>Описание:</b> {o['description']}\n"
        f"📍 <b>Адрес:</b> {o['address']} ({o['district']})\n"
        f"⏰ <b>Старт:</b> {start}\n"
        f"⚙️ <b>Формат:</b> {fmt}\n"
        f"👥 <b>Места:</b> {o['places_taken']}/{o['places_total']}\n"
        f"🌍 <b>Гражданство:</b> {o['citizenship_required']}\n"
        f"ℹ️ <b>Особенности:</b> {o['features']}\n"
        f"📌 <b>Статус:</b> {status}\n\n"
        f"<b>👷 Исполнители:</b>\n"
    )

    if workers:
        for w in workers:
            # перевод статусов работников
            st_map = {
                "accepted": "📌 Принял",
                "arrived": "📍 Прибыл",
                "done": "✅ Отработал",
                "no_show": "⚠️ Не явился",
                "cancelled": "❌ Отменил",
            }
            ws = st_map.get(w["status"], w["status"])
            text += f"— {w['name']} ({w['phone']}) [{ws}]\n"
    else:
        text += "— пока нет\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Назначить", callback_data=f"admin_assign:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➖ Снять", callback_data=f"admin_unassign:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚀 Рассылка", callback_data=f"admin_broadcast:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить заказ",
                    callback_data=f"admin_cancel_order:{order_id}",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_orders_back")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ====== Назад к списку ======
@router.callback_query(F.data == "admin_orders_back")
async def back_to_orders(callback: CallbackQuery):
    await show_orders(callback.message)


# ====== 3. Отмена заказа ======
@router.callback_query(F.data.startswith("admin_cancel_order:"))
async def cancel_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
        con.commit()
    await callback.answer(f"Заказ #{order_id} отменён.", show_alert=True)
    await callback.message.edit_text(
        f"Заказ #{order_id} отменён администратором.\n\nРаботники уведомлены."
    )


# === 4. Назначить работника ===
@router.callback_query(F.data.startswith("admin_assign:"))
async def assign_worker(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        workers = con.execute(
            "SELECT id, name, phone FROM workers WHERE status='active'"
        ).fetchall()

    if not workers:
        await callback.answer("Нет доступных работников", show_alert=True)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{w['name']} ({w['phone']})",
                    callback_data=f"admin_do_assign:{order_id}:{w['id']}",
                )
            ]
            for w in workers
        ]
    )
    await callback.message.edit_text(
        f"Выберите работника для заказа #{order_id}:", reply_markup=kb
    )


@router.callback_query(F.data.startswith("admin_do_assign:"))
async def do_assign(callback: CallbackQuery, bot: Bot):
    _, order_id, worker_id = callback.data.split(":")
    order_id, worker_id = int(order_id), int(worker_id)

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        # Проверка нет ли уже
        exists = cur.execute(
            "SELECT 1 FROM shifts WHERE order_id=? AND worker_id=?",
            (order_id, worker_id),
        ).fetchone()
        if exists:
            await callback.answer("Уже назначен.", show_alert=True)
            return

        cur.execute(
            "INSERT INTO shifts (order_id, worker_id, status, start_time) VALUES (?, ?, 'accepted', strftime('%s','now'))",
            (order_id, worker_id),
        )
        cur.execute(
            "UPDATE orders SET places_taken = places_taken + 1 WHERE id=?", (order_id,)
        )
        tg_id = cur.execute(
            "SELECT telegram_id FROM workers WHERE id=?", (worker_id,)
        ).fetchone()[0]
        con.commit()

    await bot.send_message(
        tg_id, f"✅ Вы назначены администратором на заказ #{order_id}."
    )
    await callback.answer("Назначен.")


# === 5. Снять работника ===
@router.callback_query(F.data.startswith("admin_unassign:"))
async def unassign_worker(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        workers = con.execute(
            "SELECT w.id, w.name, w.phone FROM shifts s JOIN workers w ON s.worker_id=w.id WHERE s.order_id=?",
            (order_id,),
        ).fetchall()

    if not workers:
        await callback.answer("Нет назначенных работников", show_alert=True)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{w['name']} ({w['phone']})",
                    callback_data=f"admin_do_unassign:{order_id}:{w['id']}",
                )
            ]
            for w in workers
        ]
    )
    await callback.message.edit_text(
        f"Кого снять с заказа #{order_id}?", reply_markup=kb
    )


@router.callback_query(F.data.startswith("admin_do_unassign:"))
async def do_unassign(callback: CallbackQuery, bot: Bot):
    _, order_id, worker_id = callback.data.split(":")
    order_id, worker_id = int(order_id), int(worker_id)

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(
            "DELETE FROM shifts WHERE order_id=? AND worker_id=?", (order_id, worker_id)
        )
        cur.execute(
            "UPDATE orders SET places_taken = places_taken - 1 WHERE id=?", (order_id,)
        )
        tg_id = cur.execute(
            "SELECT telegram_id FROM workers WHERE id=?", (worker_id,)
        ).fetchone()[0]
        con.commit()

    await bot.send_message(
        tg_id,
        f"❌ Вы сняты администратором с заказа #{order_id}. Это не влияет на ваш рейтинг.",
    )
    await callback.answer("Снят.")


# ====== 4. Отмена из-за неоплаты ======
@router.callback_query(F.data.startswith("admin_cancel_unpaid:"))
async def cancel_unpaid(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
        # вытаскиваем работников
        workers = cur.execute(
            "SELECT w.telegram_id FROM shifts s JOIN workers w ON s.worker_id=w.id WHERE s.order_id=?",
            (order_id,),
        ).fetchall()
        con.commit()

    # уведомляем
    for w in workers:
        try:
            await bot.send_message(
                w["telegram_id"],
                f"⚠️ Работа приостановлена: заказ №{order_id} закрыт из-за неоплаты клиента.\n"
                f"Это не влияет на ваш рейтинг.",
            )
        except Exception:
            pass

    await callback.answer(f"Заказ #{order_id} отменён (неоплата).", show_alert=True)
    await callback.message.edit_text(
        f"Заказ #{order_id} отменён по причине неоплаты клиента.\n\nРаботники уведомлены."
    )


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Создать заказ"),
                KeyboardButton(text="📦 Заказы"),
            ],
            [
                KeyboardButton(text="👷 Рабочие"),
                KeyboardButton(text="💰 Выплаты"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


@router.message(F.text == "/admin")
async def admin_menu_entry(message: types.Message):
    await message.answer("Админ-панель:", reply_markup=admin_menu())
