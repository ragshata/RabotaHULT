# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, types
from tgbot.data.config import PATH_DATABASE

router = Router()


@router.callback_query(F.data.startswith("shift_done_autoping:"))
async def shift_done_from_autoping(c: types.CallbackQuery):
    sid = int(c.data.split(":")[1])
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    with sqlite3.connect(PATH_DATABASE) as con:
        con.execute(
            "UPDATE shifts SET status='done', finished_at=? WHERE id=?", (now, sid)
        )
        con.commit()
    await c.answer("Спасибо! Отметили, что вы отработали.", show_alert=True)
    await c.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("shift_still:"))
async def shift_still_working(c: types.CallbackQuery):
    await c.answer(
        "Ок, учли что вы ещё на смене. Напомните позже «✅ Отработал».", show_alert=True
    )


@router.callback_query(F.data.startswith("shift_issue:"))
async def shift_issue(c: types.CallbackQuery):
    # тут можно раскрыть «быстрые причины» и слать сигнал оператору
    await c.answer("Сообщение оператору отправлено. Ожидайте связи.", show_alert=True)
