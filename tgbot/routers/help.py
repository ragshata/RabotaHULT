# -*- coding: utf-8 -*-
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

router = Router()


def help_keyboard() -> InlineKeyboardMarkup:
    # те же ссылки, что и при регистрации
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📖 Правила сервиса", url="https://telegra.ph/Proba-09-29-12"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔒 Политика конфиденциальности",
                    url="https://telegra.ph/Proba-09-29-12",
                )
            ],
        ]
    )


@router.message(F.text == "❓ Помощь")
async def help_menu(message: types.Message):
    text = (
        "❓ <b>Помощь</b>\n\n"
        "Здесь собраны основные документы сервиса:\n"
        "• Правила использования\n"
        "• Политика конфиденциальности\n\n"
        "Нажмите кнопки ниже, чтобы открыть документы."
    )
    await message.answer(text, reply_markup=help_keyboard(), parse_mode="HTML")
