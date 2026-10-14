import aiosqlite

DB_NAME = "photo_center.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Пользователи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                username TEXT,
                full_name TEXT,
                saved_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                role TEXT DEFAULT 'client'
            )
        """)

        # Цены с акциями и дедлайнами
        await db.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                service_code TEXT PRIMARY KEY,
                name TEXT,
                price REAL,
                bulk_price REAL DEFAULT 0,
                bulk_threshold INTEGER DEFAULT 100,
                promo_price REAL DEFAULT NULL,
                promo_until TEXT DEFAULT ''
            )
        """)

        # Заказы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT DEFAULT '001',
                client_id INTEGER,
                client_name TEXT,
                client_phone TEXT,
                comment TEXT DEFAULT '',
                status TEXT DEFAULT 'new',
                staff_id INTEGER DEFAULT NULL,
                staff_name TEXT DEFAULT NULL,
                reject_reason TEXT DEFAULT NULL,
                total_amount REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Позиции заказа
        await db.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                item_type TEXT,
                details TEXT,
                quantity INTEGER,
                file_ids TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (id)
            )
        """)

        # Бронирование
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                client_id INTEGER,
                booking_date TEXT,
                booking_time TEXT,
                service_name TEXT,
                status TEXT DEFAULT 'booked',
                FOREIGN KEY (order_id) REFERENCES orders (id)
            )
        """)

        # Синхронизация сообщений
        await db.execute("""
            CREATE TABLE IF NOT EXISTS order_messages (
                order_id INTEGER,
                chat_id INTEGER,
                message_id INTEGER
            )
        """)

        # Блокировка слотов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blocked_slots (
                date_str TEXT,
                time_slot TEXT,
                PRIMARY KEY (date_str, time_slot)
            )
        """)

        # Таблица текстов и кнопок (CMS)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()

        # Автомиграция колонок для акций
        for col, col_def in [
            ("promo_price", "REAL DEFAULT NULL"),
            ("promo_until", "TEXT DEFAULT ''")
        ]:
            try:
                await db.execute(f"ALTER TABLE prices ADD COLUMN {col} {col_def}")
                await db.commit()
            except Exception:
                pass

        # Дефолтные тексты и надписи на кнопках бота
        default_cms = [
            ('btn_photo', '📸 Печать фотографий'),
            ('btn_docs', '📄 Печать документов'),
            ('btn_booking', '📅 Запись на фото на документы'),
            ('btn_cart', '🛒 Мой заказ / Корзина'),
            ('btn_my_orders', '📋 Мои записи и заказы'),
            ('msg_welcome', 'Добро пожаловать в цифровой фотоцентр! Выберите нужную услугу:'),
            ('msg_broadcast_title', '📢 Объявление фотоцентра:'),
            ('salon_status', 'open'),
            ('salon_address', 'г. Москва, ул. Центральная, д. 5'),
            ('salon_phone', '+7 (999) 000-00-00'),
            ('booking_notice_min', '30')
        ]
        for k, v in default_cms:
            await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        # Базовые цены
        default_prices = [
            ('photo_10x15', 'Фото 10х15', 25.0, 18.0, 100),
            ('photo_15x20', 'Фото 15х20', 50.0, 40.0, 100),
            ('photo_20x30', 'Фото 20х30', 100.0, 80.0, 100),
            ('doc_a4_bw', 'Документ А4 (Ч/Б)', 10.0, 10.0, 0),
            ('doc_a4_color', 'Документ А4 (Цвет)', 35.0, 35.0, 0),
            ('doc_a3_bw', 'Документ А3 (Ч/Б)', 25.0, 25.0, 0),
            ('doc_a3_color', 'Документ А3 (Цвет)', 70.0, 70.0, 0),
            ('doc_photo_passport_rf', 'Фото на Паспорт РФ (3.5х4.5)', 400.0, 400.0, 0),
            ('doc_photo_zagran', 'Фото на Загранпаспорт (3.5х4.5)', 400.0, 400.0, 0),
            ('doc_photo_med', 'Фото на Медкнижку (3х4 без уголка)', 350.0, 350.0, 0),
            ('doc_photo_driver_left', 'Водительское (3х4, левый угол)', 350.0, 350.0, 0),
            ('doc_photo_driver_right', 'Водительское (3х4, правый угол)', 350.0, 350.0, 0),
            ('doc_photo_standart_3x4', 'Стандартное фото 3х4 (4 шт)', 350.0, 350.0, 0)
        ]
        for p in default_prices:
            await db.execute("INSERT OR IGNORE INTO prices (service_code, name, price, bulk_price, bulk_threshold) VALUES (?, ?, ?, ?, ?)", p)
        await db.commit()