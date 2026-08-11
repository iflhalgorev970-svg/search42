import asyncio
import logging
import datetime
from html import escape

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)
from geopy.distance import great_circle

# Импорты для Google Таблиц
import gspread
from google.oauth2.service_account import Credentials

# ⚠️ ВАЖНО: Вставь свой актуальный токен бота!
BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"
ALLOWED_GROUP_ID = -5484524824

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

# --- НАСТРОЙКА GOOGLE SHEETS ---
# Сюда вставь ссылку на свою Google Таблицу!
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Xppxgp1fSkl46ku_VA5NLvRYmB4hSBKbj2FAinTIkUI/edit?gid=0#gid=0"

try:
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    gc = gspread.authorize(creds)
    worksheet = gc.open_by_url(SHEET_URL).sheet1
    google_sheets_enabled = True
    logging.info("Успешное подключение к Google Sheets!")
except Exception as e:
    logging.error(f"Ошибка подключения к Google Sheets (проверь credentials.json и ссылку): {e}")
    google_sheets_enabled = False

# Функция асинхронной записи в таблицу
async def log_to_sheets(user_id, username, action, geo="Нет гео"):
    if not google_sheets_enabled:
        return
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_safe = username if username else "Скрыт"
    
    def write_sync():
        try:
            worksheet.append_row([now, str(user_id), username_safe, action, geo])
        except Exception as e:
            logging.error(f"Ошибка записи в таблицу: {e}")
            
    await asyncio.to_thread(write_sync)

# Словари для связи сообщений (переписка)
user_to_admin_msg = {}
admin_msg_to_user = {}

# --- СТРУКТУРА БАЗЫ ДАННЫХ (Страна -> Город) ---
DATABASE = {
    "Россия": {
        "Москва": {"coords": (55.7558, 37.6173), "link": "https://t.me/MskChat42"},
        "Санкт-Петербург": {"coords": (59.9342, 30.3351), "link": "https://t.me/SpbChat42"},
        "Калининград": {"coords": (54.7104, 20.4522), "link": "https://t.me/+6vdXRB4zF1FkZDZi"},
        "Нижний Новгород": {"coords": (56.3269, 44.0059), "link": "https://t.me/Nizhny42"},
        "Волгоград": {"coords": (48.7080, 44.5133), "link": "https://t.me/bratuhiVLG42"},
        "Архангельск": {"coords": (64.5401, 40.5433), "link": "https://t.me/FortyTwo_Arkh"},
        "Пермь": {"coords": (58.0105, 56.2502), "link": "https://t.me/sperm42"},
        "Челябинск": {"coords": (55.1644, 61.4368), "link": "https://t.me/ChelChat42"},
        "Троицк": {"coords": (54.0674, 61.5491), "link": "https://t.me/Troitsk42"},
        "Екатеринбург": {"coords": (56.8389, 60.6057), "link": "https://t.me/ekbratuxi"},
        "Тюмень": {"coords": (57.1522, 65.5272), "link": "https://t.me/Tyumen_42"},
        "Омск": {"coords": (54.9885, 73.3242), "link": "https://t.me/OMSK_42"},
        "Новосибирск": {"coords": (55.0084, 82.9357), "link": "https://t.me/+g_1_lZ-3W7BhMmM6"},
        "Барнаул": {"coords": (53.3548, 83.7698), "link": "https://t.me/Barnaul42"},
        "Владивосток": {"coords": (43.1198, 131.8869), "link": "https://t.me/VladChat42"},
    },
    "Беларусь": {
        "Минск": {"coords": (53.9006, 27.5590), "link": "https://t.me/Minsk422"},
    }
}

FLAT_CITIES = {}
for country, cities in DATABASE.items():
    for city, data in cities.items():
        FLAT_CITIES[city] = data

class UserFlow(StatesGroup):
    waiting_auto_geo = State()
    waiting_verification_geo = State()
    waiting_ticket_geo = State()
    waiting_admin_response = State()

@dp.message.middleware()
async def check_group_middleware(handler, event: types.Message, data):
    if event.chat.type in ["group", "supergroup"]:
        if event.chat.id != ALLOWED_GROUP_ID:
            await event.chat.leave()
            return
    return await handler(event, data)


@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти чат", callback_data="find_chat")],
        [InlineKeyboardButton(text="➕ Предложить новый чат", callback_data="missing_country_or_city")]
    ])
    await message.answer(
        f"Привет, {escape(message.from_user.first_name)}! 🤙\n"
        "Давай найдем чат 42братух в твоем городе.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "find_chat")
async def find_chat_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Выбрать страну", callback_data="choose_country")],
        [InlineKeyboardButton(text="📍 Автопоиск по Гео", callback_data="auto_search_geo")]
    ])
    await callback.message.edit_text("Как будем искать?", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "choose_country")
async def choose_country(callback: types.CallbackQuery):
    buttons = []
    for country in DATABASE.keys():
        buttons.append([InlineKeyboardButton(text=country, callback_data=f"country:{country}")])
    buttons.append([InlineKeyboardButton(text="❌ Моей страны нет в списке", callback_data="missing_country_or_city")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="find_chat")])
    await callback.message.edit_text("Выбери свою страну:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("country:"))
async def choose_city(callback: types.CallbackQuery):
    country = callback.data.split(":")[1]
    buttons = []
    for city in DATABASE.get(country, {}).keys():
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"city:{city}")])
    buttons.append([InlineKeyboardButton(text="❌ Моего города нет в списке", callback_data="missing_country_or_city")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к странам", callback_data="choose_country")])
    await callback.message.edit_text(f"Страна: <b>{country}</b>\nВыбери город:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("city:"))
async def request_verification_geo(callback: types.CallbackQuery, state: FSMContext):
    city = callback.data.split(":")[1]
    await state.update_data(chosen_city=city)
    await state.set_state(UserFlow.waiting_verification_geo)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Скинуть своё ГЕО", request_location=True)],
        [KeyboardButton(text="❌ Не могу скинуть гео")]
    ], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer(
        f"Ещё миллисекундочку... Нам нужно подтвердить, что ты находишься в районе города <b>{city}</b>.\n"
        "Отправь свою геопозицию:", reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()

@dp.message(UserFlow.waiting_verification_geo, F.location)
async def verify_geo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chosen_city = data.get("chosen_city")
    user_coords = (message.location.latitude, message.location.longitude)
    target_coords = FLAT_CITIES[chosen_city]["coords"]
    distance = great_circle(user_coords, target_coords).kilometers
    
    geo_str = f"{user_coords[0]}, {user_coords[1]}"
    username = message.from_user.username or message.from_user.first_name
    
    if distance <= 100:
        city_link = FLAT_CITIES[chosen_city]["link"]
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти в чат ({chosen_city})", url=city_link)]])
        
        await log_to_sheets(message.from_user.id, username, f"Выдан чат: {chosen_city}", geo_str)
        
        await message.answer(f"✅ Поздравляем, вот чат вашего города <b>{chosen_city}</b>!", reply_markup=kb, parse_mode="HTML")
        await message.answer("Меню закрыто. Для нового поиска жми /start", reply_markup=ReplyKeyboardRemove())
        await state.clear()
    else:
        note_text = f"Пытался зайти в {chosen_city}, но расстояние {round(distance)}км."
        await log_to_sheets(message.from_user.id, username, f"Тикет (далеко от {chosen_city})", geo_str)
        await send_ticket_to_admins(message.from_user, message.location.latitude, message.location.longitude, note=note_text)
        await message.answer("Ой-ой, кажется ваша геопозиция не совпадает...\nВаш запрос зафиксирован, администратор скоро к вам обратится.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserFlow.waiting_admin_response)

@dp.callback_query(F.data == "auto_search_geo")
async def request_auto_geo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_auto_geo)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Отправить ГЕО для поиска", request_location=True)]
    ], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer("Отправь свою геопозицию, и я найду ближайший чат!", reply_markup=kb)
    await callback.answer()

@dp.message(UserFlow.waiting_auto_geo, F.location)
async def process_auto_geo(message: types.Message, state: FSMContext):
    user_coords = (message.location.latitude, message.location.longitude)
    geo_str = f"{user_coords[0]}, {user_coords[1]}"
    username = message.from_user.username or message.from_user.first_name
    
    closest_city = None
    min_dist = float('inf')
    
    for city, data in FLAT_CITIES.items():
        dist = great_circle(user_coords, data["coords"]).kilometers
        if dist < min_dist:
            min_dist = dist
            closest_city = city
            
    if min_dist <= 100:
        city_link = FLAT_CITIES[closest_city]["link"]
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти в чат ({closest_city})", url=city_link)]])
        
        await log_to_sheets(message.from_user.id, username, f"Автопоиск: выдан {closest_city}", geo_str)
        
        await message.answer(f"✅ Поздравляем! Найден чат 42Братух в <b>{closest_city}</b> (расстояние: {round(min_dist)} км).", reply_markup=kb, parse_mode="HTML")
        await message.answer("Меню закрыто. Для нового поиска жми /start", reply_markup=ReplyKeyboardRemove())
        await state.clear()
    else:
        note_text = f"Автопоиск. Ближайший город {closest_city} в {round(min_dist)}км."
        await log_to_sheets(message.from_user.id, username, f"Тикет (автопоиск не нашел)", geo_str)
        await send_ticket_to_admins(message.from_user, message.location.latitude, message.location.longitude, note=note_text)
        await message.answer("Ой-ой, кажется вашего города нет в базе данных.\nВаш запрос зафиксирован, администратор скоро к вам обратится.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserFlow.waiting_admin_response)

@dp.callback_query(F.data == "missing_country_or_city")
async def missing_data_ticket(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_ticket_geo)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Отправить ГЕО к заявке", request_location=True)],
        [KeyboardButton(text="❌ Пропустить гео")]
    ], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer("Давай передадим запрос админам. Если можешь, прикрепи геопозицию для точности, или пропусти этот шаг:", reply_markup=kb)
    await callback.answer()

@dp.message(UserFlow.waiting_verification_geo, F.text == "❌ Не могу скинуть гео")
@dp.message(UserFlow.waiting_ticket_geo)
async def process_manual_ticket(message: types.Message, state: FSMContext):
    lat, lon = None, None
    geo_str = "Нет гео"
    username = message.from_user.username or message.from_user.first_name
    
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        geo_str = f"{lat}, {lon}"
        
    await log_to_sheets(message.from_user.id, username, "Тикет (ручная заявка / нет гео)", geo_str)
    await send_ticket_to_admins(message.from_user, lat, lon, note="Запрос на добавление / проблемы с гео")
    
    await message.answer("Ваш запрос зафиксирован, администрация скоро к вам обратится.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserFlow.waiting_admin_response)

async def send_ticket_to_admins(user: types.User, lat=None, lon=None, note=""):
    username = f"@{user.username}" if user.username else "нет юзернейма"
    full_name_safe = escape(user.full_name)
    geo_text = "Гео не предоставлено"
    if lat and lon:
        geo_text = f"<code>{lat}, {lon}</code>\n🗺 <a href='https://yandex.ru/maps/?pt={lon},{lat}&z=10&l=map'>Яндекс Карты</a>"
    admin_text = (
        f"🚨 <b>Новый тикет от пользователя!</b>\n\n"
        f"👤 Пользователь: {full_name_safe}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🔗 Ссылка: {username}\n"
        f"🌍 Координаты: {geo_text}\n"
        f"📝 Инфо: <i>{note}</i>\n\n"
        f"💬 <i>Ответьте на это сообщение (Reply), чтобы написать пользователю!</i>\n\n"
        f"👇 <b>Выберите город для выдачи или отклоните:</b>"
    )
    buttons = []
    cities_keys = list(FLAT_CITIES.keys())
    for i in range(0, len(cities_keys), 2):
        row = [InlineKeyboardButton(text=cities_keys[i], callback_data=f"app:{user.id}:{i}")]
        if i + 1 < len(cities_keys):
            row.append(InlineKeyboardButton(text=cities_keys[i + 1], callback_data=f"app:{user.id}:{i + 1}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отказать", callback_data=f"rej:{user.id}")])
    admin_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        sent_msg = await bot.send_message(
            chat_id=ALLOWED_GROUP_ID,
            text=admin_text,
            reply_markup=admin_kb,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        user_to_admin_msg[user.id] = sent_msg.message_id
        admin_msg_to_user[sent_msg.message_id] = user.id
    except Exception as e:
        logging.error(f"Ошибка отправки тикета: {e}")

@dp.callback_query(F.data.startswith("app:"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.message.chat.id != ALLOWED_GROUP_ID:
        return
    _, user_id_str, city_idx_str = callback.data.split(":")
    target_user_id = int(user_id_str)
    cities_keys = list(FLAT_CITIES.keys())
    city_name = cities_keys[int(city_idx_str)]
    city_link = FLAT_CITIES[city_name]["link"]
    admin_name = escape(callback.from_user.first_name)
    try:
        user_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти в чат ({city_name})", url=city_link)]])
        await bot.send_message(chat_id=target_user_id, text=f"🎉 Администратор подобрал для тебя чат города <b>{city_name}</b>!", reply_markup=user_kb, parse_mode="HTML")
        original_text = callback.message.html_text.split("💬")[0]
        await callback.message.edit_text(f"{original_text}\n\n✅ <b>Тикет закрыт (Одобрено)</b>\n👤 Ответил: {admin_name}\n🏙 Выдан город: <b>{city_name}</b>", parse_mode="HTML", disable_web_page_preview=True)
        await log_to_sheets(target_user_id, "Админ", f"Тикет одобрен админом ({city_name})", "-")
    except Exception as e:
        logging.error(f"Ошибка отправки пользователю {target_user_id}: {e}")

@dp.callback_query(F.data.startswith("rej:"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.message.chat.id != ALLOWED_GROUP_ID:
        return
    _, user_id_str = callback.data.split(":")
    target_user_id = int(user_id_str)
    admin_name = escape(callback.from_user.first_name)
    try:
        await bot.send_message(chat_id=target_user_id, text="😔 К сожалению, администраторы не смогли подобрать чат по вашей заявке.")
    except Exception as e:
        pass
    await callback.message.edit_text(f"{callback.message.html_text.split('💬')[0]}\n\n❌ <b>Тикет закрыт (Отклонено)</b>\n👤 Ответил: {admin_name}", parse_mode="HTML", disable_web_page_preview=True)
    await log_to_sheets(target_user_id, "Админ", "Тикет отклонен админом", "-")

@dp.message(F.chat.id == ALLOWED_GROUP_ID, F.reply_to_message)
async def reply_from_group(message: types.Message):
    target_user_id = admin_msg_to_user.get(message.reply_to_message.message_id)
    if target_user_id:
        try:
            if message.text:
                await bot.send_message(target_user_id, f"📩 <b>Сообщение от администратора:</b>\n\n{escape(message.text)}", parse_mode="HTML")
            else:
                await message.copy_to(target_user_id)
            admin_msg_to_user[message.message_id] = target_user_id
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception:
            pass

@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def user_text_message(message: types.Message):
    admin_msg_id = user_to_admin_msg.get(message.from_user.id)
    if admin_msg_id:
        try:
            sent_msg = await message.copy_to(ALLOWED_GROUP_ID, reply_to_message_id=admin_msg_id)
            admin_msg_to_user[sent_msg.message_id] = message.from_user.id
            await message.answer("✉️ Сообщение передано администраторам!")
        except Exception:
            pass

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
