import asyncio
import logging
import datetime
import aiosqlite
import csv
import os
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
    BotCommandScopeAllGroupChats
)
from aiogram.client.default import DefaultBotProperties
from geopy.distance import great_circle

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"
ALLOWED_GROUP_ID = -1004400238613 # ID ГРУППЫ АДМИНОВ
ADMIN_ID = 2103317502 
REQUESTS_TOPIC_ID = 46 
APPROVED_TOPIC_ID = 42 
SETTINGS_TOPIC_ID = 69  # Топик для смены фразы калла

# ЧАТЫ, КОТОРЫЕ НЕ БУДУТ СВЕТИТЬСЯ В ЛС И БАЗЕ ГОРОДОВ (но в них работают команды)
IGNORED_CHATS = {-1003923209265}

DB_NAME = "database.db"
LOG_FILE = "users_log.csv"
DEFAULT_PING_PHRASE = "ПЯТЁРКА ПХ ПОБЕДА"

# Глобальная переменная для фразы калла (можно менять через топик настроек)
current_ping_phrase = DEFAULT_PING_PHRASE

CHAT_USERNAMES = [
    "@MskChat42", "@SpbChat42", "@Nizhny42", "@bratuhiVLG42", 
    "@FortyTwo_Arkh", "@sperm42", "@ChelChat42", "@Troitsk42", 
    "@ekbratuxi", "@Tyumen_42", "@OMSK_42", "@Barnaul42", 
    "@VladChat42", "@Minsk422"
]

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())

allowed_chats = set()

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

# --- ИНИЦИАЛИЗАЦИЯ ФАЙЛОВ И БД ---
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
        await db.commit()
        
        async with db.execute('SELECT chat_id FROM old_bot_chats') as cursor:
            async for row in cursor: allowed_chats.add(row[0])

# --- УМНОЕ ОБНОВЛЕНИЕ ПРОФИЛЯ ЮЗЕРА ---
async def update_profile(user_id, username, pm_start=False, chat_msg=False, action=None, geo=None, chat_name=None):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_safe = username if username else "Без_юзернейма"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR IGNORE INTO user_profiles (user_id, username) VALUES (?, ?)', (user_id, username_safe))
        await db.execute('UPDATE user_profiles SET username = ? WHERE user_id = ?', (username_safe, user_id))
        
        if pm_start:
            await db.execute('UPDATE user_profiles SET first_pm_date = COALESCE(first_pm_date, ?) WHERE user_id = ?', (now, user_id))
        if chat_msg:
            await db.execute('UPDATE user_profiles SET first_chat_date = COALESCE(first_chat_date, ?) WHERE user_id = ?', (now, user_id))
        if action:
            await db.execute('UPDATE user_profiles SET last_action = ? WHERE user_id = ?', (action, user_id))
        if geo:
            await db.execute('UPDATE user_profiles SET geo = ? WHERE user_id = ?', (geo, user_id))
            
        await db.commit()

async def auto_fetch_chats():
    async with aiosqlite.connect(DB_NAME) as db:
        for uname in CHAT_USERNAMES:
            try:
                chat = await bot.get_chat(uname)
                await db.execute('INSERT OR IGNORE INTO old_bot_chats (chat_id, city_name) VALUES (?, ?)', (chat.id, chat.title))
                allowed_chats.add(chat.id)
            except Exception: pass
        await db.commit()

# --- ФУНКЦИЯ АВТО-БЭКАПА ---
async def send_auto_backup(bot: Bot, trigger_text: str):
    prof_file = "user_profiles.csv"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT user_id, username, first_pm_date, first_chat_date, last_action, geo FROM user_profiles') as cursor:
                users = await cursor.fetchall()
                with open(prof_file, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f, delimiter=';')
                    writer.writerow(["ID", "Юзернейм", "Дата старта в ЛС", "Дата первого сообщения", "Последнее действие", "Гео", "Статистика по чатам (где и сколько)"])
                    for u in users:
                        uid = u[0]
                        async with db.execute('''
                            SELECT o.city_name, s.message_count 
                            FROM stats s 
                            JOIN old_bot_chats o ON s.chat_id = o.chat_id 
                            WHERE s.user_id = ?
                        ''', (uid,)) as c2:
                            user_stats = await c2.fetchall()
                        stats_str = ", ".join([f"{city}: {count}" for city, count in user_stats]) if user_stats else "Нет сообщений"
                        writer.writerow([u[0], u[1], u[2], u[3], u[4], u[5], stats_str])
                        
        await bot.send_message(chat_id=ADMIN_ID, text=f"🤖 <b>Авто-бэкап:</b> {trigger_text}")
        await bot.send_document(chat_id=ADMIN_ID, document=FSInputFile(prof_file))
        if os.path.exists(DB_NAME): await bot.send_document(chat_id=ADMIN_ID, document=FSInputFile(DB_NAME))
        if os.path.exists(LOG_FILE): await bot.send_document(chat_id=ADMIN_ID, document=FSInputFile(LOG_FILE))
    except Exception as e:
        logging.error(f"Ошибка авто-бэкапа: {e}")

# Сигналы запуска и остановки
async def on_startup(bot: Bot):
    await send_auto_backup(bot, "🟢 Запуск бота")

async def on_shutdown(bot: Bot):
    await send_auto_backup(bot, "🔴 Выключение/Обновление бота")

class UserFlow(StatesGroup):
    waiting_auto_geo = State()
    waiting_verification_geo = State()
    waiting_ticket_geo = State()
    waiting_admin_response = State()

user_to_admin_msg = {}
admin_msg_to_user = {}

@dp.message.middleware()
async def check_group_middleware(handler, event: types.Message, data):
    if event.chat.type in ["group", "supergroup"]:
        chat_id = event.chat.id
        if chat_id != ALLOWED_GROUP_ID and chat_id not in IGNORED_CHATS:
            if chat_id not in allowed_chats:
                allowed_chats.add(chat_id)
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute('INSERT OR IGNORE INTO old_bot_chats (chat_id, city_name) VALUES (?, ?)', (chat_id, event.chat.title or "Неизвестный чат"))
                    await db.commit()
    return await handler(event, data)

# --- МЕНЮ ЛС ---
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
                   GROUP BY s.chat_id 
                   ORDER BY total DESC LIMIT 10'''
        try:
            async with db.execute(query) as cursor: rows = await cursor.fetchall()
        except Exception: rows = []
        
        async with db.execute('SELECT SUM(message_count) FROM stats WHERE user_id = ?', (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            total_personal = row[0] if row and row[0] else 0

    text = "🌍 <b>Глобальный рейтинг городов:</b>\n\n"
    if not rows: 
        text += "Пока нет данных о статистике.\n"
    else:
        for i, (city, total) in enumerate(rows, 1): 
            text += f"{i}. <b>{city}</b> — {total} сообщ.\n"
    
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

# --- АДМИН ПАНЕЛЬ (ФОРУМ) ---
async def send_ticket_to_admins(user: types.User, lat=None, lon=None, note="", target_city=None):
    username = f"@{user.username}" if user.username else "нет юзернейма"
    geo_text = f"<code>{lat}, {lon}</code>" if lat and lon else "Гео не предоставлено"
    
    chats_info = ""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
            SELECT o.city_name, s.message_count 
            FROM stats s 
            JOIN old_bot_chats o ON s.chat_id = o.chat_id 
            WHERE s.user_id = ?
        ''', (user.id,)) as cursor:
            rows = await cursor.fetchall()
            
    if rows:
        chats_info = "\n💬 <b>Активность в чатах:</b>\n"
        for city_name, count in rows:
            chats_info += f" ├ {city_name}: {count} сообщ.\n"
    else:
        chats_info = "\n💬 <b>Активность в чатах:</b> 0 сообщений\n"
        
    applied_text = f"\n🎯 <b>Подавал заявку в:</b> {target_city}" if target_city else "\n🎯 <b>Подавал заявку в:</b> Город/Страна не из списка"

    admin_text = (
        f"🚨 <b>Новый тикет!</b>\n"
        f"👤 {escape(user.full_name)}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"🔗 {username}\n"
        f"🌍 {geo_text}"
        f"{applied_text}"
        f"{chats_info}"
        f"\n📝 <i>{note}</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать разрешение на чат", callback_data=f"open_app:{user.id}")],
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"rej:{user.id}")]
    ])
    try:
        sent_msg = await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=REQUESTS_TOPIC_ID, text=admin_text, reply_markup=kb)
        user_to_admin_msg[user.id] = sent_msg.message_id
        admin_msg_to_user[sent_msg.message_id] = user.id
    except Exception as e: logging.error(f"Ошибка тикета: {e}")

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
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"rej:{user_id_str}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data.startswith("app:"))
async def admin_approve(callback: types.CallbackQuery):
    _, user_id_str, city_idx_str = callback.data.split(":")
    city_name = list(FLAT_CITIES.keys())[int(city_idx_str)]
    
    await update_profile(int(user_id_str), None, action=f"Одобрен вручную ({city_name})")
    
    try:
        await callback.message.edit_text(f"{callback.message.html_text}\n\n✅ <b>Одобрено: {city_name}</b>", reply_markup=None)
        await bot.send_message(chat_id=ALLOWED_GROUP_ID, message_thread_id=APPROVED_TOPIC_ID, text=f"✅ Заявка одобрена ({city_name}):\n{callback.message.html_text}")
    except Exception: 
        pass
        
    try:
        await bot.send_message(chat_id=int(user_id_str), text=f"🎉 Админ выдал чат <b>{city_name}</b>!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Войти ({city_name})", url=FLAT_CITIES[city_name]["link"])]]))
    except Exception:
        try:
            await callback.message.reply(f"⚠️ Заявка закрыта, но бот не смог отправить ссылку юзеру (возможно, он заблокировал бота).")
        except Exception:
            pass
            
    await callback.answer("Выдано!")

@dp.callback_query(F.data.startswith("rej:"))
async def admin_reject(callback: types.CallbackQuery):
    _, user_id_str = callback.data.split(":")
    await update_profile(int(user_id_str), None, action="Отказано админом")
    
    try:
        await callback.message.edit_text(f"{callback.message.html_text}\n\n❌ <b>Отклонено</b>", reply_markup=None)
    except Exception:
        pass
        
    try: 
        await bot.send_message(chat_id=int(user_id_str), text="😔 Отказано в подборе чата.")
    except Exception: 
        pass
        
    await callback.answer("Отклонено!")

@dp.message(F.chat.id == ALLOWED_GROUP_ID, F.reply_to_message)
async def reply_from_group(message: types.Message):
    target_user_id = admin_msg_to_user.get(message.reply_to_message.message_id)
    if target_user_id and message.text:
        try: await bot.send_message(target_user_id, f"📩 <b>От админа:</b>\n{escape(message.text)}")
        except Exception: pass

# --- ИЗМЕНЕНИЕ ФРАЗЫ КАЛЛА ЧЕРЕЗ ТОПИК НАСТРОЕК ---
@dp.message(F.chat.id == ALLOWED_GROUP_ID)
async def handle_admin_group(message: types.Message):
    global current_ping_phrase
    if message.from_user.is_bot: return
    
    if message.message_thread_id == SETTINGS_TOPIC_ID:
        new_phrase = message.text
        if not new_phrase: return
        
        current_ping_phrase = new_phrase.strip()
        await message.reply(f"✅ Фраза для калла успешно изменена!\nНовая фраза: <b>{escape(current_ping_phrase)}</b>")

# --- ГРУППОВЫЕ КОМАНДЫ (ТОП И CALL) ---
@dp.message(Command("top", "стата"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ALLOWED_GROUP_ID and chat_id not in allowed_chats and chat_id not in IGNORED_CHATS: 
        return
    await send_top_page(message, page=0)

async def send_top_page(message_or_call, page):
    chat_id = message_or_call.chat.id if isinstance(message_or_call, types.Message) else message_or_call.message.chat.id
    limit = 42
    offset = page * limit
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_name, message_count FROM stats WHERE chat_id = ? ORDER BY message_count DESC LIMIT ? OFFSET ?', (chat_id, limit, offset)) as cursor:
            rows = await cursor.fetchall()
        async with db.execute('SELECT COUNT(*) FROM stats WHERE chat_id = ?', (chat_id,)) as cursor:
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
    
    if isinstance(message_or_call, types.Message):
        await message_or_call.answer(text, reply_markup=kb)
    else:
        await message_or_call.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("top_page:"))
async def paginate_top(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    await send_top_page(callback, page)
    await callback.answer()

@dp.message(Command("call"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_call(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ALLOWED_GROUP_ID and chat_id not in allowed_chats and chat_id not in IGNORED_CHATS: 
        return
        
    member = await bot.get_chat_member(chat_id, message.from_user.id)
    if member.status not in ['administrator', 'creator']: return
    
    parts = message.text.split(maxsplit=1)
    admin_text = parts[1] if len(parts) > 1 else ""
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, user_name FROM stats WHERE chat_id = ?', (chat_id,)) as cursor:
            users = await cursor.fetchall()
            
    if not users: return
    chunk_size = 5
    user_chunks = [users[i:i + chunk_size] for i in range(0, len(users), chunk_size)]
    
    for chunk in user_chunks:
        mentions = " ".join([f'<a href="tg://user?id={uid}">@{escape(str(name))}</a>' for uid, name in chunk])
        
        if admin_text:
            final_text = f"{admin_text}\n{mentions}\n{current_ping_phrase}"
        else:
            final_text = f"{mentions}\n{current_ping_phrase}"
        
        try:
            await message.reply(final_text)
            await asyncio.sleep(1)
        except Exception: pass

@dp.message(Command("backup"), F.chat.type == "private", F.from_user.id == ADMIN_ID)
async def cmd_backup(message: types.Message):
    await send_auto_backup(bot, "Ручной запрос /backup")

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def collect_stats(message: types.Message):
    await update_profile(message.from_user.id, message.from_user.username, chat_msg=True, chat_name=message.chat.title)
    
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
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # В меню бота осталась только команда /top
    await bot.set_my_commands([
        BotCommand(command="top", description="Топ-42 активных участников")
    ], scope=BotCommandScopeAllGroupChats())
    
    await auto_fetch_chats()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
