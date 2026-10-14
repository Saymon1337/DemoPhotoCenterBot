import html
import asyncio
import logging
from datetime import datetime
from collections import defaultdict
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import OWNER_ID
from database.queries import (
    add_or_update_user, get_all_prices, get_price, 
    create_order, add_order_item, create_booking, 
    get_staff_and_owner_ids, save_order_message,
    get_user_profile, save_user_profile, get_user_role,
    get_text, is_promo_active, get_button_aliases
)
from keyboards.client_kb import (
    get_main_menu_kb, get_photo_sizes_kb, get_doc_format_kb,
    get_interactive_cart_kb, get_file_inspector_kb, get_phone_kb, get_skip_comment_kb
)
from keyboards.admin_kb import get_order_staff_kb, get_admin_main_kb, get_admin_reply_kb

router = Router()
logger = logging.getLogger(__name__)

user_locks = defaultdict(asyncio.Lock)
debounce_tasks = {}

class OrderFSM(StatesGroup):
    uploading_files = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_comment = State()
    waiting_for_file_comment = State()

async def get_current_cms_texts() -> dict:
    keys = ['btn_photo', 'btn_docs', 'btn_booking', 'btn_cart', 'btn_my_orders', 'msg_welcome', 'msg_broadcast_title']
    return {k: await get_text(k) for k in keys}

# Старт
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    try:
        await state.clear()
        uid = message.from_user.id
        await add_or_update_user(uid, message.from_user.username, message.from_user.full_name)
        role = await get_user_role(uid)
        is_owner = (uid == OWNER_ID or role == 'owner')

        if is_owner or role == 'staff':
            safe_name = html.escape(message.from_user.first_name or "Коллега")
            role_label = "Владелец" if is_owner else "Сотрудник"
            await message.answer(f"👑 <b>Рабочий кабинет: {role_label}</b>\n\nЗдравствуйте, <b>{safe_name}</b>!", reply_markup=get_admin_reply_kb(), parse_mode="HTML")
            try:
                kb = get_admin_main_kb(is_owner=is_owner)
            except TypeError:
                kb = get_admin_main_kb()
            await message.answer("🛠 <b>Панель управления фотоцентра</b>\nВыберите действие:", reply_markup=kb, parse_mode="HTML")
            return

        cms = await get_current_cms_texts()
        safe_name = html.escape(message.from_user.first_name or "Гость")
        welcome_text = cms.get('msg_welcome') or 'Добро пожаловать в цифровой фотоцентр! Выберите нужную услугу:'
        await message.answer(f"👋 Здравствуйте, <b>{safe_name}</b>!\n\n{html.escape(welcome_text)}", reply_markup=get_main_menu_kb(cms), parse_mode="HTML")
    except Exception as e:
        logger.exception(f"Ошибка в cmd_start: {e}")
        await message.answer(f"❌ Ошибка запуска: {e}")

# САМОИСЦЕЛЯЮЩИЙСЯ РОУТЕР КНОПОК МЕНЮ
@router.message(StateFilter(None), F.text)
async def dynamic_client_menu_router(message: Message, state: FSMContext):
    txt = message.text.strip()
    txt_lower = txt.lower()

    # 0. Служебная кнопка админов
    if txt == "🛠 Панель управления" or "панель управления" in txt_lower:
        from handlers.admin import cmd_admin
        await cmd_admin(message)
        return

    cms = await get_current_cms_texts()

    # Получаем ВСЮ ИСТОРИЮ названий для каждой кнопки (текущие + прошлые изменения)
    photo_aliases = await get_button_aliases('btn_photo', default="📸 Печать фотографий")
    docs_aliases = await get_button_aliases('btn_docs', default="📄 Печать документов")
    booking_aliases = await get_button_aliases('btn_booking', default="📅 Запись на фото на документы")
    cart_aliases = await get_button_aliases('btn_cart', default="🛒 Мой заказ / Корзина")
    orders_aliases = await get_button_aliases('btn_my_orders', default="📋 Мои записи и заказы")

    # Функция автообновления кнопок на экране клиента, если нажата старая кнопка
    async def refresh_keyboard_if_outdated(current_btn_key: str):
        current_name = cms.get(current_btn_key)
        if current_name and txt != current_name:
            # На лету обновляем клавиатуру на телефоне клиента на актуальную из CMS!
            await message.answer("🔄 <i>Меню обновлено до актуального состояния.</i>", reply_markup=get_main_menu_kb(cms), parse_mode="HTML")

    # 1. Фотопечать (сработает при ЛЮБОМ старом или новом названии кнопки)
    if txt in photo_aliases or any(a.lower() == txt_lower for a in photo_aliases) or "фото" in txt_lower:
        await refresh_keyboard_if_outdated('btn_photo')
        await choose_photo_size(message)
        return

    # 2. Печать документов
    if txt in docs_aliases or any(a.lower() == txt_lower for a in docs_aliases) or "документ" in txt_lower:
        await refresh_keyboard_if_outdated('btn_docs')
        await choose_doc_format(message)
        return

    # 3. Запись на фото
    if txt in booking_aliases or any(a.lower() == txt_lower for a in booking_aliases) or "запись" in txt_lower:
        await refresh_keyboard_if_outdated('btn_booking')
        from handlers.booking import start_booking
        await start_booking(message)
        return

    # 4. Корзина
    if txt in cart_aliases or any(a.lower() == txt_lower for a in cart_aliases) or "корзин" in txt_lower or (txt_lower.startswith("заказ") and "мои" not in txt_lower):
        await refresh_keyboard_if_outdated('btn_cart')
        await view_cart_cmd(message, state)
        return

    # 5. Мои заказы
    if txt in orders_aliases or any(a.lower() == txt_lower for a in orders_aliases) or "мои записи" in txt_lower or "мои заказы" in txt_lower:
        await refresh_keyboard_if_outdated('btn_my_orders')
        from handlers.booking import view_client_bookings_and_orders
        await view_client_bookings_and_orders(message)
        return

@router.callback_query(F.data == "back_to_menu")
async def back_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(None)
    cms = await get_current_cms_texts()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Главное меню:", reply_markup=get_main_menu_kb(cms))

# Печать фото
async def choose_photo_size(message: Message):
    try:
        prices = await get_all_prices()
        p = [x for x in prices if x.get('service_code', '').startswith('photo_') and 'doc' not in x.get('service_code', '')]

        lines = ["📸 <b>Печать фотографий на фотобумаге</b>\n\nТарифы:"]
        if p:
            for item in p:
                if is_promo_active(item):
                    try:
                        d_fmt = datetime.strptime(item['promo_until'], "%Y-%m-%d").strftime("%d.%m")
                    except Exception:
                        d_fmt = item['promo_until']
                    lines.append(f"• {html.escape(item['name'])}: 🔥 <b>АКЦИЯ до {d_fmt}: {item['promo_price']} ₽</b> <s>(вместо {item['price']} ₽)</s>")
                else:
                    lines.append(f"• {html.escape(item['name'])}: <b>{item['price']} ₽</b> (от {item['bulk_threshold']} шт: <b>{item['bulk_price']} ₽</b>)")
        else:
            lines.append("• Фото 10х15: <b>25.0 ₽</b> (от 100 шт: <b>18.0 ₽</b>)")
            lines.append("• Фото 15х20: <b>50.0 ₽</b> (от 100 шт: <b>40.0 ₽</b>)")
            lines.append("• Фото 20х30: <b>100.0 ₽</b> (от 100 шт: <b>80.0 ₽</b>)")

        lines.append("\nВыберите желаемый размер:")
        await message.answer("\n".join(lines), reply_markup=get_photo_sizes_kb(), parse_mode="HTML")
    except Exception as e:
        logger.exception(f"Error in choose_photo_size: {e}")
        await message.answer("📸 <b>Печать фотографий на фотобумаге</b>\n\nВыберите желаемый размер:", reply_markup=get_photo_sizes_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("photo_size:"))
async def start_photo_upload(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    code = callback.data.split(":")[1]
    p_info = await get_price(code)
    name = p_info['name'] if p_info else code

    msg = await callback.message.edit_text(
        f"📥 Выбран размер: <b>{html.escape(name)}</b>\n\nОтправьте фотографии (можно альбомом или файлами).\n\n📊 <b>Загружено файлов: 0 шт.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить загрузку (0 шт)", callback_data="finish_upload")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
        ]),
        parse_mode="HTML"
    )
    await state.update_data(current_service=code, current_files=[], status_msg_id=msg.message_id)
    await state.set_state(OrderFSM.uploading_files)

# Печать документов
async def choose_doc_format(message: Message):
    try:
        prices = await get_all_prices()
        p = [x for x in prices if x.get('service_code', '').startswith('doc_a')]
        lines = ["📄 <b>Печать документов (PDF, сканы, фото)</b>\n\nТарифы:"]
        if p:
            for item in p:
                if is_promo_active(item):
                    try:
                        d_fmt = datetime.strptime(item['promo_until'], "%Y-%m-%d").strftime("%d.%m")
                    except Exception:
                        d_fmt = item['promo_until']
                    lines.append(f"• {html.escape(item['name'])}: 🔥 <b>АКЦИЯ до {d_fmt}: {item['promo_price']} ₽</b> <s>(вместо {item['price']} ₽)</s>")
                else:
                    lines.append(f"• {html.escape(item['name'])}: <b>{item['price']} ₽</b>")
        else:
            lines.append("• Документ А4 (Ч/Б): <b>10.0 ₽</b>")
            lines.append("• Документ А4 (Цвет): <b>35.0 ₽</b>")
            lines.append("• Документ А3 (Ч/Б): <b>25.0 ₽</b>")
            lines.append("• Документ А3 (Цвет): <b>70.0 ₽</b>")

        lines.append("\nВыберите формат:")
        await message.answer("\n".join(lines), reply_markup=get_doc_format_kb(), parse_mode="HTML")
    except Exception as e:
        logger.exception(f"Error in choose_doc_format: {e}")
        await message.answer("📄 <b>Печать документов</b>\n\nВыберите формат:", reply_markup=get_doc_format_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("doc_fmt:"))
async def start_doc_upload(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    code = callback.data.split(":")[1]
    p_info = await get_price(code)
    name = p_info['name'] if p_info else code

    msg = await callback.message.edit_text(
        f"📥 Выбран формат: <b>{html.escape(name)}</b>\n\nОтправьте документы (PDF, DOCX или фото).\n\n📊 <b>Загружено файлов: 0 шт.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить загрузку (0 шт)", callback_data="finish_upload")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
        ]),
        parse_mode="HTML"
    )
    await state.update_data(current_service=code, current_files=[], status_msg_id=msg.message_id)
    await state.set_state(OrderFSM.uploading_files)

# Прием файлов
async def debounce_update_counter(bot, chat_id: int, status_msg_id: int, state: FSMContext, user_id: int):
    await asyncio.sleep(0.35)
    async with user_locks[user_id]:
        data = await state.get_data()
        count = len(data.get("current_files", []))
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=status_msg_id,
            text=f"📥 Файлы принимаются!\n\n📊 <b>Всего загружено: {count} шт.</b>\nНажмите кнопку завершения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ Завершить загрузку ({count} шт)", callback_data="finish_upload")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
            ]),
            parse_mode="HTML"
        )
    except Exception:
        pass
    debounce_tasks.pop(user_id, None)

@router.message(OrderFSM.uploading_files, F.photo | F.document)
async def receive_any_file(message: Message, state: FSMContext):
    is_photo = bool(message.photo)
    fid = message.photo[-1].file_id if is_photo else message.document.file_id
    uid = message.from_user.id
    async with user_locks[uid]:
        data = await state.get_data()
        files = data.get("current_files", [])
        files.append({"file_id": fid, "copies": 1, "comment": "", "is_photo": is_photo})
        await state.update_data(current_files=files)
        sm_id = data.get("status_msg_id")

    if sm_id:
        if uid in debounce_tasks:
            debounce_tasks[uid].cancel()
        debounce_tasks[uid] = asyncio.create_task(debounce_update_counter(message.bot, message.chat.id, sm_id, state, uid))

@router.callback_query(F.data == "finish_upload")
async def finish_upload(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    service_code = data.get("current_service")
    files = data.get("current_files", [])
    if not files:
        await callback.answer("⚠️ Вы не загрузили файлы!", show_alert=True)
        return

    p_info = await get_price(service_code)
    name = p_info['name'] if p_info else service_code
    cart = data.get("cart", [])
    itype = "photo" if "photo_" in service_code and "doc_photo" not in service_code else "doc"
    cart.append({"type": itype, "service_code": service_code, "details": name, "quantity": len(files), "files": files})
    await state.update_data(cart=cart, current_files=[], current_service=None)
    await state.set_state(None)

    await callback.message.edit_text(
        f"✅ Добавлено в корзину: <b>{html.escape(name)}</b> ({len(files)} файлов)\n\nВ корзине можно настроить тираж и комментарии!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Открыть корзину", callback_data="back_to_cart_view")],
            [InlineKeyboardButton(text="⬅ В главное меню", callback_data="back_to_menu")]
        ]),
        parse_mode="HTML"
    )

# Калькулятор корзины
async def calculate_cart_total(cart: list) -> float:
    total = 0.0
    for it in cart:
        p_info = await get_price(it.get('service_code', ''))
        if not p_info:
            continue
        qty = sum(f.get('copies', 1) for f in it['files']) if ('files' in it and it['files']) else it.get('quantity', 1)
        if is_promo_active(p_info):
            total += qty * p_info['promo_price']
        else:
            total += qty * (p_info['bulk_price'] if p_info['bulk_threshold'] > 0 and qty >= p_info['bulk_threshold'] else p_info['price'])
    return total

def build_cart_text(cart: list, total_sum: float) -> str:
    lines = ["🛒 <b>ВАША КОРЗИНА:</b>\n"]
    for idx, item in enumerate(cart, 1):
        if 'files' in item and item['files']:
            c_sum = sum(f.get('copies', 1) for f in item['files'])
            lines.append(f"<b>Позиция #{idx}. {html.escape(item['details'])}</b> (всего {c_sum} шт.):")
            for f_i, f in enumerate(item['files'], 1):
                c_text = f" | коммент: <i>{html.escape(f['comment'])}</i>" if f.get('comment') else ""
                lines.append(f"   ▫️ Файл {f_i}: <b>{f.get('copies', 1)} шт.</b>{c_text}")
        else:
            lines.append(f"<b>Позиция #{idx}. {html.escape(item['details'])}</b> — <b>{item.get('quantity', 1)} шт.</b>")
    lines.append(f"\n💰 <b>Итого к оплате:</b> {total_sum:.1f} ₽")
    return "\n".join(lines)

async def view_cart_cmd(message: Message, state: FSMContext):
    data = await state.get_data()
    cart = data.get("cart", [])
    if not cart:
        await message.answer("🛒 Ваша корзина пуста.", reply_markup=get_interactive_cart_kb(cart))
        return
    tot = await calculate_cart_total(cart)
    await message.answer(build_cart_text(cart, tot), reply_markup=get_interactive_cart_kb(cart), parse_mode="HTML")

@router.callback_query(F.data == "back_to_cart_view")
async def view_cart_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    cart = data.get("cart", [])
    if not cart:
        await callback.message.edit_text("🛒 Ваша корзина пуста.", reply_markup=get_interactive_cart_kb([]))
        return
    tot = await calculate_cart_total(cart)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(build_cart_text(cart, tot), reply_markup=get_interactive_cart_kb(cart), parse_mode="HTML")

@router.callback_query(F.data.startswith("cart_qty:"))
async def change_cart_group_qty(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, idx_str, action = callback.data.split(":")
    idx = int(idx_str)
    data = await state.get_data()
    cart = data.get("cart", [])
    if idx < len(cart):
        item = cart[idx]
        if action == "plus":
            if 'files' in item and item['files']:
                for f in item['files']:
                    f['copies'] = f.get('copies', 1) + 1
                item['quantity'] = sum(f['copies'] for f in item['files'])
            else:
                item['quantity'] = item.get('quantity', 1) + 1
        elif action == "minus":
            if 'files' in item and item['files']:
                for f in item['files']:
                    if f.get('copies', 1) > 1:
                        f['copies'] -= 1
                item['quantity'] = sum(f['copies'] for f in item['files'])
            else:
                if item.get('quantity', 1) > 1:
                    item['quantity'] -= 1
        await state.update_data(cart=cart)
        tot = await calculate_cart_total(cart)
        await callback.message.edit_text(build_cart_text(cart, tot), reply_markup=get_interactive_cart_kb(cart), parse_mode="HTML")

@router.callback_query(F.data.startswith("inspect_files:"))
async def inspect_files_flow(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, i_idx, f_idx = callback.data.split(":")
    i_idx, f_idx = int(i_idx), int(f_idx)
    data = await state.get_data()
    cart = data.get("cart", [])
    if i_idx >= len(cart) or not cart[i_idx].get("files"):
        await callback.answer("Файлы не найдены", show_alert=True)
        return
    files = cart[i_idx]["files"]
    f_idx = max(0, min(f_idx, len(files) - 1))
    target = files[f_idx]
    c_safe = html.escape(target.get('comment') or 'нет')
    cap = f"🖼 <b>Файл №{f_idx + 1} из {len(files)}</b>\nУслуга: <b>{html.escape(cart[i_idx]['details'])}</b>\nКопий: <b>{target.get('copies', 1)} шт.</b>\nКомментарий: <i>{c_safe}</i>"
    kb = get_file_inspector_kb(i_idx, f_idx, len(files), target.get('copies', 1))
    try:
        await callback.message.delete()
    except Exception:
        pass
    if target.get('is_photo'):
        await callback.bot.send_photo(callback.from_user.id, photo=target['file_id'], caption=cap, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.bot.send_document(callback.from_user.id, document=target['file_id'], caption=cap, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("fcomm:"))
async def start_file_comment(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, i_idx, f_idx = callback.data.split(":")
    await state.update_data(target_item_idx=int(i_idx), target_file_idx=int(f_idx))
    await state.set_state(OrderFSM.waiting_for_file_comment)
    await callback.message.reply("💬 Введите комментарий для файла:", parse_mode="HTML")

@router.message(OrderFSM.waiting_for_file_comment)
async def save_file_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    i_idx, f_idx = data.get("target_item_idx"), data.get("target_file_idx")
    cart = data.get("cart", [])
    if i_idx is not None and f_idx is not None and i_idx < len(cart):
        cart[i_idx]['files'][f_idx]['comment'] = message.text.strip()
        await state.update_data(cart=cart)
    await state.set_state(None)
    await message.answer("✅ Сохранено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 К файлу", callback_data=f"inspect_files:{i_idx}:{f_idx}")],
        [InlineKeyboardButton(text="🛒 В корзину", callback_data="back_to_cart_view")]
    ]))

@router.callback_query(F.data.startswith("fcopy:"))
async def change_file_copy(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, i_idx, f_idx, act = callback.data.split(":")
    i_idx, f_idx = int(i_idx), int(f_idx)
    data = await state.get_data()
    cart = data.get("cart", [])
    if i_idx < len(cart) and f_idx < len(cart[i_idx]['files']):
        cur = cart[i_idx]['files'][f_idx].get('copies', 1)
        cur = cur + 1 if act == "plus" else max(1, cur - 1)
        cart[i_idx]['files'][f_idx]['copies'] = cur
        cart[i_idx]['quantity'] = sum(f.get('copies', 1) for f in cart[i_idx]['files'])
        await state.update_data(cart=cart)
        c_safe = html.escape(cart[i_idx]['files'][f_idx].get('comment') or 'нет')
        cap = f"🖼 <b>Файл №{f_idx + 1} из {len(cart[i_idx]['files'])}</b>\nУслуга: <b>{html.escape(cart[i_idx]['details'])}</b>\nКопий: <b>{cur} шт.</b>\nКомментарий: <i>{c_safe}</i>"
        try:
            await callback.message.edit_caption(caption=cap, reply_markup=get_file_inspector_kb(i_idx, f_idx, len(cart[i_idx]['files']), cur), parse_mode="HTML")
        except Exception:
            pass

@router.callback_query(F.data.startswith("fdel:"))
async def delete_single_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Удалено!", show_alert=True)
    _, i_idx, f_idx = callback.data.split(":")
    i_idx, f_idx = int(i_idx), int(f_idx)
    data = await state.get_data()
    cart = data.get("cart", [])
    if i_idx < len(cart) and f_idx < len(cart[i_idx]['files']):
        cart[i_idx]['files'].pop(f_idx)
        if not cart[i_idx]['files']:
            cart.pop(i_idx)
        else:
            cart[i_idx]['quantity'] = sum(f.get('copies', 1) for f in cart[i_idx]['files'])
        await state.update_data(cart=cart)
    await view_cart_callback(callback, state)

@router.callback_query(F.data.startswith("cart_del:"))
async def delete_cart_group(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Удалено!")
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    cart = data.get("cart", [])
    if idx < len(cart):
        cart.pop(idx)
        await state.update_data(cart=cart)
    await view_cart_callback(callback, state)

@router.callback_query(F.data == "clear_cart")
async def clear_cart_all(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Корзина очищена!")
    await state.update_data(cart=[])
    await callback.message.edit_text("🗑 Корзина полностью очищена.", reply_markup=get_interactive_cart_kb([]))

# Оформление заказа
@router.callback_query(F.data == "checkout_order")
async def checkout_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    cart = data.get("cart", [])
    if not cart:
        await callback.answer("Корзина пуста!", show_alert=True)
        return

    profile = await get_user_profile(callback.from_user.id)
    if profile and profile.get('phone') and profile.get('saved_name'):
        await state.update_data(client_name=profile['saved_name'], client_phone=profile['phone'])
        await state.set_state(OrderFSM.waiting_for_comment)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            f"👤 Оформление на: <b>{html.escape(profile['saved_name'])}</b> (тел: <code>{html.escape(profile['phone'])}</code>)\n\n💬 Напишите комментарий к заказу или нажмите «Пропустить»:",
            reply_markup=get_skip_comment_kb(),
            parse_mode="HTML"
        )
    else:
        await state.set_state(OrderFSM.waiting_for_name)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer("📝 Укажите ваше <b>Имя</b> (сохранится для будущих заказов):", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")

@router.message(OrderFSM.waiting_for_name)
async def process_order_name(message: Message, state: FSMContext):
    await state.update_data(client_name=message.text.strip())
    await state.set_state(OrderFSM.waiting_for_phone)
    await message.answer("📱 Отправьте контактный номер телефона:", reply_markup=get_phone_kb())

@router.message(OrderFSM.waiting_for_phone)
async def process_order_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    data = await state.get_data()
    name = data.get("client_name", message.from_user.first_name or "Клиент")
    await save_user_profile(message.from_user.id, name, phone)
    await state.update_data(client_phone=phone)
    await state.set_state(OrderFSM.waiting_for_comment)
    await message.answer("💬 Напишите комментарий к заказу или нажмите «Пропустить»:", reply_markup=get_skip_comment_kb(), parse_mode="HTML")

@router.callback_query(F.data == "skip_comment")
async def skip_comment_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Оформляем...")
    try:
        await callback.message.edit_text("⏳ <b>Оформляем ваш заказ, подождите...</b>", parse_mode="HTML")
    except Exception:
        pass
    await finalize_order(callback.bot, callback.from_user.id, state, comment="Без комментария")

@router.message(OrderFSM.waiting_for_comment)
async def comment_received_handler(message: Message, state: FSMContext):
    await message.answer("⏳ <b>Оформляем ваш заказ, подождите...</b>", parse_mode="HTML")
    await finalize_order(message.bot, message.from_user.id, state, comment=message.text.strip())

async def finalize_order(bot, user_id: int, state: FSMContext, comment: str):
    cms = await get_current_cms_texts()
    try:
        data = await state.get_data()
        cart = data.get("cart", [])
        if not cart:
            await bot.send_message(user_id, "⚠️ Корзина пуста.", reply_markup=get_main_menu_kb(cms))
            await state.clear()
            return

        name = data.get("client_name", "Клиент")
        phone = data.get("client_phone", "Не указан")
        tot = await calculate_cart_total(cart)
        order_id, order_code = await create_order(user_id, name, phone, tot, comment)

        b_info = None
        for item in cart:
            if item.get('type') == 'booking':
                s_name = item.get('service_title') or item.get('details')
                await create_booking(order_id, user_id, item['date'], item['time'], s_name)
                b_info = f"📅 Запись: {item['details']}"
                await add_order_item(order_id, 'booking', f"Запись: {item['details']}", 1, [])
            else:
                files_data = item.get('files', [])
                qty = sum(f.get('copies', 1) for f in files_data) if files_data else item.get('quantity', 1)
                await add_order_item(order_id, item.get('type', 'photo'), item.get('details', 'Печать'), qty, files_data)

        await state.clear()
        res = [
            f"🎉 <b>Заказ #{order_code} успешно оформлен!</b>",
            f"👤 Имя: {html.escape(name)}",
            f"📞 Телефон: <code>{html.escape(phone)}</code>",
            f"💬 Комментарий: <i>{html.escape(comment)}</i>",
            f"💰 Сумма: <b>{tot:.1f} ₽</b>"
        ]
        if b_info:
            res.append(f"\n{b_info}")
        res.append("\nСледите за статусом в меню «Мои записи и заказы»!")
        await bot.send_message(user_id, "\n".join(res), reply_markup=get_main_menu_kb(cms), parse_mode="HTML")

        staff_ids = await get_staff_and_owner_ids()
        staff_msg = (
            f"⚡️ <b>НОВЫЙ ЗАКАЗ #{order_code}</b>\n\n"
            f"👤 Клиент: {html.escape(name)} (ID: <code>{user_id}</code>)\n"
            f"📞 Телефон: <code>{html.escape(phone)}</code>\n"
            f"💬 Комментарий: {html.escape(comment)}\n"
            f"💰 Сумма: <b>{tot:.1f} ₽</b>\n\n<b>Состав:</b>\n"
        )
        for it in cart:
            c_sum = sum(f.get('copies', 1) for f in it['files']) if ('files' in it and it['files']) else it.get('quantity', 1)
            staff_msg += f"• {html.escape(it['details'])} — {c_sum} шт.\n"

        for s_id in staff_ids:
            try:
                s_msg = await bot.send_message(s_id, staff_msg, reply_markup=get_order_staff_kb(order_id), parse_mode="HTML")
                await save_order_message(order_id, s_id, s_msg.message_id)
            except Exception as ex:
                logger.error(f"Err send staff {s_id}: {ex}")

    except Exception as e:
        logger.exception(f"Err finalize: {e}")
        await bot.send_message(user_id, f"❌ Ошибка сохранения: <i>{html.escape(str(e))}</i>", reply_markup=get_main_menu_kb(cms), parse_mode="HTML")

@router.callback_query(F.data == "noop")
async def noop_click(callback: CallbackQuery):
    await callback.answer()
