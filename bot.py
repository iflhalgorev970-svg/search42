import math
import sqlite3
import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, \
    CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# Включаем логирование в консоль
logging.basicConfig(level=logging.INFO)

# --- НАСТРОЙКИ БОТА ---
BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"
MAX_DISTANCE_KM = 50.0  # Радиус автоматического входа в чат (в км)

# Список ID админов, которым доступна команда /panel
ADMIN_IDS = [5818997833, 2103317502]

# Чистый запуск без прокси (для обхода блокировок используй VPN на ПК)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('requests.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            tg_id INTEGER,
            city TEXT,
            additional TEXT,
            lat REAL,
            lon REAL
        )
    ''')
    conn.commit()
    conn.close()


# --- FSM СОСТОЯНИЯ ДЛЯ АНКЕТЫ ---
class RequestForm(StatesGroup):
    waiting_for_city = State()
    waiting_for_additional = State()


# --- БАЗА ДАННЫХ С КООРДИНАТАМИ И ТВОИМИ ССЫЛКАМИ ---
CITIES = [
    {"name": "Калининград", "lat": 54.7104, "lon": 20.4522, "link": "https://t.me/+6vdXRB4zF1FkZDZi"},
    {"name": "Минск", "lat": 53.9006, "lon": 27.5590, "link": "https://t.me/Minsk422"},
    {"name": "Нижний Новгород", "lat": 56.3269, "lon": 44.0059, "link": "https://t.me/Nizhny42"},
    {"name": "Волгоград", "lat": 48.7080, "lon": 44.5133, "link": "https://t.me/bratuhiVLG42"},
    {"name": "Архангельск", "lat": 64.5401, "lon": 40.5433, "link": "https://t.me/FortyTwo_Arkh"},
    {"name": "Пермь", "lat": 58.0296, "lon": 56.2668, "link": "https://t.me/sperm42"},
    {"name": "Челябинск", "lat": 55.1644, "lon": 61.4368, "link": "https://t.me/ChelChat42"},
    {"name": "Троицк", "lat": 54.0454, "lon": 61.5489, "link": "https://t.me/Troitsk42"},
    {"name": "Екатеринбург", "lat": 56.8389, "lon": 60.6057, "link": "https://t.me/EkaBurg42"},
    {"name": "Тюмень", "lat": 57.1522, "lon": 65.5272, "link": "https://t.me/Tyumen_42"},
    {"name": "Омск", "lat": 54.9885, "lon": 73.3242, "link": "https://t.me/OMSK_42"},
    {"name": "Новосибирск", "lat": 55.0084, "lon": 82.9357, "link": "https://t.me/+g_1_lZ-3W7BhMmM6"},
    {"name": "Барнаул", "lat": 53.3548, "lon": 83.7698, "link": "https://t.me/Barnaul42"},
    {"name": "Владивосток", "lat": 43.1198, "lon": 131.8869, "link": "https://t.me/VladChat42"}
]


# Вычисление расстояния на сфере Земли (Формула Гаверсинуса)
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# --- ОБРАБОТКА КОМАНДЫ /START ---
@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Найти мой 42 чат", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "Привет! Нажми на кнопку ниже, чтобы поделиться геопозицией. "
        "Бот автоматически подберет чат твоего города или предложит подать заявку, если твоего региона еще нет в списке!",
        reply_markup=kb
    )


# --- ОБРАБОТКА ГЕОЛОКАЦИИ ПОЛЬЗОВАТЕЛЯ ---
@dp.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    user_lat = message.location.latitude
    user_lon = message.location.longitude

    closest_city = None
    min_distance = float('inf')

    for city in CITIES:
        dist = get_distance(user_lat, user_lon, city["lat"], city["lon"])
        if dist < min_distance:
            min_distance = dist
            closest_city = city

    # Сценарий 1: Пользователь близко к одному из чатов
    if min_distance <= MAX_DISTANCE_KM:
        await message.answer(
            f"📍 Твой город определен как (или находится рядом с): **{closest_city['name']}**.\n"
            f"Вот инвайт-ссылка на твой чат 42ых: {closest_city['link']}",
            parse_mode="Markdown"
        )
    # Сценарий 2: Пользователь слишком далеко от всех чатов
    else:
        await state.update_data(lat=user_lat, lon=user_lon)
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📩 Подать заявку", callback_data="start_anketa")]]
        )
        await message.answer(
            f"Поблизости с тобой пока нет активных чатов (ближайший — {closest_city['name']} в {round(min_distance)} км).\n\n"
            f"Хочешь подать заявку админам на открытие чата в твоем регионе?",
            reply_markup=inline_kb
        )


# --- ОПРОС ЮЗЕРА ДЛЯ ЗАЯВКИ (FSM) ---
@dp.callback_query(F.data == "start_anketa")
async def start_anketa(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Напиши название своего города (или крупного центра рядом):")
    await state.set_state(RequestForm.waiting_for_city)
    await callback.answer()


@dp.message(RequestForm.waiting_for_city)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Введи свой игровой ник и добавочное инфо (например, готов ли ты развивать этот чат):")
    await state.set_state(RequestForm.waiting_for_additional)


@dp.message(RequestForm.waiting_for_additional)
async def process_additional(message: Message, state: FSMContext):
    user_data = await state.get_data()

    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    tg_id = message.from_user.id
    city = user_data['city']
    additional = message.text
    lat = user_data['lat']
    lon = user_data['lon']

    # Сохраняем заявку в базу данных requests.db
    conn = sqlite3.connect('requests.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO admin_requests (username, tg_id, city, additional, lat, lon) VALUES (?, ?, ?, ?, ?, ?)",
        (username, tg_id, city, additional, lat, lon)
    )
    conn.commit()
    conn.close()

    await message.answer(
        "✅ Твоя заявка успешно сохранена! Админы изучат её. Если в твоем городе наберется много людей, мы откроем новый сквад!")
    await state.clear()


# --- АДМИН-КОМАНДА /PANEL ДЛЯ СБОРКИ HTML ---
@dp.message(Command("panel"))
async def get_admin_panel(message: Message):
    # Доступ только админам из списка ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect('requests.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, tg_id, city, additional, lat, lon FROM admin_requests")
    rows = cursor.fetchall()
    conn.close()

    # Собираем строки таблицы для веб-страницы
    table_rows_html = ""
    for row in rows:
        r_id, uname, tg_id, city, add_info, lat, lon = row
        table_rows_html += f"""
        <tr>
            <td>{r_id}</td>
            <td><b>{uname}</b> (ID: {tg_id})</td>
            <td><span class="badge">{city}</span></td>
            <td>{add_info}</td>
            <td><a href="https://maps.google.com/?q={lat},{lon}" target="_blank" class="map-link">🗺️ Открыть карту ({lat}, {lon})</a></td>
        </tr>
        """

    # Код HTML-страницы админки
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>42 Сквады — Админ Панель</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1a1a1e; color: #e2e2e6; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #ff9f1c; border-bottom: 2px solid #ff9f1c; padding-bottom: 10px; font-size: 26px; }}
        .stats {{ display: inline-block; background: #06d6a0; color: #1a1a1e; padding: 6px 16px; border-radius: 20px; font-weight: bold; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #24242b; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
        th, td {{ padding: 14px 18px; text-align: left; }}
        th {{ background-color: #ff9f1c; color: #1a1a1e; font-weight: bold; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }}
        tr {{ border-bottom: 1px solid #33333f; transition: background 0.2s; }}
        tr:hover {{ background-color: #2d2d35; }}
        .badge {{ background: #ef476f; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 13px; }}
        .map-link {{ color: #118ab2; text-decoration: none; font-weight: bold; }}
        .map-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📑 Заявки на создание новых 42-чатов</h1>
        <div class="stats">Всего входящих заявок: {len(rows)}</div>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Пользователь</th>
                    <th>Введенный Город</th>
                    <th>Ник / Добавочное инфо</th>
                    <th>Точная локация (GPS)</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html if table_rows_html else "<tr><td colspan='5' style='text-align:center;'>Заявок пока нет. Бот работает в штатном режиме!</td></tr>"}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

    filename = "admin_panel.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    await message.answer_document(
        document=FSInputFile(filename),
        caption="📋 Сгенерирована свежая админ-панель. Открой этот HTML-файл на ПК или телефоне для просмотра таблицы заявок."
    )
    os.remove(filename)


# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    import asyncio

    init_db()  # Создаем базу данных, если её нет
    asyncio.run(dp.start_polling(bot))