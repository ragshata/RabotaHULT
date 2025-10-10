# -*- coding: utf-8 -*-
import sqlite3
from aiogram import Router, F, types
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import StateFilter
from aiogram.fsm.state import StatesGroup, State

from tgbot.data.config import PATH_DATABASE, get_admins
from tgbot.routers.admin_panel import admin_menu
from tgbot.utils.misc.bot_models import FSM


router = Router()


# ================= FSM Состояния =================
class Onboarding(StatesGroup):
    get_phone = State()
    get_name = State()
    get_city = State()
    get_district = State()
    get_citizenship = State()
    get_country = State()
    finish_registration = State()


# ================= Вспомогательные =================
def save_worker_data(user_id: int, field: str, value):
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            f"UPDATE workers SET {field} = ? WHERE telegram_id = ?", (value, user_id)
        )
        con.commit()


def ensure_worker_record(user_id: int) -> None:
    """Создаём пустую запись работника, если её ещё нет (имя берём только из регистрации)."""
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO workers 
            (telegram_id, name, phone, city, district, citizenship, created_at)
            VALUES (?, '', '', '', '', '', strftime('%s','now'))
            """,
            (user_id,),
        )
        con.commit()


def is_registered(user_id: int) -> bool:
    """Пользователь считается зарегистрированным, если у него есть непустой телефон и имя."""
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT phone, name FROM workers WHERE telegram_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        phone, name = row["phone"], row["name"]
        return bool(phone and str(phone).strip()) and bool(name and str(name).strip())


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Новые заказы")],
            [KeyboardButton(text="📅 Мои смены")],
            [KeyboardButton(text="💰 Баланс")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )


def policy_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен", callback_data="agree_policy")],
            [
                InlineKeyboardButton(
                    text="📖 Правила",
                    url="https://telegra.ph/Pravila-servisa--RabotayBro-10-10",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔒 Политика конфиденциальности",
                    url="https://telegra.ph/Politika-konfidencialnosti-10-10-37",
                )
            ],
        ]
    )


# ================= Хэндлеры =================
# === 1. START ===
@router.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSM):
    user_id = message.from_user.id

    # Если это админ — сразу кидаем в админку
    if user_id in get_admins():
        await message.answer(
            "Добро пожаловать в админ-панель!", reply_markup=admin_menu()
        )
        return

    # Создаём «черновик» пользователя
    ensure_worker_record(user_id)

    # Если уже зарегистрирован — главное меню
    if is_registered(user_id):
        await message.answer("С возвращением! Главное меню:", reply_markup=main_menu())
        await state.clear()
        return

    # Новый пользователь → регистрация
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Ну Здравствуй Брат! RabotayBro — это бот для поиска подработки в Екатеринбурге. "
        "Подтвердите номер телефона для регистрации нажав кнопку ниже 👇",
        reply_markup=kb,
    )

    await state.set_state(Onboarding.get_phone)


# === 2. Телефон ===
@router.message(StateFilter(Onboarding.get_phone), F.contact)
async def get_phone(message: types.Message, state: FSM):
    phone = message.contact.phone_number
    save_worker_data(message.from_user.id, "phone", phone)
    await message.answer(
        "Укажите ваше имя (2–40 символов).", reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Onboarding.get_name)


@router.message(StateFilter(Onboarding.get_phone))
async def invalid_phone(message: types.Message):
    await message.answer("Нужно подтвердить номер. Нажмите “📱 Отправить номер”.")
    return


# === 3. Имя ===
@router.message(StateFilter(Onboarding.get_name))
async def get_name(message: types.Message, state: FSM):
    name = message.text.strip()
    if not (2 <= len(name) <= 40) or name.isdigit():
        await message.answer("Укажите имя (2–40 символов).")
        return

    save_worker_data(
        message.from_user.id, "name", name
    )  # <- сохраняем вручную введённое имя

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Екатеринбург")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Выберите ваш город:", reply_markup=kb)
    await state.set_state(Onboarding.get_city)


# === 4. Город ===
@router.message(StateFilter(Onboarding.get_city), F.text == "Екатеринбург")
async def get_city(message: types.Message, state: FSM):
    save_worker_data(message.from_user.id, "city", "Екатеринбург")

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Академический"),
                KeyboardButton(text="Верх-Исетский"),
            ],
            [KeyboardButton(text="Железнодорожный"), KeyboardButton(text="Кировский")],
            [KeyboardButton(text="Ленинский"), KeyboardButton(text="Октябрьский")],
            [
                KeyboardButton(text="Орджоникидзевский"),
                KeyboardButton(text="Чкаловский"),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Выберите ваш район:", reply_markup=kb)
    await state.set_state(Onboarding.get_district)


# === 5. Район ===
@router.message(StateFilter(Onboarding.get_district))
async def get_district(message: types.Message, state: FSM):
    district = message.text.strip()
    valid_districts = [
        "Академический",
        "Верх-Исетский",
        "Железнодорожный",
        "Кировский",
        "Ленинский",
        "Октябрьский",
        "Орджоникидзевский",
        "Чкаловский",
    ]
    if district not in valid_districts:
        await message.answer("Выберите район из списка кнопок.")
        return

    save_worker_data(message.from_user.id, "district", district)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Гражданин РФ"), KeyboardButton(text="Иностранец")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Укажите гражданство:", reply_markup=kb)
    await state.set_state(Onboarding.get_citizenship)


# === 6. Гражданство ===
@router.message(StateFilter(Onboarding.get_citizenship), F.text == "Гражданин РФ")
async def citizen_rf(message: types.Message, state: FSM):
    save_worker_data(message.from_user.id, "citizenship", "РФ")
    await message.answer(
        "Отправляя данные, вы соглашаетесь с Правилами и Политикой конфиденциальности.",
        reply_markup=policy_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(StateFilter(Onboarding.get_citizenship), F.text == "Иностранец")
async def citizen_foreign(message: types.Message, state: FSM):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Казахстан"), KeyboardButton(text="Узбекистан")],
            [KeyboardButton(text="Кыргызстан"), KeyboardButton(text="Таджикистан")],
            [KeyboardButton(text="Азербайджан"), KeyboardButton(text="Армения")],
            [KeyboardButton(text="Беларусь"), KeyboardButton(text="Другая страна")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Выберите страну:", reply_markup=kb)
    await state.set_state(Onboarding.get_country)


# === 6.1 Страна для иностранцев ===
@router.message(StateFilter(Onboarding.get_country))
async def get_country(message: types.Message, state: FSM):
    save_worker_data(message.from_user.id, "citizenship", "Иностранец")
    save_worker_data(message.from_user.id, "country", message.text.strip())
    await message.answer(
        "Отправляя данные, вы соглашаетесь с Правилами и Политикой конфиденциальности.",
        reply_markup=policy_keyboard(),
        disable_web_page_preview=True,
    )


# === 7. Завершение ===
@router.callback_query(F.data == "agree_policy")
async def agree_and_finish(callback: types.CallbackQuery, state: FSM):
    text = (
        "Ваш аккаунт успешно активирован. Добро пожаловать в RabotayBro. ✅\n\n"
        "Мы предлагаем следующие форматы сотрудничества:\n"
        "- Почасовая оплата (минимум 4 часа): 400 ₽/час\n"
        "- Смена (8 часов): 3500 ₽\n"
        "- Полный день (12 часов): 4800 ₽\n\n"
        "Загляни в «📦 Новые заказы» — если готов работать!"
    )

    await callback.answer()

    # снимаем старую inline-клавиатуру (если была)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # отправляем НОВОЕ сообщение с ReplyKeyboardMarkup главного меню
    await callback.message.answer(text, reply_markup=main_menu())

    await state.clear()
