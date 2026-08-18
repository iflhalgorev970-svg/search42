import telebot
import sqlite3
import re
import time
from datetime import datetime

# Настройки бота (замени на свой токен, если нужно, или подтягивай из окружения)
TOKEN = "ТОКЕН_ТВОЕГО_БОТА"
bot = telebot.TeleBot(TOKEN)

DB_NAME = "database.db"

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Таблица для подсчета сообщений и статистики
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER,
            chat_id INTEGER,
            user_name TEXT,
            message_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    # Таблица профилей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Проверка на админа чата
def is_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except:
        return False

# Сбор статистики с сообщений
@bot.message_handler(func=lambda message: True, content_types=['text', 'sticker', 'photo', 'video', 'document'])
def handle_messages(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Аноним"
    
    # Игнорируем личку, работаем только в группах/супергруппах
    if message.chat.type == 'private':
        return

    # Считаем только сообщения длиннее 5 символов (как ты и хотел для фильтрации мусора)
    text = message.text or message.caption or ""
    if len(text.strip()) >= 5:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Обновляем или добавляем статистику в чате
        cursor.execute('''
            INSERT INTO stats (user_id, chat_id, user_name, message_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, chat_id) 
            DO UPDATE SET message_count = message_count + 1, user_name = ?
        ''', (user_id, chat_id, user_name, user_name))
        
        # Обновляем профиль
        cursor.execute('''
            INSERT INTO user_profiles (user_id, username)
            VALUES (?, ?)
            ON CONFLICT(user_id) 
            DO UPDATE SET username = ?
        ''', (user_id, user_name, user_name))
        
        conn.commit()
        conn.close()

# Команда /call (Скрытое/массовое упоминание без закреплений!)
@bot.message_handler(commands=['call'])
def call_users(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if message.chat.type == 'private':
        bot.reply_to(message, "Эту команду можно использовать только в чатах комьюнити!")
        return

    # Проверяем, админ ли вызывает (или оставляй доступ всем, если задумывалось для админов)
    if not is_admin(chat_id, user_id):
        bot.reply_to(message, "❌ Эта команда доступна только администраторам.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, user_name FROM stats WHERE chat_id = ?', (chat_id,))
    users = cursor.fetchall()
    conn.close()

    if not users:
        bot.reply_to(message, "В базе пока нет пользователей для этого чата. Запусти парсер истории!")
        return

    # Собираем красивый текст с упоминаниями по имени (скрытая ссылка на ID, не засоряет ники)
    call_text = "📢 **Внимание, сбор комьюнити!**\n\n"
    chunk = ""
    
  for uid, name in users:
        # Очищаем имя от недопустимых символов для markdown
        clean_name = str(name).replace("[", "").replace("]", "")
        mention = f"[{clean_name}](tg://user?id={uid}) "
        
        if len(chunk) + len(mention) > 4000:
            bot.send_message(chat_id, call_text + chunk, parse_mode="Markdown")
            chunk = ""
        chunk += mention

    if chunk:
        bot.send_message(chat_id, call_text + chunk, parse_mode="Markdown")

    # Удалили строчку с bot.pin_chat_message(...) — теперь ничего само не закрепляется!

# Команда /top (Геймификация и рейтинг активности)
@bot.message_handler(commands=['top'])
def show_top(message):
    chat_id = message.chat.id
    if message.chat.type == 'private':
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_name, message_count 
        FROM stats 
        WHERE chat_id = ? 
        ORDER BY message_count DESC 
        LIMIT 10
    ''', (chat_id,))
    top_users = cursor.fetchall()
    conn.close()

    if not top_users:
        bot.reply_to(message, "📊 Статистика пока пуста.")
        return

    text = "🏆 **Топ активных участников чата:**\n\n"
    for i, (name, count) in enumerate(top_users, 1):
        text += f"{i}. **{name}** — {count} сообщ.\n"

    bot.send_message(chat_id, text, parse_mode="Markdown")

# Команда /backup для скачивания базы
@bot.message_handler(commands=['backup'])
def get_backup(message):
    # Можешь ограничить только для себя по своему user_id, либо оставить админам
    try:
        with open(DB_NAME, 'rb') as f:
            bot.send_document(message.chat.id, f, caption="💾 Твой актуальный файл базы данных.")
    except Exception as e:
        bot.reply_to(message, f"Не удалось отправить бэкап: {e}")

if __name__ == "__main__":
    print("🤖 Бот запущен и готов к работе...")
    bot.infinity_polling(skip_pending=True)
