import asyncio
import logging
import datetime
import aiosqlite
import csv
import os
import json
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
    ReplyKeyboardRemove,
    FSInputFile,
    BotCommand,
    BotCommandScopeAllGroupChats,
    LinkPreviewOptions 
)
from aiogram.client.default import DefaultBotProperties
from geopy.distance import great_circle

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"
ALLOWED_GROUP_ID = -1004400238613 
ADMIN_ID = 2103317502 
REQUESTS_TOPIC_ID = 46 
APPROVED_TOPIC_ID = 42 

IGNORED_CHATS = {-1003923209265}

DB_NAME = "database.db"
LOG_FILE = "users_log.csv"

current_ping = {
    "type": "text",      
    "file_id": None,     
    "text": "ПЯТЁРКА ПХ ПОБЕДА" 
}

DATABASE = {
    "Россия": {
        "Москва": {"coords": (55.7558, 37.6173), "link": "https://t.me/bratyxi42msk"},
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
CHAT_USERNAMES = []
for country, cities in DATABASE.items():
    for city, data in cities.items():
        FLAT_CITIES[city] = data
        link = data["link"]
        if "t.me/" in link and "+" not in link:
            uname = "@" + link.split("t.me/")[1]
            CHAT_USERNAMES.append(uname)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())

allowed_chats = set()

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["Дата", "ID", "Юзернейм", "Действие", "Гео"])

async def log_to_sheets(user_id, username, action, geo="Нет гео"):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_safe = username if username else "Скрыт"
    def write_sync():
        try:
            with open(LOG_FILE, mode='a', encoding='utf-8-sig', newline='') as f:
                csv.writer(f, delimiter=';').writerow([now, str(user_id), username_safe, action, geo])
        except Exception as e:
            logging.error(f"Ошибка записи: {e}")
    await asyncio.to_thread(write_sync)

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS stats (
                            user_id INTEGER, chat_id INTEGER, user_name TEXT, message_count INTEGER DEFAULT 0,
                            PRIMARY KEY (user_id, chat_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS old_bot_chats (
                            chat_id INTEGER PRIMARY KEY, city_name TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_profiles (
                            user_id INTEGER PRIMARY KEY, 
                            username TEXT, 
                            first_pm_date TEXT, 
                            first_chat_date TEXT, 
                            last_action TEXT, 
                            geo TEXT, 
                            chat_name TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, until_date TEXT)''')
        try: await db.execute('ALTER TABLE blacklist ADD COLUMN until_date TEXT')
        except Exception: pass
        await db.commit()
        
        async with db.execute('SELECT chat_id FROM old_bot_chats') as cursor:
            async for row in cursor: allowed_chats.add(row[0])

async def update_profile(user_id, username, pm_start=False, chat_msg=False, action=None, geo=None, chat_name=None):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_safe = username if username else "Без_юзернейма"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR IGNORE INTO user_profiles (user_id, username) VALUES (?, ?)', (user_id, username_safe))
        await db.execute('UPDATE user_profiles SET username = ? WHERE user_id = ?', (username_safe, user_id))
        
        if pm_start: await db.execute('UPDATE user_profiles SET first_pm_date = COALESCE(first_pm_date, ?) WHERE user_id = ?', (now, user_id))
        if chat_msg: await db.execute('UPDATE user_profiles SET first_chat_date = COALESCE(first_chat_date, ?) WHERE user_id = ?', (now, user_id))
        if action: await db.execute('UPDATE user_profiles SET last_action = ? WHERE user_id = ?', (action, user_id))
        if geo: await db.execute('UPDATE user_profiles SET geo = ? WHERE user_id = ?', (geo, user_id))
        await db.commit()

async def auto_fetch_chats():
    async with aiosqlite.connect(DB_NAME) as db:
        for country, cities in DATABASE.items():
            for city_name, data in cities.items():
                link = data["link"]
                if "t.me/" in link and "+" not in link:
                    uname = "@" + link.split("t.me/")[1]
                    try:
                        chat = await bot.get_chat(uname)
                        await db.execute('INSERT INTO old_bot_chats (chat_id, city_name) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET city_name=excluded.city_name', (chat.id, city_name))
                        allowed_chats.add(chat.id)
                    except Exception: pass
        await db.commit()

async def send_auto_backup(bot: Bot, trigger_text: str):
    prof_file = "user_profiles.csv"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT user_id, username, first_pm_date, first_chat_date, last_action, geo FROM user_profiles') as cursor:
                users = await cursor.fetchall()
                
                with open(prof_file, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f, delimiter=';')
                    cities_list = list(FLAT_CITIES.keys())
                    headers = ["ID", "Юзернейм", "Дата старта в ЛС", "Дата первого сообщения", "Последнее действие", "Гео", "Общая статистика"] + cities_list
                    writer.writerow(headers)
                    
                    for u in users:
                        uid = u[0]
                        raw_uname = u[1]
                        uname_safe = f"@{raw_uname}" if raw_uname and raw_uname != "Без_юзернейма" else "Без_юзернейма"
                        
                        async with db.execute('''SELECT o.city_name, s.message_count FROM stats s JOIN old_bot_chats o ON s.chat_id = o.chat_id WHERE s.user_id = ?''', (uid,)) as c2:
                            user_stats = await c2.fetchall()
                            
                        stats_dict = {city: count for city, count in user_stats}
                        stats_str = ", ".join([f"{city}: {count}" for city, count in user_stats]) if user_stats else "Нет сообщений"
                        
                        row = [uid, uname_safe, u[2], u[3], u[4], u[5], stats_str]
                        for city in cities_list: row.append(stats_dict.get(city, 0))
                        writer.writerow(row)
                        
        await bot.send_message(chat_id=ADMIN_ID, text=f"🤖 <b>Авто-бэкап:</b> {trigger_text}")
        await bot.send_document(chat_id=ADMIN_ID, document=FSInputFile(prof_file))
        if os.path.exists(DB_NAME): await bot.send_document(chat_id=ADMIN_ID, document=FSInputFile(DB_NAME))
        if os.path.exists(LOG_FILE): await bot.send_document(chat_id=ADMIN_ID, document=FSInputFile(LOG_FILE))
    except Exception as e: logging.error(f"Ошибка авто-бэкапа: {e}")

async def on_startup(bot: Bot): logging.info("🟢 Бот запущен")
async def on_shutdown(bot: Bot): await send_auto_backup(bot, "🔴 Выключение/Обновление бота")

class UserFlow(StatesGroup):
    waiting_auto_geo = State()
    waiting_verification_geo = State()
    waiting_ticket_geo = State()
    waiting_admin_response = State()

class AdminFlow(StatesGroup):
    waiting_mute_duration = State()

user_to_admin_msg = {}
admin_msg_to_user = {}

@dp.message.middleware()
async def global_middleware(handler, event: types.Message, data):
    if event.chat.type == "private":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT until_date FROM blacklist WHERE user_id = ?', (event.from_user.id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    if row[0] is None: return 
                    else:
                        until_date = datetime.datetime.fromisoformat(row[0])
                        if datetime.datetime.now() < until_date: return 
                        else:
                            await db.execute('DELETE FROM blacklist WHERE user_id = ?', (event.from_user.id,))
                            await db.commit()
                            
    if event.chat.type in ["group", "supergroup"]:
        chat_id = event.chat.id
        if chat_id != ALLOWED_GROUP_ID and chat_id not in IGNORED_CHATS:
            if chat_id not in allowed_chats:
                allowed_chats.add(chat_id)
                matched_city = "Скрытый/Неизвестный чат"
                for c_name, c_data in FLAT_CITIES.items():
                    if event.chat.username and event.chat.username.lower() in c_data["link"].lower():
                        matched_city = c_name
                        break
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute('INSERT INTO old_bot_chats (chat_id, city_name) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET city_name=excluded.city_name', (chat_id, matched_city))
                    await db.commit()
    return await handler(event, data)

# --- УЗНАТЬ ID ЧАТА ДЛЯ ИМПОРТА ---
@dp.message(Command("chatid"))
async def cmd_chatid(message: types.Message):
    await message.reply(f"ID этого чата: <code>{message.chat.id}</code>\n<i>Скопируй его и напиши в описании к файлу result.json в личку боту.</i>")

# --- ОБРАБОТКА ФАЙЛОВ ОТ АДМИНА (БЭКАПЫ И JSON ТЕЛЕГРАМА) ---
@dp.message(F.chat.type == "private", F.from_user.id == ADMIN_ID, F.document)
async def handle_admin_files(message: types.Message):
    doc_name = message.document.file_name
    
    # Восстановление базы
    if doc_name in [DB_NAME, LOG_FILE]:
        await message.reply(f"⏳ Скачиваю файл <b>{doc_name}</b>...")
        file = await bot.get_file(message.document.file_id)
        await bot.download_file(file.file_path, destination=doc_name)
        if doc_name == DB_NAME:
            await init_db()
            await auto_fetch_chats()
        await message.reply(f"✅ Файл <b>{doc_name}</b> успешно восстановлен! Бот готов к работе.")

    # Обновленный Импорт JSON из Telegram Desktop
    elif doc_name.endswith(".json"):
        args = message.caption.split() if message.caption else []
        if not args or not (args[0].lstrip('-').isdigit()):
            await message.reply("⚠️ Ошибка! Скинь файл выгрузки `result.json` и в **описании (caption)** к файлу напиши ID чата (например: `-1001234567890`).")
            return

        chat_id = int(args[0])
        await message.reply(f"⏳ Читаю выгрузку Telegram (JSON) и вытягиваю АБСОЛЮТНО ВСЕХ пользователей для чата <code>{chat_id}</code>...")
        
        file = await bot.get_file(message.document.file_id)
        await bot.download_file(file.file_path, destination="temp_export.json")
        
        try:
            with open("temp_export.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                
            users_to_add = {}
            for msg in data.get("messages", []):
                uid_str = None
                uname = None
                
                # 1. Обычные сообщения (кто-то что-то написал)
                if "from_id" in msg and "from" in msg:
                    uid_str = str(msg["from_id"])
                    uname = msg["from"]
                # 2. Системные сообщения (вступил в группу, пригласили, сменил фотку и т.д.)
                elif "actor_id" in msg and "actor" in msg:
                    uid_str = str(msg["actor_id"])
                    uname = msg["actor"]
                    
                if uid_str and uname:
                    # Очищаем префиксы от старых и новых версий Телеги
                    if uid_str.startswith("user"):
                        uid_str = uid_str.replace("user", "")
                    
                    if uid_str.lstrip("-").isdigit():
                        uid = int(uid_str)
                        if uid > 0: # Добавляем только реальных людей (не ботов/каналы)
                            users_to_add[uid] = uname
                        
            if not users_to_add:
                await message.reply("⚠️ В файле не найдено ни одного пользователя. Убедись, что это правильная выгрузка истории чата.")
                return

            async with aiosqlite.connect(DB_NAME) as db:
                for uid, uname in users_to_add.items():
                    # Жестко прописываем минимум 1 сообщение всем найденным юзерам, даже если они молчуны
                    await db.execute('''INSERT INTO stats (user_id, chat_id, user_name, message_count) 
                                        VALUES (?, ?, ?, 1)
                                        ON CONFLICT(user_id, chat_id) DO UPDATE SET 
                                        message_count = CASE WHEN message_count = 0 THEN 1 ELSE message_count END,
                                        user_name = excluded.user_name''', 
                                        (uid, chat_id, uname))
                    await db.execute('INSERT OR IGNORE INTO user_profiles (user_id, username) VALUES (?, ?)', 
                                     (uid, uname))
                await db.commit()
                
            await message.reply(f"✅ Успешно извлечено и добавлено <b>{len(users_to_add)}</b> уникальных пользователей (включая молчунов)!\nОни уже готовы к призыву в калле.")
        except Exception as e:
            await message.reply(f"❌ Ошибка при чтении файла JSON: {e}")
        finally:
            if os.path.exists("temp_export.json"):
                os.remove("temp_export.json")

@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await update_profile(message.from_user.id, message.from_user.username, pm_start=True, action="Запустил бота")
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Найти чат")], [KeyboardButton(text="📊 Статистика")]], resize_keyboard=True)
    await message.answer(f"Привет, {escape(message.from_user.first_name)}! 🤙\nВыбери действие:", reply_markup=kb)

@dp.message(F.text == "🔙 Назад", F.chat.type == "private")
async def back_to_main(message: types.Message, state: FSMContext):
    await cmd_start(message, state)

@dp.message(F.text == "🔍 Найти чат", F.chat.type == "private")
async def find_chat_start(message: types.Message, state: FSMContext):
    await state.clear()
    await update_profile(message.from_user.id, message.from_user.username, action="Нажал 'Найти чат'")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Выбрать страну", callback_data="choose_country")],
        [InlineKeyboardButton(text="📍 Автопоиск по Гео", callback_data="auto_search_geo")]
    ])
    await message.answer("Как будем искать?", reply_markup=kb)

@dp.message(F.text == "📊 Статистика", F.chat.type == "private")
async def global_stats(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        query = '''SELECT o.city_name, SUM(s.message_count) as total 
                   FROM stats s 
                   JOIN old_bot_chats o ON s.chat_id = o.chat_id 
                   GROUP BY o.city_name 
                   ORDER BY total DESC LIMIT 10'''
        try:
            async with db.execute(query) as cursor: rows = await cursor.fetchall()
        except Exception: rows = []
        
        async with db.execute('SELECT SUM(message_count) FROM stats WHERE user_id = ?', (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            total_personal = row[0] if row and row[0] else 0

    text = "🌍 <b>Глобальный рейтинг городов:</b>\n\n"
    if not rows: text += "Пока нет данных о статистике.\n"
    else:
        for i, (city, total) in enumerate(rows, 1): text += f"{i}. <b>{city}</b> — {total} сообщ.\n"
    
    text += f"\n💬 <b>Твои сообщения во всех чатах:</b> {total_personal}"
    await message.answer(text)

@dp.callback_query(F.data == "choose_country")
async def choose_country(callback: types.CallbackQuery):
    buttons = [[InlineKeyboardButton(text=country, callback_data=f"country:{country}")] for country in DATABASE.keys()]
    buttons.append([InlineKeyboardButton(text="❌ Моей страны нет в списке", callback_data="missing_country_or_city")])
    await callback.message.edit_text("Выбери свою страну:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("country:"))
async def choose_city(callback: types.CallbackQuery):
    country = callback.data.split(":")[1]
    buttons = [[InlineKeyboardButton(text=city, callback_data=f"city:{city}")] for city in DATABASE.get(country, {}).keys()]
    buttons.append([InlineKeyboardButton(text="❌ Моего города нет в списке", callback_data="missing_country_or_city")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к странам", callback_data="choose_country")])
    await callback.message.edit_text(f"Страна: <b>{country}</b>\nВыбери город:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("city:"))
async def request_verification_geo(callback: types.CallbackQuery, state: FSMContext):
    city = callback.data.split(":")[1]
    await state.update_data(chosen_city=city)
    await state.set_state(UserFlow.waiting_verification_geo)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Скинуть своё ГЕО", request_location=True)], 
        [KeyboardButton(text="❌ Не могу скинуть гео")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer(f"Нам нужно подтвердить, что ты в районе города <b>{city}</b>.\nОтправь геопозицию:", reply_markup=kb)

@dp.callback_query(F.data == "auto_search_geo")
async def request_auto_geo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_auto_geo)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Отправить ГЕО для поиска", request_location=True)],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer("Отправь свою геопозицию, и я найду ближайший чат!", reply_markup=kb)

@dp.message(UserFlow.waiting_verification_geo, F.location)
async def verify_geo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chosen_city = data.get("chosen_city")
    user_coords = (message.location.latitude, message.location.longitude)
    geo_str = f"{user_coords[0]}, {user_coords[1]}"
    target_coords = FLAT_CITIES[chosen_city]["coords"]
    distance = great_circle(user_coords, target_coords).kilometers
    
    if distance <= 100:
        await update_profile(message.from_user.id, message.from_user.username, action=f"Одобрен автоматом ({chosen_city})", geo=geo_str)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти в чат ({chosen_city})", url=FLAT_CITIES[chosen_city]["link"])]])
        await log_to_sheets(message.from_user.id, message.from_user.username, f"Выдан чат: {chosen_city}", geo_str)
        await message.answer(f"✅ Чат вашего города: <b>{chosen_city}</b>!", reply_markup=kb)
        await state.clear()
        try: await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=APPROVED_TOPIC_ID, text=f"🤖 <b>Авто-одобрение по ГЕО (Выбор города)</b>\n👤 {escape(message.from_user.full_name)} (<code>{message.from_user.id}</code>)\n📍 Выдан: <b>{chosen_city}</b>\n🌍 Расстояние: {round(distance)} км.")
        except Exception: pass
    else:
        await update_profile(message.from_user.id, message.from_user.username, action=f"Тикет по гео (далеко от {chosen_city})", geo=geo_str)
        await send_ticket_to_admins(message.from_user, message.location.latitude, message.location.longitude, f"Пытался зайти в {chosen_city}, но расстояние {round(distance)}км.", target_city=chosen_city)
        await message.answer("Ой-ой, геопозиция не совпадает. Запрос передан администратору.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserFlow.waiting_admin_response)

@dp.message(UserFlow.waiting_auto_geo, F.location)
async def process_auto_geo(message: types.Message, state: FSMContext):
    user_coords = (message.location.latitude, message.location.longitude)
    geo_str = f"{user_coords[0]}, {user_coords[1]}"
    closest_city = min(FLAT_CITIES.keys(), key=lambda c: great_circle(user_coords, FLAT_CITIES[c]["coords"]).kilometers)
    min_dist = great_circle(user_coords, FLAT_CITIES[closest_city]["coords"]).kilometers
            
    if min_dist <= 100:
        await update_profile(message.from_user.id, message.from_user.username, action=f"Автопоиск: выдан {closest_city}", geo=geo_str)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти в чат ({closest_city})", url=FLAT_CITIES[closest_city]["link"])]])
        await log_to_sheets(message.from_user.id, message.from_user.username, f"Автопоиск: выдан {closest_city}", geo_str)
        await message.answer(f"✅ Найден чат <b>{closest_city}</b>.", reply_markup=kb)
        await state.clear()
        try: await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=APPROVED_TOPIC_ID, text=f"🤖 <b>Авто-одобрение по ГЕО (Автопоиск)</b>\n👤 {escape(message.from_user.full_name)} (<code>{message.from_user.id}</code>)\n📍 Выдан: <b>{closest_city}</b>\n🌍 Расстояние: {round(min_dist)} км.")
        except Exception: pass
    else:
        await update_profile(message.from_user.id, message.from_user.username, action=f"Тикет автопоиск (далеко от {closest_city})", geo=geo_str)
        await send_ticket_to_admins(message.from_user, message.location.latitude, message.location.longitude, f"Автопоиск. Ближайший {closest_city} в {round(min_dist)}км.", target_city=closest_city)
        await message.answer("Вашего города нет в базе. Запрос передан администратору.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(UserFlow.waiting_admin_response)

@dp.callback_query(F.data == "missing_country_or_city")
async def missing_data_ticket(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_ticket_geo)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить ГЕО к заявке", request_location=True)], [KeyboardButton(text="❌ Пропустить гео")], [KeyboardButton(text="🔙 Назад")]], resize_keyboard=True)
    await callback.message.delete()
    await callback.message.answer("Давай передадим запрос админам. Прикрепи геопозицию или пропусти:", reply_markup=kb)

@dp.message(UserFlow.waiting_verification_geo, F.text == "❌ Не могу скинуть гео")
@dp.message(UserFlow.waiting_ticket_geo)
async def process_manual_ticket(message: types.Message, state: FSMContext):
    lat = message.location.latitude if message.location else None
    lon = message.location.longitude if message.location else None
    geo_str = f"{lat}, {lon}" if lat else None
    data = await state.get_data()
    target_city = data.get("chosen_city")
    
    await update_profile(message.from_user.id, message.from_user.username, action="Тикет (ручная заявка без гео)", geo=geo_str)
    await log_to_sheets(message.from_user.id, message.from_user.username, "Тикет (ручная заявка)")
    await send_ticket_to_admins(message.from_user, lat, lon, note="Запрос на добавление / проблемы с гео", target_city=target_city)
    await message.answer("Запрос зафиксирован, администрация скоро к вам обратится.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserFlow.waiting_admin_response)

async def send_ticket_to_admins(user: types.User, lat=None, lon=None, note="", target_city=None):
    username = f"@{user.username}" if user.username else "нет юзернейма"
    geo_text = f"<code>{lat}, {lon}</code>" if lat and lon else "Гео не предоставлено"
    
    chats_info = ""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''SELECT o.city_name, s.message_count FROM stats s JOIN old_bot_chats o ON s.chat_id = o.chat_id WHERE s.user_id = ? AND s.message_count > 0''', (user.id,)) as cursor:
            rows = await cursor.fetchall()
            
    if rows:
        chats_info = "\n💬 <b>Активность в чатах:</b>\n"
        for city_name, count in rows: chats_info += f" ├ {city_name}: {count} сообщ.\n"
    else: chats_info = "\n💬 <b>Активность в чатах:</b> 0 сообщений\n"
        
    applied_text = f"\n🎯 <b>Подавал заявку в:</b> {target_city}" if target_city else "\n🎯 <b>Подавал заявку в:</b> Город/Страна не из списка"
    admin_text = f"🚨 <b>Новый тикет!</b>\n👤 {escape(user.full_name)}\n🆔 <code>{user.id}</code>\n🔗 {username}\n🌍 {geo_text}{applied_text}{chats_info}\n📝 <i>{note}</i>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать разрешение на чат", callback_data=f"open_app:{user.id}")],
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"rej:{user.id}")],
        [InlineKeyboardButton(text="🔨 Наказание в ЛС", callback_data=f"punish:{user.id}")]
    ])
    try:
        sent_msg = await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=REQUESTS_TOPIC_ID, text=admin_text, reply_markup=kb)
        user_to_admin_msg[user.id] = sent_msg.message_id
        admin_msg_to_user[sent_msg.message_id] = user.id
    except Exception as e: logging.error(f"Ошибка тикета: {e}")

@dp.message(F.chat.type == "private")
async def catch_all_pms(message: types.Message):
    await update_profile(message.from_user.id, message.from_user.username, action="Написал в бота (Саппорт)")
    user_link = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейма"
    header = f"📩 <b>Новое сообщение</b>\n👤 {escape(message.from_user.full_name)}\n🆔 <code>{message.from_user.id}</code>\n🔗 {user_link}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔨 Наказание в ЛС", callback_data=f"punish:{message.from_user.id}")]])
    try:
        await bot.send_message(ALLOWED_GROUP_ID, header, message_thread_id=REQUESTS_TOPIC_ID)
        copied_msg = await message.copy_to(chat_id=ALLOWED_GROUP_ID, message_thread_id=REQUESTS_TOPIC_ID, reply_markup=kb)
        admin_msg_to_user[copied_msg.message_id] = message.from_user.id
    except Exception as e: logging.error(f"Ошибка пересылки ЛС: {e}")

@dp.callback_query(F.data.startswith("punish:"))
async def punish_menu(callback: types.CallbackQuery):
    user_id = callback.data.split(":")[1]
    old_kb = callback.message.reply_markup.inline_keyboard
    new_kb = [row for row in old_kb if row[0].callback_data != callback.data]
    new_kb.append([
        InlineKeyboardButton(text="🔇 Мут (ЛС)", callback_data=f"mute_prompt:{user_id}"),
        InlineKeyboardButton(text="🚫 Бан (ЛС)", callback_data=f"ban_user:{user_id}")
    ])
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_kb))

@dp.callback_query(F.data.startswith("mute_prompt:"))
async def mute_prompt(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.data.split(":")[1]
    await state.set_state(AdminFlow.waiting_mute_duration)
    await state.update_data(mute_user_id=user_id)
    await callback.message.reply(f"🔇 Напиши количество <b>минут</b> для мута пользователя <code>{user_id}</code> в ЛС бота (только число):")
    await callback.answer()

@dp.message(AdminFlow.waiting_mute_duration, F.chat.id == ALLOWED_GROUP_ID)
async def process_mute(message: types.Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.reply("⚠️ Ошибка! Нужно ввести только число (минуты). Операция отменена.")
        await state.clear()
        return
        
    minutes = int(message.text)
    data = await state.get_data()
    target_user = int(data['mute_user_id'])
    until_date = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR REPLACE INTO blacklist (user_id, until_date) VALUES (?, ?)', (target_user, until_date.isoformat()))
        await db.commit()
        
    await message.reply(f"✅ Пользователь <code>{target_user}</code> успешно <b>замучен в ЛС бота на {minutes} минут</b>.")
    await state.clear()

@dp.callback_query(F.data.startswith("ban_user:"))
async def cb_ban_user(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR REPLACE INTO blacklist (user_id, until_date) VALUES (?, NULL)', (user_id,))
        await db.commit()
    try: await callback.message.edit_text(f"{callback.message.html_text}\n\n🚫 <b>ЗАБАНЕН АДМИНОМ В ЛС БОТА</b>", reply_markup=None)
    except Exception: pass
    await callback.answer("Забанен в боте!")

@dp.callback_query(F.data.startswith("open_app:"))
async def open_approve_menu(callback: types.CallbackQuery):
    user_id_str = callback.data.split(":")[1]
    buttons = []
    cities = list(FLAT_CITIES.keys())
    for i in range(0, len(cities), 2):
        row = [InlineKeyboardButton(text=cities[i], callback_data=f"app:{user_id_str}:{i}")]
        if i + 1 < len(cities): row.append(InlineKeyboardButton(text=cities[i + 1], callback_data=f"app:{user_id_str}:{i + 1}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"close_app:{user_id_str}")])
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("close_app:"))
async def close_approve_menu(callback: types.CallbackQuery):
    user_id_str = callback.data.split(":")[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать разрешение на чат", callback_data=f"open_app:{user_id_str}")],
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"rej:{user_id_str}")],
        [InlineKeyboardButton(text="🔨 Наказание в ЛС", callback_data=f"punish:{user_id_str}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data.startswith("app:"))
async def admin_approve(callback: types.CallbackQuery):
    _, user_id_str, city_idx_str = callback.data.split(":")
    city_name = list(FLAT_CITIES.keys())[int(city_idx_str)]
    await update_profile(int(user_id_str), None, action=f"Одобрен вручную ({city_name})")
    
    try: await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=APPROVED_TOPIC_ID, text=f"✅ <b>Заявка одобрена ({city_name}):</b>\n{callback.message.html_text}")
    except Exception: pass
    try: await callback.message.delete()
    except Exception: pass
    try: await bot.send_message(chat_id=int(user_id_str), text=f"🎉 Админ выдал чат <b>{city_name}</b>!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти ({city_name})", url=FLAT_CITIES[city_name]["link"])]]))
    except Exception: pass
    await callback.answer("Выдано!")

@dp.callback_query(F.data.startswith("rej:"))
async def admin_reject(callback: types.CallbackQuery):
    _, user_id_str = callback.data.split(":")
    await update_profile(int(user_id_str), None, action="Отказано админом")
    
    try: await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=APPROVED_TOPIC_ID, text=f"❌ <b>Заявка отклонена:</b>\n{callback.message.html_text}")
    except Exception: pass
    try: await callback.message.delete()
    except Exception: pass
    try: await bot.send_message(chat_id=int(user_id_str), text="😔 Отказано в подборе чата.")
    except Exception: pass
    await callback.answer("Отклонено!")

@dp.message(F.chat.id == ALLOWED_GROUP_ID, F.reply_to_message)
async def reply_from_group(message: types.Message):
    if message.text and message.text.startswith("/"): return
    if message.caption and message.caption.startswith("/"): return

    target_user_id = admin_msg_to_user.get(message.reply_to_message.message_id)
    if target_user_id:
        try: 
            await message.copy_to(chat_id=target_user_id)
            await message.reply("✅ Ответ переслан пользователю!")
        except Exception as e: await message.reply(f"❌ Ошибка отправки (возможно, юзер заблокировал бота): {e}")

@dp.message(Command("worldBan"), F.chat.id == ALLOWED_GROUP_ID)
async def cmd_worldBan(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Использование: <code>/worldBan @username</code> или <code>/worldBan ID</code>")
        return
        
    target = args[1].replace("@", "")
    async with aiosqlite.connect(DB_NAME) as db:
        if target.isdigit(): user_id = int(target)
        else:
            async with db.execute('SELECT user_id FROM user_profiles WHERE username = ? OR username = ?', (target, f"@{target}")) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await message.reply("❌ Пользователь с таким юзернеймом не найден в базе бота.")
                    return
                user_id = row[0]
        await db.execute('INSERT OR REPLACE INTO blacklist (user_id, until_date) VALUES (?, NULL)', (user_id,))
        await db.commit()
        
    success = 0
    for cid in allowed_chats:
        try:
            await bot.ban_chat_member(chat_id=cid, user_id=user_id)
            success += 1
        except Exception: pass
        
    await message.reply(f"💀 <b>ПОЛНЫЙ БАН ВЕЗДЕ!</b>\nПользователь <code>{user_id}</code> полностью отключен от всех функций бота, заблокирован в ЛС и выкинут из {success} чатов сети.")

@dp.message(Command("worldUnban"), F.chat.id == ALLOWED_GROUP_ID)
async def cmd_worldUnban(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Использование: <code>/worldUnban @username</code> или <code>/worldUnban ID</code>")
        return
        
    target = args[1].replace("@", "")
    async with aiosqlite.connect(DB_NAME) as db:
        if target.isdigit(): user_id = int(target)
        else:
            async with db.execute('SELECT user_id FROM user_profiles WHERE username = ? OR username = ?', (target, f"@{target}")) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await message.reply("❌ Пользователь не найден в базе бота.")
                    return
                user_id = row[0]
        await db.execute('DELETE FROM blacklist WHERE user_id = ?', (user_id,))
        await db.commit()
        
    success = 0
    for cid in allowed_chats:
        try:
            await bot.unban_chat_member(chat_id=cid, user_id=user_id, only_if_banned=True)
            success += 1
        except Exception: pass
        
    await message.reply(f"🕊 <b>ГЛОБАЛЬНЫЙ РАЗБАН!</b>\nПользователь <code>{user_id}</code> удален из черного списка бота и разбанен в {success} чатах. Ему снова доступны все функции.")

@dp.message(Command("mut"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_mut_in_chat(message: types.Message):
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ['administrator', 'creator'] and message.from_user.id != ADMIN_ID: return
    
    args = message.text.split()
    target_id = None
    minutes = 0
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        if len(args) > 1 and args[1].isdigit(): minutes = int(args[1])
        else:
            await message.reply("⚠️ Укажи время мута. Пример: <code>/mut 60</code> (в реплай)")
            return
    elif len(args) >= 3:
        target_name = args[1].replace("@", "")
        if args[2].isdigit(): minutes = int(args[2])
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT user_id FROM user_profiles WHERE username = ? OR username = ?', (target_name, f"@{target_name}")) as cursor:
                row = await cursor.fetchone()
                if row: target_id = row[0]
    
    if not target_id:
        await message.reply("⚠️ Пользователь не найден. Ответь на его сообщение или используй формат <code>/mut @username 60</code>")
        return
        
    until_date = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(chat_id=message.chat.id, user_id=target_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
        await message.reply(f"🔇 Пользователь ограничен в этом чате на {minutes} минут.")
    except Exception as e: await message.reply(f"❌ Ошибка: У бота нет прав администратора или юзер админ.")

@dp.message(Command("setphrase"), F.chat.id == ALLOWED_GROUP_ID)
async def set_new_phrase(message: types.Message):
    global current_ping
    target = message.reply_to_message or message
    text_html = target.html_text or ""
    
    if target == message:
        raw_text = message.text or message.caption or ""
        cmd_prefix = raw_text.split()[0] if raw_text else ""
        if cmd_prefix and text_html.startswith(cmd_prefix):
            text_html = text_html.replace(cmd_prefix, "", 1).strip()
            
    if target.photo: current_ping = {"type": "photo", "file_id": target.photo[-1].file_id, "text": text_html}
    elif target.video: current_ping = {"type": "video", "file_id": target.video.file_id, "text": text_html}
    elif target.audio: current_ping = {"type": "audio", "file_id": target.audio.file_id, "text": text_html}
    elif target.voice: current_ping = {"type": "voice", "file_id": target.voice.file_id, "text": text_html}
    elif target.animation: current_ping = {"type": "animation", "file_id": target.animation.file_id, "text": text_html}
    else:
        if not text_html:
            await message.reply("⚠️ Ошибка! Напиши текст после команды или сделай реплай на нужное сообщение (текст/фото/видео).")
            return
        current_ping = {"type": "text", "file_id": None, "text": text_html}
        
    await message.reply(f"✅ Установлен новый формат калла: <b>{current_ping['type'].upper()}</b>\n\n(Всё оформление, ссылки и медиа сохранены!)")

@dp.message(Command("top", "стата"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ALLOWED_GROUP_ID and chat_id not in allowed_chats and chat_id not in IGNORED_CHATS: return
    await send_top_page(message, page=0)

async def send_top_page(message_or_call, page):
    chat_id = message_or_call.chat.id if isinstance(message_or_call, types.Message) else message_or_call.message.chat.id
    limit = 42
    offset = page * limit
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_name, message_count FROM stats WHERE chat_id = ? AND message_count > 0 ORDER BY message_count DESC LIMIT ? OFFSET ?', (chat_id, limit, offset)) as cursor:
            rows = await cursor.fetchall()
        async with db.execute('SELECT COUNT(*) FROM stats WHERE chat_id = ? AND message_count > 0', (chat_id,)) as cursor:
            total_users = (await cursor.fetchone())[0]

    if not rows and page == 0:
        text = "Статистика пока пуста."
        if isinstance(message_or_call, types.Message): await message_or_call.answer(text)
        return
        
    text = f"🏆 <b>Топ чата (Страница {page+1}):</b>\n\n"
    for i, (uname, count) in enumerate(rows, offset + 1):
        safe_name = escape(uname) if uname else "Пользователь"
        text += f"{i}. {safe_name} — {count}\n"

    buttons = []
    if page > 0: buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"top_page:{page-1}"))
    if offset + limit < total_users: buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"top_page:{page+1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
    
    if isinstance(message_or_call, types.Message): await message_or_call.answer(text, reply_markup=kb)
    else: await message_or_call.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("top_page:"))
async def paginate_top(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    await send_top_page(callback, page)
    await callback.answer()

@dp.message(Command("call"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_call(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ALLOWED_GROUP_ID and chat_id not in allowed_chats and chat_id not in IGNORED_CHATS: return
        
    member = await bot.get_chat_member(chat_id, message.from_user.id)
    if member.status not in ['administrator', 'creator']: return
    
    parts = message.text.split(maxsplit=1)
    admin_text = parts[1] if len(parts) > 1 else ""
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, user_name FROM stats WHERE chat_id = ? AND message_count > 0', (chat_id,)) as cursor:
            users = await cursor.fetchall()
            
    if not users: 
        await message.reply("⚠️ В базе этого чата пока нет активных пользователей для калла.")
        return
        
    chunk_size = 5
    user_chunks = [users[i:i + chunk_size] for i in range(0, len(users), chunk_size)]
    
    for chunk in user_chunks:
        mentions = " ".join([f'<a href="tg://user?id={uid}">@{escape(str(name))}</a>' for uid, name in chunk])
        parts_to_join = []
        if admin_text: parts_to_join.append(admin_text)
        parts_to_join.append(mentions)
        if current_ping["text"]: parts_to_join.append(current_ping["text"])
        final_text = "\n".join(parts_to_join)
        
        try:
            m_type = current_ping["type"]
            f_id = current_ping["file_id"]
            if m_type == "text": await message.reply(final_text, link_preview_options=LinkPreviewOptions(is_disabled=True))
            elif m_type == "photo": await message.reply_photo(photo=f_id, caption=final_text)
            elif m_type == "video": await message.reply_video(video=f_id, caption=final_text)
            elif m_type == "audio": await message.reply_audio(audio=f_id, caption=final_text)
            elif m_type == "voice": await message.reply_voice(voice=f_id, caption=final_text)
            elif m_type == "animation": await message.reply_animation(animation=f_id, caption=final_text)
            await asyncio.sleep(1)
        except Exception as e: logging.error(f"Ошибка калла: {e}")

@dp.message(Command("backup"), F.chat.type == "private", F.from_user.id == ADMIN_ID)
async def cmd_backup(message: types.Message):
    await send_auto_backup(bot, "Ручной запрос /backup")

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def collect_stats(message: types.Message):
    matched_city = "Неизвестный город"
    for c_name, c_data in FLAT_CITIES.items():
        if message.chat.username and message.chat.username.lower() in c_data["link"].lower():
            matched_city = c_name
            break
            
    await update_profile(message.from_user.id, message.from_user.username, chat_msg=True, chat_name=matched_city)
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''INSERT INTO stats (user_id, chat_id, user_name, message_count) VALUES (?, ?, ?, 1)
                            ON CONFLICT(user_id, chat_id) DO UPDATE SET message_count = message_count + 1, user_name = excluded.user_name''', 
                            (message.from_user.id, message.chat.id, message.from_user.full_name))
        await db.commit()

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await bot.set_my_commands([BotCommand(command="top", description="Топ-42 активных участников")], scope=BotCommandScopeAllGroupChats())
    await auto_fetch_chats()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
