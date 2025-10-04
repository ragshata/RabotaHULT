# -*- coding: utf-8 -*-
from aiogram import Dispatcher

from tgbot.middlewares.exists_user import ExistsUserMiddleware
from tgbot.middlewares.throttling import ThrottlingMiddleware


def register_all_middlwares(dp: Dispatcher):
    dp.message.middleware(ExistsUserMiddleware())
    dp.message.middleware(ThrottlingMiddleware())
