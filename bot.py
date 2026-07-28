import asyncio
import logging
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

# ⚠️ ВАЖНО: Перевыпусти токен в @BotFather через /revoke и вставь новый!
BOT_TOKEN = "8872040047:AAFDwAi6atIR4_I-rGE2Ky_-55hx24EUSHM"

# ID группы админов (ОБЯЗАТЕЛЬНО с -100 в начале!)
ALLOWED_GROUP_ID = -5484524824

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

# Словари для связи сообщений (переписка)
user_to_admin_msg = {}
admin_msg_to_user = {}

# База данных городов
CITIES = {
    "Москва": {"coords": (55.7558, 37.6173), "link": "https://t.me/MskChat42"},
    "Санкт-Петербург": {"coords": (59.9342, 30.3351), "link": "https://t.me/SpbChat42"},
    "Калининград": {"coords": (54.7104, 20.4522), "link": "https://t.me/+6vdXRB4zF1FkZDZi"},
    "Минск": {"coords": (53.9006, 27.5590), "link": "https://t.me/Minsk422"},
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
}


# --- СОСТОЯНИЯ (FSM) ---
class UserFlow(StatesGroup):
    selecting_city = State()
    waiting_location_check = State()
    waiting_location_ticket = State()


# --- КЛАВИАТУРЫ ---
def get_cities_keyboard():
    buttons = []
    cities_list = list(CITIES.keys())
    for i in range(0, len(cities_list), 2):
        row = [KeyboardButton(text=cities_list[i])]
        if i + 1 < len(cities_list):
            row.append(KeyboardButton(text=cities_list[i + 1]))
        buttons.append(row)

    buttons.append([KeyboardButton(text="❌ Моего города здесь нет")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


location_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📍 Поделиться местоположением", request_location=True)],
        [KeyboardButton(text="⬅️ Назад")]
    ],
    resize_keyboard=True
)


# --- МИДЛВАРЬ ДЛЯ ПРОВЕРКИ ГРУППЫ ---
@dp.message.middleware()
async def check_group_middleware(handler, event: types.Message, data):
    if event.chat.type in ["group", "supergroup"]:
        if event.chat.id != ALLOWED_GROUP_ID:
            await event.chat.leave()
            return
    return await handler(event, data)


# --- СТАРТ И ВЫБОР ГОРОДА ---

@dp.message(CommandStart(), F.chat.type == "private")
@dp.message(F.text == "⬅️ Назад", F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(UserFlow.selecting_city)

    user_name = escape(message.from_user.first_name)
    await message.answer(
        f"Привет, {user_name}!\n"
        "Выберите город, в котором вы живёте, чтобы мы могли подобрать его:\n\n"
        "Сделано @g0sting",
        reply_markup=get_cities_keyboard()
    )


# --- СЦЕНАРИЙ 1: ВЫБОР ИЗВЕСТНОГО ГОРОДА ---

@dp.message(UserFlow.selecting_city, F.text.in_(CITIES.keys()))
async def city_selected(message: types.Message, state: FSMContext):
    selected_city = message.text
    await state.update_data(chosen_city=selected_city)
    await state.set_state(UserFlow.waiting_location_check)

    await message.answer(
        f"Вы выбрали город: <b>{selected_city}</b>.\n"
        "Просим скинуть ваше местоположение для проверки.",
        reply_markup=location_kb,
        parse_mode="HTML"
    )


@dp.message(UserFlow.waiting_location_check, F.location)
async def check_location_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chosen_city = data.get("chosen_city")

    user_coords = (message.location.latitude, message.location.longitude)
    target_coords = CITIES[chosen_city]["coords"]

    # Проверка расстояния (радиус 100 км)
    distance = great_circle(user_coords, target_coords).kilometers

    if distance <= 100:
        # Локация совпала
        city_link = CITIES[chosen_city]["link"]
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Войти в чат ({chosen_city})", url=city_link)],
            [InlineKeyboardButton(text="Что-то не так...",
                                  callback_data=f"something_wrong:{message.location.latitude}:{message.location.longitude}")]
        ])

        await message.answer(
            f"✅ Геолокация подтверждена! Вы находитесь в районе города <b>{chosen_city}</b>.",
            reply_markup=inline_kb,
            parse_mode="HTML"
        )
        await state.clear()
    else:
        # Локация не совпала
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Обратиться к администратору",
                                  callback_data=f"req:{message.location.latitude}:{message.location.longitude}")]
        ])

        await message.answer(
            f"Извините, но кажется вы находитесь не в городе <b>{chosen_city}</b>.\n"
            f"(Расстояние от города порядка {round(distance)} км).",
            reply_markup=inline_kb,
            parse_mode="HTML"
        )


# --- СЦЕНАРИЙ 2: "МОЕГО ГОРОДА ЗДЕСЬ НЕТ" ---

@dp.message(UserFlow.selecting_city, F.text == "❌ Моего города здесь нет")
async def city_not_found(message: types.Message, state: FSMContext):
    await state.set_state(UserFlow.waiting_location_ticket)
    await message.answer(
        "Просим скинуть ваше местоположение для того, чтобы администратор нашёл самый подходящий вариант.",
        reply_markup=location_kb
    )


@dp.message(UserFlow.waiting_location_ticket, F.location)
async def process_ticket_location(message: types.Message, state: FSMContext):
    lat = round(message.location.latitude, 4)
    lon = round(message.location.longitude, 4)

    # Отправляем тикет админу
    await send_ticket_to_admins(message.from_user, lat, lon)

    await message.answer(
        "Ваш запрос отправлен в администрацию, ждите ⏳",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.clear()


# --- ОБРАБОТКА ИНЛАЙН-КНОПОК ПОЛЬЗОВАТЕЛЯ ---

@dp.callback_query(F.data.startswith("something_wrong:"))
async def something_wrong_handler(callback: types.CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await send_ticket_to_admins(callback.from_user, lat, lon)
    await callback.message.edit_text("Ваш запрос отправлен в администрацию, ждите ⏳")
    await callback.answer()


# --- ВЫНОСНАЯ ФУНКЦИЯ ОТПРАВКИ ТИКЕТА АДМИНАМ ---

async def send_ticket_to_admins(user: types.User, lat, lon):
    username = f"@{user.username}" if user.username else "нет юзернейма"
    full_name_safe = escape(user.full_name)
    yandex_maps_link = f"https://yandex.ru/maps/?pt={lon},{lat}&z=10&l=map"

    admin_text = (
        f"🚨 <b>Новый тикет от пользователя!</b>\n\n"
        f"👤 Пользователь: {full_name_safe}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🔗 Ссылка: {username}\n"
        f"🌍 Координаты: <code>{lat}, {lon}</code>\n"
        f"🗺 <a href='{yandex_maps_link}'>Посмотреть на Яндекс Картах</a>\n\n"
        f"💬 <i>Ответьте на это сообщение (Reply), чтобы написать пользователю!</i>\n\n"
        f"👇 <b>Выберите город для выдачи или отклоните:</b>"
    )

    buttons = []
    cities_keys = list(CITIES.keys())
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


# ОБРАБОТКА КНОПКИ "Обратиться к администратору" ИЗ СООБЩЕНИЯ О НЕОБНАРУЖЕНИИ
@dp.callback_query(F.data.startswith("req:"))
async def req_callback_handler(callback: types.CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await send_ticket_to_admins(callback.from_user, lat, lon)
    await callback.message.edit_text("Ваш запрос отправлен в администрацию, ждите ⏳")
    await callback.answer()


# --- ХЕНДЛЕРЫ АДМИНИСТРИРОВАНИЯ ---

@dp.callback_query(F.data.startswith("app:"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.message.chat.id != ALLOWED_GROUP_ID:
        await callback.answer("Работает только в группе админов!", show_alert=True)
        return

    _, user_id_str, city_idx_str = callback.data.split(":")
    target_user_id = int(user_id_str)

    cities_keys = list(CITIES.keys())
    city_name = cities_keys[int(city_idx_str)]
    city_link = CITIES[city_name]["link"]
    admin_name = escape(callback.from_user.first_name)

    try:
        user_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Войти в чат ({city_name})", url=city_link)]
        ])
        await bot.send_message(
            chat_id=target_user_id,
            text=f"🎉 Администратор подобрал для тебя чат города <b>{city_name}</b>!",
            reply_markup=user_kb,
            parse_mode="HTML"
        )

        original_text = callback.message.html_text.split("💬")[0]
        await callback.message.edit_text(
            f"{original_text}\n\n✅ <b>Тикет закрыт (Одобрено)</b>\n"
            f"👤 Ответил: {admin_name}\n"
            f"🏙 Выдан город: <b>{city_name}</b>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        await callback.answer(f"Ссылка на {city_name} отправлена!")

    except Exception as e:
        logging.error(f"Ошибка отправки пользователю {target_user_id}: {e}")
        await callback.answer("⚠️ Не удалось отправить (пользователь заблокировал бота).", show_alert=True)


@dp.callback_query(F.data.startswith("rej:"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.message.chat.id != ALLOWED_GROUP_ID:
        await callback.answer("Работает только в группе админов!", show_alert=True)
        return

    _, user_id_str = callback.data.split(":")
    target_user_id = int(user_id_str)
    admin_name = escape(callback.from_user.first_name)

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text="😔 К сожалению, администраторы не смогли подобрать чат по вашей заявке."
        )
    except Exception as e:
        logging.error(f"Ошибка отправки отказа: {e}")

    original_text = callback.message.html_text.split("💬")[0]
    await callback.message.edit_text(
        f"{original_text}\n\n❌ <b>Тикет закрыт (Отклонено)</b>\n"
        f"👤 Ответил: {admin_name}",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer("Тикет отклонен.")


# --- ПЕРЕПИСКА МЕЖДУ АДМИНОМ И ПОЛЬЗОВАТЕЛЕМ ---

@dp.message(F.chat.id == ALLOWED_GROUP_ID, F.reply_to_message)
async def reply_from_group(message: types.Message):
    reply_msg_id = message.reply_to_message.message_id
    target_user_id = admin_msg_to_user.get(reply_msg_id)

    if target_user_id:
        try:
            if message.text:
                await bot.send_message(
                    chat_id=target_user_id,
                    text=f"📩 <b>Сообщение от администратора:</b>\n\n{escape(message.text)}",
                    parse_mode="HTML"
                )
            else:
                await message.copy_to(chat_id=target_user_id)
                await bot.send_message(
                    chat_id=target_user_id,
                    text="👆 <i>(Сообщение выше от администратора)</i>",
                    parse_mode="HTML"
                )

            admin_msg_to_user[message.message_id] = target_user_id
            await message.react([types.ReactionTypeEmoji(emoji="👍")])

        except Exception as e:
            logging.error(f"Ошибка при пересылке: {e}")
            await message.reply("⚠️ Не удалось доставить сообщение пользователю.")


@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def user_text_message(message: types.Message):
    user_id = message.from_user.id
    admin_msg_id = user_to_admin_msg.get(user_id)

    if admin_msg_id:
        try:
            sent_msg = await message.copy_to(
                chat_id=ALLOWED_GROUP_ID,
                reply_to_message_id=admin_msg_id
            )
            admin_msg_to_user[sent_msg.message_id] = user_id
            await message.answer("✉️ Сообщение передано администраторам!")
        except Exception as e:
            logging.error(f"Ошибка пересылки: {e}")
            await message.answer("⚠️ Не удалось отправить сообщение администраторам.")
    else:
        await message.answer("Напишите /start для начала работы с ботом.")


# --- ЗАПУСК БОТА ---
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
