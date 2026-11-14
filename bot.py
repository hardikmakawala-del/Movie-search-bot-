import os
import re
import logging
import asyncio
from contextlib import contextmanager
from urllib.parse import urlparse

from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
RENDER_EXTERNAL_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_PATH = os.environ["WEBHOOK_PATH"].strip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].strip()
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "").strip()

GENRES = [
    "Action", "Comedy", "Drama", "Horror", "Romance",
    "Thriller", "Sci-Fi", "Animation", "Adventure", "Crime",
]
LANGUAGES = [
    "Hindi", "Gujarati", "English", "Tamil", "Telugu",
    "Malayalam", "Kannada", "Bengali", "Korean", "Japanese", "Other",
]

DB_POOL = None

QUALITY_PATTERNS = {
    "download_480": re.compile(r"\b480\sp\b\s[:-]\s*(https?://\S+)", re.I),
    "download_720": re.compile(r"\b720\sp\b\s[:-]\s*(https?://\S+)", re.I),
    "download_1080": re.compile(r"\b1080\sp\b\s[:-]\s*(https?://\S+)", re.I),
}
YEAR_RE = re.compile(r"\b(18[8-9]\d|19\d{2}|20\d{2}|2100)\b")
LANGUAGE_TAGS = {
    "hindi": "Hindi", "gujarati": "Gujarati", "english": "English",
    "tamil": "Tamil", "telugu": "Telugu", "telegu": "Telugu",
    "malayalam": "Malayalam", "kannada": "Kannada", "kan": "Kannada",
    "bengali": "Bengali", "korean": "Korean", "japanese": "Japanese",
}

def init_pool():
    global DB_POOL
    dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    DB_POOL = ThreadedConnectionPool(1, 8, dsn, cursor_factory=RealDictCursor)

@contextmanager
def db_connection():
    if DB_POOL is None:
        raise RuntimeError("Database pool has not been initialized")
    conn = DB_POOL.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        DB_POOL.putconn(conn)

def init_db():
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS movies (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    year INTEGER,
                    language TEXT NOT NULL DEFAULT 'Other',
                    genres TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    poster_url TEXT NOT NULL DEFAULT '',
                    official_url TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE movies ADD COLUMN IF NOT EXISTS download_480 TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE movies ADD COLUMN IF NOT EXISTS download_720 TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE movies ADD COLUMN IF NOT EXISTS download_1080 TEXT NOT NULL DEFAULT ''")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS movies_title_idx
                ON movies USING GIN (to_tsvector('simple', title))
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS movies_created_at_idx
                ON movies (created_at DESC)
            """)

def home_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔎 Search movie"), KeyboardButton("🎭 Browse genres")],
            [KeyboardButton("🌍 Browse languages"), KeyboardButton("🆕 Latest movies")],
            [KeyboardButton("ℹ️ Help")],
        ],
        resize_keyboard=True,
    )

def list_keyboard(values, prefix):
    rows = []
    for i in range(0, len(values), 2):
        rows.append([
            InlineKeyboardButton(v, callback_data=f"{prefix}:{v}")
            for v in values[i:i + 2]
        ])
    return InlineKeyboardMarkup(rows)

def find_movies_db(search_text=None, field=None, value=None, limit=8):
    with db_connection() as conn:
        with conn.cursor() as cur:
            if search_text:
                term = search_text.strip()
                pattern = f"%{term}%"
                cur.execute("""
                    SELECT * FROM movies
                    WHERE title ILIKE %s
                    OR to_tsvector('simple', title) @@ plainto_tsquery('simple', %s)
                    ORDER BY year DESC NULLS LAST, title
                    LIMIT %s
                """, (pattern, term, limit))
            elif field == "genre":
                cur.execute("""
                    SELECT * FROM movies
                    WHERE genres ILIKE %s
                    ORDER BY year DESC NULLS LAST, title LIMIT %s
                """, (f"%{value}%", limit))
            elif field == "language":
                cur.execute("""
                    SELECT * FROM movies
                    WHERE language ILIKE %s
                    ORDER BY year DESC NULLS LAST, title LIMIT %s
                """, (value, limit))
            else:
                cur.execute("""
                    SELECT * FROM movies
                    ORDER BY created_at DESC, year DESC NULLS LAST
                    LIMIT %s
                """, (limit,))
            return cur.fetchall()

def format_movie(movie):
    year = movie["year"] if movie["year"] else "N/A"
    genres = movie["genres"] or "Not specified"
    description = (movie["description"] or "No description added.")[:650]

    text = (
        f"🎬 {movie['title']} ({year})\n"
        f"🌍 Language: {movie['language']}\n"
        f"🎭 Genre: {genres}\n\n"
        f"{description}"
    )
    if movie.get("official_url"):
        text += f"\n\n🔗 Official page: {movie['official_url']}"
    return text[:1000]

def download_keyboard(movie):
    buttons = []
    for label, field in (
        ("480p Download", "download_480"),
        ("720p Download", "download_720"),
        ("1080p Download", "download_1080"),
    ):
        url = movie.get(field) or ""
        if url and urlparse(url).scheme in ("http", "https"):
            buttons.append([InlineKeyboardButton(label, url=url)])
    return InlineKeyboardMarkup(buttons) if buttons else None

async def show_movies(message, movies):
    if not movies:
        await message.reply_text("આ શોધ માટે કોઈ ફિલ્મ મળી નથી. બીજી રીતે શોધી જુઓ.")
        return

    for movie in movies:
        text = format_movie(movie)
        markup = download_keyboard(movie)
        poster = movie.get("poster_url") or ""
        if poster:
            try:
                await message.reply_photo(
                    photo=poster,
                    caption=text,
                    reply_markup=markup,
                )
                continue
            except Exception:
                log.exception("Could not send poster for movie id=%s", movie["id"])

        await message.reply_text(
            text,
            disable_web_page_preview=True,
            reply_markup=markup,
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "નમસ્તે! 🎬 Movie Search & Filter Bot માં સ્વાગત છે.\n\n"
        "ફિલ્મનું નામ શોધો અથવા Genre / Language પ્રમાણે browse કરો.",
        reply_markup=home_keyboard(),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ઉપયોગ:\n"
        "• Search movie: ફિલ્મનું નામ લખો\n"
        "• Browse genres: genre પસંદ કરો\n"
        "• Browse languages: ભાષા પસંદ કરો\n"
        "• Latest movies: તાજેતરમાં ઉમેરેલી ફિલ્મો",
        reply_markup=home_keyboard(),
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "🔎 Search movie":
        context.user_data["mode"] = "search"
        await update.message.reply_text("ફિલ્મનું નામ લખો:")
    elif text == "🎭 Browse genres":
        await update.message.reply_text("Genre પસંદ કરો:", reply_markup=list_keyboard(GENRES, "genre"))
    elif text == "🌍 Browse languages":
        await update.message.reply_text("Language પસંદ કરો:", reply_markup=list_keyboard(LANGUAGES, "language"))
    elif text == "🆕 Latest movies":
        movies = await asyncio.to_thread(find_movies_db)
        await show_movies(update.message, movies)
    elif text == "ℹ️ Help":
        await help_command(update, context)
    else:
        movies = await asyncio.to_thread(find_movies_db, text)
        await show_movies(update.message, movies)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kind, value = query.data.split(":", 1)
    if kind == "genre":
        movies = await asyncio.to_thread(find_movies_db, None, "genre", value)
        await query.message.reply_text(f"🎭 Genre: {value}")
        await show_movies(query.message, movies)
    elif kind == "language":
        movies = await asyncio.to_thread(find_movies_db, None, "language", value)
        await query.message.reply_text(f"🌍 Language: {value}")
        await show_movies(query.message, movies)

def main():
    init_pool()
    init_db()

    app = Application.builder().token(BOT_TOKEN).concurrent_updates(8).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(genre|language):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    webhook_url = f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}"
    log.info("Starting webhook at %s", webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,
    )

if __name__ == "__main__":
    main()
    
