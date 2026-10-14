import aiosqlite
import json
from datetime import datetime
import pytz
from config import TIMEZONE
from database.db import DB_NAME

# --- CMS: Настройки, тексты и История кнопок (Alias History) ---

async def get_text(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def set_text(key: str, value: str):
    """Сохраняет новый текст и автоматически архивирует старое название в историю."""
    old_value = await get_text(key)
    async with aiosqlite.connect(DB_NAME) as db:
        # Создаем таблицу истории названий кнопок, если ее еще нет
        await db.execute("""
            CREATE TABLE IF NOT EXISTS button_history (
                btn_key TEXT,
                old_text TEXT,
                PRIMARY KEY (btn_key, old_text)
            )
        """)
        # Если было старое название и оно изменилось — сохраняем в историю
        if old_value and old_value != value and key.startswith("btn_"):
            await db.execute("INSERT OR IGNORE INTO button_history (btn_key, old_text) VALUES (?, ?)", (key, old_value))
            
        await db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        await db.commit()

async def get_button_aliases(key: str, default: str = "") -> list[str]:
    """Возвращает текущее название кнопки + ВСЕ ее исторические названия."""
    aliases = set()
    current = await get_text(key, default)
    if current:
        aliases.add(current)
    if default:
        aliases.add(default)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS button_history (
                btn_key TEXT,
                old_text TEXT,
                PRIMARY KEY (btn_key, old_text)
            )
        """)
        async with db.execute("SELECT old_text FROM button_history WHERE btn_key = ?", (key,)) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                if r[0]:
                    aliases.add(r[0])
    return list(aliases)

# --- Пользователи и Профиль ---

async def add_or_update_user(tg_id: int, username: str, full_name: str, default_role: str = 'client'):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (tg_id, username, full_name, role) VALUES (?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name
        """, (tg_id, username or "", full_name or "", default_role))
        await db.commit()

async def get_user_profile(tg_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT saved_name, phone FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def save_user_profile(tg_id: int, saved_name: str, phone: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET saved_name = ?, phone = ? WHERE tg_id = ?", (saved_name, phone, tg_id))
        await db.commit()

async def get_user_role(tg_id: int) -> str:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT role FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 'client'

async def set_user_role_by_username(username: str, role: str) -> bool:
    clean = username.lstrip('@')
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("UPDATE users SET role = ? WHERE LOWER(username) = LOWER(?)", (role, clean))
        await db.commit()
        return cursor.rowcount > 0

async def get_staff_and_owner_ids() -> list[int]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tg_id FROM users WHERE role IN ('owner', 'staff')") as cursor:
            return [r[0] for r in await cursor.fetchall()]

async def get_all_users_by_target(target: str) -> list[int]:
    async with aiosqlite.connect(DB_NAME) as db:
        q = "SELECT tg_id FROM users WHERE role = 'client'" if target == 'clients' else (
            "SELECT tg_id FROM users WHERE role IN ('owner', 'staff')" if target == 'staff' else "SELECT tg_id FROM users"
        )
        async with db.execute(q) as cursor:
            return [r[0] for r in await cursor.fetchall()]

# --- Цены и Акции ---

async def get_all_prices():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM prices") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def get_price(service_code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM prices WHERE service_code = ?", (service_code,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

def is_promo_active(item: dict) -> bool:
    if not item.get('promo_price') or not item.get('promo_until'):
        return False
    now_str = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
    return now_str <= item['promo_until']

async def set_product_promo(service_code: str, promo_price: float, until_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE prices SET promo_price = ?, promo_until = ? WHERE service_code = ?", (promo_price, until_date, service_code))
        await db.commit()

async def remove_product_promo(service_code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE prices SET promo_price = NULL, promo_until = '' WHERE service_code = ?", (service_code,))
        await db.commit()

async def update_standard_price(service_code: str, new_price: float, bulk_price: float = None, bulk_thresh: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        if bulk_price is not None and bulk_thresh is not None:
            await db.execute("UPDATE prices SET price = ?, bulk_price = ?, bulk_threshold = ? WHERE service_code = ?", (new_price, bulk_price, bulk_thresh, service_code))
        else:
            await db.execute("UPDATE prices SET price = ? WHERE service_code = ?", (new_price, service_code))
        await db.commit()

# --- Бронирование слотов ---

async def get_booked_slots(date_str: str) -> list[str]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT booking_time FROM bookings WHERE booking_date = ? AND status = 'booked'", (date_str,)) as cursor:
            booked = [r[0] for r in await cursor.fetchall()]
        async with db.execute("SELECT time_slot FROM blocked_slots WHERE date_str = ?", (date_str,)) as cursor:
            blocked = [r[0] for r in await cursor.fetchall()]
        return list(set(booked + blocked))

async def create_booking(order_id: int, client_id: int, date_str: str, time_str: str, service: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO bookings (order_id, client_id, booking_date, booking_time, service_name, status) VALUES (?, ?, ?, ?, ?, 'booked')", (order_id, client_id, date_str, time_str, service))
        await db.commit()

async def cancel_booking(booking_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        await db.commit()

async def get_client_active_bookings(client_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bookings WHERE client_id = ? AND status = 'booked' ORDER BY booking_date ASC, booking_time ASC", (client_id,)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def toggle_block_slot(date_str: str, time_slot: str) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM blocked_slots WHERE date_str = ? AND time_slot = ?", (date_str, time_slot)) as cursor:
            exists = await cursor.fetchone()
        if exists:
            await db.execute("DELETE FROM blocked_slots WHERE date_str = ? AND time_slot = ?", (date_str, time_slot))
            await db.commit()
            return False
        else:
            await db.execute("INSERT INTO blocked_slots VALUES (?, ?)", (date_str, time_slot))
            await db.commit()
            return True

# --- Заказы ---

async def create_order(client_id: int, client_name: str, client_phone: str, total_amount: float, comment: str = '') -> tuple[int, str]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT MAX(id) FROM orders") as cursor:
            row = await cursor.fetchone()
            code_num = ((row[0] or 0) % 999) + 1
            order_code = f"{code_num:03d}"
        cursor = await db.execute("INSERT INTO orders (order_code, client_id, client_name, client_phone, total_amount, comment) VALUES (?, ?, ?, ?, ?, ?)", (order_code, client_id, client_name, client_phone, total_amount, comment or ''))
        await db.commit()
        return cursor.lastrowid, order_code

async def add_order_item(order_id: int, item_type: str, details: str, quantity: int, files_data: list):
    json_str = json.dumps(files_data, ensure_ascii=False)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO order_items (order_id, item_type, details, quantity, file_ids) VALUES (?, ?, ?, ?, ?)", (order_id, item_type, details, quantity, json_str))
        await db.commit()

async def get_order_by_id(order_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_client_all_orders_with_items(client_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE client_id = ? ORDER BY id DESC LIMIT 10", (client_id,)) as cursor:
            orders = [dict(r) for r in await cursor.fetchall()]
        res = []
        for o in orders:
            async with db.execute("SELECT details, quantity FROM order_items WHERE order_id = ?", (o['id'],)) as it_cur:
                items = [dict(r) for r in await it_cur.fetchall()]
            res.append({"order": o, "items": items})
        return res

async def get_today_orders_and_bookings(date_str: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE DATE(created_at) = DATE(?) ORDER BY id DESC", (date_str,)) as cursor:
            orders = [dict(r) for r in await cursor.fetchall()]
        async with db.execute("SELECT * FROM bookings WHERE booking_date = ? ORDER BY booking_time ASC", (date_str,)) as cursor:
            bookings = [dict(r) for r in await cursor.fetchall()]
        return orders, bookings

async def find_order_by_code_or_id(query_str: str):
    clean = query_str.strip().lstrip('#')
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE order_code = ? OR id = ?", (clean, clean)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_active_orders():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE status IN ('new', 'in_progress') ORDER BY id DESC LIMIT 20") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def update_order_status(order_id: int, status: str, staff_id: int = None, staff_name: str = None, reason: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        if status == 'in_progress':
            await db.execute("UPDATE orders SET status = ?, staff_id = ?, staff_name = ? WHERE id = ?", (status, staff_id, staff_name, order_id))
        elif status == 'rejected':
            await db.execute("UPDATE orders SET status = ?, reject_reason = ? WHERE id = ?", (status, reason, order_id))
        else:
            await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()

async def save_order_message(order_id: int, chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO order_messages VALUES (?, ?, ?)", (order_id, chat_id, message_id))
        await db.commit()

async def get_order_messages(order_id: int) -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT chat_id, message_id FROM order_messages WHERE order_id = ?", (order_id,)) as cursor:
            return await cursor.fetchall()

async def get_shift_statistics(date_str: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT COUNT(*) as total_orders,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_orders,
                   SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_orders,
                   SUM(CASE WHEN status = 'completed' THEN total_amount ELSE 0 END) as total_revenue
            FROM orders WHERE DATE(created_at) = DATE(?)
        """, (date_str,)) as cursor:
            summary = dict(await cursor.fetchone())
        async with db.execute("""
            SELECT COALESCE(staff_name, 'Не назначен') as staff_name, COUNT(*) as count, SUM(total_amount) as revenue
            FROM orders WHERE DATE(created_at) = DATE(?) AND status = 'completed' GROUP BY staff_name
        """, (date_str,)) as cursor:
            by_staff = [dict(r) for r in await cursor.fetchall()]
        return summary, by_staff
