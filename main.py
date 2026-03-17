# You will need to install the following libraries:
# pip install aiogram aiosqlite

import asyncio
import logging
import sqlite3
import secrets
import pytz
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration (Update these values) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_FILE = os.getenv("DB_FILE", "database.db")
VOTE_REVIEW_CHAT_ID = int(os.getenv("VOTE_REVIEW_CHAT_ID", "-1003011914795"))
WITHDRAW_REVIEW_CHAT_ID = int(os.getenv("WITHDRAW_REVIEW_CHAT_ID", "-1002588901573"))

# --- Database Connection and Setup ---
try:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    print("ULANDI")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            balance TEXT,
            status TEXT,
            referal TEXT,
            outing TEXT,
            username TEXT,
            full_name TEXT,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Try to add missing columns for backward compatibility
    for col_info in [("username", "TEXT"), ("full_name", "TEXT"), ("registered_at", "TEXT DEFAULT CURRENT_TIMESTAMP")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_info[0]} {col_info[1]}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ovozlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            phone_number TEXT UNIQUE,
            time TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            system TEXT,
            account_number TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

except sqlite3.Error as err:
    print(f"ULANMADI: {err}")
    exit()

# --- Aiogram Router for Handlers ---
router = Router()

# --- Aiogram FSM States ---
class VoteState(StatesGroup):
    waiting_for_phone = State()

class WithdrawState(StatesGroup):
    waiting_for_system = State()
    waiting_for_account = State()
    waiting_for_amount = State()

class AdminState(StatesGroup):
    waiting_for_post = State()
    waiting_for_setting_value = State()

# --- Initial Settings ---
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "min": "5000",
    "user": "MalikovBekzod",
    "url": "https://openbudget.uz/boards/initiatives/initiative/53/925401fa-d03f-458f-8a1a-bd049a448bb2",
    "teleg": "https://t.me/ochiqbudjet_1_bot?start=053457795014",
    "ref": "5000",
    "ovoz": "25000",
    "chan": "-1002968553152",
    "ovozlar": "0"
}

def load_settings():
    current_settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded_settings = json.load(f)
                if isinstance(loaded_settings, dict):
                    current_settings.update(loaded_settings)
            return current_settings
        except Exception as e:
            print(f"Error loading settings: {e}")
            
    # Save default if not exists
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(current_settings, f, indent=4, ensure_ascii=False)
    return current_settings

def save_settings(new_settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving settings: {e}")

settings = load_settings()

# --- Keyboard Layouts ---
def get_panel_keyboard():
    builder = ReplyKeyboardBuilder()
    # builder.row(KeyboardButton(text="📨 Xabar yuborish"))

    builder.row(
        KeyboardButton(text="📊 Statistika"),
        KeyboardButton(text="⚙️ Sozlama")
    )
    builder.row(KeyboardButton(text="🏠 Ortga"))
    return builder.as_markup(resize_keyboard=True)

def get_menu_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        # KeyboardButton(text="🖇️ Taklif qilish"),
        KeyboardButton(text="📮 Ovoz berish")
    )
    builder.row(
        KeyboardButton(text="💵 Hisobim"),
        KeyboardButton(text="📃 To'lovlar")
    )
    builder.row(
        KeyboardButton(text="📑 Yo'riqnoma"),
        KeyboardButton(text="🗣 Adminga bog'lanish")
    )
    return builder.as_markup(resize_keyboard=True)

def get_back_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🏠 Orqaga"))
    return builder.as_markup(resize_keyboard=True)

def get_phone_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📞 Raqamni yuborish", request_contact=True))
    builder.row(KeyboardButton(text="🏠 Orqaga"))
    return builder.as_markup(resize_keyboard=True)

def get_bosh_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="👨‍💻 Panel"))
    return builder.as_markup(resize_keyboard=True)


# --- Helper Functions ---
def get_tashkent_time():
    """Returns the current time in Asia/Tashkent timezone as a string."""
    tz = pytz.timezone('Asia/Tashkent')
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

USERS_JSON_FILE = "users.json"

def sync_user_to_json(user_data_row):
    """Synchronizes a single user's database tuple to the users.json file."""
    if not user_data_row:
        return
        
    users_dict = {}
    if os.path.exists(USERS_JSON_FILE):
        try:
            with open(USERS_JSON_FILE, 'r', encoding='utf-8') as f:
                users_dict = json.load(f)
        except Exception:
            pass

    uid = str(user_data_row[1])
    users_dict[uid] = {
        'id': user_data_row[0],
        'user_id': user_data_row[1],
        'balance': user_data_row[2],
        'status': user_data_row[3],
        'referal': user_data_row[4],
        'outing': user_data_row[5],
    }
    if len(user_data_row) > 6:
        users_dict[uid]['username'] = user_data_row[6]
    if len(user_data_row) > 7:
        users_dict[uid]['full_name'] = user_data_row[7]
    if len(user_data_row) > 8:
        users_dict[uid]['registered_at'] = user_data_row[8]

    try:
        with open(USERS_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_dict, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving to users.json: {e}")

def get_user_data(user_id, tg_user=None):
    """Fetches or creates a user's data from the database."""
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    user_data = cursor.fetchone()
    if not user_data:
        username = tg_user.username if tg_user else None
        full_name = tg_user.full_name if tg_user else None
        
        cursor.execute(
            "INSERT INTO users (user_id, balance, status, referal, outing, username, full_name, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(user_id), '0', 'active', '0', '0', username, full_name, get_tashkent_time())
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
        user_data = cursor.fetchone()
        sync_user_to_json(user_data)
    else:
        # Optionally update username and full_name if they changed
        if tg_user and len(user_data) >= 8:
            if user_data[6] != tg_user.username or user_data[7] != tg_user.full_name:
                cursor.execute(
                    "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                    (tg_user.username, tg_user.full_name, str(user_id))
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
                user_data = cursor.fetchone()
                sync_user_to_json(user_data)
            
    return user_data

def get_user_status(user_id):
    """Checks the user's status."""
    cursor.execute("SELECT status FROM users WHERE user_id = ?", (str(user_id),))
    result = cursor.fetchone()
    return result[0] if result else 'deactive'

def update_user_status(user_id, status):
    """Updates the user's status in the database."""
    cursor.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, str(user_id)))
    conn.commit()


def callback_parts(raw_data: str, expected_parts: int):
    if not raw_data:
        return None
    parts = raw_data.split("=")
    if len(parts) != expected_parts:
        return None
    return parts


# --- Command and Message Handlers ---
@router.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    
    get_user_data(user_id, message.from_user)

    # ref_id = message.text.split()[1] if len(message.text.split()) > 1 else None
    # if ref_id and str(ref_id) != str(user_id):
    #     referrer_data = get_user_data(ref_id)
    #     if referrer_data:
    #         referrer_balance = int(referrer_data[2])
    #         new_balance = referrer_balance + int(settings['ref'])
    #         new_referal_count = int(referrer_data[4]) + 1
    #         cursor.execute(
    #             "UPDATE users SET balance = ?, referal = ? WHERE user_id = ?",
    #             (str(new_balance), str(new_referal_count), str(ref_id))
    #         )
    #         conn.commit()
            
    #         await message.bot.send_message(
    #             chat_id=ref_id,
    #             text=f"👤 <b>Siz <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> ni taklif qildingiz va {settings['ref']} so'm berildi.</b>",
    #             parse_mode=ParseMode.HTML
    #         )
    await message.answer(
        f"<b>❓Qanday ovoz beraman?:</b>\n"
        f"—<i>Pastdagi</i> <b>📮 Ovoz berish</b><i> tugmasini bosing va ovoz bermoqchi bo'lgan telefon raqamingizni namunadagidek yuboring, va sayt orqali yoki telegram orqali ovoz berishni tanlang, ovoz berib bo'lganingizdan keyin, botga qaytib </i><b>✅ Ovoz berdim</b><i> tugmasini bosing. Ovozingiz adminlar tomonidan tez fursatda ko'rib chiqiladi, agar tasdiqlansa hisobingizga pul qo'shiladi.</i>\n\n"
        f"❓<b>Pulni qanday yechib olaman?:</b>\n"
        f"— 💵 <b>Hisobim</b> bo'limiga o'ting va «<b>💰 Pul yechish</b>» tugmasini bosing. To'lov tizimlaridan birini tanlang. Karta raqamingiz yoki telefon raqamingizni kiriting. Administratorimiz hisobingizni to'ldiradi.\n\n"
        f"💰 <b>1 ta ovoz narxi: {settings['ovoz']} so'm</b>\n\n"
        f"🙆‍♂️ <b>Admin:</b> @{settings['user']}",
        parse_mode=ParseMode.HTML
    )

    await message.answer(
        "<b>🎯 OpenBudget botiga xush kelibsiz.\n\n✅ Quyidagi tugmalardan birini tanlang</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu_keyboard()
    )

@router.message(Command(commands=['panel', 'admin']))
async def admin_panel_start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("<b>👨‍💻 Panel:</b>", parse_mode=ParseMode.HTML, reply_markup=get_panel_keyboard())
    else:
        await message.answer("Siz panelga kira olmaysiz.", reply_markup=get_menu_keyboard())

@router.message(lambda message: message.text == "🏠 Ortga")
async def go_to_home(message: Message, state:FSMContext):
    await state.clear()
    await message.answer("<b>🏠 Asosiy menyudasiz:</b>", parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard())


@router.message(lambda message: message.text == "🗣 Adminga bog'lanish")
async def go_to_home(message: Message, state:FSMContext):
    await state.clear()
    await message.answer(f"<b>Bot bo'yicha yoki boshqa murojatlaringiz bo'lsa: @{settings['user']}</b>", parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard())


@router.message(lambda message: message.text == "🏠 Orqaga")
async def go_home(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id == ADMIN_ID:
        await message.answer("<b>🏠 Asosiy menyudasiz:</b>", parse_mode=ParseMode.HTML, reply_markup=get_panel_keyboard())
    else:
        await message.answer("<b>🏠 Asosiy menyudasiz:</b>", parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard())

@router.message(lambda message: message.text == "💵 Hisobim")
async def my_account(message: Message):
    user_data = get_user_data(message.from_user.id, message.from_user)
    db_id = user_data[0]
    balance = user_data[2]
    referal = user_data[4]
    outing = user_data[5]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Pul yechish", callback_data="out"))
    
    await message.answer(
        f"🆔 <b>ID raqamingiz: <code>{db_id}</code>\n"
        f"🎯 Hisobingiz:</b> {balance} so'm\n"
        f"💳 <b>Yechib olingan:</b> {outing} so'm\n"
        f"🙆‍♂️ <b>Referallaringiz:</b> {referal} ta",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

# --- Vote System (FSM) ---
@router.message(lambda message: message.text == "📮 Ovoz berish")
async def vote_request(message: Message, state: FSMContext):
    await message.answer(
        "<b>📞 Telefon raqamingizni kiriting yuboring:\n\n✅ Namuna: +998931234567\n\nYoki pastdagi tugma orqali yuboring.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_phone_keyboard()
    )
    await state.set_state(VoteState.waiting_for_phone)

@router.message(VoteState.waiting_for_phone)
async def process_phone_number(message: Message, state: FSMContext):
    if message.text == "🏠 Orqaga":
        await state.clear()
        if message.from_user.id == ADMIN_ID:
            await message.answer("<b>🏠 Asosiy menyudasiz:</b>", parse_mode=ParseMode.HTML, reply_markup=get_panel_keyboard())
        else:
            await message.answer("<b>🏠 Asosiy menyudasiz:</b>", parse_mode=ParseMode.HTML, reply_markup=get_menu_keyboard())
        return

    if message.contact:
        phone_number = message.contact.phone_number
        if not phone_number.startswith('+'):
            phone_number = "+" + phone_number
    elif message.text:
        phone_number = message.text
    else:
        await message.answer("<b>Matn yoki kontakt yuboring.</b>", parse_mode=ParseMode.HTML, reply_markup=get_phone_keyboard())
        return

    stripped_number = phone_number.replace(" ", "").replace("+", "")

    cursor.execute("SELECT * FROM ovozlar WHERE phone_number = ?", (stripped_number[3:],))
    already_voted = cursor.fetchone() is not None

    if already_voted :
        await message.answer(
            "<b>🚫 Bu raqamdan ovoz berib bo'lingan!\n\n📞 Telefon raqamingizni kiriting:\n\n✅ Namuna: +998931234567</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_phone_keyboard()
        )
    
    elif phone_number.startswith('+99833'):
        await message.answer(
            "<b>🚫 HUMANS raqami qabul qilinmaydi!\n\n📞 Telefon raqamingizni kiriting:\n\n✅ Namuna: +998931234567</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_phone_keyboard()
        )
    
    elif phone_number.startswith('+998') and len(phone_number) == 13 and stripped_number.isdigit():
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="📮 Ovoz berish (Sayt)", url=settings['url'])
        )
        builder.row(
            InlineKeyboardButton(text="📮 Ovoz berish (Telegram)", url=settings['teleg'])
        )
        builder.row(InlineKeyboardButton(text="✅ Ovoz berdim", callback_data=f"ovoz={stripped_number}"))
        
        await message.answer(
            "<b>📞 Telefon raqam qabul qilindi.\n\n📲 Havola orqali kirib ovoz bering</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        await state.clear()
    else:
        await message.answer(
            "<b>📞 Telefon raqamingizni kiriting:\n\n✅ Namuna: +998931234567</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_phone_keyboard()
        )

@router.callback_query(lambda c: c.data and c.data.startswith("ovoz="))
async def handle_vote_submission(call: types.CallbackQuery):
    await call.answer()

    payload = callback_parts(call.data, 2)
    if not payload:
        await call.answer("Xato so'rov", show_alert=True)
        return

    number = payload[1]
    user_id = call.from_user.id

    await call.message.edit_text(
        text=f"📮 <b>So'rovingiz yuborildi.\n📞 Raqam:</b> +{number}\n\n⏰ <i>Administratorlarimiz tez orada tekshirib chiqishadi. Agar tasdiqlansa balansingizga pul qo'shiladi!</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )

    await call.message.answer(
        "<b>🏠 Asosiy menyudasiz:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu_keyboard()
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💸 Ovozni tasdiqlash", callback_data=f"add={user_id}={number}"),
        InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"cancel={user_id}={number}")
    )

    # Capture the exact time the 'Ovoz berdim' button was clicked
    timezone = pytz.timezone('Asia/Tashkent')
    local_time = datetime.now(timezone)
    timestamp_str = local_time.strftime("%d-%m-%Y %H:%M:%S")
    
    await call.bot.send_message(
        chat_id=VOTE_REVIEW_CHAT_ID,
        text=f"📮 <b>Ovoz berganlik haqida ma'lumot:\n\n📞 Raqam:</b> +{number}\n📲 <b>Foydalanuvchi:</b> <a href='tg://user?id={user_id}'>{user_id}</a>\n<b>📅 Vaqt:</b> {timestamp_str}\n\n✅ <b>Quyidagilardan birini tanlang:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cancel="))
async def cancel_vote_confirmation(call: types.CallbackQuery):
    await call.answer()

    payload = callback_parts(call.data, 3)
    if not payload:
        await call.answer("Xato so'rov", show_alert=True)
        return

    user_id = payload[1]
    number = payload[2]

    # Change the review message text directly instead of completely hiding details
    original_text = call.message.text
    if "✅ Quyidagilardan" in original_text:
        new_text = original_text.split("✅ Quyidagilardan")[0].strip() + "\n\n❌ Bekor qilindi"
    else:
        new_text = f"📮 <b>Ovoz berganlik haqida ma'lumot:</b>\n\n📞 <b>Raqam:</b> +{number}\n📲 <b>Foydalanuvchi:</b> {user_id}\n\n❌ <b>Bekor qilindi</b>"

    await call.message.edit_text(new_text, parse_mode=ParseMode.HTML, reply_markup=None)

    await call.message.bot.send_message(
        chat_id=user_id,
        text="❌ Afsuski ovozingiz tasdiqlanmadi,\nEhtimoliy sabab: Bu raqamdan oldin ovoz berilgan",
        reply_markup=get_menu_keyboard()
    )


@router.callback_query(lambda c: c.data and c.data.startswith("add="))
async def approve_vote_confirmation(call: types.CallbackQuery):
    await call.answer()

    payload = callback_parts(call.data, 3)
    if not payload:
        await call.answer("Xato so'rov", show_alert=True)
        return

    user_id = payload[1]
    number = payload[2]

    cursor.execute("INSERT OR IGNORE INTO ovozlar (user_id, phone_number, time) VALUES(?, ?, ?)", (str(user_id), str(number)[3:], get_tashkent_time()))
    if cursor.rowcount == 0:
        await call.message.edit_text(f"⚠️ Allaqachon ko'rib chiqilgan +{number}")
        return

    cursor.execute(
        "UPDATE users SET balance = CAST(balance AS INTEGER) + ? WHERE user_id = ?",
        (int(settings["ovoz"]), str(user_id))
    )
    conn.commit()

    original_text = call.message.text
    if "✅ Quyidagilardan" in original_text:
        new_text = original_text.split("✅ Quyidagilardan")[0].strip() + "\n\n✅ Tasdiqlandi"
    else:
        new_text = f"📮 <b>Ovoz berganlik haqida ma'lumot:</b>\n\n📞 <b>Raqam:</b> +{number}\n📲 <b>Foydalanuvchi:</b> {user_id}\n\n✅ <b>Tasdiqlandi</b>"

    await call.message.edit_text(new_text, parse_mode=ParseMode.HTML, reply_markup=None)

    await call.message.bot.send_message(
        chat_id=user_id,
        text="✅ Ovozingiz qabul qilindi,\n🤗 Balansingizga pul qo'shildi",
        reply_markup=get_menu_keyboard()
    )


# --- Other Handlers ---
# @router.message(lambda message: message.text == "🖇️ Taklif qilish")
# async def referral_link(message: Message):
#     user_id = message.from_user.id
#     user_data = get_user_data(user_id)
#     referral_count = user_data[4]
#     bot_info = await message.bot.get_me()
#     bot_username = bot_info.username

#     referral_url = f"https://t.me/{bot_username}?start={user_id}"
    
#     builder = InlineKeyboardBuilder()
#     builder.row(InlineKeyboardButton(text="🔄 Havolani ulashish", url=f"https://telegram.me/share/url/?url={referral_url}"))
    
#     await message.answer(
#         f"<b>🖇️ Sizning referal havolangiz:\n\n<code>{referral_url}</code>\n\n💰 Har bir referal uchun {settings['ref']} so'm\n🙆‍♂️ Sizning referallaringiz: {referral_count} ta</b>",
#         parse_mode=ParseMode.HTML,
#         reply_markup=builder.as_markup()
#     )

@router.message(lambda message: message.text == "📃 To'lovlar")
async def payment_channel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Kanalga o'tish", url="https://t.me/+4i6In_EHOfg2MGVi"))
    await message.answer("<b>🎯 Bizning bot orqali to'langan barcha to'lovlar isbot kanali:</b>", parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())


@router.message(lambda message: message.text == "📑 Yo'riqnoma")
async def instructions(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👨‍💻 Bot dasturchisi", url=f"https://t.me/MalikovBekzod"))
    await message.answer(
        f"<b>❓Qanday ovoz beraman?:</b>\n"
        f"—<i>Pastdagi</i> <b>📮 Ovoz berish</b><i> tugmasini bosing va ovoz bermoqchi bo'lgan telefon raqamingizni namunadagidek yuboring, va sayt orqali yoki telegram orqali ovoz berishni tanlang, ovoz berib bo'lganingizdan keyin, botga qaytib </i><b>✅ Ovoz berdim</b><i> tugmasini bosing. Ovozingiz adminlar tomonidan tez fursatda ko'rib chiqiladi, agar tasdiqlansa hisobingizga pul qo'shiladi.</i>\n\n"
        f"❓<b>Pulni qanday yechib olaman?:</b>\n"
        f"— 💵 <b>Hisobim</b> bo'limiga o'ting va «<b>💰 Pul yechish</b>» tugmasini bosing. To'lov tizimlaridan birini tanlang. Karta raqamingiz yoki telefon raqamingizni kiriting. Administratorimiz hisobingizni to'ldiradi.\n\n"
        f"\n"
        f"🙆‍♂️ <b>Admin:</b> @{settings['user']}",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

# --- Withdrawal Process (FSM) ---
@router.callback_query(lambda c: c.data == "out")
async def start_withdrawal(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user_data = get_user_data(call.from_user.id, call.from_user)
    balance = int(user_data[2])
    
    if balance > 0:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🇺🇿 Humo/🔵 UzCard", callback_data="y=HUMO"),
        )
        
        builder.row(
            InlineKeyboardButton(text="📞 Paynet", callback_data="y=Paynet")
        )

        builder.row(
            InlineKeyboardButton(text="« Orqaga", callback_data="qayt")
        )

        await call.message.edit_text("<b>📑 Tizimlardan birini tanlang:</b>", parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await state.set_state(WithdrawState.waiting_for_system)
    else:
        await call.answer("🚫 Hisobingizda mablag' yo'q!", show_alert=True)

@router.callback_query(lambda c: c.data.startswith("y="), WithdrawState.waiting_for_system)
async def select_system(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    
    tizim = call.data.split('=')[1]
    
    if tizim == "HUMO":
        send_text = "💳 Karta raqamingizni kiriting:"

    else:
        send_text = "📞 Telefon raqamingizni kiriting:"
    
    await state.update_data(tizim=tizim)
    await call.message.edit_text(f"<b>{send_text}</b>", parse_mode=ParseMode.HTML, reply_markup=None)
    await call.message.answer("<b>❗️<i> Malumotlarni to'g'ri kiriting!</i></b>",parse_mode=ParseMode.HTML, reply_markup=get_back_keyboard())
    await state.set_state(WithdrawState.waiting_for_account)

@router.message(WithdrawState.waiting_for_account)
async def get_withdrawal_account(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("<b>Matn yuboring.</b>", parse_mode=ParseMode.HTML)
        return

    account_number = message.text
    await state.update_data(account_number=account_number)
    
    await message.answer(
        f"<b>❓ Qancha pulingizni yechib olasiz?\n\n📲 Minimal: {settings['min']} so'm</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_keyboard()
    )
    await state.set_state(WithdrawState.waiting_for_amount)

@router.message(WithdrawState.waiting_for_amount)
async def process_withdrawal(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("✍️<b> Raqamlardan foydalaning:</b>", parse_mode=ParseMode.HTML)
        return

    user_id = message.from_user.id
    user_data = get_user_data(user_id, message.from_user)
    current_balance = int(user_data[2])
    
    try:
        amount = int(message.text)
    except (ValueError, TypeError):
        await message.answer("✍️<b> Raqamlardan foydalaning:</b>")
        return

    if amount < int(settings['min']):
        await message.answer(f"🚫 <b>Minimal {settings['min']} so'm!</b>\n\n<i>✍️ Qayta urinib ko'ring:</i>", parse_mode=ParseMode.HTML)
        return
    
    if amount > current_balance:
        await message.answer("🚫 <b>Mablag' yetarli emas!</b>\n\n<i>✍️ Qayta urinib ko'ring:</i>", parse_mode=ParseMode.HTML)
        return

    cursor.execute(
        "UPDATE users SET balance = CAST(balance AS INTEGER) - ? WHERE user_id = ? AND CAST(balance AS INTEGER) >= ?",
        (amount, str(user_id), amount)
    )
    if cursor.rowcount == 0:
        await message.answer("🚫 <b>Mablag' yetarli emas!</b>\n\n<i>✍️ Qayta urinib ko'ring:</i>", parse_mode=ParseMode.HTML)
        return

    conn.commit()

    data = await state.get_data()
    tizim = data.get("tizim")
    account_number = data.get("account_number")

    if not tizim or not account_number:
        await message.answer("🚫 <b>So'rov ma'lumotlari topilmadi. Qayta urinib ko'ring.</b>", parse_mode=ParseMode.HTML)
        await state.clear()
        return

    request_id = secrets.token_urlsafe(8)
    cursor.execute(
        "INSERT INTO withdrawal_requests (id, user_id, system, account_number, amount, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, str(user_id), str(tizim), str(account_number), int(amount), get_tashkent_time())
    )
    conn.commit()
    
    await message.answer(
        f"✅ <b>Pul yechish so'rovingiz yuborildi\n"
        f"📑 To'lov tizimi:</b> {tizim}\n"
        f"💳 <b>Karta:</b> {account_number}\n"
        f"✍️ <b>Miqdor:</b> {amount} so'm\n\n"
        f"⏳ <b><i>Tez orada adminlarimiz pulni to'lab berishadi</i></b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu_keyboard()
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlash va kanalga yuborish", callback_data=f"done={request_id}"),
        InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"no={request_id}")
    )
    await message.bot.send_message(
        chat_id=WITHDRAW_REVIEW_CHAT_ID,
        text=f"✅ <b>Foydalanuvchi pul yechmoqchi\n\n👤 ID:</b> <a href='tg://user?id={user_id}'>{user_id}</a>\n"
             f"📑 <b>To'lov tizimi:</b> {tizim}\n"
             f"💳 <b>Karta:</b> <code>{account_number}</code>\n"
             f"✍️ <b>Miqdor:</b> {amount} so'm",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.clear()

@router.callback_query(lambda c: c.data == "qayt")
async def cancel_withdrawal(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("Operatsiya bekor qilindi.")
    await call.message.answer(
        "<b>🏠 Asosiy menyudasiz:</b>", 
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu_keyboard()
    )
    await state.clear()


# --- Admin Panel ---
@router.message(lambda message: message.text == "📊 Statistika")
async def show_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    cursor.execute("SELECT COUNT(*) FROM ovozlar")
    votes_from_the_bot = cursor.fetchone()[0]
        
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'deactive'")
    deactive_users = cursor.fetchone()[0]
    active_users = total_users - deactive_users
    
    await message.answer(
        f"<b>📊 Bot statistikasi:\n\n📮 Bot orqali berilgan jami ovozlar: {votes_from_the_bot} ta\n👤 Aktiv azolar: {active_users} ta\n"
        f"👤 Tark etganlar: {deactive_users} ta\n👤 Hammasi: {total_users} ta</b>\n",
        parse_mode=ParseMode.HTML,
        reply_markup=get_panel_keyboard()
    )

# @router.message(lambda message: message.text == "📨 Xabar yuborish")
# async def start_broadcast(message: Message, state: FSMContext):
#     if message.from_user.id != ADMIN_ID:
#         return
        
#     builder = InlineKeyboardBuilder()
#     builder.row(InlineKeyboardButton(text="📤 Oddiy", callback_data="send_broadcast"))
#     await message.answer("<b>Yuboriladigan xabar turini tanlang;</b>", parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
#     await state.set_state(AdminState.waiting_for_post)

# @router.callback_query(lambda c: c.data == "send_broadcast")
# async def get_broadcast_message(call: types.CallbackQuery, state: FSMContext):
#     await call.answer()
#     await call.message.edit_text("<b>Xabar matnini kiriting:</b>", parse_mode=ParseMode.HTML, reply_markup=None)
#     await call.message.answer("👨‍💻 Panel", reply_markup=get_bosh_keyboard())
#     await state.set_state(AdminState.waiting_for_post)

# @router.message(AdminState.waiting_for_post)
# async def send_broadcast(message: Message, state: FSMContext):
#     if message.from_user.id != ADMIN_ID:
#         return
        
#     await message.answer("✅ <b>Xabar Yuborish Boshlandi!</b>", parse_mode=ParseMode.HTML, reply_markup=get_bosh_keyboard())
    
#     cursor.execute("SELECT user_id, status FROM users")
#     users = cursor.fetchall()
    
#     sent_count = 0
#     failed_count = 0
    
#     for user_id, status in users:
#         try:
#             await message.bot.copy_message(
#                 chat_id=user_id,
#                 from_chat_id=message.chat.id,
#                 message_id=message.message_id
#             )
#             sent_count += 1
#             if status == 'deactive':
#                  update_user_status(user_id, 'active')
#         except Exception:
#             failed_count += 1
#             update_user_status(user_id, 'deactive')
        
#     await message.answer(
#         f"✅ <b>Yuborildi:</b> {sent_count}\n\n❌ <b>Yuborilmadi:</b> {failed_count}",
#         parse_mode=ParseMode.HTML
#     )
#     await state.clear()


@router.message(lambda message: message.text == "⚙️ Sozlama")
async def set_settings(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="1. Minimal pul yechish", callback_data="set_min"))
    builder.row(InlineKeyboardButton(text="2. Referal narxi", callback_data="set_ref"))
    builder.row(InlineKeyboardButton(text="3. Ovoz berish narxi", callback_data="set_ovoz"))
    builder.row(InlineKeyboardButton(text="4. Ovoz URL - https bilan", callback_data="set_url"))
    builder.row(InlineKeyboardButton(text="5. To'lovlar kanali ID -100 bilan", callback_data="set_chan"))
    builder.row(InlineKeyboardButton(text="6. Admin username @siz", callback_data="set_user"))
    builder.row(InlineKeyboardButton(text="7. Telegram Ovoz URL", callback_data="set_teleg"))
    await message.answer("<b>✍️ Qaysi birini tahrirlaysiz?</b>", parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data.startswith("set_"))
async def get_new_setting_value(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
        
    await call.answer()
    
    setting_key = call.data.split('_')[1]
    await state.update_data(setting_key=setting_key)
    
    await call.message.edit_text("✍️ <b>Yangi qiymatni kiriting:</b>", parse_mode=ParseMode.HTML, reply_markup=None)
    await call.message.answer("👨‍💻 Panel", reply_markup=get_bosh_keyboard())
    await state.set_state(AdminState.waiting_for_setting_value)


@router.message(AdminState.waiting_for_setting_value)
async def save_new_setting(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
        
    data = await state.get_data()
    setting_key = data.get('setting_key')
    
    if setting_key:
        new_value = message.text
        settings[setting_key] = new_value
        save_settings(settings)
        await message.answer(f"<b>✅ Saqlandi: {new_value}</b>", parse_mode=ParseMode.HTML, reply_markup=get_panel_keyboard())
    else:
        await message.answer("Xatolik yuz berdi. Qayta urinib ko'ring.")
    
    await state.clear()

@router.callback_query(lambda c: c.data and c.data.startswith(("done=", "no=")))
async def admin_complete_or_cancel_withdrawal(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
        
    await call.answer()
    payload = callback_parts(call.data, 2)
    if not payload:
        await call.answer("Xato so'rov", show_alert=True)
        return

    action = payload[0]
    request_id = payload[1]

    cursor.execute(
        "SELECT user_id, system, account_number, amount, status FROM withdrawal_requests WHERE id = ?",
        (request_id,)
    )
    request_row = cursor.fetchone()
    if not request_row:
        await call.answer("So'rov topilmadi", show_alert=True)
        return

    user_id, tizim, karta, miqdor, request_status = request_row
    if request_status != 'pending':
        await call.answer("Bu so'rov allaqachon yakunlangan", show_alert=True)
        return

    if action == 'done':
        cursor.execute("UPDATE withdrawal_requests SET status = 'done' WHERE id = ? AND status = 'pending'", (request_id,))
        if cursor.rowcount == 0:
            await call.answer("Bu so'rov allaqachon yakunlangan", show_alert=True)
            return

        cursor.execute(
            "UPDATE users SET outing = CAST(outing AS INTEGER) + ? WHERE user_id = ?",
            (int(miqdor), str(user_id))
        )
        conn.commit()
        
        # Keep details and append approved status
        new_text = f"✅ <b>Foydalanuvchi pul yechmoqchi\n\n👤 ID:</b> {user_id}\n📑 <b>To'lov tizimi:</b> {tizim}\n💳 <b>Karta:</b> {karta}\n✍️ <b>Miqdor:</b> {miqdor} so'm\n\n✅ <b>To'landi</b>"
        await call.message.edit_text(new_text, parse_mode=ParseMode.HTML, reply_markup=None)

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=f"📮 Ovoz berish", url=f"https://t.me/open_budget_mahalla_bot"))
        
        await call.bot.send_message(
            chat_id=settings['chan'],
            text=f"📑 <b>Foydalanuvchi puli to'lab berildi\n\n👤 ID:</b> <a href='tg://user?id={user_id}'>{call.from_user.full_name}</a>\n"
                 f"📑 <b>To'lov tizimi:</b> {tizim}\n"
                 f"💳 <b>Karta:</b> <tg-spoiler>{karta[:4]+'******'+karta[12:] if len(karta) == 16 else karta[:6]+'**'+karta[8:]}</tg-spoiler>\n"
                 f"✍️ <b>Miqdor:</b> {miqdor} so'm\n\n<b>🎯 Xolat:</b> Muvaffaqiyatli\n\n"
                 f" <b>Ovoz berish boti:</b> @open_budget_mahalla_bot",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
        await call.bot.send_message(
            chat_id=user_id,
            text=f"<b>✅ Sizning so'rovingiz tasdiqlandi!\n\n📲 Kartangizga {miqdor} so'm solindi!</b>",
            parse_mode=ParseMode.HTML
        )

    elif action == 'no':
        cursor.execute("UPDATE withdrawal_requests SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (request_id,))
        if cursor.rowcount == 0:
            await call.answer("Bu so'rov allaqachon yakunlangan", show_alert=True)
            return

        cursor.execute(
            "UPDATE users SET balance = CAST(balance AS INTEGER) + ? WHERE user_id = ?",
            (int(miqdor), str(user_id))
        )
        conn.commit()
        
        # Keep details and append cancelled status
        new_text = f"✅ <b>Foydalanuvchi pul yechmoqchi\n\n👤 ID:</b> {user_id}\n📑 <b>To'lov tizimi:</b> {tizim}\n💳 <b>Karta:</b> {karta}\n✍️ <b>Miqdor:</b> {miqdor} so'm\n\n❌ <b>To'lov bekor qilindi</b>"
        await call.message.edit_text(new_text, parse_mode=ParseMode.HTML, reply_markup=None)
        
        await call.bot.send_message(
            chat_id=user_id,
            text="❌ <b>So'rovingiz bekor qilindi, pulingiz qaytarilmadi!</b>",
            parse_mode=ParseMode.HTML
        )

# --- Main function to run the bot ---
async def main():
    logging.basicConfig(level=logging.INFO)
    dp = Dispatcher()
    dp.include_router(router)
    
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
