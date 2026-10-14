import html
from datetime import datetime, timedelta
import pytz
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import TIMEZONE
from database.queries import (
    get_booked_slots, get_price, cancel_booking, 
    get_client_active_bookings, get_client_all_orders_with_items
)
from keyboards.client_kb import get_doc_photo_types_kb

router = Router()

class BookingFSM(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()

def get_moscow_now():
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)

def generate_day_slots(target_date_str: str, booked_slots: list[str]) -> list[str]:
    now = get_moscow_now()
    today_str = now.strftime("%Y-%m-%d")
    is_today = (target_date_str == today_str)

    available_slots = []
    start_time = datetime.strptime("10:00", "%H:%M")
    end_time = datetime.strptime("18:30", "%H:%M")
    
    current_slot = start_time
    while current_slot <= end_time:
        slot_str = current_slot.strftime("%H:%M")
        
        if slot_str in booked_slots:
            current_slot += timedelta(minutes=30)
            continue
            
        if is_today:
            slot_full_datetime = now.replace(
                hour=current_slot.hour, 
                minute=current_slot.minute, 
                second=0, 
                microsecond=0
            )
            time_diff = (slot_full_datetime - now).total_seconds() / 60
            if time_diff < 30:
                current_slot += timedelta(minutes=30)
                continue
                
        available_slots.append(slot_str)
        current_slot += timedelta(minutes=30)
        
    return available_slots

def get_dates_kb():
    now = get_moscow_now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    
    kb = [
        [InlineKeyboardButton(text=f"📅 Сегодня ({now.strftime('%d.%m.%Y')})", callback_data=f"book_date:{today}")],
        [InlineKeyboardButton(text=f"📅 Завтра ({(now + timedelta(days=1)).strftime('%d.%m.%Y')})", callback_data=f"book_date:{tomorrow}")],
        [InlineKeyboardButton(text="⬅ Отмена", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# 1. Выбор типа фото
@router.message(F.text == "📅 Запись на фото на документы")
async def start_booking(message: Message):
    await message.answer(
        "📸 <b>Запись на фотосъемку на документы</b>\n\n"
        "Выберите формат фотографии:",
        reply_markup=get_doc_photo_types_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("doctype:"))
async def process_doc_type(callback: CallbackQuery, state: FSMContext):
    service_code = callback.data.split(":")[1]
    p_info = await get_price(service_code)
    name = p_info['name'] if p_info else service_code
    price = p_info['price'] if p_info else 350.0
    
    await state.update_data(booking_service_code=service_code, booking_service_name=name)
    await state.set_state(BookingFSM.waiting_for_date)
    
    await callback.message.edit_text(
        f"Выбрано: <b>{html.escape(name)}</b> ({price} ₽)\n\n"
        "График работы студии: 10:00 - 19:00 (МСК).\n"
        "⏱ Длительность съемки: 30 минут.\n"
        "Выберите дату визита:",
        reply_markup=get_dates_kb(),
        parse_mode="HTML"
    )

# 2. Выбор даты и показ слотов
@router.callback_query(F.data.startswith("book_date:"))
async def process_booking_date(callback: CallbackQuery, state: FSMContext):
    selected_date = callback.data.split(":")[1]
    await state.update_data(booking_date=selected_date)
    
    booked = await get_booked_slots(selected_date)
    slots = generate_day_slots(selected_date, booked)
    date_formatted = datetime.strptime(selected_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    
    if not slots:
        await callback.message.edit_text(
            f"😔 На дату <b>{date_formatted}</b> нет свободных мест или смена окончена.\n"
            "Попробуйте выбрать другой день:",
            reply_markup=get_dates_kb(),
            parse_mode="HTML"
        )
        return

    keyboard_buttons = []
    row = []
    for s in slots:
        row.append(InlineKeyboardButton(text=f"⏰ {s}", callback_data=f"book_time:{s}"))
        if len(row) == 3:
            keyboard_buttons.append(row)
            row = []
    if row:
        keyboard_buttons.append(row)
        
    keyboard_buttons.append([InlineKeyboardButton(text="⬅ Назад к датам", callback_data="back_to_dates")])
    
    await state.set_state(BookingFSM.waiting_for_time)
    await callback.message.edit_text(
        f"📅 Выбрана дата: <b>{date_formatted}</b>\n\nВыберите свободное время:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingFSM.waiting_for_date)
    await callback.message.edit_text("Выберите дату визита:", reply_markup=get_dates_kb())

# 3. БЕЗОПАСНЫЙ ВЫБОР ВРЕМЕНИ БЕЗ ОБРЕЗАНИЯ МИНУТ
@router.callback_query(F.data.startswith("book_time:"), BookingFSM.waiting_for_time)
async def process_booking_time(callback: CallbackQuery, state: FSMContext):
    # Извлекаем полное время "16:30", не обрезая минуты!
    selected_time = callback.data.replace("book_time:", "").strip()
    
    data = await state.get_data()
    selected_date = data.get("booking_date")
    service_code = data.get("booking_service_code")
    service_name = data.get("booking_service_name", "Фото на документы")
    
    booked_now = await get_booked_slots(selected_date)
    if selected_time in booked_now:
        await callback.answer("⚠️ Этот слот только что был занят! Выберите другой.", show_alert=True)
        return

    try:
        date_formatted = datetime.strptime(selected_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        date_formatted = selected_date
    
    cart = data.get("cart", [])
    cart.append({
        "type": "booking",
        "service_code": service_code,
        "service_title": service_name,
        "details": f"{service_name} ({date_formatted} в {selected_time} МСК)",
        "date": selected_date,
        "date_formatted": date_formatted,
        "time": selected_time,
        "quantity": 1,
        "files": []
    })
    
    await state.update_data(cart=cart)
    await state.set_state(None)
    
    await callback.message.edit_text(
        f"✅ <b>Запись добавлена в корзину!</b>\n\n"
        f"📸 Услуга: <b>{html.escape(service_name)}</b>\n"
        f"📅 Дата: <b>{date_formatted}</b>\n"
        f"⏰ Точное время: <b>{selected_time} (МСК)</b>\n\n"
        "Перейдите в Корзину для оформления заказа.",
        parse_mode="HTML"
    )

# 4. РАЗДЕЛ «МОИ ЗАПИСИ И ЗАКАЗЫ» — ПОКАЗЫВАЕТ ВСЁ
@router.message(F.text == "📋 Мои записи и заказы")
async def view_client_bookings_and_orders(message: Message):
    bookings = await get_client_active_bookings(message.from_user.id)
    orders_data = await get_client_all_orders_with_items(message.from_user.id)
    
    if not bookings and not orders_data:
        await message.answer("У вас пока нет оформленных заказов или записей.")
        return
        
    lines = ["📋 <b>ВАШИ ЗАКАЗЫ И ЗАПИСИ:</b>\n"]
    kb = []
    
    # 1. Записи на фотосессию (с точной датой и минутами)
    if bookings:
        lines.append("📅 <b>Записи на съемку фото на документы:</b>")
        for b in bookings:
            try:
                d_fmt = datetime.strptime(b['booking_date'], "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                d_fmt = b['booking_date']
            
            t_fmt = b['booking_time']
            if ":" not in t_fmt:
                t_fmt = f"{t_fmt}:00"
                
            lines.append(f"• <b>{html.escape(b['service_name'])}</b>")
            lines.append(f"  📅 <b>{d_fmt} в {t_fmt} (МСК)</b>")
            kb.append([InlineKeyboardButton(text=f"❌ Отменить запись на {d_fmt} в {t_fmt}", callback_data=f"cancel_bk:{b['id']}")])
        lines.append("")
        
    # 2. Заказы с их полным содержимым
    if orders_data:
        lines.append("📦 <b>История и статус заказов:</b>")
        status_map = {
            "new": "🆕 Принят в обработку",
            "in_progress": "🟡 В работе у мастера",
            "completed": "🟢 ГОТОВ К ВЫДАЧЕ",
            "rejected": "🔴 Отклонен"
        }
        for item in orders_data:
            o = item["order"]
            items = item["items"]
            code = o['order_code'] if ('order_code' in o.keys() and o['order_code']) else str(o['id'])
            st_text = status_map.get(o['status'], o['status'])
            
            lines.append(f"• <b>Заказ #{code}</b> | Сумма: <b>{o['total_amount']} ₽</b>")
            lines.append(f"  Статус: <b>{st_text}</b>")
            if items:
                for it in items:
                    lines.append(f"   ▫️ {html.escape(it['details'])} ({it['quantity']} шт.)")
            if o['status'] == 'rejected' and o['reject_reason']:
                lines.append(f"  Причина отказа: <i>{html.escape(o['reject_reason'])}</i>")
            lines.append("")
            
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None, parse_mode="HTML")

@router.callback_query(F.data.startswith("cancel_bk:"))
async def cancel_booking_callback(callback: CallbackQuery):
    booking_id = int(callback.data.split(":")[1])
    await cancel_booking(booking_id)
    await callback.answer("Запись отменена!", show_alert=True)
    await callback.message.edit_text("✅ Запись успешно отменена. Слот времени освобожден.")