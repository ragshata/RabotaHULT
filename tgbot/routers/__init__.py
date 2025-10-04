# -*- coding: utf-8 -*-
from aiogram import Dispatcher, F

# Импортируем все роутеры
from tgbot.routers import (
    admin_balance,
    admin_cancel,
    admin_orders,
    admin_workers,
    onboarding,
    orders,
    shifts,
    balance,
    profile,
    shifts_actions,
    help,
)
from tgbot.routers import admin_panel  # если нужен отдельный модуль админки


# Регистрация всех роутеров
def register_all_routers(dp: Dispatcher):
    # Работаем только в личке
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")

    # === Пользовательские роутеры ===
    dp.include_router(onboarding.router)  # Онбординг + регистрация
    dp.include_router(orders.router)  # Лента заказов
    dp.include_router(shifts.router)  # Мои смены
    dp.include_router(balance.router)  # Баланс и выплаты
    dp.include_router(admin_orders.router)  # Функционал админа
    dp.include_router(admin_cancel.router)  #
    dp.include_router(shifts_actions.router)  #
    dp.include_router(admin_balance.router)  # Выплаты админа
    dp.include_router(profile.router)  # Профиль юзера
    dp.include_router(admin_workers.router)  # Список юезров
    dp.include_router(help.router)  # Помощь

    # === Админский роутер (если нужен) ===
    dp.include_router(admin_panel.router)
