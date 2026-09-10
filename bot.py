import os
import logging
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiohttp import web

# --- ДАННЫЕ ---
# Токен бота лучше передать через Environment Variables в Render (ключ BOT_TOKEN)
TOKEN = os.getenv("BOT_TOKEN")
# Твой API ключ RScript
RSCRIPT_API_KEY = "rsc_live_rooek3E4bE0JQGuQp1DcNT7EqriXJ8ng"
API_URL = "https://api.rscripts.net/v2/scripts"
# Порт для Render (обязательно для Web Service)
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ЛОГИКА API ---
async def search_scripts(query: str):
    headers = {"Authorization": f"Bearer {RSCRIPT_API_KEY}"}
    params = {"q": query, "page": 1, "limit": 6}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(API_URL, headers=headers, params=params)
            return r.json() if r.status_code == 200 else None
        except Exception as e:
            logging.error(f"Search error: {e}")
            return None

# --- ХЕНДЛЕРЫ БОТА ---
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🦾 <b>RScript Search Bot</b> запущен.\nОтправь название игры, чтобы найти читы.", parse_mode="HTML")

@dp.message(F.text)
async def handle_msg(message: types.Message):
    query = message.text
    msg = await message.answer(f"🔎 Ищу скрипты для <code>{query}</code>...", parse_mode="HTML")
    
    data = await search_scripts(query)
    if not data or not data.get("scripts"):
        await msg.edit_text("❌ Ничего не найдено.")
        return

    await msg.delete()
    for s in data["scripts"]:
        # Собираем инфо о скрипте
        title = s.get("title", "No Title")
        game = s.get("game", "N/A")
        status = "🟢 Safe/Work" if not s.get("isPatched") else "🔴 Patched"
        
        txt = f"📜 <b>{title}</b>\n🎮 Игра: {game}\n🛠 Статус: {status}"
        
        kb = InlineKeyboardBuilder()
        url = f"https://rscripts.net/script/{s.get('slug')}"
        kb.row(InlineKeyboardButton(text="📥 Get Script", url=url))
        
        img = s.get("image")
        if img:
            try:
                await message.answer_photo(photo=img, caption=txt, reply_markup=kb.as_markup(), parse_mode="HTML")
            except:
                await message.answer(txt, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await message.answer(txt, reply_markup=kb.as_markup(), parse_mode="HTML")

# --- СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (RENDER) ---
# Render убьет процесс, если он не откроет порт и не будет отвечать на запросы.
async def health_check(request):
    return web.Response(text="Bot Alive")

async def run_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- MAIN ---
async def main():
    # Запускаем и веб-сервер, и бота одновременно
    await asyncio.gather(
        run_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
