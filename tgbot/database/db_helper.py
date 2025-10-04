# -*- coding: utf-8 -*-
import sqlite3

from tgbot.data.config import PATH_DATABASE
from tgbot.utils.const_functions import ded


# Преобразование полученного списка в словарь
def dict_factory(cursor, row) -> dict:
    save_dict = {}
    for idx, col in enumerate(cursor.description):
        save_dict[col[0]] = row[idx]
    return save_dict


################################################################################
# Создание всех таблиц для БД
def create_dbx():
    with sqlite3.connect(PATH_DATABASE) as con:
        con.row_factory = dict_factory

        ############################################################
        # Таблица с рабочими (профили)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS workers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                city TEXT,
                district TEXT NOT NULL,
                citizenship TEXT NOT NULL,
                country TEXT,
                rating REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                telegram_login TEXT,
                created_at INTEGER
            )
            """
        )

        print("Table workers ready")

        ############################################################
        # Таблица заказов
        con.execute(
            ded(
                """
                CREATE TABLE IF NOT EXISTS orders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_name TEXT,
                    client_phone TEXT,  
                    description TEXT,
                    address TEXT,
                    district TEXT,
                    start_time INTEGER,
                    format TEXT,
                    citizenship_required TEXT,
                    places_total INTEGER,
                    places_taken INTEGER DEFAULT 0,
                    features TEXT,
                    status TEXT DEFAULT 'created'
                )
                """
            )
        )
        print("Table orders ready")

        ############################################################
        # Таблица смен (записи рабочих на заказы)
        con.execute(
            ded(
                """
                CREATE TABLE IF NOT EXISTS shifts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    worker_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'accepted',   -- accepted/arrived/done/cancelled/no_show
                    start_time INTEGER,               -- плановое время старта (из заказа)
                    end_time INTEGER,                 -- плановое время окончания (по формату)
                    accepted_at INTEGER,              -- когда работник взял заказ
                    arrived_at INTEGER,               -- когда отметил "я на месте"
                    finished_at INTEGER,              -- когда нажал "отработал"
                    remind_2h_sent INTEGER DEFAULT 0,
                    remind_30m_sent INTEGER DEFAULT 0,
                    remind_start_sent INTEGER DEFAULT 0,
                    autoping_sent INTEGER DEFAULT 0,
                    no_show_marked INTEGER DEFAULT 0,
                    FOREIGN KEY(order_id) REFERENCES orders(id),
                    FOREIGN KEY(worker_id) REFERENCES workers(id)
                )
                """
            )
        )
        print("Table shifts ready")

        ############################################################
        # Таблица пропущенных заказов (на 48ч)
        con.execute(
            ded(
                """
                CREATE TABLE IF NOT EXISTS skipped_orders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL,
                    skipped_at INTEGER,
                    FOREIGN KEY(worker_id) REFERENCES workers(id),
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                )
                """
            )
        )
        print("Table skipped_orders ready")

        ############################################################
        # Таблица транзакций (баланс и выплаты)
        con.execute(
            ded(
                """
                CREATE TABLE IF NOT EXISTS transactions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'unpaid',
                    created_at INTEGER,
                    FOREIGN KEY(worker_id) REFERENCES workers(id),
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                )
                """
            )
        )
        print("Table transactions ready")
