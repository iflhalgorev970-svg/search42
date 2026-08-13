import asyncio
import logging
import datetime
import aiosqlite
from html import escape

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
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
from aiogram.client.default import DefaultBotProperties
from geopy.distance import great_circle

# Импорты для Google Таблиц
import gspread
from google.oauth2.service_account import Credentials

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Xppxgp1fSkl46ku_VA5NLvRYmB4hSBKbj2FAinTIkUI/edit?usp=sharing" # <--- ВСТАВЬ ССЫЛКУ СЮДА!
ALLOWED_GROUP_ID = -5484524824 # <--- ВСТАВЬ ID ГРУППЫ АДМИНОВ (ДЛЯ ТИКЕТОВ)
DB_NAME = "database.db"
PING_PHRASE = "ПЯТЁРКА ПХ ПОБЕДА"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())

allowed_chats = set()

# --- БАЗА ГОРОДОВ И КООРДИНАТ ---
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

# --- ИНИЦИАЛИЗАЦИЯ GOOGLE ТАБЛИЦ ---
try:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    gc = gspread.authorize(creds)
    worksheet = gc.open_by_url(SHEET_URL).sheet1
    google_sheets_enabled = True
    logging.info("Успешное подключение к Google Sheets!")
except Exception as e:
    logging.error(f"Ошибка подключения к Google Sheets (проверь ссылку/файл): {e}")
    google_sheets_enabled = False

async def log_to_sheets(user_id, username, action, geo="Нет гео"):
    if not google_sheets_enabled: return
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_safe = username if username else "Скрыт"
    def write_sync():
        try: worksheet.append_row([now, str(user_id), username_safe, action, geo])
        except Exception as e: logging.error(f"Ошибка записи в таблицу: {e}")
    await asyncio.to_thread(write_sync)

# --- ИНИЦИАЛИЗАЦИЯ БД (SQLITE) ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS stats (
                            user_id INTEGER,
                            chat_id INTEGER,
                            user_name TEXT,
                            message_count INTEGER DEFAULT 0,
                            PRIMARY KEY (user_id, chat_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS old_bot_chats (
                            chat_id INTEGER PRIMARY KEY,
                            city_name TEXT)''')
        await db.commit()
        try:
            async with db.execute('SELECT chat_id FROM old_bot_chats') as cursor:
                async for row in cursor:
                    allowed_chats.add(row[0])
            logging.info(f"Loaded {len(allowed_chats)} allowed chats into whitelist.")
        except Exception as e:
            logging.error(f"Ошибка загрузки вайтлиста: {e}")

# --- СОСТОЯНИЯ И СЛОВАРИ ---
class UserFlow(StatesGroup):
    waiting_auto_geo = State()
    waiting_verification_geo = State()
    waiting_ticket_geo = State()
    waiting_admin_response = State()

user_to_admin_msg = {}
admin_msg_to_user = {}

# --- МИДЛВАРЬ (Защита админ-группы) ---
@dp.message.middleware()
async def check_group_middleware(handler, event: types.Message, data):
    if event.chat.type in ["group", "supergroup"]:
        if event.chat.id == ALLOWED_GROUP_ID:
            pass # Это наша группа админов, всё ок
        elif event.chat.id not in allowed_chats:
            pass # Это неизвестная группа, просто игнорим текст
    return await handler(event, data)

# --- ЛИЧНЫЕ СООБЩЕНИЯ (МЕНЮ) ---
@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Найти чат")],
            [KeyboardButton(text="📊 Статистика")]
        ],
        resize_keyboard=True
    )
    await message.answer(f"Привет, {escape(message.from_user.first_name)}! 🤙\nГлавное меню. Выбери действие:", reply_markup=kb)

# ==========================================
# ======= ЛОГИКА ПОИСКА ЧАТА (ВЕРНУЛ) ======
# ==========================================

@dp.message(F.text == "🔍 Найти чат", F.chat.type == "private")
async def find_chat_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Выбрать страну", callback_data="choose_country")],
        [InlineKeyboardButton(text="📍 Автопоиск по Гео", callback_data="auto_search_geo")]
    ])
    await message.answer("Как будем искать?", reply_markup=kb)

@dp.callback_query(F.data == "choose_country")
async def choose_country(callback: types.CallbackQuery):
    buttons = [[InlineKeyboardButton(text=country, callback_data=f"country:{country}")] for country in DATABASE.keys()]
    buttons.append([InlineKeyboardButton(text="❌ Моей страны нет в списке", callback_data="missing_country_or_city")])
    await callback.message.edit_text("Выбери свою страну:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("country:"))
async def choose_city(callback: types.CallbackQuery):
    country = callback.data.split(":")[1]
    buttons = [[InlineKeyboardButton(text=city, callback_data=f"city:{city}")] for city in DATABASE.get(country, {}).keys()]
    buttons.append([InlineKeyboardButton(text="❌ Моего города нет в списке", callback_data="missing_country_or_city")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к странам", callback_data="choose_country")])
    await callback.message.edit_text(f"Страна: <b>{country}</b>\nВыбери город:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("city:"))
async def request_verification_geo(callback: types.CallbackQuery, state: FSMContext):
    city = callback.data.split(":")[1]
    await state.update_data(chosen_city=city)
    await state.set_state(UserFlow.waiting_verification_geo)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Скинуть своё ГЕО", request_location=True)], [KeyboardButton(text="❌ Не могу скинуть гео")]], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer(f"Ещё миллисекундочку... Нам нужно подтвердить, что ты находишься в районе города <b>{city}</b>.\nОтправь свою геопозицию:", reply_markup=kb)
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
        await message.answer(f"✅ Поздравляем, вот чат вашего города: <b>{chosen_city}</b>!", reply_markup=kb)
        await message.answer("Для нового поиска жми /start", reply_markup=ReplyKeyboardRemove())
        await state.clear()
    else:
        note_text = f"Пытался зайти в {chosen_city}, но расстояние {round(distance)}км."
        await log_to_sheets(message.from_user.id, username, f"Тикет (далеко от {chosen_city})", geo_str)
        await send_ticket_to_admins(message.from_user, message.location.latitude, message.location.longitude, note=note_text)
        await message.answer("Ой-ой, кажется ваша геопозиция не совпадает...\nЗапрос передан администратору.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserFlow.waiting_admin_response)

@dp.callback_query(F.data == "auto_search_geo")
async def request_auto_geo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_auto_geo)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить ГЕО для поиска", request_location=True)]], resize_keyboard=True)
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
        await message.answer(f"✅ Найден чат <b>{closest_city}</b> (расстояние: {round(min_dist)} км).", reply_markup=kb)
        await message.answer("Для нового поиска жми /start", reply_markup=ReplyKeyboardRemove())
        await state.clear()
    else:
        note_text = f"Автопоиск. Ближайший город {closest_city} в {round(min_dist)}км."
        await log_to_sheets(message.from_user.id, username, f"Тикет (автопоиск не нашел)", geo_str)
        await send_ticket_to_admins(message.from_user, message.location.latitude, message.location.longitude, note=note_text)
        await message.answer("Вашего города нет в базе. Запрос передан администратору.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserFlow.waiting_admin_response)

@dp.callback_query(F.data == "missing_country_or_city")
async def missing_data_ticket(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_ticket_geo)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить ГЕО к заявке", request_location=True)], [KeyboardButton(text="❌ Пропустить гео")]], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer("Давай передадим запрос админам. Прикрепи геопозицию или пропусти этот шаг:", reply_markup=kb)
    await callback.answer()

@dp.message(UserFlow.waiting_verification_geo, F.text == "❌ Не могу скинуть гео")
@dp.message(UserFlow.waiting_ticket_geo)
async def process_manual_ticket(message: types.Message, state: FSMContext):
    lat, lon = None, None
    geo_str = "Нет гео"
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        geo_str = f"{lat}, {lon}"
    await log_to_sheets(message.from_user.id, message.from_user.username, "Тикет (ручная заявка)", geo_str)
    await send_ticket_to_admins(message.from_user, lat, lon, note="Запрос на добавление / проблемы с гео")
    await message.answer("Запрос зафиксирован, администрация скоро к вам обратится.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserFlow.waiting_admin_response)

async def send_ticket_to_admins(user: types.User, lat=None, lon=None, note=""):
    username = f"@{user.username}" if user.username else "нет юзернейма"
    geo_text = f"<code>{lat}, {lon}</code>" if lat and lon else "Гео не предоставлено"
    admin_text = f"🚨 <b>Новый тикет!</b>\n👤 {escape(user.full_name)}\n🆔 <code>{user.id}</code>\n🔗 {username}\n🌍 {geo_text}\n📝 <i>{note}</i>"
    buttons = []
    cities_keys = list(FLAT_CITIES.keys())
    for i in range(0, len(cities_keys), 2):
        row = [InlineKeyboardButton(text=cities_keys[i], callback_data=f"app:{user.id}:{i}")]
        if i + 1 < len(cities_keys): row.append(InlineKeyboardButton(text=cities_keys[i + 1], callback_data=f"app:{user.id}:{i + 1}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отказать", callback_data=f"rej:{user.id}")])
    try:
        sent_msg = await bot.send_message(chat_id=ALLOWED_GROUP_ID, text=admin_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        user_to_admin_msg[user.id] = sent_msg.message_id
        admin_msg_to_user[sent_msg.message_id] = user.id
    except Exception: pass

@dp.callback_query(F.data.startswith("app:"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.message.chat.id != ALLOWED_GROUP_ID: return
    _, user_id_str, city_idx_str = callback.data.split(":")
    city_name = list(FLAT_CITIES.keys())[int(city_idx_str)]
    try:
        await bot.send_message(chat_id=int(user_id_str), text=f"🎉 Админ выдал чат <b>{city_name}</b>!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти ({city_name})", url=FLAT_CITIES[city_name]["link"])]]))
        await callback.message.edit_text(f"{callback.message.html_text}\n\n✅ <b>Одобрено: {city_name}</b>")
        await log_to_sheets(int(user_id_str), "Админ", f"Тикет одобрен ({city_name})", "-")
    except Exception: pass

@dp.callback_query(F.data.startswith("rej:"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.message.chat.id != ALLOWED_GROUP_ID: return
    _, user_id_str = callback.data.split(":")
    try: await bot.send_message(chat_id=int(user_id_str), text="😔 Отказано в подборе чата.")
    except Exception: pass
    await callback.message.edit_text(f"{callback.message.html_text}\n\n❌ <b>Отклонено</b>")

@dp.message(F.chat.id == ALLOWED_GROUP_ID, F.reply_to_message)
async def reply_from_group(message: types.Message):
    target_user_id = admin_msg_to_user.get(message.reply_to_message.message_id)
    if target_user_id and message.text:
        try:
            await bot.send_message(target_user_id, f"📩 <b>От админа:</b>\n{escape(message.text)}")
            admin_msg_to_user[message.message_id] = target_user_id
        except Exception: pass

# Пересылка ответов от юзера админам (если в состоянии тикета)
@dp.message(F.chat.type == "private", ~F.text.in_({"🔍 Найти чат", "📊 Статистика"}), ~F.text.startswith("/"))
async def user_text_message(message: types.Message, state: FSMContext):
    admin_msg_id = user_to_admin_msg.get(message.from_user.id)
    if admin_msg_id:
        try:
            sent_msg = await message.copy_to(ALLOWED_GROUP_ID, reply_to_message_id=admin_msg_id)
            admin_msg_to_user[sent_msg.message_id] = message.from_user.id
        except Exception: pass

# ==========================================
# ===== СТАТИСТИКА И ГРУППОВЫЕ КОМАНДЫ =====
# ==========================================

@dp.message(F.text == "📊 Статистика", F.chat.type == "private")
async def global_stats(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        query = '''SELECT o.city_name, SUM(s.message_count) as total FROM stats s JOIN old_bot_chats o ON s.chat_id = o.chat_id GROUP BY s.chat_id ORDER BY total DESC LIMIT 10'''
        try:
            async with db.execute(query) as cursor: rows = await cursor.fetchall()
        except Exception: rows = []
    if not rows: text = "📊 Пока нет данных о статистике."
    else:
        text = "🌍 <b>Глобальный рейтинг городов:</b>\n\n"
        for i, (city, total) in enumerate(rows, 1): text += f"{i}. <b>{city}</b> — {total} сообщ.\n"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Моя статистика", callback_data="my_stats")]]))

@dp.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT SUM(message_count) FROM stats WHERE user_id = ?', (callback.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row and row[0] else 0
    await callback.answer(f"Твоя статистика: {total} сообщений во всех чатах!", show_alert=True)

@dp.message(Command("add_chat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_add_chat(message: types.Message):
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ['administrator', 'creator']: return
    city_name = message.text.replace("/add_chat", "").strip()
    if not city_name:
        await message.answer("Укажи название города! Например: /add_chat Москва")
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS old_bot_chats (chat_id INTEGER PRIMARY KEY, city_name TEXT)''')
        await db.execute('INSERT OR REPLACE INTO old_bot_chats (chat_id, city_name) VALUES (?, ?)', (message.chat.id, city_name))
        await db.commit()
    allowed_chats.add(message.chat.id)
    await message.answer(f"✅ Чат '{city_name}' (ID: {message.chat.id}) добавлен в белый список!\nСбор статистики запущен 🤙")

@dp.message(Command("top", "стата"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top(message: types.Message):
    if message.chat.id not in allowed_chats: return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, user_name, message_count FROM stats WHERE chat_id = ? ORDER BY message_count DESC LIMIT 10', (message.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer("Статистика пока пуста.")
        return
    text = f"🏆 <b>Топ-10 самых активных в этом чате:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, uname, count) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        safe_name = escape(uname) if uname else "Пользователь"
        text += f"{medal} <a href='tg://user?id={uid}'>{safe_name}</a> — {count}\n"
    await message.answer(text)

@dp.message(Command("call"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_call(message: types.Message):
    if message.chat.id not in allowed_chats: return
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ['administrator', 'creator']: return
    try: await message.delete()
    except Exception: pass
    admin_text = message.text.replace("/call", "").strip() or "Внимание!"
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id FROM stats WHERE chat_id = ?', (message.chat.id,)) as cursor:
            users = [row[0] async for row in cursor]
    if not users: return
    chunk_size = 5
    user_chunks = [users[i:i + chunk_size] for i in range(0, len(users), chunk_size)]
    for chunk in user_chunks:
        parts = []
        chars_per_user = max(1, len(PING_PHRASE) // len(chunk))
        for i in range(len(chunk)):
            parts.append(PING_PHRASE[i * chars_per_user:] if i == len(chunk) - 1 else PING_PHRASE[i * chars_per_user : (i+1) * chars_per_user])
        ping_html = "".join([f'<a href="tg://user?id={uid}">{parts[i]}</a>' for i, uid in enumerate(chunk)])
        try:
            sent_msg = await message.answer(f"{admin_text}\n\n<tg-spoiler>{ping_html}</tg-spoiler>")
            await sent_msg.pin(disable_notification=False)
            await asyncio.sleep(1)
        except Exception: pass

# Самый нижний хэндлер (чтобы не перехватывал команды)
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def collect_stats(message: types.Message):
    if message.chat.id not in allowed_chats: return
    text = message.text or message.caption or ""
    if len(text) > 5:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute('''INSERT INTO stats (user_id, chat_id, user_name, message_count) VALUES (?, ?, ?, 1)
                                ON CONFLICT(user_id, chat_id) DO UPDATE SET message_count = message_count + 1, user_name = excluded.user_name''', 
                                (message.from_user.id, message.chat.id, message.from_user.full_name))
            await db.commit()

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
