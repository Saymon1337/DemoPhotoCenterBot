import json
import html
from datetime import datetime, timedelta
import pytz
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import OWNER_ID, TIMEZONE
from database.queries import (
    get_user_role, set_user_role_by_username, get_all_prices,
    get_price, get_order_by_id, update_order_status,
    get_shift_statistics, get_order_messages, get_active_orders,
    toggle_block_slot, get_all_users_by_target, find_order_by_code_or_id,
    get_text, set_text, get_today_orders_and_bookings,
    set_product_promo, remove_product_promo, update_standard_price, is_promo_active
)
from database.db import DB_NAME
import aiosqlite
from keyboards.admin_kb import (
    get_admin_main_kb, get_order_staff_kb, get_admin_cancel_kb,
    get_broadcast_target_kb, get_salon_settings_kb, get_cms_edit_kb,
    get_product_manage_kb
)

router = Router()

class AdminFSM(StatesGroup):
    waiting_for_reject_reason = State()
    waiting_for_client_msg = State()
    waiting_for_staff_username = State()
    waiting_for_search_id = State()
    waiting_for_broadcast_text = State()
    waiting_for_address = State()
    waiting_for_phone = State()
    waiting_for_notice = State()
    waiting_for_cms_text = State()
    waiting_for_std_price = State()
    waiting_for_promo_info = State()

async def sync_order_card(bot, order_id: int, new_text: str, status: str = 'in_progress'):
    all_msgs = await get_order_messages(order_id)
    kb = get_order_staff_kb(order_id, status=status)
    for c_id, m_id in all_msgs:
        try:
            await bot.edit_message_text(chat_id=c_id, message_id=m_id, text=new_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

# 1. Заказы персонала
@router.callback_query(F.data.startswith("ord_take:"))
async def take_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    staff_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    order = await get_order_by_id(order_id)
    code = order.get('order_code') if order else str(order_id)
    await update_order_status(order_id, 'in_progress', callback.from_user.id, staff_name)
    try:
        await callback.bot.send_message(order['client_id'], f"ℹ️ <b>Ваш заказ #{code} принят специалистом {html.escape(staff_name)}!</b>", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("Заказ взят!")
    await sync_order_card(callback.bot, order_id, callback.message.text + f"\n\n🟡 <b>В РАБОТЕ у:</b> {html.escape(staff_name)}", status='in_progress')

@router.callback_query(F.data.startswith("ord_ready:"))
async def ready_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    order = await get_order_by_id(order_id)
    code = order.get('order_code') if order else str(order_id)
    await update_order_status(order_id, 'completed')
    addr = await get_text('salon_address', 'в нашем фотоцентре')
    try:
        await callback.bot.send_message(order['client_id'], f"🎉 <b>Ваш заказ #{code} ГОТОВ к выдаче!</b>\n\nАдрес: <i>{html.escape(addr)}</i>", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("Клиент уведомлен!", show_alert=True)
    await sync_order_card(callback.bot, order_id, callback.message.text + "\n\n🟢 <b>СТАТУС: ВЫПОЛНЕН И ГОТОВ</b>", status='completed')

@router.callback_query(F.data.startswith("ord_files:"))
async def get_order_files(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT item_type, details, file_ids FROM order_items WHERE order_id = ?", (order_id,)) as cursor:
            items = await cursor.fetchall()
    if not items:
        await callback.answer("Файлов нет.", show_alert=True)
        return

    await callback.answer("Отправляю...")
    for item_type, details, file_ids in items:
        if not file_ids:
            continue
        try:
            files_list = json.loads(file_ids)
        except Exception:
            files_list = [{"file_id": fid.strip(), "copies": 1, "comment": ""} for fid in file_ids.split(",") if fid.strip()]

        await callback.message.answer(f"📁 <b>{html.escape(details)}</b> ({len(files_list)} шт.):", parse_mode="HTML")
        for idx, f_obj in enumerate(files_list, 1):
            fid = f_obj["file_id"]
            cap = f"📄 <b>Файл #{idx} ({html.escape(details)})</b>\n🔢 Копий: <b>{f_obj.get('copies', 1)} шт.</b>"
            if f_obj.get("comment"):
                cap += f"\n💬 Комментарий: <i>{html.escape(f_obj['comment'])}</i>"
            sent = False
            try:
                await callback.bot.send_photo(callback.from_user.id, photo=fid, caption=cap, parse_mode="HTML")
                sent = True
            except Exception:
                pass
            if not sent:
                try:
                    await callback.bot.send_document(callback.from_user.id, document=fid, caption=cap, parse_mode="HTML")
                except Exception as e:
                    await callback.message.answer(f"⚠️ Ошибка отправки #{idx}: {e}")

@router.callback_query(F.data.startswith("ord_reject:"))
async def reject_order_prompt(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    await state.update_data(reject_order_id=order_id, orig_text=callback.message.text)
    await state.set_state(AdminFSM.waiting_for_reject_reason)
    await callback.message.answer(f"⚠️ Причина отказа для заказа #{order_id}:", reply_markup=get_admin_cancel_kb())
    await callback.answer()

@router.message(AdminFSM.waiting_for_reject_reason)
async def process_reject_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id, orig_text, reason = data.get("reject_order_id"), data.get("orig_text", ""), message.text.strip()
    await update_order_status(order_id, 'rejected', reason=reason)
    order = await get_order_by_id(order_id)
    code = order.get('order_code') if order else str(order_id)
    try:
        await message.bot.send_message(order['client_id'], f"❌ <b>Ваш заказ #{code} отклонен.</b>\nПричина: <i>{html.escape(reason)}</i>", parse_mode="HTML")
    except Exception:
        pass
    await sync_order_card(message.bot, order_id, orig_text + f"\n\n🔴 <b>ОТКЛОНЕН: {html.escape(reason)}</b>", status='rejected')
    await state.clear()
    await message.answer(f"✅ Заказ #{code} отклонен.")

@router.callback_query(F.data.startswith("ord_msg:"))
async def message_client_prompt(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    await state.update_data(target_order_id=order_id)
    await state.set_state(AdminFSM.waiting_for_client_msg)
    await callback.message.answer(f"✉️ Сообщение для клиента по заказу #{order_id}:", reply_markup=get_admin_cancel_kb())
    await callback.answer()

@router.message(AdminFSM.waiting_for_client_msg)
async def send_message_to_client(message: Message, state: FSMContext):
    data = await state.get_data()
    order = await get_order_by_id(data.get("target_order_id"))
    code = order.get('order_code') if order else str(order.get('id', ''))
    try:
        await message.bot.send_message(order['client_id'], f"💬 <b>Сообщение от фотоцентра по заказу #{code}:</b>\n\n{html.escape(message.text)}", parse_mode="HTML")
        await message.answer("✅ Доставлено клиенту в ЛС!")
    except Exception as e:
        await message.answer(f"❌ Ошибка доставки: {e}")
    await state.clear()

# 2. Панель управления
@router.message(Command("admin"))
@router.message(F.text == "🛠 Панель управления")
async def cmd_admin(message: Message):
    role = await get_user_role(message.from_user.id)
    is_owner = (message.from_user.id == OWNER_ID or role == 'owner')
    if not is_owner and role != 'staff':
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("🛠 <b>Панель управления фотоцентра</b>\nВыберите действие:", reply_markup=get_admin_main_kb(is_owner=is_owner), parse_mode="HTML")

@router.callback_query(F.data == "adm_close")
async def close_admin(callback: CallbackQuery):
    await callback.message.delete()

@router.callback_query(F.data == "adm_cancel")
async def cancel_admin_fsm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]]))

@router.callback_query(F.data == "adm_back_main")
async def back_to_admin_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    role = await get_user_role(callback.from_user.id)
    is_owner = (callback.from_user.id == OWNER_ID or role == 'owner')
    await callback.message.edit_text("🛠 <b>Панель управления фотоцентра</b>\nВыберите действие:", reply_markup=get_admin_main_kb(is_owner=is_owner), parse_mode="HTML")

# 3. Редактор текстов и кнопок (CMS для Владельца)
@router.callback_query(F.data == "adm_cms_menu")
async def cms_menu(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Только для Владельца!", show_alert=True)
        return
    await callback.message.edit_text("✏️ <b>РЕДАКТОР НАДПИСЕЙ И КНОПОК</b>\n\nВыберите элемент для изменения текста:", reply_markup=get_cms_edit_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("cms_edit:"))
async def cms_edit_start(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    cur_val = await get_text(key)
    await state.update_data(editing_cms_key=key)
    await state.set_state(AdminFSM.waiting_for_cms_text)
    await callback.message.edit_text(f"✏️ Текущее значение:\n<code>{html.escape(cur_val)}</code>\n\nОтправьте новый текст следующим сообщением:", reply_markup=get_admin_cancel_kb(), parse_mode="HTML")

@router.message(AdminFSM.waiting_for_cms_text)
async def process_new_cms_text(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("editing_cms_key")
    new_txt = message.text.strip()
    await set_text(key, new_txt)
    await state.clear()
    await message.answer(f"✅ Текст для <code>{key}</code> успешно обновлен!\nНовое значение:\n<b>{html.escape(new_txt)}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ К редактору текстов", callback_data="adm_cms_menu")]]), parse_mode="HTML")

# 4. Цены и акции с дедлайном
@router.callback_query(F.data == "adm_prices")
async def list_prices(callback: CallbackQuery):
    prices = await get_all_prices()
    kb = []
    for p in prices:
        status_icon = "🔥 " if is_promo_active(p) else ""
        kb.append([InlineKeyboardButton(text=f"{status_icon}{p['name']} ({p['price']} ₽)", callback_data=f"pr_view:{p['service_code']}")])
    kb.append([InlineKeyboardButton(text="⬅ Назад", callback_data="adm_back_main")])
    await callback.message.edit_text("💰 <b>Выберите услугу для настройки:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("pr_view:"))
async def view_product_config(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    p = await get_price(code)
    has_promo = is_promo_active(p)
    
    text = [
        f"⚙️ <b>Настройка: {p['name']}</b>\n",
        f"• Базовая розница: <b>{p['price']} ₽</b>",
        f"• Опт: <b>{p['bulk_price']} ₽</b> (от {p['bulk_threshold']} шт.)"
    ]
    if has_promo:
        try:
            d_fmt = datetime.strptime(p['promo_until'], "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            d_fmt = p['promo_until']
        text.append(f"\n🔥 <b>АКТИВНА АКЦИЯ:</b>")
        text.append(f"• Акционная цена: <b>{p['promo_price']} ₽</b>")
        text.append(f"• Действует до: <b>{d_fmt} (включительно)</b>")
    else:
        text.append("\nАкций на этот товар сейчас нет.")
        
    await callback.message.edit_text("\n".join(text), reply_markup=get_product_manage_kb(code, has_promo), parse_mode="HTML")

# Запуск акции с датой дедлайна
@router.callback_query(F.data.startswith("pr_prm:"))
async def promo_start(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[1]
    await state.update_data(editing_code=code)
    await state.set_state(AdminFSM.waiting_for_promo_info)
    text = (
        "🔥 <b>Запуск акции с датой окончания</b>\n\n"
        "Отправьте акционную цену и дедлайн через пробел:\n"
        "<code>[цена] [дата ДД.ММ или число дней]</code>\n\n"
        "<i>Пример на дату:</i> <code>18 20.10</code>\n"
        "<i>Пример на 7 дней:</i> <code>18 7</code>"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_cancel_kb(), parse_mode="HTML")

@router.message(AdminFSM.waiting_for_promo_info)
async def process_promo_info(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    data = await state.get_data()
    code = data.get("editing_code")
    try:
        p_price = float(parts[0])
        val = parts[1]
        now_dt = datetime.now(pytz.timezone(TIMEZONE))
        
        # Если ввели количество дней (например, 7)
        if val.isdigit() and len(val) <= 3:
            until_dt = now_dt + timedelta(days=int(val))
            until_str = until_dt.strftime("%Y-%m-%d")
            display_date = until_dt.strftime("%d.%m.%Y")
        else: # Если ввели дату ДД.ММ
            d_parts = val.split(".")
            day, month = int(d_parts[0]), int(d_parts[1])
            year = now_dt.year
            until_dt = datetime(year, month, day)
            until_str = until_dt.strftime("%Y-%m-%d")
            display_date = f"{day:02d}.{month:02d}.{year}"
            
        await set_product_promo(code, p_price, until_str)
        await state.clear()
        await message.answer(
            f"✅ <b>Акция запущена!</b>\n\nТовар: <code>{code}</code>\nЦена: <b>{p_price} ₽</b>\nДедлайн: <b>до {display_date}</b> включительно.\n\nКлиенты сразу видят акционную плашку в каталоге!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ К товару", callback_data=f"pr_view:{code}")]]),
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка формата: {e}. Пример: <code>18 20.10</code> или <code>18 7</code>")

@router.callback_query(F.data.startswith("pr_rmp:"))
async def promo_remove(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    await remove_product_promo(code)
    await callback.answer("Акция снята!", show_alert=True)
    await view_product_config(callback)

@router.callback_query(F.data.startswith("pr_std:"))
async def std_price_start(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[1]
    await state.update_data(editing_code=code)
    await state.set_state(AdminFSM.waiting_for_std_price)
    await callback.message.edit_text("Отправьте базовую цену числом (или <code>[цена] [опт] [порог]</code>):", reply_markup=get_admin_cancel_kb(), parse_mode="HTML")

@router.message(AdminFSM.waiting_for_std_price)
async def process_std_price(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    data = await state.get_data()
    code = data.get("editing_code")
    try:
        new_price = float(parts[0])
        bulk_p = float(parts[1]) if len(parts) > 1 else None
        bulk_t = int(parts[2]) if len(parts) > 2 else None
        await update_standard_price(code, new_price, bulk_p, bulk_t)
        await state.clear()
        await message.answer("✅ Базовая цена обновлена!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ К товару", callback_data=f"pr_view:{code}")]]))
    except Exception:
        await message.answer("❌ Введите число или <code>30 20 50</code>")

# 5. Журнал смены и активные заказы
@router.callback_query(F.data == "adm_today_journal")
async def show_today_journal(callback: CallbackQuery):
    now_msk = datetime.now(pytz.timezone(TIMEZONE))
    today_str = now_msk.strftime("%Y-%m-%d")
    orders, bookings = await get_today_orders_and_bookings(today_str)
    st_map = {"new": "🆕 Новый", "in_progress": "🟡 В работе", "completed": "🟢 ГОТОВ", "rejected": "🔴 Отказ"}
    lines = [f"📅 <b>ЖУРНАЛ СМЕНЫ — {now_msk.strftime('%d.%m.%Y')} (МСК)</b>\n"]
    kb = []

    lines.append("📸 <b>Записи на сегодня:</b>")
    if bookings:
        for b in bookings:
            t_fmt = b['booking_time'] if ":" in b['booking_time'] else f"{b['booking_time']}:00"
            lines.append(f"• <b>{t_fmt}</b> — {html.escape(b['service_name'])} ({'✅ Активна' if b['status'] == 'booked' else '❌ Отменена'})")
    else:
        lines.append("• Записей нет.")
    lines.append("\n📦 <b>Заказы смены:</b>")
    if orders:
        for o in orders:
            code = o.get('order_code') or str(o.get('id', ''))
            resp = f" ({o['staff_name']})" if (o['status'] == 'in_progress' and o['staff_name']) else ""
            lines.append(f"• <b>#{code}</b> | {html.escape(o['client_name'])} | <b>{o['total_amount']} ₽</b> | {st_map.get(o['status'], o['status'])}{resp}")
            kb.append([InlineKeyboardButton(text=f"Открыть заказ #{code}", callback_data=f"open_ord:{o['id']}")])
    else:
        lines.append("• Заказов за сегодня нет.")
    kb.append([InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data == "adm_active_orders")
async def list_active_orders(callback: CallbackQuery):
    orders = await get_active_orders()
    if not orders:
        await callback.message.edit_text("Сейчас нет активных заказов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]]))
        return
    kb = []
    lines = ["📋 <b>Активные заказы в работе:</b>\n"]
    for o in orders:
        code = o.get('order_code') or str(o.get('id', ''))
        st_text = "🆕 Новый" if o['status'] == 'new' else f"🟡 {o.get('staff_name') or 'В работе'}"
        lines.append(f"• <b>#{code}</b> | {html.escape(o['client_name'])} | {o['total_amount']} ₽ | {st_text}")
        kb.append([InlineKeyboardButton(text=f"Открыть заказ #{code}", callback_data=f"open_ord:{o['id']}")])
    kb.append([InlineKeyboardButton(text="⬅ Назад в меню", callback_data="adm_back_main")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("open_ord:"))
async def open_single_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    order = await get_order_by_id(order_id)
    code = order.get('order_code') or str(order_id)
    status_val = order.get('status', 'new')
    text = (
        f"📦 <b>КАРТОЧКА ЗАКАЗА #{code}</b>\n\n"
        f"👤 Клиент: {html.escape(order.get('client_name', 'Клиент'))} (тел: <code>{html.escape(order.get('client_phone', 'нет'))}</code>)\n"
        f"Статус: <b>{status_val.upper()}</b>\n"
        f"Ответственный: {html.escape(order.get('staff_name') or 'Не назначен')}\n"
        f"Сумма: <b>{order.get('total_amount', 0)} ₽</b>\n"
        f"Комментарий: {html.escape(order.get('comment') or 'нет')}"
    )
    await callback.message.edit_text(text, reply_markup=get_order_staff_kb(order_id, status=status_val), parse_mode="HTML")

@router.callback_query(F.data == "adm_search_order")
async def search_order_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.waiting_for_search_id)
    await callback.message.edit_text("🔍 Введите номер заказа (например: <code>001</code> или <code>15</code>):", reply_markup=get_admin_cancel_kb(), parse_mode="HTML")

@router.message(AdminFSM.waiting_for_search_id)
async def process_search_order(message: Message, state: FSMContext):
    query = message.text.strip()
    order = await find_order_by_code_or_id(query)
    if not order:
        await message.answer(f"❌ Заказ #{html.escape(query)} не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]]))
        await state.clear()
        return
    await state.clear()
    code = order.get('order_code') or str(order.get('id', ''))
    status_val = order.get('status', 'new')
    text = (
        f"📦 <b>РЕЗУЛЬТАТ ПОИСКА: ЗАКАЗ #{code}</b>\n\n"
        f"👤 Клиент: {html.escape(order.get('client_name', 'Клиент'))} (тел: <code>{html.escape(order.get('client_phone', 'нет'))}</code>)\n"
        f"Статус: <b>{status_val.upper()}</b>\n"
        f"Ответственный: {html.escape(order.get('staff_name') or 'Не назначен')}\n"
        f"Сумма: <b>{order.get('total_amount', 0)} ₽</b>\n"
        f"Комментарий: {html.escape(order.get('comment') or 'нет')}"
    )
    await message.answer(text, reply_markup=get_order_staff_kb(order.get('id'), status=status_val), parse_mode="HTML")

# 6. Салон, блокировка слотов и персонал
@router.callback_query(F.data == "adm_salon_settings")
async def salon_settings_menu(callback: CallbackQuery):
    status = await get_text('salon_status', 'open')
    addr = await get_text('salon_address', 'Не указан')
    phone = await get_text('salon_phone', 'Не указан')
    notice = await get_text('booking_notice_min', '30')
    is_open = (status == 'open')
    text = (
        "⚙️ <b>НАСТРОЙКИ САЛОНА</b>\n\n"
        f"• Статус: <b>{'🟢 Открыт' if is_open else '🔴 ЗАКРЫТ'}</b>\n"
        f"• Адрес: <i>{html.escape(addr)}</i>\n"
        f"• Телефон: <code>{html.escape(phone)}</code>\n"
        f"• Порог записи: <b>{notice} мин.</b>"
    )
    await callback.message.edit_text(text, reply_markup=get_salon_settings_kb(is_open), parse_mode="HTML")

@router.callback_query(F.data == "adm_toggle_salon")
async def toggle_salon_status(callback: CallbackQuery):
    cur = await get_text('salon_status', 'open')
    new_st = 'closed' if cur == 'open' else 'open'
    await set_text('salon_status', new_st)
    await callback.answer(f"Салон {'ЗАКРЫТ' if new_st == 'closed' else 'ОТКРЫТ'}!", show_alert=True)
    await salon_settings_menu(callback)

@router.callback_query(F.data == "adm_set_address")
async def set_address_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.waiting_for_address)
    await callback.message.edit_text("📍 Новый адрес фотоцентра:", reply_markup=get_admin_cancel_kb())

@router.message(AdminFSM.waiting_for_address)
async def process_new_address(message: Message, state: FSMContext):
    await set_text('salon_address', message.text.strip())
    await state.clear()
    await message.answer("✅ Адрес обновлен!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В настройки", callback_data="adm_salon_settings")]]))

@router.callback_query(F.data == "adm_set_phone")
async def set_phone_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.waiting_for_phone)
    await callback.message.edit_text("📞 Новый телефон фотоцентра:", reply_markup=get_admin_cancel_kb())

@router.message(AdminFSM.waiting_for_phone)
async def process_new_phone(message: Message, state: FSMContext):
    await set_text('salon_phone', message.text.strip())
    await state.clear()
    await message.answer("✅ Телефон обновлен!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В настройки", callback_data="adm_salon_settings")]]))

@router.callback_query(F.data == "adm_set_notice")
async def set_notice_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.waiting_for_notice)
    await callback.message.edit_text("⏱ Порог времени до записи в минутах (например: <code>30</code>):", reply_markup=get_admin_cancel_kb(), parse_mode="HTML")

@router.message(AdminFSM.waiting_for_notice)
async def process_new_notice(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
        await set_text('booking_notice_min', str(val))
        await state.clear()
        await message.answer(f"✅ Установлено {val} мин!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В настройки", callback_data="adm_salon_settings")]]))
    except ValueError:
        await message.answer("Введите целое число!")

@router.callback_query(F.data == "adm_block_slots")
async def block_slots_choose_day(callback: CallbackQuery):
    now_msk = datetime.now(pytz.timezone(TIMEZONE))
    today = now_msk.strftime("%Y-%m-%d")
    kb = [[InlineKeyboardButton(text=f"Сегодня ({now_msk.strftime('%d.%m.%Y')})", callback_data=f"bl_day:{today}")], [InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]]
    await callback.message.edit_text("⛔ <b>Блокировка слотов:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("bl_day:"))
async def block_slots_grid(callback: CallbackQuery):
    selected_date = callback.data.split(":")[1]
    times = ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30", "18:00", "18:30"]
    kb, row = [], []
    for t in times:
        row.append(InlineKeyboardButton(text=t, callback_data=f"tgl_slot#{selected_date}#{t}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="⬅ Назад", callback_data="adm_back_main")])
    await callback.message.edit_text(f"Слоты на {selected_date}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("tgl_slot#"))
async def toggle_slot_state(callback: CallbackQuery):
    parts = callback.data.split("#")
    is_blocked = await toggle_block_slot(parts[1], parts[2])
    await callback.answer(f"Слот {parts[2]} {'заблокирован' if is_blocked else 'разблокирован'}!", show_alert=True)

@router.callback_query(F.data == "adm_staff")
async def manage_staff_menu(callback: CallbackQuery, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT username, full_name, role FROM users WHERE role IN ('owner', 'staff')") as cursor:
            staff_list = await cursor.fetchall()
    lines = ["👥 <b>Персонал фотоцентра:</b>\n"]
    kb = []
    for un, fn, r in staff_list:
        tag = f"@{un}" if un else "без ника"
        lines.append(f"• {html.escape(fn)} ({tag}) — <i>{r.upper()}</i>")
        if un and r != 'owner':
            kb.append([InlineKeyboardButton(text=f"❌ Снять: @{un}", callback_data=f"rev_st:{un}")])
    lines.append("\nОтправьте <b>@username</b> сотрудника:")
    kb.append([InlineKeyboardButton(text="⬅ Назад", callback_data="adm_back_main")])
    await state.set_state(AdminFSM.waiting_for_staff_username)
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("rev_st:"))
async def revoke_staff(callback: CallbackQuery):
    un = callback.data.split(":")[1]
    await set_user_role_by_username(un, 'client')
    await callback.answer(f"Права сняты!", show_alert=True)
    await callback.message.edit_text("Права отозваны.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]]))

@router.message(AdminFSM.waiting_for_staff_username)
async def process_grant_staff(message: Message, state: FSMContext):
    success = await set_user_role_by_username(message.text.strip(), 'staff')
    if success:
        await message.answer(f"✅ Пользователю <b>{html.escape(message.text.strip())}</b> выданы права персонала!", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Пользователь <b>{html.escape(message.text.strip())}</b> еще не запускал бота.", parse_mode="HTML")
    await state.clear()

# 7. Рассылка и Отчеты
@router.callback_query(F.data == "adm_broadcast")
async def broadcast_menu(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Только для Владельца!", show_alert=True)
        return
    await callback.message.edit_text("📢 <b>Кому отправить объявление?</b>", reply_markup=get_broadcast_target_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("bcast_to:"))
async def start_broadcast_text(callback: CallbackQuery, state: FSMContext):
    await state.update_data(broadcast_target=callback.data.split(":")[1])
    await state.set_state(AdminFSM.waiting_for_broadcast_text)
    await callback.message.edit_text("Напишите текст объявления для рассылки:", reply_markup=get_admin_cancel_kb())

@router.message(AdminFSM.waiting_for_broadcast_text)
async def send_broadcast_message(message: Message, state: FSMContext):
    data = await state.get_data()
    header = await get_text('msg_broadcast_title', '📢 Объявление фотоцентра:')
    users = await get_all_users_by_target(data.get("broadcast_target"))
    sent = 0
    for uid in users:
        try:
            await message.bot.send_message(uid, f"<b>{html.escape(header)}</b>\n\n{html.escape(message.text.strip())}", parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await state.clear()
    await message.answer(f"✅ Доставлено {sent} пользователям.")

@router.callback_query(F.data == "adm_report_now")
async def generate_report_now(callback: CallbackQuery):
    now_msk = datetime.now(pytz.timezone(TIMEZONE))
    summary, by_staff = await get_shift_statistics(now_msk.strftime("%Y-%m-%d"))
    lines = [
        f"📊 <b>ОТЧЕТ ЗА СМЕНУ ({now_msk.strftime('%d.%m.%Y')})</b>\n",
        f"• Всего заказов: <b>{summary['total_orders'] or 0}</b>",
        f"• Выполнено: <b>{summary['completed_orders'] or 0}</b>",
        f"• Отклонено: <b>{summary['rejected_orders'] or 0}</b>",
        f"• Касса: <b>{summary['total_revenue'] or 0.0:.1f} ₽</b>\n",
        "👨‍💻 <b>Выработка персонала:</b>"
    ]
    if by_staff:
        for st in by_staff:
            lines.append(f"• {st['staff_name']}: {st['count']} шт. ({st['revenue']:.1f} ₽)")
    else:
        lines.append("• Выполненных заказов нет.")
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ В админку", callback_data="adm_back_main")]]), parse_mode="HTML")