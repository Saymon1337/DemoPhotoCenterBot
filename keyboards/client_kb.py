from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# Динамическое главное меню: текст кнопок читается из БД
def get_main_menu_kb(texts: dict) -> ReplyKeyboardMarkup:
    b_photo = texts.get('btn_photo', '📸 Печать фотографий')
    b_docs = texts.get('btn_docs', '📄 Печать документов')
    b_book = texts.get('btn_booking', '📅 Запись на фото на документы')
    b_cart = texts.get('btn_cart', '🛒 Мой заказ / Корзина')
    b_orders = texts.get('btn_my_orders', '📋 Мои записи и заказы')
    
    kb = [
        [KeyboardButton(text=b_photo), KeyboardButton(text=b_docs)],
        [KeyboardButton(text=b_book)],
        [KeyboardButton(text=b_cart), KeyboardButton(text=b_orders)]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)

def get_photo_sizes_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10х15", callback_data="photo_size:photo_10x15")],
        [InlineKeyboardButton(text="15х20", callback_data="photo_size:photo_15x20")],
        [InlineKeyboardButton(text="20х30", callback_data="photo_size:photo_20x30")],
        [InlineKeyboardButton(text="⬅ Назад в меню", callback_data="back_to_menu")]
    ])

def get_doc_format_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="А4 (Ч/Б)", callback_data="doc_fmt:doc_a4_bw"), InlineKeyboardButton(text="А4 (Цвет)", callback_data="doc_fmt:doc_a4_color")],
        [InlineKeyboardButton(text="А3 (Ч/Б)", callback_data="doc_fmt:doc_a3_bw"), InlineKeyboardButton(text="А3 (Цвет)", callback_data="doc_fmt:doc_a3_color")],
        [InlineKeyboardButton(text="⬅ Назад в меню", callback_data="back_to_menu")]
    ])

def get_doc_photo_types_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Паспорт РФ (3.5х4.5)", callback_data="doctype:doc_photo_passport_rf")],
        [InlineKeyboardButton(text="✈️ Загранпаспорт (3.5х4.5)", callback_data="doctype:doc_photo_zagran")],
        [InlineKeyboardButton(text="🏥 Медкнижка / Студенческий (3х4)", callback_data="doctype:doc_photo_med")],
        [InlineKeyboardButton(text="🚗 Водительское (левый угол)", callback_data="doctype:doc_photo_driver_left")],
        [InlineKeyboardButton(text="🚗 Водительское (правый угол)", callback_data="doctype:doc_photo_driver_right")],
        [InlineKeyboardButton(text="📸 Стандартные 3х4 (4 шт)", callback_data="doctype:doc_photo_standart_3x4")],
        [InlineKeyboardButton(text="⬅ Назад в меню", callback_data="back_to_menu")]
    ])

def get_interactive_cart_kb(cart: list) -> InlineKeyboardMarkup:
    if not cart:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В главное меню", callback_data="back_to_menu")]])
    kb = []
    for idx, item in enumerate(cart):
        if item['type'] in ('photo', 'doc'):
            kb.append([InlineKeyboardButton(text=f"🔍 Настроить копии #{idx+1} ({len(item['files'])} шт)", callback_data=f"inspect_files:{idx}:0")])
            kb.append([
                InlineKeyboardButton(text="➖ 1", callback_data=f"cart_qty:{idx}:minus"),
                InlineKeyboardButton(text=f"Всего: {item['quantity']} шт", callback_data="noop"),
                InlineKeyboardButton(text="➕ 1", callback_data=f"cart_qty:{idx}:plus"),
                InlineKeyboardButton(text="❌ Удалить", callback_data=f"cart_del:{idx}")
            ])
        else:
            kb.append([
                InlineKeyboardButton(text=f"📅 #{idx+1} Запись на съемку", callback_data="noop"),
                InlineKeyboardButton(text="❌ Удалить", callback_data=f"cart_del:{idx}")
            ])
    kb.append([InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout_order")])
    kb.append([InlineKeyboardButton(text="🗑 Очистить всё", callback_data="clear_cart"), InlineKeyboardButton(text="⬅ В меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_file_inspector_kb(item_idx: int, file_idx: int, total_files: int, copies: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖ 1", callback_data=f"fcopy:{item_idx}:{file_idx}:minus"),
            InlineKeyboardButton(text=f"Тираж: {copies} шт", callback_data="noop"),
            InlineKeyboardButton(text="➕ 1", callback_data=f"fcopy:{item_idx}:{file_idx}:plus")
        ],
        [InlineKeyboardButton(text="💬 Комментарий к файлу", callback_data=f"fcomm:{item_idx}:{file_idx}")],
        [
            InlineKeyboardButton(text="⬅ Пред.", callback_data=f"inspect_files:{item_idx}:{max(0, file_idx - 1)}"),
            InlineKeyboardButton(text=f"{file_idx + 1}/{total_files}", callback_data="noop"),
            InlineKeyboardButton(text="След. ➡", callback_data=f"inspect_files:{item_idx}:{min(total_files - 1, file_idx + 1)}")
        ],
        [InlineKeyboardButton(text="🗑 Удалить этот файл", callback_data=f"fdel:{item_idx}:{file_idx}"), InlineKeyboardButton(text="✅ В корзину", callback_data="back_to_cart_view")]
    ])

def get_skip_comment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏩ Пропустить комментарий", callback_data="skip_comment")]])