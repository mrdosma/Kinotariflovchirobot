# Aiogram 3 kino tariflovchi (movie describer) bot
# Til: O'zbekcha | Framework: Aiogram 3 | Python 3.10+

import os
import asyncio
import logging
import sqlite3
from typing import Optional, Dict, Any, List

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

try:
    import httpx
except ImportError:
    httpx = None

# ------------------- Sozlamalar -------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("kino-bot")

# ------------------- Ichki ma'lumotlar bazasi -------------------

LOCAL_MOVIES = {
    "inception": {
        "title": "Inception (2010)",
        "plot": "Dom Kobb tushlar ichida g'oya o'g'irlash bo'yicha mutaxassis. Unga buning aksi — g'oya joylash topshirig'i beriladi.",
        "rating": "8.8/10 (IMDb)",
        "rating_score": 8.8,
        "genre": ["ilmiy-fantastika", "triller", "drama"],
        "similar": ["interstellar", "matrix", "fight club"],
    },
    "interstellar": {
        "title": "Interstellar (2014)",
        "plot": "Insoniyatni qutqarish uchun kosmik ekspeditsiya vaqt va makon chegaralarini bosib o'tadi.",
        "rating": "8.6/10 (IMDb)",
        "rating_score": 8.6,
        "genre": ["ilmiy-fantastika", "drama", "sarguzasht"],
        "similar": ["inception", "2001: a space odyssey", "arrival"],
    },
    "matrix": {
        "title": "The Matrix (1999)",
        "plot": "Neo haqiqat va simulyatsiya o'rtasidagi chegarani kashf etadi va qarshilikka qo'shiladi.",
        "rating": "8.7/10 (IMDb)",
        "rating_score": 8.7,
        "genre": ["ilmiy-fantastika", "aksion", "triller"],
        "similar": ["inception", "fight club", "blade runner 2049"],
    },
    "godfather": {
        "title": "The Godfather (1972)",
        "plot": "Korleone oilasining kuch, sadoqat va xiyonat haqidagi klassik sagasi.",
        "rating": "9.2/10 (IMDb)",
        "rating_score": 9.2,
        "genre": ["drama", "jinoyat"],
        "similar": ["fight club", "goodfellas", "scarface"],
    },
    "fight club": {
        "title": "Fight Club (1999)",
        "plot": "Nomuayyan hikoyachi va Tyler Durden yashirin jang klubi orqali tizimga qarshi borishadi.",
        "rating": "8.8/10 (IMDb)",
        "rating_score": 8.8,
        "genre": ["drama", "triller", "psixologik"],
        "similar": ["godfather", "inception", "matrix"],
    },
    "shawshank redemption": {
        "title": "The Shawshank Redemption (1994)",
        "plot": "Nohaq qamalgan bank menejeri qamoqxonada umid va do'stlik orqali ozodlikka yo'l topadi.",
        "rating": "9.3/10 (IMDb)",
        "rating_score": 9.3,
        "genre": ["drama"],
        "similar": ["godfather", "green mile", "schindler's list"],
    },
    "dark knight": {
        "title": "The Dark Knight (2008)",
        "plot": "Batman Gotham shahrini Joker nomli g'ayritabiiy jinoyatchidan himoya qiladi.",
        "rating": "9.0/10 (IMDb)",
        "rating_score": 9.0,
        "genre": ["aksion", "triller", "jinoyat"],
        "similar": ["matrix", "inception", "batman begins"],
    },
    "forrest gump": {
        "title": "Forrest Gump (1994)",
        "plot": "Past aqliy qobiliyatli lekin katta yurakli Forrest Gump hayotning barcha sinovlaridan o'tadi.",
        "rating": "8.8/10 (IMDb)",
        "rating_score": 8.8,
        "genre": ["drama", "komediya", "romantik"],
        "similar": ["shawshank redemption", "green mile", "cast away"],
    },
    "pulp fiction": {
        "title": "Pulp Fiction (1994)",
        "plot": "Los-Angelesdagi bir necha kriminal hikoya bir-biriga chirmashib ketadi.",
        "rating": "8.9/10 (IMDb)",
        "rating_score": 8.9,
        "genre": ["jinoyat", "drama", "triller"],
        "similar": ["godfather", "fight club", "reservoir dogs"],
    },
    "schindler's list": {
        "title": "Schindler's List (1993)",
        "plot": "Ikkinchi jahon urushi davrida nemis biznesmen Oskar Schindler yahudiy ishchilarini Holokostdan qutqaradi.",
        "rating": "9.0/10 (IMDb)",
        "rating_score": 9.0,
        "genre": ["drama", "tarix", "urush"],
        "similar": ["shawshank redemption", "godfather", "forrest gump"],
    },
}

# ------------------- SQLite: Sevimlilar -------------------

DB_PATH = "favorites.db"

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS favorites "
        "(user_id INTEGER, movie_key TEXT, PRIMARY KEY (user_id, movie_key))"
    )
    con.commit()
    con.close()

def db_add_favorite(user_id: int, movie_key: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR IGNORE INTO favorites (user_id, movie_key) VALUES (?, ?)",
        (user_id, movie_key),
    )
    con.commit()
    con.close()

def db_remove_favorite(user_id: int, movie_key: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "DELETE FROM favorites WHERE user_id=? AND movie_key=?",
        (user_id, movie_key),
    )
    con.commit()
    con.close()

def db_get_favorites(user_id: int) -> List[str]:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT movie_key FROM favorites WHERE user_id=?", (user_id,)
    ).fetchall()
    con.close()
    return [r[0] for r in rows]

# ------------------- OMDb yordamchi -------------------

async def fetch_movie_from_omdb(title: str) -> Optional[Dict[str, Any]]:
    if not OMDB_API_KEY:
        return None
    if httpx is None:
        logger.warning("httpx o'rnatilmagan. 'pip install httpx' qiling.")
        return None

    params = {"t": title, "apikey": OMDB_API_KEY, "plot": "short"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("http://www.omdbapi.com/", params=params)
            data = r.json()
            if data.get("Response") == "True":
                score_str = data.get("imdbRating", "")
                try:
                    score = float(score_str)
                except (ValueError, TypeError):
                    score = 0.0
                genres = [g.strip().lower() for g in (data.get("Genre") or "").split(",") if g.strip()]
                return {
                    "title": f"{data.get('Title')} ({data.get('Year')})",
                    "plot": data.get("Plot") or "Syujet topilmadi.",
                    "rating": (score_str and f"{score_str}/10 (IMDb)") or "Bahosi mavjud emas",
                    "rating_score": score,
                    "genre": genres,
                    "similar": [],
                }
    except Exception as e:
        logger.exception("OMDb so'rovida xato: %s", e)
    return None

# ------------------- Qidiruv va formatlash -------------------

async def lookup_movie(title: str) -> Optional[Dict[str, Any]]:
    info = await fetch_movie_from_omdb(title)
    if info:
        return info
    key = title.strip().lower()
    return LOCAL_MOVIES.get(key)

def format_movie_card(movie: Dict[str, Any], show_genres: bool = True) -> str:
    title = movie.get("title", "Noma'lum nom")
    plot = movie.get("plot", "Ma'lumot topilmadi")
    rating = movie.get("rating", "—")
    genres = movie.get("genre", [])
    genre_str = (", ".join(genres).capitalize() if genres else "—")
    text = (
        f"<b>{title}</b>\n"
        f"<i>Bahosi:</i> {rating}\n"
    )
    if show_genres and genres:
        text += f"<i>Janr:</i> {genre_str}\n"
    text += f"\n<b>Qisqacha:</b> {plot}"
    return text

def format_similar(movie: Dict[str, Any]) -> str:
    similar = movie.get("similar", [])
    if not similar:
        return ""
    return "\n\n<i>O'xshash filmlar:</i> " + ", ".join(
        LOCAL_MOVIES[k]["title"] if k in LOCAL_MOVIES else k.title()
        for k in similar[:3]
    )

# ------------------- Bot va dispatcher -------------------

dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    payload = command.args
    text = (
        "Salom! 👋\n\n"
        "Men kino tariflovchi botman.\n\n"
        "<b>Buyruqlar:</b>\n"
        "• <code>/kino &lt;nomi&gt;</code> — Film ma'lumoti\n"
        "• <code>/top</code> — Eng yuqori reytingli filmlar\n"
        "• <code>/janr &lt;janr&gt;</code> — Janr bo'yicha filmlar\n"
        "• <code>/sevimli_qoshish &lt;nomi&gt;</code> — Sevimliga qo'shish\n"
        "• <code>/sevimlilar</code> — Sevimlilar ro'yxati\n"
        "• <code>/sevimli_ochirish &lt;nomi&gt;</code> — Sevimlilardan o'chirish\n"
        "• <code>/help</code> — Yordam"
    )
    if payload:
        info = await lookup_movie(payload)
        if info:
            text = format_movie_card(info) + format_similar(info)
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>Yordam:</b>\n\n"
        "• <code>/kino &lt;nomi&gt;</code> — Film ma'lumoti va o'xshash tavsiyalar\n"
        "• <code>/top</code> — Eng yuqori reytingli 5 ta film\n"
        "• <code>/janr &lt;janr&gt;</code> — Janr bo'yicha qidirish\n"
        "  Janrlar: drama, triller, aksion, komediya, jinoyat,\n"
        "  ilmiy-fantastika, psixologik, romantik, tarix, urush, sarguzasht\n"
        "• <code>/sevimli_qoshish &lt;nomi&gt;</code> — Sevimliga qo'shish\n"
        "• <code>/sevimlilar</code> — Saqlangan filmlaringiz\n"
        "• <code>/sevimli_ochirish &lt;nomi&gt;</code> — Sevimlilardan o'chirish\n\n"
        "Inline: <code>@bot_username Matrix</code>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("about"))
async def cmd_about(message: Message):
    text = (
        "📽️ <b>Kino tariflovchi bot</b>\n"
        "• Framework: Aiogram 3\n"
        "• Til: O'zbekcha\n"
        "• Ichki baza: 10 ta film\n"
        "• OMDb API orqali istalgan film qidirish mumkin\n"
        "• Sevimlilar SQLite da saqlanadi"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("kino"))
async def cmd_kino(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Iltimos, film nomini yozing. Masalan: <code>/kino Inception</code>", parse_mode=ParseMode.HTML)
        return
    info = await lookup_movie(command.args)
    if info:
        text = format_movie_card(info) + format_similar(info)
        await message.answer(text, parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            "Kechirasiz, bu nom bo'yicha ma'lumot topilmadi.\n"
            "Boshqa nom bilan urinib ko'ring yoki OMDb API kalitini sozlang."
        )

@dp.message(Command("top"))
async def cmd_top(message: Message):
    sorted_movies = sorted(
        LOCAL_MOVIES.values(), key=lambda m: m["rating_score"], reverse=True
    )[:5]
    lines = ["<b>🏆 Eng yuqori reytingli 5 ta film:</b>\n"]
    for i, m in enumerate(sorted_movies, 1):
        lines.append(f"{i}. <b>{m['title']}</b> — {m['rating']}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

@dp.message(Command("janr"))
async def cmd_janr(message: Message, command: CommandObject):
    if not command.args:
        await message.reply(
            "Janr nomini kiriting. Masalan: <code>/janr drama</code>\n\n"
            "Mavjud janrlar: drama, triller, aksion, komediya, jinoyat, "
            "ilmiy-fantastika, psixologik, romantik, tarix, urush, sarguzasht",
            parse_mode=ParseMode.HTML,
        )
        return
    target = command.args.strip().lower()
    matches = [
        m for m in LOCAL_MOVIES.values()
        if target in m.get("genre", [])
    ]
    if not matches:
        await message.answer(f"<b>{target}</b> janrida film topilmadi.", parse_mode=ParseMode.HTML)
        return
    lines = [f"<b>🎬 {target.capitalize()} janridagi filmlar:</b>\n"]
    for m in sorted(matches, key=lambda x: x["rating_score"], reverse=True):
        lines.append(f"• <b>{m['title']}</b> — {m['rating']}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

@dp.message(Command("sevimli_qoshish"))
async def cmd_add_favorite(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Film nomini kiriting. Masalan: <code>/sevimli_qoshish Inception</code>", parse_mode=ParseMode.HTML)
        return
    key = command.args.strip().lower()
    movie = LOCAL_MOVIES.get(key)
    if not movie:
        movie = await fetch_movie_from_omdb(command.args)
    if not movie:
        await message.answer("Bu nomli film topilmadi.")
        return
    db_add_favorite(message.from_user.id, key)
    await message.answer(
        f"✅ <b>{movie['title']}</b> sevimlilar ro'yxatiga qo'shildi!",
        parse_mode=ParseMode.HTML,
    )

@dp.message(Command("sevimli_ochirish"))
async def cmd_remove_favorite(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Film nomini kiriting. Masalan: <code>/sevimli_ochirish Inception</code>", parse_mode=ParseMode.HTML)
        return
    key = command.args.strip().lower()
    db_remove_favorite(message.from_user.id, key)
    await message.answer(f"🗑️ <b>{key.title()}</b> sevimlilardan o'chirildi.", parse_mode=ParseMode.HTML)

@dp.message(Command("sevimlilar"))
async def cmd_favorites(message: Message):
    keys = db_get_favorites(message.from_user.id)
    if not keys:
        await message.answer("Sevimlilar ro'yxatingiz bo'sh.\n<code>/sevimli_qoshish &lt;film nomi&gt;</code> orqali qo'shing.", parse_mode=ParseMode.HTML)
        return
    lines = ["<b>⭐ Sevimli filmlaringiz:</b>\n"]
    for k in keys:
        movie = LOCAL_MOVIES.get(k)
        if movie:
            lines.append(f"• <b>{movie['title']}</b> — {movie['rating']}")
        else:
            lines.append(f"• {k.title()}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ------------------- Inline rejim -------------------

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    q = (query.query or "").strip()
    results = []

    suggestions = ["Inception", "Interstellar", "Matrix", "Godfather", "Fight Club"]
    candidates = suggestions if not q else [q]

    for idx, title in enumerate(candidates, start=1):
        info = await lookup_movie(title)
        if not info:
            info = {"title": title, "plot": "Natija topilmadi", "rating": "—", "genre": [], "similar": []}
        text = format_movie_card(info) + format_similar(info)
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

# ------------------- Botni ishga tushirish -------------------

async def on_startup(bot: Bot):
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="help", description="Yordam"),
        BotCommand(command="kino", description="Film ma'lumoti"),
        BotCommand(command="top", description="Eng yuqori reytingli filmlar"),
        BotCommand(command="janr", description="Janr bo'yicha qidirish"),
        BotCommand(command="sevimli_qoshish", description="Sevimliga qo'shish"),
        BotCommand(command="sevimlilar", description="Sevimlilar ro'yxati"),
        BotCommand(command="sevimli_ochirish", description="Sevimlilardan o'chirish"),
        BotCommand(command="about", description="Bot haqida"),
    ]
    await bot.set_my_commands(commands)

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN o'rnatilmagan. BOT_TOKEN environment o'zgaruvchisini kiriting!")
        raise SystemExit(1)

    init_db()
    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp.startup.register(on_startup)

    try:
        logger.info("Bot polling'ni boshladi...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
