# -*- coding: utf-8 -*-
import sqlite3
import datetime as dt
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from tgbot.data.config import PATH_DATABASE


# ================= Вспомогательные =================
def _ensure_notifications_table(con: sqlite3.Connection):
    """Таблица логов рассылок (чтобы не дублировались уведомления)"""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL,
            kind TEXT NOT NULL,              -- 'pre2h' | 'no_show' | 'autoping'
            sent_at INTEGER NOT NULL,
            UNIQUE(shift_id, kind)
        )
        """
    )


def _now_ts() -> int:
    return int(dt.datetime.now().timestamp())


def _format_hhmm(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def _planned_end_ts(order_start: int, fmt: str) -> int:
    """Возвращает плановое время окончания смены"""
    if fmt == "shift8":
        return order_start + 8 * 3600
    if fmt == "day12":
        return order_start + 12 * 3600
    # Почасовая (минимум 4 часа)
    return order_start + 4 * 3600


# ===================== 1) Напоминания за 2 часа =====================
async def job_send_pre_start_reminders(bot: Bot):
    """
    Каждые 5 минут: напоминание за 2 часа до старта.
    Только если статус смены = 'accepted' и ещё не слали 'pre2h'.
    """
    now = _now_ts()
    win_from = now + 2 * 3600
    win_to = win_from + 5 * 60  # окно 5 минут

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        _ensure_notifications_table(con)

        rows = con.execute(
            """
            SELECT s.id AS shift_id, s.worker_id, w.telegram_id, o.id AS order_id,
                   o.address, o.district, o.start_time
            FROM shifts s
            JOIN workers w ON w.id = s.worker_id
            JOIN orders  o ON o.id = s.order_id
            WHERE s.status = 'accepted'
              AND o.status = 'created'
              AND o.start_time BETWEEN ? AND ?
              AND NOT EXISTS (
                    SELECT 1 FROM notifications_log nl
                    WHERE nl.shift_id = s.id AND nl.kind = 'pre2h'
              )
            """,
            (win_from, win_to),
        ).fetchall()

        for r in rows:
            try:
                text = (
                    f"⏰ Напоминание: смена по заказу №{r['order_id']} начнётся в "
                    f"{_format_hhmm(r['start_time'])}.\n"
                    f"📍 Адрес: {r['address']} ({r['district']}).\n"
                    f"Не забудьте отметить прибытие кнопкой «📍 Я на месте»."
                )
                await bot.send_message(r["telegram_id"], text)
                con.execute(
                    "INSERT OR IGNORE INTO notifications_log (shift_id, kind, sent_at) VALUES (?, 'pre2h', ?)",
                    (r["shift_id"], now),
                )
                con.commit()
            except Exception:
                pass


# --- NEW: уведомление в момент старта ---
async def job_notify_on_start(bot: Bot):
    now = _now_ts()
    # окно "прямо сейчас" 5 мин
    win_from = now
    win_to = now + 5 * 60

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        _ensure_notifications_table(con)

        rows = con.execute(
            """
            SELECT s.id AS shift_id, s.worker_id, w.telegram_id, o.id AS order_id, o.start_time
            FROM shifts s
            JOIN workers w ON w.id = s.worker_id
            JOIN orders  o ON o.id = s.order_id
            WHERE s.status = 'accepted'
              AND o.status IN ('created','started')
              AND o.start_time BETWEEN ? AND ?
              AND NOT EXISTS (
                    SELECT 1 FROM notifications_log nl
                    WHERE nl.shift_id = s.id AND nl.kind = 'start_now'
              )
            """,
            (win_from, win_to),
        ).fetchall()

        for r in rows:
            try:
                await bot.send_message(
                    r["telegram_id"],
                    "🚦 Смена началась. Подтвердите прибытие — “📍 Я на месте”.",
                )
                con.execute(
                    "INSERT OR IGNORE INTO notifications_log (shift_id, kind, sent_at) VALUES (?, 'start_now', ?)",
                    (r["shift_id"], now),
                )
                con.commit()
            except Exception:
                pass


# --- NEW: напоминание за 30 минут до старта ---
async def job_send_30min_reminders(bot: Bot):
    now = _now_ts()
    win_from = now + 30 * 60
    win_to = win_from + 5 * 60  # окно 5 минут

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        _ensure_notifications_table(con)

        rows = con.execute(
            """
            SELECT s.id AS shift_id, s.worker_id, w.telegram_id, o.id AS order_id,
                   o.address, o.district, o.start_time
            FROM shifts s
            JOIN workers w ON w.id = s.worker_id
            JOIN orders  o ON o.id = s.order_id
            WHERE s.status = 'accepted'
              AND o.status = 'created'
              AND o.start_time BETWEEN ? AND ?
              AND NOT EXISTS (
                    SELECT 1 FROM notifications_log nl
                    WHERE nl.shift_id = s.id AND nl.kind = 'pre30m'
              )
            """,
            (win_from, win_to),
        ).fetchall()

        for r in rows:
            try:
                text = "⏳ Скоро старт! Нажмите “📍 Я на месте”, когда прибудете."
                await bot.send_message(r["telegram_id"], text)
                con.execute(
                    "INSERT OR IGNORE INTO notifications_log (shift_id, kind, sent_at) VALUES (?, 'pre30m', ?)",
                    (r["shift_id"], now),
                )
                con.commit()
            except Exception:
                pass


# ===================== 2) Неявки через 15 минут =====================
async def job_mark_no_shows_and_penalize(bot: Bot):
    """
    Если прошло 15+ минут от старта и статус смены 'accepted',
    то помечаем 'no_show', рейтинг -1.0, блокировка 7 дней.
    """
    now = _now_ts()
    threshold = now - 15 * 60

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        _ensure_notifications_table(con)

        rows = con.execute(
            """
            SELECT s.id AS shift_id, s.worker_id, w.telegram_id,
                   o.id AS order_id, o.start_time
            FROM shifts s
            JOIN workers w ON w.id = s.worker_id
            JOIN orders  o ON o.id = s.order_id
            WHERE s.status = 'accepted'
              AND o.start_time <= ?
              AND NOT EXISTS (
                    SELECT 1 FROM notifications_log nl
                    WHERE nl.shift_id = s.id AND nl.kind = 'no_show'
              )
            """,
            (threshold,),
        ).fetchall()

        for r in rows:
            try:
                con.execute(
                    "UPDATE shifts SET status='no_show' WHERE id=?", (r["shift_id"],)
                )
                con.execute(
                    "UPDATE workers SET rating = rating - 1.0, blocked_until = ? WHERE id=?",
                    (now + 7 * 86400, r["worker_id"]),
                )
                con.execute(
                    "INSERT OR IGNORE INTO notifications_log (shift_id, kind, sent_at) VALUES (?, 'no_show', ?)",
                    (r["shift_id"], now),
                )
                con.commit()

                await bot.send_message(
                    r["telegram_id"],
                    "❌ Вы не отметились на смене в течение 15 минут после старта.\n"
                    "Статус: не явился.\n"
                    "Рейтинг снижен на 1.0, профиль заблокирован на 7 дней.",
                )
            except Exception:
                pass


# ===================== 3) Автопинг после окончания =====================
async def job_autoping_after_end(bot: Bot):
    """
    Через 30 минут после планового окончания смены
    шлём автопинг, если статус = 'accepted' или 'arrived'.
    """
    now = _now_ts()

    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = sqlite3.Row
        _ensure_notifications_table(con)

        rows = con.execute(
            """
            SELECT s.id AS shift_id, s.worker_id, w.telegram_id,
                   o.id AS order_id, o.start_time, o.format, o.address, o.district
            FROM shifts s
            JOIN workers w ON w.id = s.worker_id
            JOIN orders  o ON o.id = s.order_id
            WHERE s.status IN ('accepted','arrived')
              AND o.status IN ('created','started')
            """
        ).fetchall()

        for r in rows:
            end_ts = _planned_end_ts(r["start_time"], r["format"])
            if now < end_ts + 30 * 60:
                continue

            exists = con.execute(
                "SELECT 1 FROM notifications_log WHERE shift_id=? AND kind='autoping' LIMIT 1",
                (r["shift_id"],),
            ).fetchone()
            if exists:
                continue

            try:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ Отработал",
                                callback_data=f"shift_done:{r['shift_id']}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="⏳ Ещё работаю",
                                callback_data=f"shift_still:{r['shift_id']}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="⚠️ Проблема",
                                callback_data=f"shift_issue:{r['shift_id']}",
                            )
                        ],
                    ]
                )
                text = (
                    f"⏳ Смена по заказу №{r['order_id']} завершилась.\n"
                    f"📍 Адрес: {r['address']} ({r['district']}).\n"
                    "Подтвердите статус:"
                )
                await bot.send_message(r["telegram_id"], text, reply_markup=kb)

                con.execute(
                    "INSERT OR IGNORE INTO notifications_log (shift_id, kind, sent_at) VALUES (?, 'autoping', ?)",
                    (r["shift_id"], now),
                )
                con.commit()
            except Exception:
                pass
