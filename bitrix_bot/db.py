import logging

import psycopg2
from psycopg2 import Error
from psycopg2.extras import RealDictCursor
from .config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT
    )


def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id SERIAL PRIMARY KEY,
          telegram_id BIGINT NOT NULL,
          username VARCHAR(255),
          bitrix_url VARCHAR(255),
          bitrix_id BIGINT,
          is_enabled BOOLEAN DEFAULT FALSE,
          chat_id BIGINT,
          main_chat_id BIGINT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sprints (
          id SERIAL PRIMARY KEY,
          chat_id BIGINT NOT NULL,
          deadline TIMESTAMP NULL,
          is_active BOOLEAN DEFAULT FALSE,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS sprint_tasks
                       (
                           id             SERIAL PRIMARY KEY,
                           sprint_id      INT    NOT NULL,
                           bitrix_task_id BIGINT NOT NULL,
                           created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           FOREIGN KEY (sprint_id) REFERENCES sprints (id)
                               ON DELETE CASCADE
                               ON UPDATE CASCADE
                       );
                       """)

        conn.commit()
        cursor.close()
        conn.close()
        logging.debug("Инициализация базы данных завершена.")
    except Error as e:
        logging.error("Ошибка при инициализации БД: %s", e)


def get_url(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT bitrix_url FROM users "
                   "WHERE telegram_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0]


def add_user(user_id: int, username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s, %s)",
        (user_id, username)
    )
    conn.commit()
    cursor.close()
    conn.close()


def set_url(user_id: int, bitrix_url: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET bitrix_url=%s WHERE telegram_id=%s",
        (bitrix_url, user_id)
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, is_enabled, bitrix_url, bitrix_id, chat_id 
        FROM users 
        WHERE telegram_id=%s
    """, (user_id,))
    user_row = cursor.fetchone()
    cursor.close()
    conn.close()
    return user_row


def get_user_by_username(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
                SELECT id, telegram_id, is_enabled, bitrix_url, bitrix_id
                FROM users
                WHERE username=%s
            """, (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_admin_info(admin_user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, username FROM users WHERE id=%s",
                   (admin_user_id,))
    admin_info = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin_info


def enable_user(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_enabled=TRUE WHERE username=%s",
        (username,)
    )
    conn.commit()
    cursor.close()
    conn.close()


def disable_user(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_enabled=FALSE WHERE username=%s",
        (username,)
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_username(user_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id=%s", (user_id,))
    admin_info = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin_info


def set_user_bitrix_id(user_id: int, new_bitrix_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
        SET bitrix_id = %s
        WHERE telegram_id = %s
    """, (new_bitrix_id, user_id))
    rowcount = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return rowcount > 0


def get_bitrix_id_for_user(username: str) -> int or None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT bitrix_id
        FROM users
        WHERE username=%s
        LIMIT 1
    """, (username,))

    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row and row[0]:
        return row[0]
    return None


def set_user_chat_id(telegram_id: int, chat_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
        SET chat_id = %s
        WHERE telegram_id = %s
    """, (chat_id, telegram_id))
    conn.commit()
    cursor.close()
    conn.close()


def get_users_for_daily_report() -> list[tuple]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT telegram_id, username, bitrix_url, main_chat_id
        FROM users
        WHERE main_chat_id IS NOT NULL 
          AND bitrix_url IS NOT NULL 
          AND bitrix_url <> ''
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def set_main_chat_id(telegram_id: int, main_chat_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET main_chat_id = %s 
        WHERE telegram_id = %s
    """, (main_chat_id, telegram_id))
    conn.commit()
    cursor.close()
    conn.close()


def get_users_for_weekly_report() -> list[tuple]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT telegram_id, username, bitrix_url
        FROM users
        WHERE bitrix_url IS NOT NULL AND bitrix_url <> ''
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def get_sprint_for_chat(chat_id: int):
    """
    Возвращает запись из sprints для данного чата,
    если нужно — можно проверять is_active или нет
    """
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT * 
        FROM sprints
        WHERE chat_id = %s
        ORDER BY id DESC 
        LIMIT 1
    """, (chat_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def create_sprint(chat_id: int):
    """
    Создаёт новый спринт в состоянии "is_active=0" (подготовка),
    deadline=NULL. Возвращает ID созданного спринта.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sprints (chat_id, deadline, is_active)
        VALUES (%s, NULL, 0)
        RETURNING id
        """,
        (chat_id,)
    )
    new_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return new_id
