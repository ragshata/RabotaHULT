# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from tgbot.data.config import PATH_DATABASE
from tgbot.utils.misc.bot_filters import IsAdmin

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE_SIZE = 10


# ====================== Вспомогательные ======================
def _dicts(con):
    con.row_factory = sqlite3.Row
    return con.cursor()


def _citizenship_display(w: dict) -> str:
    """Красиво отобразить гражданство и страну"""
    if w.get("citizenship") == "Иностранец" and w.get("country"):
        return f"🌍 Иностранец ({w['country']})"
    elif w.get("citizenship") == "РФ":
        return "🇷🇺 Гражданин РФ"
    return w.get("citizenship", "-")


def _status_display(w: dict) -> str:
    return "🟢 Активен" if w.get("status") == "active" else "🔴 Заблокирован"


def _count_shifts(con: sqlite3.Connection, worker_id: int) -> int:
    """Подсчёт всех смен работника"""
    return con.execute(
        "SELECT COUNT(*) FROM shifts WHERE worker_id=?", (worker_id,)
    ).fetchone()[0]


def _get_recent_shifts(worker_id: int, limit: int = 5):
    """Последние N смен"""
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute(
            """
            SELECT s.id AS shift_id, o.description, o.start_time, o.format, s.status
            FROM shifts s
            JOIN orders o ON o.id = s.order_id
            WHERE s.worker_id=?
            ORDER BY o.start_time DESC
            LIMIT ?
            """,
            (worker_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _format_shift_row(s: dict) -> str:
    """Формат одной смены для истории"""
    start = dt.datetime.fromtimestamp(s["start_time"]).strftime("%d.%m %H:%M")
    status_ru = {
        "accepted": "принял участие",
        "arrived": "прибыл",
        "done": "завершил",
        "no_show": "не явился",
        "cancelled": "отменён",
    }.get(s["status"], s["status"])

    if s["format"] == "hour":
        rate = "400 ₽/час"
    elif s["format"] == "shift8":
        rate = "3500 ₽ (8ч)"
    else:
        rate = "4800 ₽ (12ч)"

    return (
        f"📅 {start} — {s['description']}\n🧩 {s['format']} | 💰 {rate} | {status_ru}"
    )


# ====================== Список работников ======================
@router.message(F.text == "👷 Рабочие")
async def show_workers(message: types.Message):
    """Показать список работников (инлайн-кнопки)"""
    page = 0
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        rows = cur.execute(
            "SELECT * FROM workers ORDER BY id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, page * PAGE_SIZE),
        ).fetchall()
        total = cur.execute("SELECT COUNT(*) FROM workers").fetchone()[0]

    if not rows:
        await message.answer("❗️ В базе нет зарегистрированных работников.")
        return

    kb_rows = []
    for w in rows:
        w = dict(w)
        text = f"{w['name']} | {w['phone']} | {_citizenship_display(w)}"
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=text, callback_data=f"admin_worker_info:{w['id']}:{page}"
                )
            ]
        )

    nav = []
    if (page + 1) * PAGE_SIZE < total:
        nav.append(
            InlineKeyboardButton(
                text="➡️ Вперёд", callback_data=f"admin_workers_page:{page+1}"
            )
        )
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"admin_workers_page:{page-1}"
            )
        )
    if nav:
        kb_rows.append(nav)

    await message.answer(
        "👷 <b>Список работников</b>:\nНажмите на пользователя, чтобы открыть карточку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode="HTML",
    )


# ====================== Пагинация ======================
@router.callback_query(F.data.startswith("admin_workers_page:"))
async def paginate_workers(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute(
            "SELECT * FROM workers ORDER BY id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, page * PAGE_SIZE),
        ).fetchall()
        total = cur.execute("SELECT COUNT(*) FROM workers").fetchone()[0]

    if not rows:
        await callback.answer("Нет работников на этой странице.", show_alert=True)
        return

    kb_rows = []
    for w in rows:
        w = dict(w)
        text = f"{w['name']} | {w['phone']} | {_citizenship_display(w)}"
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=text, callback_data=f"admin_worker_info:{w['id']}:{page}"
                )
            ]
        )

    nav = []
    if (page + 1) * PAGE_SIZE < total:
        nav.append(
            InlineKeyboardButton(
                text="➡️ Вперёд", callback_data=f"admin_workers_page:{page+1}"
            )
        )
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"admin_workers_page:{page-1}"
            )
        )
    if nav:
        kb_rows.append(nav)

    await callback.message.edit_text(
        "👷 <b>Список работников</b>:\nНажмите на пользователя, чтобы открыть карточку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode="HTML",
    )
    await callback.answer()


# ====================== Карточка работника ======================
@router.callback_query(F.data.startswith("admin_worker_info:"))
async def show_worker_card(callback: CallbackQuery):
    _, worker_id, page = callback.data.split(":")
    worker_id = int(worker_id)
    page = int(page)

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        w = con.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
        if not w:
            await callback.answer("Работник не найден.", show_alert=True)
            return
        w = dict(w)
        total_shifts = _count_shifts(con, worker_id)

    text = (
        f"👤 <b>{w['name']}</b> (ID: {w['id']})\n"
        f"📞 Телефон: <code>{w['phone']}</code>\n"
        f"🌍 Гражданство: {_citizenship_display(w)}\n"
        f"🏙 Район: {w.get('district', '-')}\n"
        f"⭐️ Рейтинг: {w.get('rating', 0):.1f}\n"
        f"📊 Статус: {_status_display(w)}\n"
        f"🗓 Всего смен: {total_shifts}\n"
        f"👥 Telegram: @{w.get('telegram_login', '-')}\n"
        f"📅 Дата регистрации: "
        f"{dt.datetime.fromtimestamp(w.get('created_at', 0)).strftime('%d.%m.%Y %H:%M') if w.get('created_at') else '-'}"
    )

    is_blocked = w.get("status") == "blocked"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 История смен",
                    callback_data=f"admin_worker_history:{w['id']}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("🔓 Разблокировать" if is_blocked else "🔒 Заблокировать"),
                    callback_data=f"admin_worker_toggle:{w['id']}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад к списку", callback_data=f"admin_workers_page:{page}"
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ====================== История смен ======================
@router.callback_query(F.data.startswith("admin_worker_history:"))
async def show_worker_history(callback: CallbackQuery):
    _, worker_id, page = callback.data.split(":")
    worker_id = int(worker_id)

    shifts = _get_recent_shifts(worker_id)
    if not shifts:
        text = "❗️ У пользователя пока нет смен."
    else:
        text = "📊 <b>Последние 5 смен:</b>\n\n"
        text += "\n\n".join(_format_shift_row(s) for s in shifts)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"admin_worker_info:{worker_id}:{page}",
                )
            ]
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ====================== Блокировка/Разблокировка ======================
@router.callback_query(F.data.startswith("admin_worker_toggle:"))
async def toggle_worker_status(callback: CallbackQuery):
    _, worker_id, page = callback.data.split(":")
    worker_id = int(worker_id)
    page = int(page)

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        w = con.execute(
            "SELECT id, status FROM workers WHERE id=?", (worker_id,)
        ).fetchone()
        if not w:
            await callback.answer("Работник не найден.", show_alert=True)
            return
        w = dict(w)
        new_status = "active" if w["status"] == "blocked" else "blocked"
        con.execute("UPDATE workers SET status=? WHERE id=?", (new_status, worker_id))
        con.commit()

    msg = (
        "✅ Работник разблокирован."
        if new_status == "active"
        else "🚫 Работник заблокирован."
    )
    await callback.answer(msg, show_alert=True)
    await show_worker_card(callback)
