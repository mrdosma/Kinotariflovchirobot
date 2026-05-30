# Kinotarif Bot — Aiogram 3 | Python 3.10+
# Funksiyalar: kino bazasi, kod orqali qidirish, VIP (Telegram Stars),
# majburiy obuna, admin panel, statistika, forward xabar indeksi

import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineQuery,
    InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)

# ------------------- Sozlamalar -------------------

BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
OMDB_API_KEY    = os.getenv("OMDB_API_KEY", "")
# Majburiy obuna kanali, masalan: @mychanel  (bo'sh qolsa — o'chiriladi)
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "")
# Admin user_id lari, vergul bilan: 123456,789012
_admin_env      = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [int(x) for x in _admin_env.split(",") if x.strip().isdigit()]

VIP_STARS_PRICE = int(os.getenv("VIP_STARS_PRICE", "50"))   # necha Stars = 1 oy VIP
VIP_DAYS        = int(os.getenv("VIP_DAYS", "30"))

DB_PATH = "prokino.db"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("prokino")

try:
    import httpx
except ImportError:
    httpx = None

# ------------------- DB -------------------

def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_con()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            joined_at   TEXT DEFAULT (datetime('now')),
            is_vip      INTEGER DEFAULT 0,
            vip_until   TEXT
        );
        CREATE TABLE IF NOT EXISTS movies (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            code         TEXT UNIQUE NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT,
            file_id      TEXT,
            file_type    TEXT DEFAULT 'document',
            genre        TEXT,
            is_vip       INTEGER DEFAULT 0,
            added_at     TEXT DEFAULT (datetime('now')),
            download_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS downloads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            movie_id    INTEGER,
            ts          TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id     INTEGER,
            movie_id    INTEGER,
            PRIMARY KEY (user_id, movie_id)
        );
        CREATE TABLE IF NOT EXISTS channel_posts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id       INTEGER,
            channel_username TEXT,
            message_id       INTEGER,
            text             TEXT,
            UNIQUE(channel_id, message_id)
        );
        CREATE TABLE IF NOT EXISTS user_channels (
            user_id          INTEGER PRIMARY KEY,
            channel_id       INTEGER,
            channel_username TEXT
        );
    """)
    con.commit()
    con.close()

# ------------------- Foydalanuvchi -------------------

def upsert_user(user_id: int, username: str, full_name: str):
    con = get_con()
    con.execute(
        "INSERT INTO users(user_id, username, full_name) VALUES(?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name",
        (user_id, username or "", full_name or ""),
    )
    con.commit(); con.close()

def get_user(user_id: int) -> Optional[sqlite3.Row]:
    con = get_con()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close(); return row

def is_vip(user_id: int) -> bool:
    row = get_user(user_id)
    if not row or not row["is_vip"]:
        return False
    if row["vip_until"]:
        return datetime.fromisoformat(row["vip_until"]) > datetime.now()
    return bool(row["is_vip"])

def grant_vip(user_id: int, days: int):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    con = get_con()
    con.execute(
        "UPDATE users SET is_vip=1, vip_until=? WHERE user_id=?",
        (until, user_id),
    )
    con.commit(); con.close()

def revoke_vip(user_id: int):
    con = get_con()
    con.execute("UPDATE users SET is_vip=0, vip_until=NULL WHERE user_id=?", (user_id,))
    con.commit(); con.close()

def user_count() -> int:
    con = get_con()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close(); return n

def new_users_since(days: int) -> int:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    con = get_con()
    n = con.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (since,)).fetchone()[0]
    con.close(); return n

def vip_count() -> int:
    now = datetime.now().isoformat()
    con = get_con()
    n = con.execute(
        "SELECT COUNT(*) FROM users WHERE is_vip=1 AND (vip_until IS NULL OR vip_until > ?)", (now,)
    ).fetchone()[0]
    con.close(); return n

# ------------------- Kinolar -------------------

def add_movie(code: str, title: str, description: str,
              file_id: str, file_type: str, genre: str, is_vip_movie: int) -> bool:
    try:
        con = get_con()
        con.execute(
            "INSERT INTO movies(code, title, description, file_id, file_type, genre, is_vip) "
            "VALUES(?,?,?,?,?,?,?)",
            (code.upper(), title, description, file_id, file_type, genre, is_vip_movie),
        )
        con.commit(); con.close(); return True
    except sqlite3.IntegrityError:
        return False

def get_movie_by_code(code: str) -> Optional[sqlite3.Row]:
    con = get_con()
    row = con.execute("SELECT * FROM movies WHERE code=?", (code.upper(),)).fetchone()
    con.close(); return row

def delete_movie(code: str) -> bool:
    con = get_con()
    cur = con.execute("DELETE FROM movies WHERE code=?", (code.upper(),))
    con.commit(); con.close()
    return cur.rowcount > 0

def list_movies(genre: str = "", vip_only: bool = False, limit: int = 20) -> List[sqlite3.Row]:
    con = get_con()
    q = "SELECT * FROM movies WHERE 1=1"
    params: list = []
    if genre:
        q += " AND genre LIKE ?"
        params.append(f"%{genre}%")
    if vip_only:
        q += " AND is_vip=1"
    q += " ORDER BY download_count DESC LIMIT ?"
    params.append(limit)
    rows = con.execute(q, params).fetchall()
    con.close(); return rows

def top_movies(n: int = 10) -> List[sqlite3.Row]:
    con = get_con()
    rows = con.execute(
        "SELECT * FROM movies ORDER BY download_count DESC LIMIT ?", (n,)
    ).fetchall()
    con.close(); return rows

def record_download(user_id: int, movie_id: int):
    con = get_con()
    con.execute("INSERT INTO downloads(user_id, movie_id) VALUES(?,?)", (user_id, movie_id))
    con.execute("UPDATE movies SET download_count = download_count + 1 WHERE id=?", (movie_id,))
    con.commit(); con.close()

def total_downloads() -> int:
    con = get_con()
    n = con.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    con.close(); return n

def downloads_since(days: int) -> int:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    con = get_con()
    n = con.execute("SELECT COUNT(*) FROM downloads WHERE ts >= ?", (since,)).fetchone()[0]
    con.close(); return n

def movie_count() -> int:
    con = get_con()
    n = con.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    con.close(); return n

# ------------------- Sevimlilar -------------------

def fav_add(user_id: int, movie_id: int):
    con = get_con()
    con.execute("INSERT OR IGNORE INTO favorites VALUES(?,?)", (user_id, movie_id))
    con.commit(); con.close()

def fav_remove(user_id: int, movie_id: int):
    con = get_con()
    con.execute("DELETE FROM favorites WHERE user_id=? AND movie_id=?", (user_id, movie_id))
    con.commit(); con.close()

def fav_list(user_id: int) -> List[sqlite3.Row]:
    con = get_con()
    rows = con.execute(
        "SELECT m.* FROM movies m JOIN favorites f ON m.id=f.movie_id WHERE f.user_id=?",
        (user_id,),
    ).fetchall()
    con.close(); return rows

# ------------------- Kanal indeks -------------------

def db_set_user_channel(user_id: int, channel_id: int, uname: str):
    con = get_con()
    con.execute(
        "INSERT OR REPLACE INTO user_channels VALUES(?,?,?)",
        (user_id, channel_id, uname),
    )
    con.commit(); con.close()

def db_get_user_channel(user_id: int) -> Optional[Dict]:
    con = get_con()
    row = con.execute("SELECT * FROM user_channels WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return dict(row) if row else None

def db_save_post(channel_id: int, uname: str, msg_id: int, text: str):
    con = get_con()
    con.execute(
        "INSERT OR IGNORE INTO channel_posts(channel_id, channel_username, message_id, text) "
        "VALUES(?,?,?,?)",
        (channel_id, uname, msg_id, text[:2000]),
    )
    con.commit(); con.close()

def db_search_posts(channel_id: int, query: str) -> List[Dict]:
    con = get_con()
    rows = con.execute(
        "SELECT message_id, text, channel_username FROM channel_posts "
        "WHERE channel_id=? AND text LIKE ? LIMIT 5",
        (channel_id, f"%{query}%"),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def db_post_count(channel_id: int) -> int:
    con = get_con()
    n = con.execute("SELECT COUNT(*) FROM channel_posts WHERE channel_id=?", (channel_id,)).fetchone()[0]
    con.close(); return n

# ------------------- Yordamchi -------------------

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def check_subscription(bot: Bot, user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception:
        return True  # kanal topilmasa bloklama

def sub_keyboard() -> InlineKeyboardMarkup:
    channel = REQUIRED_CHANNEL if REQUIRED_CHANNEL.startswith("@") else f"@{REQUIRED_CHANNEL}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=f"https://t.me/{channel.lstrip('@')}"),
        InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub"),
    ]])

def movie_card(m: sqlite3.Row) -> str:
    vip_badge = "👑 VIP" if m["is_vip"] else "🆓 Bepul"
    genre = m["genre"] or "—"
    desc = m["description"] or "Tavsif yo'q"
    return (
        f"🎬 <b>{m['title']}</b>\n"
        f"🔑 Kod: <code>{m['code']}</code>\n"
        f"🎭 Janr: {genre}\n"
        f"📊 {vip_badge} | Yuklanishlar: {m['download_count']}\n\n"
        f"📝 {desc}"
    )

async def send_movie(bot: Bot, chat_id: int, m: sqlite3.Row):
    if not m["file_id"]:
        await bot.send_message(chat_id, movie_card(m), parse_mode=ParseMode.HTML)
        return
    caption = movie_card(m)
    ftype = m["file_type"]
    if ftype == "video":
        await bot.send_video(chat_id, m["file_id"], caption=caption, parse_mode=ParseMode.HTML)
    elif ftype == "photo":
        await bot.send_photo(chat_id, m["file_id"], caption=caption, parse_mode=ParseMode.HTML)
    else:
        await bot.send_document(chat_id, m["file_id"], caption=caption, parse_mode=ParseMode.HTML)

try:
    import httpx as _httpx
except ImportError:
    _httpx = None

async def fetch_omdb(title: str) -> Optional[Dict]:
    if not OMDB_API_KEY or not _httpx:
        return None
    try:
        async with _httpx.AsyncClient(timeout=10) as c:
            r = await c.get("http://www.omdbapi.com/", params={"t": title, "apikey": OMDB_API_KEY, "plot": "short"})
            d = r.json()
            if d.get("Response") == "True":
                return {"title": f"{d['Title']} ({d['Year']})", "plot": d.get("Plot", ""), "rating": d.get("imdbRating", "—")}
    except Exception:
        pass
    return None

# ------------------- Dispatcher -------------------

dp = Dispatcher()

# === MAJBURIY OBUNA ===

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery, bot: Bot):
    if await check_subscription(bot, call.from_user.id):
        await call.message.edit_text("✅ Obuna tasdiqlandi! /start bosing.")
    else:
        await call.answer("Hali obuna bo'lmadingiz!", show_alert=True)

# === START ===

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    if not await check_subscription(bot, message.from_user.id):
        await message.answer(
            "⚠️ Botdan foydalanish uchun avval kanalga obuna bo'ling!",
            reply_markup=sub_keyboard(),
        )
        return

    payload = command.args
    if payload:
        # deep-link orqali kod kelgan bo'lsa
        m = get_movie_by_code(payload)
        if m:
            if m["is_vip"] and not is_vip(message.from_user.id):
                await message.answer(
                    "👑 Bu kino VIP foydalanuvchilar uchun.\n"
                    "VIP olish uchun: /vip"
                )
                return
            record_download(message.from_user.id, m["id"])
            await send_movie(bot, message.chat.id, m)
            return

    text = (
        "🎬 <b>Kinotarif Bot</b> ga xush kelibsiz!\n\n"
        "<b>Asosiy buyruqlar:</b>\n"
        "• <code>/kino &lt;kod&gt;</code> — Kino olish\n"
        "• <code>/top</code> — Eng ko'p yuklangan kinolar\n"
        "• <code>/janr &lt;janr&gt;</code> — Janr bo'yicha\n"
        "• <code>/sevimlilar</code> — Sevimlilarim\n"
        "• <code>/vip</code> — VIP obuna\n"
        "• <code>/kanal @nomi</code> — Kanal ulash\n"
        "• <code>/qidir &lt;nom&gt;</code> — Kanaldan qidirish\n"
        "• <code>/help</code> — Batafsil yordam"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

# === YORDAM ===

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>📖 Yordam</b>\n\n"
        "<b>Kino:</b>\n"
        "• <code>/kino &lt;kod&gt;</code> — Kodni bilsangiz to'g'ridan yuklash\n"
        "• <code>/top</code> — Top 10 kino\n"
        "• <code>/janr &lt;janr&gt;</code> — Janr bo'yicha ro'yxat\n"
        "• <code>/sevimli_qoshish &lt;kod&gt;</code> — Sevimliga qo'shish\n"
        "• <code>/sevimli_ochirish &lt;kod&gt;</code> — Olib tashlash\n"
        "• <code>/sevimlilar</code> — Sevimlilar ro'yxati\n\n"
        "<b>VIP:</b>\n"
        "• <code>/vip</code> — VIP obuna (Telegram Stars)\n"
        "• <code>/vip_holat</code> — VIP holatini tekshirish\n\n"
        "<b>Kanal qidirish:</b>\n"
        "• <code>/kanal @nomi</code> — Kanal ulash\n"
        "• <code>/qidir &lt;nom&gt;</code> — Kanaldan qidirish\n\n"
        "<b>Admin (faqat adminlar):</b>\n"
        "• <code>/admin</code> — Admin panel\n"
        "• <code>/addmovie</code> — Kino qo'shish\n"
        "• <code>/delmovie &lt;kod&gt;</code> — O'chirish\n"
        "• <code>/stats</code> — Statistika\n"
        "• <code>/vip_ber &lt;user_id&gt;</code> — VIP berish\n"
        "• <code>/vip_ol &lt;user_id&gt;</code> — VIP olish"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

# === KINO OLISH ===

@dp.message(Command("kino"))
async def cmd_kino(message: Message, command: CommandObject, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("⚠️ Avval kanalga obuna bo'ling!", reply_markup=sub_keyboard())
        return
    if not command.args:
        await message.reply("Kino kodini kiriting. Masalan: <code>/kino ABC123</code>", parse_mode=ParseMode.HTML)
        return
    m = get_movie_by_code(command.args.strip())
    if not m:
        # OMDb orqali qidirish
        info = await fetch_omdb(command.args.strip())
        if info:
            await message.answer(
                f"<b>{info['title']}</b>\n⭐ {info['rating']}/10\n\n{info['plot']}",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer("❌ Bu kodli kino topilmadi.")
        return
    if m["is_vip"] and not is_vip(message.from_user.id):
        await message.answer("👑 Bu kino VIP uchun.\nVIP olish: /vip")
        return
    record_download(message.from_user.id, m["id"])
    await send_movie(bot, message.chat.id, m)

# === TOP ===

@dp.message(Command("top"))
async def cmd_top(message: Message, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("⚠️ Avval kanalga obuna bo'ling!", reply_markup=sub_keyboard())
        return
    movies = top_movies(10)
    if not movies:
        await message.answer("Hozircha kino yo'q.")
        return
    lines = ["🏆 <b>Eng ko'p yuklangan kinolar:</b>\n"]
    for i, m in enumerate(movies, 1):
        vip = "👑" if m["is_vip"] else ""
        lines.append(f"{i}. {vip} <b>{m['title']}</b> — <code>{m['code']}</code> ({m['download_count']} yuklanish)")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# === JANR ===

@dp.message(Command("janr"))
async def cmd_janr(message: Message, command: CommandObject, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("⚠️ Avval kanalga obuna bo'ling!", reply_markup=sub_keyboard())
        return
    if not command.args:
        await message.reply("Masalan: <code>/janr drama</code>", parse_mode=ParseMode.HTML)
        return
    movies = list_movies(genre=command.args.strip())
    if not movies:
        await message.answer(f"<b>{command.args}</b> janrida kino topilmadi.", parse_mode=ParseMode.HTML)
        return
    lines = [f"🎭 <b>{command.args.capitalize()} janridagi kinolar:</b>\n"]
    for m in movies:
        vip = "👑" if m["is_vip"] else "🆓"
        lines.append(f"{vip} <b>{m['title']}</b> — <code>{m['code']}</code>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# === SEVIMLILAR ===

@dp.message(Command("sevimli_qoshish"))
async def cmd_fav_add(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Kino kodini kiriting: <code>/sevimli_qoshish ABC123</code>", parse_mode=ParseMode.HTML)
        return
    m = get_movie_by_code(command.args.strip())
    if not m:
        await message.answer("Bu kodli kino topilmadi.")
        return
    fav_add(message.from_user.id, m["id"])
    await message.answer(f"✅ <b>{m['title']}</b> sevimlilaringizga qo'shildi!", parse_mode=ParseMode.HTML)

@dp.message(Command("sevimli_ochirish"))
async def cmd_fav_remove(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Kino kodini kiriting: <code>/sevimli_ochirish ABC123</code>", parse_mode=ParseMode.HTML)
        return
    m = get_movie_by_code(command.args.strip())
    if not m:
        await message.answer("Bu kodli kino topilmadi.")
        return
    fav_remove(message.from_user.id, m["id"])
    await message.answer(f"🗑️ <b>{m['title']}</b> sevimlilardan o'chirildi.", parse_mode=ParseMode.HTML)

@dp.message(Command("sevimlilar"))
async def cmd_favorites(message: Message):
    movies = fav_list(message.from_user.id)
    if not movies:
        await message.answer("Sevimlilar bo'sh.\n<code>/sevimli_qoshish &lt;kod&gt;</code> orqali qo'shing.", parse_mode=ParseMode.HTML)
        return
    lines = ["⭐ <b>Sevimli kinolaringiz:</b>\n"]
    for m in movies:
        vip = "👑" if m["is_vip"] else "🆓"
        lines.append(f"{vip} <b>{m['title']}</b> — <code>{m['code']}</code>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# === VIP (TELEGRAM STARS) ===

@dp.message(Command("vip"))
async def cmd_vip(message: Message, bot: Bot):
    if is_vip(message.from_user.id):
        row = get_user(message.from_user.id)
        until = row["vip_until"][:10] if row and row["vip_until"] else "—"
        await message.answer(
            f"👑 Siz allaqachon VIP foydalanuvchisiz!\n"
            f"Muddati: <b>{until}</b>\n\n"
            f"Uzaytirish uchun /vip_xarid ni bosing.",
            parse_mode=ParseMode.HTML,
        )
        return
    await message.answer(
        f"👑 <b>VIP obuna</b>\n\n"
        f"• Barcha VIP kinolarga kirish\n"
        f"• {VIP_DAYS} kun muddatli\n"
        f"• Narxi: <b>{VIP_STARS_PRICE} ⭐ Telegram Stars</b>\n\n"
        f"To'lash uchun quyidagi tugmani bosing:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"⭐ {VIP_STARS_PRICE} Stars bilan to'lash", callback_data="buy_vip"),
        ]]),
    )

@dp.message(Command("vip_xarid"))
async def cmd_vip_buy_cmd(message: Message):
    await _send_vip_invoice(message.from_user.id, message.bot, message.chat.id)

@dp.callback_query(F.data == "buy_vip")
async def cb_buy_vip(call: CallbackQuery, bot: Bot):
    await call.answer()
    await _send_vip_invoice(call.from_user.id, bot, call.message.chat.id)

async def _send_vip_invoice(user_id: int, bot: Bot, chat_id: int):
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"👑 VIP obuna — {VIP_DAYS} kun",
        description=f"Kinotarif botida barcha VIP kinolarga {VIP_DAYS} kunlik kirish.",
        payload=f"vip_{user_id}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="VIP obuna", amount=VIP_STARS_PRICE)],
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("vip_"):
        user_id = int(payload.split("_")[1])
        grant_vip(user_id, VIP_DAYS)
        until = (datetime.now() + timedelta(days=VIP_DAYS)).strftime("%Y-%m-%d")
        await message.answer(
            f"🎉 To'lov qabul qilindi! VIP faollashtirildi.\n"
            f"👑 Muddati: <b>{until}</b> gacha\n\n"
            f"Endi barcha VIP kinolar sizga ochiq!",
            parse_mode=ParseMode.HTML,
        )

@dp.message(Command("vip_holat"))
async def cmd_vip_status(message: Message):
    row = get_user(message.from_user.id)
    if row and is_vip(message.from_user.id):
        until = row["vip_until"][:10] if row["vip_until"] else "Cheksiz"
        await message.answer(f"👑 VIP aktiv. Muddat: <b>{until}</b>", parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ VIP yo'q. Olish uchun: /vip")

# === KANAL ===

@dp.message(Command("kanal"))
async def cmd_kanal(message: Message, command: CommandObject, bot: Bot):
    if not command.args:
        ch = db_get_user_channel(message.from_user.id)
        if ch:
            count = db_post_count(ch["channel_id"])
            await message.answer(
                f"📡 Kanal: <b>@{ch['channel_username']}</b>\n"
                f"Indekslangan xabarlar: <b>{count}</b>\n\n"
                f"O'zgartirish: <code>/kanal @yangi_kanal</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                "Kanal ulanmagan.\nFoydalanish: <code>/kanal @kanal_nomi</code>\n\n"
                "<i>Botni kanalga admin qiling.</i>",
                parse_mode=ParseMode.HTML,
            )
        return
    username = command.args.strip().lstrip("@")
    await message.answer("Tekshirilmoqda... ⏳")
    try:
        chat = await bot.get_chat(f"@{username}")
    except Exception:
        await message.answer(f"❌ @{username} kanaliga ulanib bo'lmadi.\nBotni admin qiling.", parse_mode=ParseMode.HTML)
        return
    db_set_user_channel(message.from_user.id, chat.id, username)
    await message.answer(
        f"✅ Kanal ulandi: <b>@{username}</b>\n"
        f"Yangi postlar avtomatik saqlanadi.\n"
        f"Qidirish: <code>/qidir &lt;nom&gt;</code>",
        parse_mode=ParseMode.HTML,
    )

@dp.message(Command("qidir"))
async def cmd_qidir(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Masalan: <code>/qidir Inception</code>", parse_mode=ParseMode.HTML)
        return
    ch = db_get_user_channel(message.from_user.id)
    if not ch:
        await message.answer("Avval kanal ulang: <code>/kanal @kanal_nomi</code>", parse_mode=ParseMode.HTML)
        return
    results = db_search_posts(ch["channel_id"], command.args.strip())
    if not results:
        await message.answer(
            f"❌ «{command.args}» topilmadi.\n"
            f"Indekslangan: {db_post_count(ch['channel_id'])} xabar.\n"
            f"<i>Faqat bot admin bo'lgandan keyin tushgan xabarlar saqlanadi.</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    lines = [f"🔍 <b>«{command.args}»</b> natijalari (@{ch['channel_username']}):\n"]
    for r in results:
        preview = r["text"][:80].replace("\n", " ")
        link = f"https://t.me/{r['channel_username']}/{r['message_id']}"
        lines.append(f"• <a href='{link}'>{preview}…</a>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@dp.channel_post(F.text)
async def on_channel_post(message: Message):
    uname = message.chat.username or str(message.chat.id)
    db_save_post(message.chat.id, uname, message.message_id, message.text)

# === ADMIN PANEL ===

def admin_only(func):
    async def wrapper(message: Message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            await message.answer("⛔ Ruxsat yo'q.")
            return
        return await func(message, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

@dp.message(Command("admin"))
@admin_only
async def cmd_admin(message: Message):
    await message.answer(
        "🛠 <b>Admin panel</b>\n\n"
        "• <code>/addmovie</code> — Kino qo'shish\n"
        "• <code>/delmovie &lt;kod&gt;</code> — Kino o'chirish\n"
        "• <code>/stats</code> — Statistika\n"
        "• <code>/vip_ber &lt;user_id&gt; [kunlar]</code> — VIP berish\n"
        "• <code>/vip_ol &lt;user_id&gt;</code> — VIP olish\n\n"
        f"Jami kinolar: <b>{movie_count()}</b>\n"
        f"Jami foydalanuvchilar: <b>{user_count()}</b>",
        parse_mode=ParseMode.HTML,
    )

# Kino qo'shish: ko'p bosqichli suhbat (FSM o'rniga oddiy state dict)
_add_state: Dict[int, Dict] = {}

@dp.message(Command("addmovie"))
@admin_only
async def cmd_addmovie(message: Message):
    _add_state[message.from_user.id] = {"step": "code"}
    await message.answer(
        "➕ <b>Yangi kino qo'shish</b>\n\n"
        "1-qadam: Kino <b>kodini</b> yozing (masalan: <code>ABC123</code>)\n"
        "Bekor qilish: <code>/bekor</code>",
        parse_mode=ParseMode.HTML,
    )

@dp.message(Command("bekor"))
async def cmd_bekor(message: Message):
    if message.from_user.id in _add_state:
        del _add_state[message.from_user.id]
        await message.answer("❌ Bekor qilindi.")

@dp.message(F.text & ~F.text.startswith("/"))
async def addmovie_steps(message: Message, bot: Bot):
    uid = message.from_user.id
    if uid not in _add_state:
        return
    state = _add_state[uid]
    step = state.get("step")

    if step == "code":
        code = message.text.strip().upper()
        if get_movie_by_code(code):
            await message.answer(f"❌ <code>{code}</code> kodi allaqachon mavjud. Boshqa kod kiriting.", parse_mode=ParseMode.HTML)
            return
        state["code"] = code
        state["step"] = "title"
        await message.answer("2-qadam: Kino <b>nomini</b> yozing.", parse_mode=ParseMode.HTML)

    elif step == "title":
        state["title"] = message.text.strip()
        state["step"] = "description"
        await message.answer("3-qadam: Qisqacha <b>tavsif</b> yozing (yoki <code>-</code> o'tkazib yuborish).", parse_mode=ParseMode.HTML)

    elif step == "description":
        state["description"] = "" if message.text.strip() == "-" else message.text.strip()
        state["step"] = "genre"
        await message.answer("4-qadam: <b>Janr</b> yozing (masalan: drama, aksion).", parse_mode=ParseMode.HTML)

    elif step == "genre":
        state["genre"] = message.text.strip()
        state["step"] = "is_vip"
        await message.answer(
            "5-qadam: VIPmi?\n<code>ha</code> — VIP\n<code>yoq</code> — Bepul",
            parse_mode=ParseMode.HTML,
        )

    elif step == "is_vip":
        state["is_vip"] = 1 if message.text.strip().lower() in ("ha", "yes", "1") else 0
        state["step"] = "file"
        await message.answer(
            "6-qadam: Kino faylini yuboring (video, document, photo)\n"
            "yoki <code>-</code> bosib o'tkazib yuboring (havola keyinroq).",
            parse_mode=ParseMode.HTML,
        )

    elif step == "file":
        if message.text and message.text.strip() == "-":
            state["file_id"] = ""
            state["file_type"] = "document"
        else:
            await message.answer("Iltimos fayl yuboring yoki <code>-</code> yozing.", parse_mode=ParseMode.HTML)
            return
        _finish_addmovie(uid, message)
        await message.answer(
            f"✅ <b>{state['title']}</b> (<code>{state['code']}</code>) qo'shildi!",
            parse_mode=ParseMode.HTML,
        )

@dp.message(F.video | F.document | F.photo)
async def addmovie_file(message: Message):
    uid = message.from_user.id
    if uid not in _add_state or _add_state[uid].get("step") != "file":
        return
    state = _add_state[uid]
    if message.video:
        state["file_id"] = message.video.file_id
        state["file_type"] = "video"
    elif message.document:
        state["file_id"] = message.document.file_id
        state["file_type"] = "document"
    elif message.photo:
        state["file_id"] = message.photo[-1].file_id
        state["file_type"] = "photo"
    _finish_addmovie(uid, message)
    await message.answer(
        f"✅ <b>{state['title']}</b> (<code>{state['code']}</code>) qo'shildi!",
        parse_mode=ParseMode.HTML,
    )

def _finish_addmovie(uid: int, message: Message):
    state = _add_state.pop(uid)
    add_movie(
        code=state["code"],
        title=state["title"],
        description=state.get("description", ""),
        file_id=state.get("file_id", ""),
        file_type=state.get("file_type", "document"),
        genre=state.get("genre", ""),
        is_vip_movie=state.get("is_vip", 0),
    )

@dp.message(Command("delmovie"))
@admin_only
async def cmd_delmovie(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Kino kodini kiriting: <code>/delmovie ABC123</code>", parse_mode=ParseMode.HTML)
        return
    if delete_movie(command.args.strip()):
        await message.answer(f"✅ <code>{command.args.strip().upper()}</code> o'chirildi.", parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Bu kod topilmadi.")

@dp.message(Command("stats"))
@admin_only
async def cmd_stats(message: Message):
    await message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{user_count()}</b>\n"
        f"   — Bugun: <b>{new_users_since(1)}</b>\n"
        f"   — Hafta: <b>{new_users_since(7)}</b>\n"
        f"   — Oy: <b>{new_users_since(30)}</b>\n\n"
        f"👑 VIP foydalanuvchilar: <b>{vip_count()}</b>\n\n"
        f"🎬 Jami kinolar: <b>{movie_count()}</b>\n\n"
        f"📥 Jami yuklanishlar: <b>{total_downloads()}</b>\n"
        f"   — Bugun: <b>{downloads_since(1)}</b>\n"
        f"   — Hafta: <b>{downloads_since(7)}</b>\n"
        f"   — Oy: <b>{downloads_since(30)}</b>",
        parse_mode=ParseMode.HTML,
    )

@dp.message(Command("vip_ber"))
@admin_only
async def cmd_vip_ber(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Foydalanish: <code>/vip_ber &lt;user_id&gt; [kunlar]</code>", parse_mode=ParseMode.HTML)
        return
    parts = command.args.split()
    try:
        target = int(parts[0])
        days = int(parts[1]) if len(parts) > 1 else VIP_DAYS
    except ValueError:
        await message.answer("❌ Noto'g'ri format.")
        return
    grant_vip(target, days)
    await message.answer(f"✅ <code>{target}</code> ga {days} kunlik VIP berildi.", parse_mode=ParseMode.HTML)

@dp.message(Command("vip_ol"))
@admin_only
async def cmd_vip_ol(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Foydalanish: <code>/vip_ol &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        target = int(command.args.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri user_id.")
        return
    revoke_vip(target)
    await message.answer(f"✅ <code>{target}</code> dan VIP olindi.", parse_mode=ParseMode.HTML)

# === INLINE ===

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    q = (query.query or "").strip()
    movies = list_movies(genre="", limit=20) if not q else list_movies(limit=50)
    if q:
        movies = [m for m in movies if q.lower() in m["title"].lower() or q.upper() == m["code"]]
    results = []
    for m in movies[:10]:
        vip = "👑 " if m["is_vip"] else ""
        text = (
            f"🎬 <b>{m['title']}</b>\n"
            f"🔑 Kod: <code>{m['code']}</code>\n"
            f"📊 {vip}Yuklanishlar: {m['download_count']}\n\n"
            f"{m['description'] or ''}"
        )
        results.append(InlineQueryResultArticle(
            id=str(m["id"]),
            title=f"{vip}{m['title']}",
            description=f"Kod: {m['code']} | {m['genre'] or ''}",
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode=ParseMode.HTML,
            ),
        ))
    if not results:
        results.append(InlineQueryResultArticle(
            id="0", title="Hech narsa topilmadi",
            description="Boshqa so'z bilan urinib ko'ring",
            input_message_content=InputTextMessageContent(message_text="❌ Natija topilmadi."),
        ))
    await query.answer(results, is_personal=True, cache_time=5)

# === ISHGA TUSHIRISH ===

async def on_startup(bot: Bot):
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start",            description="Boshlash"),
        BotCommand(command="help",             description="Yordam"),
        BotCommand(command="kino",             description="Kino olish (kod bo'yicha)"),
        BotCommand(command="top",              description="Top kinolar"),
        BotCommand(command="janr",             description="Janr bo'yicha"),
        BotCommand(command="sevimlilar",       description="Sevimlilarim"),
        BotCommand(command="vip",              description="VIP obuna"),
        BotCommand(command="vip_holat",        description="VIP holatim"),
        BotCommand(command="kanal",            description="Kanal ulash"),
        BotCommand(command="qidir",            description="Kanaldan qidirish"),
        BotCommand(command="admin",            description="Admin panel"),
        BotCommand(command="stats",            description="Statistika"),
    ])

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN o'rnatilmagan!")
        raise SystemExit(1)
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS o'rnatilmagan — admin buyruqlari ishlamaydi.")

    init_db()
    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp.startup.register(on_startup)

    logger.info("Kinotarif Bot ishga tushdi.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
