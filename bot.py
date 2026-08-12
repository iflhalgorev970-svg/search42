import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"
DB_NAME = "database.db"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Кэш разрешенных чатов (Whitelist)
allowed_chats = set()

# Строка для скрытого пинга
PING_PHRASE = "ПЯТЁРКА ПХ ПОБЕДА"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Создаем таблицу статистики
        await db.execute('''CREATE TABLE IF NOT EXISTS stats (
                            user_id INTEGER,
                            chat_id INTEGER,
                            user_name TEXT,
                            message_count INTEGER DEFAULT 0,
                            PRIMARY KEY (user_id, chat_id))''')
        
        # ДОБАВЛЕНО: Заставляем бота самого создавать таблицу вайтлиста, если ее нет
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

@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Найти чат")],
            [KeyboardButton(text="📊 Статистика")]
        ],
        resize_keyboard=True
    )
    await message.answer("Главное меню. Выбери действие:", reply_markup=kb)

@dp.message(Command("add_chat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_add_chat(message: types.Message):
    # Проверка на админа
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ['administrator', 'creator']:
        return
        
    city_name = message.text.replace("/add_chat", "").strip()
    if not city_name:
        await message.answer("Укажи название города! Например: /add_chat Москва")
        return
        
    async with aiosqlite.connect(DB_NAME) as db:
        # Создаем таблицу, если вдруг её всё ещё нет
        await db.execute('''CREATE TABLE IF NOT EXISTS old_bot_chats (
                            chat_id INTEGER PRIMARY KEY,
                            city_name TEXT)''')
        # Добавляем чат в базу
        await db.execute('INSERT OR REPLACE INTO old_bot_chats (chat_id, city_name) VALUES (?, ?)', (message.chat.id, city_name))
        await db.commit()
        
    allowed_chats.add(message.chat.id)
    await message.answer(f"✅ Чат '{city_name}' (ID: {message.chat.id}) добавлен в белый список!\nСбор статистики запущен 🤙")

@dp.message(F.text == "📊 Статистика", F.chat.type == "private")
async def global_stats(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        # Глобальный топ городов (связываем статистику с названиями из старой таблицы)
        query = '''
            SELECT o.city_name, SUM(s.message_count) as total
            FROM stats s
            JOIN old_bot_chats o ON s.chat_id = o.chat_id
            GROUP BY s.chat_id
            ORDER BY total DESC
            LIMIT 10
        '''
        try:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
        except Exception:
            rows = []
            
    if not rows:
        text = "📊 Пока нет данных о статистике."
    else:
        text = "🌍 <b>Глобальный рейтинг городов:</b>\n\n"
        for i, (city, total) in enumerate(rows, 1):
            text += f"{i}. <b>{city}</b> — {total} сообщ.\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Моя статистика", callback_data="my_stats")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        query = 'SELECT SUM(message_count) FROM stats WHERE user_id = ?'
        async with db.execute(query, (callback.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row and row[0] else 0
            
    await callback.answer(f"Твоя статистика: {total} сообщений во всех чатах!", show_alert=True)

@dp.message(Command("top", "стата"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top(message: types.Message):
    if message.chat.id not in allowed_chats:
        return
        
    async with aiosqlite.connect(DB_NAME) as db:
        query = '''
            SELECT user_id, user_name, message_count 
            FROM stats 
            WHERE chat_id = ? 
            ORDER BY message_count DESC 
            LIMIT 10
        '''
        async with db.execute(query, (message.chat.id,)) as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await message.answer("Статистика пока пуста.")
        return
        
    text = f"🏆 <b>Топ-10 самых активных в этом чате:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (uid, uname, count) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        safe_name = uname.replace("<", "&lt;").replace(">", "&gt;") if uname else "Пользователь"
        text += f"{medal} <a href='tg://user?id={uid}'>{safe_name}</a> — {count}\n"
        
    await message.answer(text)

@dp.message(Command("call"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_call(message: types.Message):
    if message.chat.id not in allowed_chats:
        return

    # Проверка на админа/создателя
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ['administrator', 'creator']:
        return

    # Удаляем исходное сообщение
    try:
        await message.delete()
    except Exception:
        pass

    # Получаем текст админа
    admin_text = message.text.replace("/call", "").strip()
    if not admin_text:
        admin_text = "Внимание!"

    # Получаем юзеров чата из БД
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id FROM stats WHERE chat_id = ?', (message.chat.id,)) as cursor:
            users = [row[0] async for row in cursor]
            
    if not users:
        return

    # Разбиваем на пачки по 5 человек
    chunk_size = 5
    user_chunks = [users[i:i + chunk_size] for i in range(0, len(users), chunk_size)]

    for chunk in user_chunks:
        # Динамически делим фразу
        parts = []
        chars_per_user = max(1, len(PING_PHRASE) // len(chunk))
        
        for i in range(len(chunk)):
            if i == len(chunk) - 1:
                # Последнему достается весь остаток строки
                parts.append(PING_PHRASE[i * chars_per_user:])
            else:
                parts.append(PING_PHRASE[i * chars_per_user : (i+1) * chars_per_user])

        # Оборачиваем части в ссылки
        ping_html = ""
        for i, uid in enumerate(chunk):
            ping_html += f'<a href="tg://user?id={uid}">{parts[i]}</a>'

        # Прячем под спойлер, чтобы визуально не мусорить
        final_text = f"{admin_text}\n\n<tg-spoiler>{ping_html}</tg-spoiler>"
        
        try:
            sent_msg = await message.answer(final_text)
            # Закрепляем со звуковым уведомлением
            await sent_msg.pin(disable_notification=False)
            await asyncio.sleep(1) # Защита от FloodWait
        except Exception as e:
            logging.error(f"Call error: {e}")

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def collect_stats(message: types.Message):
    # Моментальная проверка через set в памяти
    if message.chat.id not in allowed_chats:
        return
        
    text = message.text or message.caption or ""
    # Засчитываем сообщения длиннее 5 символов
    if len(text) > 5:
        uid = message.from_user.id
        uname = message.from_user.full_name
        cid = message.chat.id
        
        async with aiosqlite.connect(DB_NAME) as db:
            # Upsert-запрос (вставляем новую или обновляем счетчик)
            await db.execute('''
                INSERT INTO stats (user_id, chat_id, user_name, message_count) 
                VALUES (?, ?, ?, 1)
                ON CONFLICT(user_id, chat_id) DO UPDATE SET 
                message_count = message_count + 1,
                user_name = excluded.user_name
            ''', (uid, cid, uname))
            await db.commit()

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
