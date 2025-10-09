# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
import aiohttp
from aiogram import Bot, Router, F, types
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)

from tgbot.data.config import PATH_DATABASE
from tgbot.routers.admin_panel import admin_menu
from tgbot.services.broadcast import broadcast_order
from tgbot.services.tz import TZ
from tgbot.utils.const_functions import format_display
from tgbot.utils.misc.bot_filters import IsAdmin

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ================= FSM =================
class CreateOrder(StatesGroup):
    client_name = State()
    client_phone = State()
    description = State()
    address = State()
    district = State()
    start_time = State()
    places_total = State()
    format = State()
    citizenship = State()
    features = State()
    confirm = State()
    edit_field = State()


# ================= Вспомогательные =================
VALID_DISTRICTS = [
    "Академический",
    "Верх-Исетский",
    "Железнодорожный",
    "Кировский",
    "Ленинский",
    "Октябрьский",
    "Орджоникидзевский",
    "Чкаловский",
]


def insert_order(data: dict) -> int:
    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO orders
            (client_name, client_phone, description, address, district,
             start_time, format, citizenship_required, places_total,
             places_taken, features, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'created')
            """,
            (
                data["client_name"],
                data["client_phone"],
                data["description"],
                data["address"],
                data["district"],
                data["start_time"],
                data["format"],
                data["citizenship"],
                data["places_total"],
                data["features"],
            ),
        )
        order_id = cur.lastrowid
        con.commit()
        return order_id


def format_order_card(data: dict, order_id: int) -> str:
    return (
        f"📦 Предпросмотр заказа (ID {order_id})\n\n"
        f"👤 Клиент: {data['client_name']} ({data['client_phone']})\n"
        f"📝 Описание: {data['description']}\n"
        f"📍 Адрес: {data['address']} ({data['district']})\n"
        f"⏰ Старт: {dt.datetime.fromtimestamp(data['start_time'], TZ).strftime('%d.%m %H:%M')}\n"
        f"⚙️ <b>Формат:</b> {format_display(['format'])}\n"
        f"👥 Места: {data['places_total']}\n"
        f"🌍 Гражданство: {data['citizenship']}\n"
        f"ℹ️ Особенности: {data['features']}"
    )


def preview_keyboard(order_id: int = 0):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data="confirm_order"
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order"),
            ],
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_order")],
        ]
    )


# ================= Хэндлеры создания =================
@router.message(F.text == "➕ Создать заказ")
async def start_create_order(message: types.Message, state):
    await state.set_state(CreateOrder.client_name)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить создание", callback_data="create_order_cancel")]
        ]
    )
    await message.answer("👤 Введите имя клиента:", reply_markup=kb)


# Кнопка «Отменить создание» (работает на любом шаге мастера)
@router.callback_query(F.data == "create_order_cancel")
async def create_order_cancel(callback: types.CallbackQuery, state):
    await state.clear()
    try:
        await callback.message.edit_text("❌ Создание заказа отменено.")
    except Exception:
        # если сообщение нельзя отредактировать (например, уже отвечали) — просто отправим новое
        await callback.message.answer("❌ Создание заказа отменено.")
    await callback.answer()


@router.message(CreateOrder.client_name)
async def step_client_name(message: types.Message, state):
    await state.update_data(client_name=message.text.strip())
    await state.set_state(CreateOrder.client_phone)
    await message.answer("📞 Введите телефон клиента:")


@router.message(CreateOrder.client_phone)
async def step_client_phone(message: types.Message, state):
    await state.update_data(client_phone=message.text.strip())
    await state.set_state(CreateOrder.description)
    await message.answer("📝 Введите краткое описание работы:")


@router.message(CreateOrder.description)
async def step_description(message: types.Message, state):
    await state.update_data(description=message.text.strip())
    await state.set_state(CreateOrder.address)
    await message.answer("📍 Введите адрес (текстом) или отправьте геолокацию:")


# --- Адрес текстом ---
@router.message(CreateOrder.address, F.text)
async def step_address_text(message: types.Message, state):
    street = message.text.strip()
    if not street.lower().startswith("ул"):
        street = f"ул. {street}"

    await state.update_data(address=street)
    await state.set_state(CreateOrder.district)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=d, callback_data=f"district:{d}")]
            for d in VALID_DISTRICTS
        ]
    )
    await message.answer(
        f"📍 Указан адрес: {street}\n\n🏙 Теперь выберите район:", reply_markup=kb
    )


# --- Адрес через локацию ---
@router.message(CreateOrder.address, F.location)
async def step_address_location(message: types.Message, state):
    lat = message.location.latitude
    lon = message.location.longitude

    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=ru"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers={"User-Agent": "RabotaPlusBot"}
            ) as resp:
                data = await resp.json()
                addr = data.get("address", {})

                road = addr.get("road", "")
                house = addr.get("house_number", "")
                street = f"ул. {road} {house}".strip() if road else "Адрес не определён"

                district_guess = addr.get("suburb") or addr.get("city_district") or ""
    except Exception:
        street = "Адрес не определён"
        district_guess = ""

    await state.update_data(address=street)

    if district_guess and any(district_guess.startswith(d) for d in VALID_DISTRICTS):
        chosen_district = next(
            d for d in VALID_DISTRICTS if district_guess.startswith(d)
        )
        await state.update_data(district=chosen_district)
        await state.set_state(CreateOrder.start_time)
        await message.answer(
            f"📍 Определён адрес: <b>{street}</b>\n"
            f"🏙 Район: <b>{chosen_district}</b>\n\n"
            f"⏰ Введите дату и время начала (формат: 15.09 09:00):",
            parse_mode="HTML",
        )
    else:
        await state.set_state(CreateOrder.district)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=d, callback_data=f"district:{d}")]
                for d in VALID_DISTRICTS
            ]
        )
        await message.answer(
            f"📍 Определён адрес: <b>{street}</b>\n\n🏙 Теперь выберите район:",
            reply_markup=kb,
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("district:"))
async def step_district(callback: types.CallbackQuery, state):
    district = callback.data.split(":", 1)[1]
    await state.update_data(district=district)
    await state.set_state(CreateOrder.start_time)

    await callback.message.answer(
        "⏰ Введите дату и время начала (формат: 15.09 09:00):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await callback.answer()


# === ВРЕМЯ СТАРТА ===
@router.message(CreateOrder.start_time)
async def step_start_time(message: types.Message, state):
    try:
        dt_obj = dt.datetime.strptime(message.text.strip(), "%d.%m %H:%M")
        dt_obj = dt_obj.replace(year=dt.datetime.now().year)
        start_ts = int(dt_obj.timestamp())
    except Exception:
        await message.answer("⚠️ Формат неверный. Введите как: 15.09 09:00")
        return

    await state.update_data(start_time=start_ts)
    await state.set_state(CreateOrder.places_total)
    await message.answer("👥 Введите количество работников (1–20):")


# === КОЛИЧЕСТВО ===
@router.message(CreateOrder.places_total)
async def step_places_total(message: types.Message, state):
    try:
        n = int(message.text.strip())
        if not 1 <= n <= 20:
            raise ValueError
    except Exception:
        await message.answer("⚠️ Введите число от 1 до 20.")
        return

    await state.update_data(places_total=n)
    await state.set_state(CreateOrder.format)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏱ Почасовая", callback_data="format:hour"),
                InlineKeyboardButton(
                    text="🕗 Смена (8ч)", callback_data="format:shift8"
                ),
            ],
            [InlineKeyboardButton(text="📅 День (12ч)", callback_data="format:day12")],
        ]
    )
    await message.answer("⚙️ Выберите формат:", reply_markup=kb)


# === ФОРМАТ ===
@router.callback_query(F.data.startswith("format:"))
async def step_format(callback: types.CallbackQuery, state):
    fmt = callback.data.split(":", 1)[1]
    await state.update_data(format=fmt)
    await state.set_state(CreateOrder.citizenship)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 РФ", callback_data="citizenship:РФ"),
                InlineKeyboardButton(
                    text="🌍 Иностранец", callback_data="citizenship:Иностранец"
                ),
            ],
            [InlineKeyboardButton(text="🤝 Любое", callback_data="citizenship:Любое")],
        ]
    )
    await callback.message.answer("🌍 Требования по гражданству:", reply_markup=kb)
    await callback.answer()


# === ГРАЖДАНСТВО ===
@router.callback_query(F.data.startswith("citizenship:"))
async def step_citizenship(callback: types.CallbackQuery, state):
    val = callback.data.split(":", 1)[1]
    await state.update_data(citizenship=val)
    await state.set_state(CreateOrder.features)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Нет", callback_data="features:none")]
        ]
    )
    await callback.message.answer(
        "ℹ️ Укажите особенности/инструкции (или «Нет»):", reply_markup=kb
    )
    await callback.answer()


# === ОСОБЕННОСТИ ===
@router.callback_query(F.data == "features:none")
async def features_none(callback: types.CallbackQuery, state):
    await state.update_data(features="нет")
    data = await state.get_data()

    preview = format_order_card(data, order_id=0)
    await state.set_state(CreateOrder.confirm)
    await callback.message.edit_text(preview, reply_markup=preview_keyboard())
    await callback.answer("Особенности: нет")


@router.message(CreateOrder.features)
async def step_features(message: types.Message, state):
    await state.update_data(features=message.text.strip())
    data = await state.get_data()

    preview = format_order_card(data, order_id=0)
    await state.set_state(CreateOrder.confirm)
    await message.answer(preview, reply_markup=preview_keyboard())


# === Подтверждение ===
@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: types.CallbackQuery, state):
    data = await state.get_data()
    order_id = insert_order(data)
    await state.clear()

    text = format_order_card(data, order_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Рассылка", callback_data=f"admin_broadcast:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=f"admin_edit_order:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=f"admin_cancel_order:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"admin_delete_order:{order_id}"
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("✅ Заказ сохранён")
    await callback.message.answer("📋 Админ-меню:", reply_markup=admin_menu())


# === Удаление заказа: шаг 1 — подтверждение ===
@router.callback_query(F.data.startswith("admin_delete_order:"))
async def admin_delete_order_confirm(callback: types.CallbackQuery):
    order_id = int(callback.data.split(":")[1])

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"admin_delete_order_yes:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Отмена", callback_data=f"admin_order:{order_id}"
                )
            ],
        ]
    )
    await callback.message.edit_text(
        f"Вы уверены, что хотите <b>удалить</b> заказ #{order_id}? "
        f"Действие необратимо: будут удалены записи смен и транзакции по заказу.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# === Удаление заказа: шаг 2 — выполнение ===
@router.callback_query(F.data.startswith("admin_delete_order_yes:"))
async def admin_delete_order_yes(callback: types.CallbackQuery):
    order_id = int(callback.data.split(":")[1])

    with sqlite3.connect(PATH_DATABASE) as con:
        cur = con.cursor()
        # Чистим связанные записи (если каскада нет)
        cur.execute("DELETE FROM transactions   WHERE order_id=?", (order_id,))
        cur.execute("DELETE FROM skipped_orders WHERE order_id=?", (order_id,))
        cur.execute("DELETE FROM shifts         WHERE order_id=?", (order_id,))
        # Сам заказ
        cur.execute("DELETE FROM orders         WHERE id=?", (order_id,))
        con.commit()

    await callback.message.edit_text(f"🗑 Заказ #{order_id} удалён.")
    await callback.answer("Готово.")
    # Вернёмся в админ-меню
    await callback.message.answer("📋 Админ-меню:", reply_markup=admin_menu())


# === Запуск рассылки ===
@router.callback_query(F.data.startswith("admin_broadcast:"))
async def admin_broadcast(callback: types.CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    await broadcast_order(bot, order_id)
    await callback.answer("✅ Рассылка запущена", show_alert=True)


# === Редактирование заказа ===
@router.callback_query(F.data == "edit_order")
async def start_edit_order(callback: types.CallbackQuery, state):
    """Показать меню выбора, что редактировать"""
    data = await state.get_data()

    if not data:
        await callback.answer("⚠️ Нет данных для редактирования. Создайте заказ заново.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Клиент", callback_data="edit_field:client_name"
                ),
                InlineKeyboardButton(
                    text="📞 Телефон", callback_data="edit_field:client_phone"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📝 Описание", callback_data="edit_field:description"
                ),
                InlineKeyboardButton(
                    text="📍 Адрес", callback_data="edit_field:address"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏙 Район", callback_data="edit_field:district"
                ),
                InlineKeyboardButton(
                    text="⏰ Время", callback_data="edit_field:start_time"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Кол-во мест", callback_data="edit_field:places_total"
                ),
                InlineKeyboardButton(
                    text="⚙️ Формат", callback_data="edit_field:format"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🌍 Гражданство", callback_data="edit_field:citizenship"
                ),
                InlineKeyboardButton(
                    text="ℹ️ Особенности", callback_data="edit_field:features"
                ),
            ],
            [
                InlineKeyboardButton(text="✅ Готово", callback_data="confirm_order"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_order"),
            ],
        ]
    )

    await callback.message.edit_text("✏️ Что вы хотите изменить?", reply_markup=kb)
    await callback.answer()


# === Переход к редактированию конкретного поля ===
@router.callback_query(F.data.startswith("edit_field:"))
async def choose_field_to_edit(callback: types.CallbackQuery, state):
    field = callback.data.split(":")[1]
    await state.update_data(edit_field=field)

    # Определяем, что показывать в зависимости от поля
    if field == "format":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏱ Почасовая", callback_data="set_format:hour"
                    ),
                    InlineKeyboardButton(
                        text="🕗 Смена (8ч)", callback_data="set_format:shift8"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📅 День (12ч)", callback_data="set_format:day12"
                    )
                ],
            ]
        )
        await callback.message.edit_text("⚙️ Выберите новый формат:", reply_markup=kb)

    elif field == "citizenship":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🇷🇺 РФ", callback_data="set_citizenship:РФ"
                    ),
                    InlineKeyboardButton(
                        text="🌍 Иностранец", callback_data="set_citizenship:Иностранец"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🤝 Любое", callback_data="set_citizenship:Любое"
                    )
                ],
            ]
        )
        await callback.message.edit_text(
            "🌍 Выберите требуемое гражданство:", reply_markup=kb
        )

    elif field == "places_total":
        await callback.message.edit_text(
            "👥 Введите новое количество работников (1–20):"
        )
        await state.set_state(CreateOrder.edit_field)
        return

    else:
        prompts = {
            "client_name": "Введите новое имя клиента:",
            "client_phone": "Введите новый телефон клиента:",
            "description": "Введите новое описание работы:",
            "address": "Введите новый адрес:",
            "district": "Введите новый район:",
            "start_time": "Введите новую дату и время (например: 15.09 09:00):",
            "features": "Введите новые особенности (или 'нет'):",
        }
        await callback.message.edit_text(prompts.get(field, "Введите новое значение:"))
        await state.set_state(CreateOrder.edit_field)

    await callback.answer()


# === Обработка кнопок для формат и гражданство ===
@router.callback_query(F.data.startswith("set_format:"))
async def set_format(callback: types.CallbackQuery, state):
    fmt = callback.data.split(":")[1]
    await state.update_data(format=fmt)
    preview = format_order_card(await state.get_data(), order_id=0)
    await callback.message.edit_text(
        f"✅ Формат обновлён.\n\n{preview}", reply_markup=preview_keyboard()
    )
    await state.set_state(CreateOrder.confirm)
    await callback.answer()


@router.callback_query(F.data.startswith("set_citizenship:"))
async def set_citizenship(callback: types.CallbackQuery, state):
    val = callback.data.split(":")[1]
    await state.update_data(citizenship=val)
    preview = format_order_card(await state.get_data(), order_id=0)
    await callback.message.edit_text(
        f"✅ Гражданство обновлено.\n\n{preview}", reply_markup=preview_keyboard()
    )
    await state.set_state(CreateOrder.confirm)
    await callback.answer()


# === Сохранение отредактированного значения вручную ===
@router.message(CreateOrder.edit_field)
async def save_edited_field(message: types.Message, state):
    data = await state.get_data()
    field = data.get("edit_field")
    new_value = message.text.strip()

    # Проверяем и конвертируем
    if field == "start_time":
        try:
            dt_obj = dt.datetime.strptime(new_value, "%d.%m %H:%M")
            dt_obj = dt_obj.replace(year=dt.datetime.now(TZ).year)
            new_value = int(dt_obj.timestamp())
        except Exception:
            await message.answer("⚠️ Формат неверный. Пример: 15.09 09:00")
            return

    if field == "places_total":
        try:
            n = int(new_value)
            if not 1 <= n <= 20:
                raise ValueError
            new_value = n
        except Exception:
            await message.answer("⚠️ Введите число от 1 до 20.")
            return

    # Обновляем в памяти FSM
    await state.update_data({field: new_value})
    preview = format_order_card(await state.get_data(), order_id=0)
    await message.answer(
        f"✅ Поле обновлено.\n\n{preview}", reply_markup=preview_keyboard()
    )
    await state.set_state(CreateOrder.confirm)
