from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def get_admin_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🛠 Панель управления")]], resize_keyboard=True)

def get_order_staff_kb(order_id: int, status: str = 'new') -> InlineKeyboardMarkup:
    kb = []
    if status == 'new':
        kb.append([InlineKeyboardButton(text="🙋‍♂️ Принять в работу", callback_data=f"ord_take:{order_id}"), InlineKeyboardButton(text="✅ Готов к выдаче", callback_data=f"ord_ready:{order_id}")])
        kb.append([InlineKeyboardButton(text="📂 Получить файлы", callback_data=f"ord_files:{order_id}"), InlineKeyboardButton(text="✉️ Написать клиенту", callback_data=f"ord_msg:{order_id}")])
        kb.append([InlineKeyboardButton(text="❌ Отклонить заказ", callback_data=f"ord_reject:{order_id}")])
    elif status == 'in_progress':
        kb.append([InlineKeyboardButton(text="✅ Готов к выдаче", callback_data=f"ord_ready:{order_id}")])
        kb.append([InlineKeyboardButton(text="📂 Получить файлы", callback_data=f"ord_files:{order_id}"), InlineKeyboardButton(text="✉️ Написать клиенту", callback_data=f"ord_msg:{order_id}")])
        kb.append([InlineKeyboardButton(text="❌ Отклонить заказ", callback_data=f"ord_reject:{order_id}")])
    elif status in ('completed', 'rejected'):
        kb.append([InlineKeyboardButton(text="📂 Получить файлы", callback_data=f"ord_files:{order_id}"), InlineKeyboardButton(text="✉️ Написать клиенту", callback_data=f"ord_msg:{order_id}")])
    kb.append([InlineKeyboardButton(text="⬅ Свернуть в админку", callback_data="adm_back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_main_kb(is_owner: bool = False) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📅 Журнал смены (сегодня)", callback_data="adm_today_journal")],
        [InlineKeyboardButton(text="📋 Активные заказы", callback_data="adm_active_orders"), InlineKeyboardButton(text="🔍 Найти заказ по ID", callback_data="adm_search_order")]
    ]
    if is_owner:
        kb.append([InlineKeyboardButton(text="✏️ Редактор текстов и кнопок", callback_data="adm_cms_menu")])
        kb.append([InlineKeyboardButton(text="💰 Цены и Акции с дедлайном", callback_data="adm_prices"), InlineKeyboardButton(text="⚙️ Статус и салон", callback_data="adm_salon_settings")])
        kb.append([InlineKeyboardButton(text="👥 Управление персоналом", callback_data="adm_staff"), InlineKeyboardButton(text="⛔ Блокировка слотов", callback_data="adm_block_slots")])
        kb.append([InlineKeyboardButton(text="📢 Рассылка объявлений", callback_data="adm_broadcast"), InlineKeyboardButton(text="📊 Итоги смены (отчет)", callback_data="adm_report_now")])
    else:
        kb.append([InlineKeyboardButton(text="⛔ Блокировка слотов", callback_data="adm_block_slots"), InlineKeyboardButton(text="📊 Итоги смены", callback_data="adm_report_now")])

    kb.append([InlineKeyboardButton(text="❌ Закрыть панель", callback_data="adm_close")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_cms_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔘 Кнопка 'Печать фото'", callback_data="cms_edit:btn_photo")],
        [InlineKeyboardButton(text="🔘 Кнопка 'Печать документов'", callback_data="cms_edit:btn_docs")],
        [InlineKeyboardButton(text="🔘 Кнопка 'Запись на фото'", callback_data="cms_edit:btn_booking")],
        [InlineKeyboardButton(text="🔘 Кнопка 'Корзина'", callback_data="cms_edit:btn_cart")],
        [InlineKeyboardButton(text="💬 Текст приветствия (/start)", callback_data="cms_edit:msg_welcome")],
        [InlineKeyboardButton(text="📢 Заголовок рассылки", callback_data="cms_edit:msg_broadcast_title")],
        [InlineKeyboardButton(text="⬅ Назад в админку", callback_data="adm_back_main")]
    ])

def get_product_manage_kb(service_code: str, has_promo: bool) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="💵 Изменить базовые цены", callback_data=f"pr_std:{service_code}")],
        [InlineKeyboardButton(text="🔥 Запустить акцию с датой", callback_data=f"pr_prm:{service_code}")]
    ]
    if has_promo:
        kb.append([InlineKeyboardButton(text="❌ Снять текущую акцию", callback_data=f"pr_rmp:{service_code}")])
    kb.append([InlineKeyboardButton(text="⬅ К списку услуг", callback_data="adm_prices")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_salon_settings_kb(is_open: bool) -> InlineKeyboardMarkup:
    b_txt = "🔴 Закрыть салон" if is_open else "🟢 Открыть салон"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b_txt, callback_data="adm_toggle_salon")],
        [InlineKeyboardButton(text="📍 Изменить адрес", callback_data="adm_set_address")],
        [InlineKeyboardButton(text="📞 Изменить телефон", callback_data="adm_set_phone")],
        [InlineKeyboardButton(text="⏱ Порог времени записи", callback_data="adm_set_notice")],
        [InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]
    ])

def get_broadcast_target_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Клиентам", callback_data="bcast_to:clients"), InlineKeyboardButton(text="👥 Сотрудникам", callback_data="bcast_to:staff")],
        [InlineKeyboardButton(text="📢 Всем", callback_data="bcast_to:all")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel")]
    ])

def get_admin_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel")]])