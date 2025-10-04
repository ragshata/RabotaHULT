# -*- coding: utf-8 -*-
import sqlite3
from aiogram import Router, F, types
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State

from tgbot.data.config import PATH_DATABASE

router = Router()


class ProfileEdit(StatesGroup):
    name = State()
    district = State()
    citizenship = State()
    country = State()
    phone = State()


# === Получение профиля ===
def get_user_profile(user_id: int) -> dict | None:
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM workers WHERE telegram_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


# === Формирование текста профиля ===
def profile_text(profile: dict) -> str:
    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🧾 Имя: {profile['name']}\n"
        f"📞 Телефон: {profile['phone']}\n"
        f"🏙 Город: {profile.get('city','—')}\n"
        f"📍 Район: {profile['district']}\n"
        f"🌍 Гражданство: {profile['citizenship']}"
    )
    if profile["citizenship"] == "Иностранец" and profile.get("country"):
        text += f" ({profile['country']})"
    text += f"\n⭐️ Рейтинг: {profile.get('rating', 0):.1f}"
    return text


# === Клавиатура редактирования профиля ===
def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить имя", callback_data="profile_edit:name"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📱 Изменить телефон", callback_data="profile_edit:phone"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Изменить район", callback_data="profile_edit:district"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌍 Изменить гражданство",
                    callback_data="profile_edit:citizenship",
                )
            ],
        ]
    )


# === Просмотр профиля ===
@router.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    profile = get_user_profile(message.from_user.id)
    if not profile:
        await message.answer("❗️ Профиль не найден. Пройдите регистрацию заново.")
        return
    await message.answer(
        profile_text(profile), reply_markup=profile_keyboard(), parse_mode="HTML"
    )


# === Вход в редактирование ===
@router.callback_query(F.data.startswith("profile_edit:"))
async def edit_profile(callback: CallbackQuery, state):
    field = callback.data.split(":")[1]

    if field == "name":
        await state.set_state(ProfileEdit.name)
        await callback.message.answer("Введите новое имя (2–40 символов):")

    elif field == "phone":
        await state.set_state(ProfileEdit.phone)
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Отправить номер", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await callback.message.answer(
            "Подтвердите новый номер телефона:", reply_markup=kb
        )

    elif field == "district":
        await state.set_state(ProfileEdit.district)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Академический", callback_data="set_district:Академический"
                    ),
                    InlineKeyboardButton(
                        text="Верх-Исетский", callback_data="set_district:Верх-Исетский"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Железнодорожный",
                        callback_data="set_district:Железнодорожный",
                    ),
                    InlineKeyboardButton(
                        text="Кировский", callback_data="set_district:Кировский"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Ленинский", callback_data="set_district:Ленинский"
                    ),
                    InlineKeyboardButton(
                        text="Октябрьский", callback_data="set_district:Октябрьский"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Орджоникидзевский",
                        callback_data="set_district:Орджоникидзевский",
                    ),
                    InlineKeyboardButton(
                        text="Чкаловский", callback_data="set_district:Чкаловский"
                    ),
                ],
            ]
        )
        await callback.message.answer("Выберите район:", reply_markup=kb)

    elif field == "citizenship":
        await state.set_state(ProfileEdit.citizenship)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🇷🇺 Гражданин РФ", callback_data="set_citizenship:РФ"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🌍 Иностранец", callback_data="set_citizenship:Иностранец"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🤝 Любое", callback_data="set_citizenship:Любое"
                    )
                ],
            ]
        )
        await callback.message.answer("Выберите гражданство:", reply_markup=kb)

    await callback.answer()


# === Сохранение имени ===
@router.message(ProfileEdit.name)
async def save_name(message: types.Message, state):
    value = message.text.strip()
    if not (2 <= len(value) <= 40) or value.isdigit():
        await message.answer("❗️ Имя должно быть от 2 до 40 символов.")
        return

    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "UPDATE workers SET name=? WHERE telegram_id=?",
            (value, message.from_user.id),
        )
        con.commit()

    await state.clear()
    profile = get_user_profile(message.from_user.id)
    await message.answer(
        "✅ Имя обновлено.\n\n" + profile_text(profile),
        reply_markup=profile_keyboard(),
        parse_mode="HTML",
    )


# === Сохранение телефона ===
@router.message(ProfileEdit.phone, F.contact)
async def save_phone(message: types.Message, state):
    phone = message.contact.phone_number
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "UPDATE workers SET phone=? WHERE telegram_id=?",
            (phone, message.from_user.id),
        )
        con.commit()

    await state.clear()
    profile = get_user_profile(message.from_user.id)
    await message.answer(
        "✅ Телефон обновлён.\n\n" + profile_text(profile),
        reply_markup=profile_keyboard(),
        parse_mode="HTML",
    )


@router.message(ProfileEdit.phone)
async def invalid_phone_edit(message: types.Message):
    await message.answer("❗️ Нужно подтвердить номер. Нажмите «📱 Отправить номер».")


# === Сохранение района ===
@router.callback_query(F.data.startswith("set_district:"))
async def save_district(callback: CallbackQuery, state):
    district = callback.data.split(":")[1]
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "UPDATE workers SET district=? WHERE telegram_id=?",
            (district, callback.from_user.id),
        )
        con.commit()

    await state.clear()
    profile = get_user_profile(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Район обновлён.\n\n" + profile_text(profile),
        reply_markup=profile_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# === Сохранение гражданства ===
@router.callback_query(F.data.startswith("set_citizenship:"))
async def save_citizenship(callback: CallbackQuery, state):
    citizenship = callback.data.split(":")[1]

    if citizenship == "Иностранец":
        await state.set_state(ProfileEdit.country)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Казахстан", callback_data="set_country:Казахстан"
                    ),
                    InlineKeyboardButton(
                        text="Узбекистан", callback_data="set_country:Узбекистан"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Кыргызстан", callback_data="set_country:Кыргызстан"
                    ),
                    InlineKeyboardButton(
                        text="Таджикистан", callback_data="set_country:Таджикистан"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Азербайджан", callback_data="set_country:Азербайджан"
                    ),
                    InlineKeyboardButton(
                        text="Армения", callback_data="set_country:Армения"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Беларусь", callback_data="set_country:Беларусь"
                    ),
                    InlineKeyboardButton(
                        text="Другая страна", callback_data="set_country:Другая страна"
                    ),
                ],
            ]
        )
        await callback.message.answer("Укажите страну:", reply_markup=kb)
    else:
        with sqlite3.connect(PATH_DATABASE) as con:
            con.execute(
                "UPDATE workers SET citizenship=?, country=NULL WHERE telegram_id=?",
                (citizenship, callback.from_user.id),
            )
            con.commit()

        await state.clear()
        profile = get_user_profile(callback.from_user.id)
        await callback.message.edit_text(
            "✅ Гражданство обновлено.\n\n" + profile_text(profile),
            reply_markup=profile_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


# === Сохранение страны (для иностранца) ===
@router.callback_query(F.data.startswith("set_country:"))
async def save_country(callback: CallbackQuery, state):
    country = callback.data.split(":")[1]
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "UPDATE workers SET citizenship='Иностранец', country=? WHERE telegram_id=?",
            (country, callback.from_user.id),
        )
        con.commit()

    await state.clear()
    profile = get_user_profile(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Гражданство обновлено.\n\n" + profile_text(profile),
        reply_markup=profile_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
