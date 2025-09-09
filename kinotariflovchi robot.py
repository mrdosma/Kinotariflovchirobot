#Aiogram 3 kino tariflovchi (movie describer) bot

#Til: O‘zbekcha | Framework: Aiogram 3 | Python 3.10+

#Muallif: t.me/Aytishnikman
#Portfolio : t.me/dmu_porfolio

#-----------------------------------------------

#FUNKSIYALAR

#- /start, /help, /about — tezkor buyruqlar

#- /kino <nomi> — film haqida qisqa ma'lumot

#- Inline rejim (@bot_username <nomi>) — chatdan chiqmay qidirish

#- Deep-link: https://t.me/<bot_username>?start=Inception

#- OMDb API (ixtiyoriy). API bo'lmasa, ichki kichik ma'lumotlar bazasiga tayanadi

#- Xatolarni ushlash, loglar, rate-limitdan ehtiyotkor foydalanish

#-----------------------------------------------

import os
import asyncio
import logging
from typing import Optional, Dict, Any
#import os import asyncio import logging from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F from aiogram.enums import ParseMode from aiogram.filters import Command, CommandObject from aiogram.types import ( Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, )

#HTTP so'rovlar uchun

try: import httpx except ImportError: httpx = None  # foydalanuvchi 'pip install httpx' qilmaguncha ishlamaydi

#------------------- Sozlamalar -------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "8413767557:AAFslk-Ej9KRX3XgU5vHArRErr348HQkcGs")

 TMDB_API_KEY = os.getenv("https://api.themoviedb.org/3/movie/550?api_key=ca4087e281f248bdc78943a48c41f90f")  # ixtiyoriy #TMDB_API_KEY

logging.basicConfig( level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s", ) logger = logging.getLogger("kino-bot")

#Kichik ichki ma'lumotlar bazasi (fallback)

LOCAL_MOVIES = { "inception": { "title": "Inception (2010)", "plot": "Dom Kobb tushlar ichida g'oya o'g'irlash bo'yicha mutaxassis. Uga buning aksi — g'oya joylash topshirig'i beriladi.", "rating": "8.8/10 (IMDb)", }, "interstellar": { "title": "Interstellar (2014)", "plot": "Insoniyatni qutqarish uchun kosmik ekspeditsiya vaqt va makon chegaralarini bosib o'tadi.", "rating": "8.6/10 (IMDb)", }, "matrix": { "title": "The Matrix (1999)", "plot": "Neo haqiqat va simulyatsiya o'rtasidagi chegarani kashf etadi va qarshilikka qo'shiladi.", "rating": "8.7/10 (IMDb)", }, "godfather": { "title": "The Godfather (1972)", "plot": "Korleone oilasining kuch, sadoqat va xiyonat haqidagi klassik sagasi.", "rating": "9.2/10 (IMDb)", }, "fight club": { "title": "Fight Club (1999)", "plot": "Nomuayyan hikoyachi va Tyler Durden yashirin jang klubi orqali tizimga qarshi borishadi.", "rating": "8.8/10 (IMDb)", }, }

#------------------- OMDb yordamchi -------------------

async def fetch_movie_from_omdb(title: str) -> Optional[Dict[str, Any]]: """OMDb API orqali film ma'lumotini olish. OMDB_API_KEY bo'lmasa None qaytaradi.""" if not TMDB_API_KEY: return None if httpx is None: logger.warning("httpx o'rnatilmagan. 'pip install httpx' qiling.") return None

params = {"t": title, "apikey": TMDB_API_KEY, "plot": "short"}
try:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://www.themoviedb.org/", params=params)
        data = r.json()
        if data.get("Response") == "True":
            return {
                "title": f"{data.get('Title')} ({data.get('Year')})",
                "plot": data.get("Plot") or "Syujet topilmadi.",
                "rating": (data.get("imdbRating") and f"{data['imdbRating']}/10 (IMDb)") or "Bahosi mavjud emas",
            }
except Exception as e:
    logger.exception("OMDb so'rovida xato: %s", e)
return None

#------------------- Formatlash -------------------

def format_movie_card(movie: Dict[str, Any]) -> str: title = movie.get("title", "Noma'lum nom") plot = movie.get("plot", "Ma'lumot topilmadi") rating = movie.get("rating", "—") return ( f"<b>{title}</b>\n" f"<i>Bahosi:</i> {rating}\n\n" f"<b>Qisqacha:</b> {plot}" )

async def lookup_movie(title: str) -> Optional[Dict[str, Any]]: # Avval OMDb, bo'lmasa lokal info = await fetch_movie_from_omdb(title) if info: return info # Lokal fallback (case-insensitive) key = title.strip().lower() return LOCAL_MOVIES.get(key)

#------------------- Bot va dispatcher -------------------

dp = Dispatcher()

@dp.message(Command("start")) async def cmd_start(message: Message, command: CommandObject): payload = command.args  # deep-link orqali keldi: /start Inception text = ( "Salom! 👋\n\n" "Men kino tariflovchi botman. Film nomini yuboring yoki /kino buyrug'idan foydalaning.\n\n" "Misollar:\n" "• <code>/kino Inception</code>\n" "• <code>/kino Interstellar</code>\n\n" "Inline ham ishlaydi: chatga <code>@bot_username Inception</code> deb yozing." ) if payload: # agar /start ga film nomi biriktirilgan bo'lsa — darhol chiqaramiz info = await lookup_movie(payload) if info: text = format_movie_card(info) await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("help")) async def cmd_help(message: Message): text = ( "Yordam:\n\n" "• <code>/start</code> — Boshlash\n" "• <code>/help</code> — Yordam\n" "• <code>/about</code> — Bot haqida\n" "• <code>/kino <nomi></code> — Film ma'lumoti (masalan: <code>/kino Matrix</code>)\n\n" "Inline: <code>@bot_username Matrix</code>\n" "Deep-link: <code>https://t.me/bot_username?start=Inception</code>\n\n" "OMDb API kaliti bo'lsa, ma'lumotlar yangilanadi. Aks holda, ichki bazaga tayanadi." ) await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("about")) async def cmd_about(message: Message): text = ( "📽️ <b>Kino tariflovchi bot</b>\n" "• Framework: Aiogram 3\n" "• Til: O‘zbekcha\n" "• Muallif: Siz 😊\n\n" "Kod GitHub'ga qo'yish, Docker/Termux'da ishga tushirish uchun tayyor. OMDb integratsiyasi ixtiyoriy." ) await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("kino")) async def cmd_kino(message: Message, command: CommandObject): if not command.args: await message.reply("Iltimos, film nomini yozing. Masalan: /kino Inception") return query = command.args info = await lookup_movie(query) if info: await message.answer(format_movie_card(info), parse_mode=ParseMode.HTML) else: await message.answer( "Kechirasiz, bu nom bo'yicha ma'lumot topilmadi. \n" "Boshqa nom bilan urinib ko'ring yoki OMDb API kalitini sozlang.")

#------------------- Inline rejim -------------------

@dp.inline_query() async def inline_handler(query: InlineQuery): q = (query.query or "").strip() results = []

# Agar foydalanuvchi hali hech narsa yozmagan bo'lsa — bir nechta tayyor takliflar
suggestions = ["Inception", "Interstellar", "Matrix", "Godfather", "Fight Club"]
candidates = suggestions if not q else [q]

for idx, title in enumerate(candidates, start=1):
    info = await lookup_movie(title)
    if not info:
        # Agar topilmasa ham placeholder natija
        info = {"title": title, "plot": "Natija topilmadi", "rating": "—"}
    text = format_movie_card(info)
    results.append(
        InlineQueryResultArticle(
            id=str(idx),
            title=info.get("title", title),
            description=info.get("plot", ""),
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            ),
        )
    )

await query.answer(results, is_personal=True, cache_time=5)

------------------- Botni ishga tushirish -------------------
#
async def on_startup(bot: Bot): # Bot buyruqlarini ko'rsatish (BotFather menyusi uchun) from aiogram.types import BotCommand

commands = [
    BotCommand(command="start", description="Boshlash"),
    BotCommand(command="help", description="Yordam"),
    BotCommand(command="about", description="Bot haqida"),
    BotCommand(command="kino", description="Film ma'lumoti"),
]
await bot.set_my_commands(commands)

async def main(): if BOT_TOKEN == "8413767557:AAFslk-Ej9KRX3XgU5vHArRErr348HQkcGs": logger.error("BOT_TOKEN o'rnatilmagan. BOT_TOKEN environment o'zgaruvchisini kiriting!") raise SystemExit(1)

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp.startup.register(on_startup)

try:
    logger.info("Bot polling'ni boshladi...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
finally:
    await bot.session.close()

if name == "main": asyncio.run(main())

