import os
import json
import logging
import asyncio
from pathlib import Path

import httpx
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardButton,
    CallbackQuery,
    ChatMemberUpdated,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

RSCRIPT_API_KEY = os.getenv(
    "RSCRIPT_API_KEY",
    "rsc_live_rooek3E4bE0JQGuQp1DcNT7EqriXJ8ng",
)
API_URL = "https://api.rscripts.net/v2/scripts"
PORT = int(os.getenv("PORT", "8080"))
DATA_FILE = Path("bot_data.json")

DEFAULT_ADMINS = [8340049069, 1593210161]
DEFAULT_CHATS = [-1004391608577]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("histro-bot")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================
# STORAGE
# =========================
def default_data():
    return {
        "admins": DEFAULT_ADMINS.copy(),
        "chats": DEFAULT_CHATS.copy(),
    }

def load_data():
    if not DATA_FILE.exists():
        data = default_data()
        save_data(data)
        return data

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        admins = [int(x) for x in raw.get("admins", DEFAULT_ADMINS)]
        chats = [int(x) for x in raw.get("chats", DEFAULT_CHATS)]

        # Гарантируем наличие стартовых админов/чата
        for admin_id in DEFAULT_ADMINS:
            if admin_id not in admins:
                admins.append(admin_id)
        for chat_id in DEFAULT_CHATS:
            if chat_id not in chats:
                chats.append(chat_id)

        data = {"admins": admins, "chats": chats}
        save_data(data)
        return data
    except Exception as e:
        logger.error("Failed to load data: %s", e)
        data = default_data()
        save_data(data)
        return data

def save_data(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)

DATA = load_data()

def is_admin(user_id: int) -> bool:
    return int(user_id) in DATA["admins"]

def is_allowed_chat(chat_id: int) -> bool:
    return int(chat_id) in DATA["chats"]

# =========================
# RSCRIPT API
# =========================
async def fetch_scripts(query: str):
    headers = {"Authorization": f"Bearer {RSCRIPT_API_KEY}"}
    params = {"q": query, "page": 1, "limit": 5}

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(API_URL, headers=headers, params=params)
            if response.status_code != 200:
                logger.error("RScript API %s: %s", response.status_code, response.text)
                return None
            return response.json()
        except Exception as e:
            logger.error("RScript request failed: %s", e)
            return None

# =========================
# ADMIN KEYBOARD
# =========================
def admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="👤 Админы", callback_data="adm:list_admins"),
        InlineKeyboardButton(text="💬 Чаты", callback_data="adm:list_chats"),
    )
    kb.row(
        InlineKeyboardButton(text="➕ Админ", callback_data="adm:add_admin"),
        InlineKeyboardButton(text="➖ Админ", callback_data="adm:del_admin"),
    )
    kb.row(
        InlineKeyboardButton(text="➕ Чат", callback_data="adm:add_chat"),
        InlineKeyboardButton(text="➖ Чат", callback_data="adm:del_chat"),
    )
    kb.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:home"))
    return kb.as_markup()

def admin_home_text():
    return (
        "<b>🛠 Admin Panel</b>\n\n"
        f"👑 Админов: <code>{len(DATA['admins'])}</code>\n"
        f"💬 Чатов: <code>{len(DATA['chats'])}</code>\n\n"
        "Команды:\n"
        "<code>/addadmin ID</code>\n"
        "<code>/deladmin ID</code>\n"
        "<code>/addchat ID</code>\n"
        "<code>/delchat ID</code>\n"
        "<code>/list</code>\n\n"
        "Или используй кнопки ниже."
    )

# pending actions: user_id -> action
PENDING = {}

# =========================
# AUTO-LEAVE FOREIGN CHATS
# =========================
@dp.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    chat_id = update.chat.id

    # В личке не выходим
    if update.chat.type == "private":
        return

    if not is_allowed_chat(chat_id):
        logger.info("Leave unauthorized chat: %s", chat_id)
        try:
            await bot.leave_chat(chat_id)
        except Exception as e:
            logger.error("leave_chat failed: %s", e)

# =========================
# USER COMMANDS
# =========================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type != "private" and not is_allowed_chat(message.chat.id):
        return

    text = (
        "👋 <b>RScript Search Bot</b>\n\n"
        "Команда поиска:\n"
        "<code>/search Blox Fruits</code>\n\n"
        "Поиск работает только в разрешённых чатах."
    )
    if is_admin(message.from_user.id):
        text += "\n\nАдминам: <code>/admin</code>"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("search"))
async def cmd_search(message: types.Message, command: CommandObject):
    # Только разрешённые чаты (группы/супергруппы)
    if message.chat.type in {"group", "supergroup"}:
        if not is_allowed_chat(message.chat.id):
            return
    else:
        # В личке разрешаем только админам (удобно тестировать)
        if not is_admin(message.from_user.id):
            await message.answer("❌ Поиск доступен только в разрешённой группе.")
            return

    if not command.args:
        await message.answer(
            "❌ Укажи название на английском.\n"
            "Пример: <code>/search Blox Fruits</code>",
            parse_mode="HTML",
        )
        return

    query = command.args.strip()
    status = await message.answer(
        f"🔎 Ищу: <b>{query}</b>...",
        parse_mode="HTML",
    )

    data = await fetch_scripts(query)
    scripts = (data or {}).get("scripts") or []

    if not scripts:
        await status.edit_text(
            f"❓ Ничего не найдено по <code>{query}</code>",
            parse_mode="HTML",
        )
        return

    await status.delete()

    for script in scripts:
        title = script.get("title", "No Title")
        game = script.get("game", "Unknown")
        patched = bool(script.get("isPatched"))
        status_text = "🔴 Patched" if patched else "🟢 Working"
        slug = script.get("slug") or ""

        caption = (
            f"📜 <b>{title}</b>\n"
            f"🎮 Game: {game}\n"
            f"🛠 Status: {status_text}"
        )

        kb = InlineKeyboardBuilder()
        if slug:
            kb.row(
                InlineKeyboardButton(
                    text="📥 Open RScripts",
                    url=f"https://rscripts.net/script/{slug}",
                )
            )

        image = script.get("image")
        try:
            if image:
                await message.answer_photo(
                    photo=image,
                    caption=caption,
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    caption,
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML",
                )
        except Exception:
            await message.answer(
                caption,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )

# =========================
# ADMIN COMMANDS
# =========================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return

    await message.answer(
        admin_home_text(),
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    admins = "\n".join(f"• <code>{x}</code>" for x in DATA["admins"]) or "—"
    chats = "\n".join(f"• <code>{x}</code>" for x in DATA["chats"]) or "—"
    await message.answer(
        f"<b>👑 Admins</b>\n{admins}\n\n<b>💬 Chats</b>\n{chats}",
        parse_mode="HTML",
    )

@dp.message(Command("addadmin"))
async def cmd_addadmin(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    if not command.args:
        await message.answer("Пример: <code>/addadmin 123456789</code>", parse_mode="HTML")
        return
    try:
        new_id = int(command.args.strip())
    except ValueError:
        await message.answer("❌ ID 
