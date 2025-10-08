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

from tgbot.data.config import PATH_DATABASE, get_admins
from tgbot.utils.misc.bot_filters import IsAdmin
from aiogram.fsm.state import StatesGroup, State
from tgbot.utils.misc.bot_models import FSM

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


@router.callback_query(F.data.startswith("admin_order:"))
async def open_admin_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    await show_order(callback, order_id)


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


# === FSM для редактирования текстовых полей ===
class AdminEditOrder(StatesGroup):
    waiting_value = State()


# ====== Показ карточки заказа ======
async def show_order(message_or_cb, order_id: int | None = None):
    """Показ карточки заказа (работает и с callback, и с message)."""
    if isinstance(message_or_cb, types.CallbackQuery):
        callback = message_or_cb
        message = callback.message
        if order_id is None:
            order_id = int(callback.data.split(":")[1])
    else:
        message = message_or_cb

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
        if isinstance(message_or_cb, types.CallbackQuery):
            await message_or_cb.answer("❌ Заказ не найден", show_alert=True)
        else:
            await message.answer("❌ Заказ не найден")
        return

    o = dict(o)
    start = dt.datetime.fromtimestamp(o["start_time"]).strftime("%d.%m %H:%M")

    format_map = {
        "hour": "⏱️ Почасовая",
        "shift8": "🕗 Смена (8ч)",
        "day12": "📅 День (12ч)",
    }
    status_map = {
        "created": "🟢 Открыт",
        "started": "🔵 В работе",
        "done": "✅ Завершён",
        "cancelled": "❌ Отменён",
    }

    fmt = format_map.get(o["format"], o["format"])
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
                    text="✏️ Редактировать", callback_data=f"admin_edit_order:{order_id}"
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
            [
                InlineKeyboardButton(
                    text="🗑 Удалить заказ",
                    callback_data=f"admin_delete_order_confirm:{order_id}",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_orders_back")],
        ]
    )

    if isinstance(message_or_cb, types.CallbackQuery):
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await message_or_cb.answer()
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ====== Подтверждение удаления ======
@router.callback_query(F.data.startswith("admin_delete_order_confirm:"))
async def admin_delete_order_confirm(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"admin_delete_order:{order_id}",
                ),
                InlineKeyboardButton(
                    text="⬅️ Отмена",
                    callback_data=f"admin_order:{order_id}",
                ),
            ]
        ]
    )

    await callback.message.edit_text(
        f"⚠️ <b>Удалить заказ #{order_id}</b>?\n\n"
        "Это действие необратимо: будут удалены все связанные смены и транзакции.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ====== Удаление заказа ======
@router.callback_query(F.data.startswith("admin_delete_order:"))
async def admin_delete_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        # каскадное удаление
        cur.execute("DELETE FROM transactions   WHERE order_id=?", (order_id,))
        cur.execute("DELETE FROM shifts         WHERE order_id=?", (order_id,))
        cur.execute("DELETE FROM skipped_orders WHERE order_id=?", (order_id,))
        cur.execute("DELETE FROM orders         WHERE id=?", (order_id,))
        con.commit()

    # сообщение об успехе
    await callback.answer("✅ Заказ удалён.", show_alert=True)
    await callback.message.edit_text(f"🗑 Заказ #{order_id} успешно удалён.")

    # 👇 Возвращаем пользователя к списку заказов
    await show_orders(callback.message)


# ====== Меню выбора поля ======
@router.callback_query(F.data.startswith("admin_edit_order:"))
async def admin_edit_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📍 Адрес",
                    callback_data=f"admin_edit_field:address:{order_id}",
                ),
                InlineKeyboardButton(
                    text="⏰ Время",
                    callback_data=f"admin_edit_field:start_time:{order_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Кол-во мест",
                    callback_data=f"admin_edit_field:places_total:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Формат", callback_data=f"admin_edit_field:format:{order_id}"
                ),
                InlineKeyboardButton(
                    text="🌍 Гражданство",
                    callback_data=f"admin_edit_field:citizenship:{order_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ Особенности",
                    callback_data=f"admin_edit_field:features:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"admin_order:{order_id}"
                )
            ],
        ]
    )
    await callback.message.edit_text("✏️ Что нужно изменить?", reply_markup=kb)
    await callback.answer()


# ====== Обработка выбора ======
@router.callback_query(F.data.startswith("admin_edit_field:"))
async def admin_edit_field(callback: CallbackQuery, state: FSM):
    _, field, order_id = callback.data.split(":")
    order_id = int(order_id)

    if field == "format":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏱️ Почасовая",
                        callback_data=f"admin_set_value:format:hour:{order_id}",
                    ),
                    InlineKeyboardButton(
                        text="🕗 Смена (8ч)",
                        callback_data=f"admin_set_value:format:shift8:{order_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📅 День (12ч)",
                        callback_data=f"admin_set_value:format:day12:{order_id}",
                    )
                ],
            ]
        )
        await callback.message.edit_text("⚙️ Выберите новый формат:", reply_markup=kb)
        await callback.answer()
        return

    if field == "citizenship":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🇷🇺 РФ",
                        callback_data=f"admin_set_value:citizenship:РФ:{order_id}",
                    ),
                    InlineKeyboardButton(
                        text="🌍 Иностранец",
                        callback_data=f"admin_set_value:citizenship:Иностранец:{order_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🤝 Любое",
                        callback_data=f"admin_set_value:citizenship:Любое:{order_id}",
                    )
                ],
            ]
        )
        await callback.message.edit_text(
            "🌍 Выберите требуемое гражданство:", reply_markup=kb
        )
        await callback.answer()
        return

    await state.set_state(AdminEditOrder.waiting_value)
    await state.update_data(order_id=order_id, field=field)
    await callback.message.answer(f"✏️ Введите новое значение для «{field}»:")
    await callback.answer()


# ====== Сохранение текстового ввода ======
@router.message(AdminEditOrder.waiting_value)
async def admin_save_text_edit(message, state: FSM):
    data = await state.get_data()
    field = data["field"]
    order_id = data["order_id"]
    value = message.text.strip()

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()

        if field == "start_time":
            try:
                dt_obj = dt.datetime.strptime(value, "%d.%m %H:%M")
                dt_obj = dt_obj.replace(year=dt.datetime.now().year)
                value = int(dt_obj.timestamp())
                cur.execute(
                    "UPDATE orders SET start_time=? WHERE id=?", (value, order_id)
                )
            except ValueError:
                await message.answer("⚠️ Формат неверный. Введите как: 15.09 09:00")
                return
        elif field == "places_total":
            try:
                n = int(value)
                if not 1 <= n <= 20:
                    raise ValueError
                cur.execute(
                    "UPDATE orders SET places_total=? WHERE id=?", (n, order_id)
                )
            except ValueError:
                await message.answer("⚠️ Введите число от 1 до 20.")
                return
        else:
            cur.execute(f"UPDATE orders SET {field}=? WHERE id=?", (value, order_id))
        con.commit()

    await state.clear()
    await message.answer("✅ Изменение сохранено. Обновляю заказ...")
    await show_order(message, order_id)


# ====== Сохранение кнопками ======
@router.callback_query(F.data.startswith("admin_set_value:"))
async def admin_set_value(callback: CallbackQuery):
    _, field, value, order_id = callback.data.split(":")
    order_id = int(order_id)
    column = "format" if field == "format" else "citizenship_required"

    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(f"UPDATE orders SET {column}=? WHERE id=?", (value, order_id))
        con.commit()

    await callback.answer("✅ Изменение сохранено.", show_alert=True)
    await show_order(callback, order_id)


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

    # кнопки по работникам (по одному в строке)
    rows = [
        [
            InlineKeyboardButton(
                text=f"{w['name']} ({w['phone']})",
                callback_data=f"admin_do_assign:{order_id}:{w['id']}",
            )
        ]
        for w in workers
    ]

    # универсальная «Назад» — возвращаемся в карточку заказа
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_order:{order_id}")]
    )

    await callback.message.edit_text(
        f"Выберите работника для заказа #{order_id}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# === 4. Назначить работника ===
@router.callback_query(F.data.startswith("admin_assign:"))
async def assign_worker(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])

    admin_ids = set(get_admins())  # список telegram_id админов

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row

        where_sql = "WHERE status='active'"
        params = []

        if admin_ids:
            placeholders = ",".join("?" * len(admin_ids))
            where_sql += f" AND telegram_id NOT IN ({placeholders})"
            params.extend(list(admin_ids))

        workers = con.execute(
            f"SELECT id, name, phone FROM workers {where_sql} ORDER BY id DESC",
            params,
        ).fetchall()

    if not workers:
        await callback.answer("Нет доступных работников.", show_alert=True)
        return

    rows = [
        [
            InlineKeyboardButton(
                text=f"{w['name']} ({w['phone']})",
                callback_data=f"admin_do_assign:{order_id}:{w['id']}",
            )
        ]
        for w in workers
    ]
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_order:{order_id}")]
    )

    await callback.message.edit_text(
        f"Выберите работника для заказа #{order_id}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# === 4.1 Подтверждение назначения ===
@router.callback_query(F.data.startswith("admin_do_assign:"))
async def do_assign(callback: CallbackQuery, bot: Bot):
    _, order_id, worker_id = callback.data.split(":")
    order_id, worker_id = int(order_id), int(worker_id)

    admin_ids = set(get_admins())  # защита от назначения админов

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # проверим, не админ ли этот worker
        w = cur.execute(
            "SELECT id, telegram_id FROM workers WHERE id=?", (worker_id,)
        ).fetchone()
        if not w:
            await callback.answer("Работник не найден.", show_alert=True)
            return
        if w["telegram_id"] in admin_ids:
            await callback.answer("Нельзя назначать администратора.", show_alert=True)
            return

        # уже назначен?
        exists = cur.execute(
            "SELECT 1 FROM shifts WHERE order_id=? AND worker_id=?",
            (order_id, worker_id),
        ).fetchone()
        if exists:
            await callback.answer("Этот работник уже назначен.", show_alert=True)
            return

        # создаём смену и увеличиваем X/Y
        cur.execute(
            "INSERT INTO shifts (order_id, worker_id, status, start_time) "
            "VALUES (?, ?, 'accepted', (SELECT start_time FROM orders WHERE id=?))",
            (order_id, worker_id, order_id),
        )
        cur.execute(
            "UPDATE orders SET places_taken = places_taken + 1 WHERE id=?", (order_id,)
        )

        tg_row = cur.execute(
            "SELECT telegram_id FROM workers WHERE id=?", (worker_id,)
        ).fetchone()
        con.commit()

    tg_id = tg_row["telegram_id"] if tg_row else None
    if tg_id:
        try:
            await bot.send_message(
                tg_id, f"✅ Вы назначены администратором на заказ #{order_id}."
            )
        except Exception:
            pass

    await callback.answer("Назначен.", show_alert=True)
    # вернёмся в карточку заказа
    await show_order(callback, order_id)


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
