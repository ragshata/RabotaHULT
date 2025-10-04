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
from tgbot.services.broadcast import broadcast_order
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
        f"⏰ Старт: {dt.datetime.fromtimestamp(data['start_time']).strftime('%d.%m %H:%M')}\n"
        f"⚙️ Формат: {data['format']}\n"
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
    await message.answer("👤 Введите имя клиента:")


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
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("✅ Заказ сохранён")


# === Запуск рассылки ===
@router.callback_query(F.data.startswith("admin_broadcast:"))
async def admin_broadcast(callback: types.CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    await broadcast_order(bot, order_id)
    await callback.answer("✅ Рассылка запущена", show_alert=True)
