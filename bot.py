import os
import re
import logging
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

GENRES = ["Action", "Comedy", "Drama", "Horror", "Romance", "Thriller", "Sci-Fi", "Animation", "Adventure", "Crime"]
LANGUAGES = ["Hindi", "Gujarati", "English", "Tamil", "Telugu", "Malayalam", "Kannada", "Bengali", "Korean", "Japanese", "Other"]

def db_connection():
    # Render may provide postgres://; psycopg2 accepts postgresql://.
    dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(dsn, cursor_factory=RealDictCursor)

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
            # Add quality-specific links safely to existing databases.
            cur.execute("ALTER TABLE movies ADD COLUMN IF NOT EXISTS download_480 TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE movies ADD COLUMN IF NOT EXISTS download_720 TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE movies ADD COLUMN IF NOT EXISTS download_1080 TEXT NOT NULL DEFAULT ''")
            cur.execute("CREATE INDEX IF NOT EXISTS movies_title_idx ON movies USING GIN (to_tsvector('simple', title))")
        conn.commit()

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
            for v in values[i:i+2]
        ])
    return InlineKeyboardMarkup(rows)

def find_movies(search_text=None, field=None, value=None, limit=8):
    with db_connection() as conn:
        with conn.cursor() as cur:
            if search_text:
                pattern = f"%{search_text.strip()}%"
                cur.execute("""
                    SELECT * FROM movies
                    WHERE title ILIKE %s OR language ILIKE %s
                       OR genres ILIKE %s OR COALESCE(description, '') ILIKE %s
                    ORDER BY year DESC NULLS LAST, title
                    LIMIT %s
                """, (pattern, pattern, pattern, pattern, limit))
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
    description = movie["description"] or "No description added."
    text = (
        f"🎬 *{movie['title']}* ({year})\n"
        f"🌍 Language: {movie['language']}\n"
        f"🎭 Genre: {genres}\n\n"
        f"{description}"
    )
    if movie["official_url"]:
        text += f"\n\n🔗 [Official / legal page]({movie['official_url']})"
    return text

def download_keyboard(movie):
    buttons = []
    for label, field in (("480p Download", "download_480"), ("720p Download", "download_720"), ("1080p Download", "download_1080")):
        url = movie.get(field) or ""
        if url:
            buttons.append([InlineKeyboardButton(label, url=url)])
    return InlineKeyboardMarkup(buttons) if buttons else None

async def show_movies(update_or_query, movies):
    if not movies:
        msg = "આ શોધ માટે કોઈ ફિલ્મ મળી નથી. બીજી રીતે શોધી જુઓ."
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(msg)
        else:
            await update_or_query.edit_message_text(msg)
        return

    for movie in movies:
        text = format_movie(movie)
        if movie["poster_url"]:
            try:
                if hasattr(update_or_query, "message") and update_or_query.message:
                    await update_or_query.message.reply_photo(
                        photo=movie["poster_url"], caption=text, parse_mode="Markdown",
                        reply_markup=download_keyboard(movie)
                    )
                else:
                    await update_or_query.message.reply_photo(
                        photo=movie["poster_url"], caption=text, parse_mode="Markdown",
                        reply_markup=download_keyboard(movie)
                    )
                continue
            except Exception:
                log.exception("Could not send poster for movie id=%s", movie["id"])

        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(
                text, parse_mode="Markdown", disable_web_page_preview=True,
                reply_markup=download_keyboard(movie)
            )
        else:
            await update_or_query.message.reply_text(
                text, parse_mode="Markdown", disable_web_page_preview=True,
                reply_markup=download_keyboard(movie)
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
        "• Latest movies: તાજેતરમાં ઉમેરેલી ફિલ્મો\n\n"
        "Admin માટે /addmovie command ઉપલબ્ધ છે.\n"
        "Download quality links (authorized links only) પણ ઉમેરાઈ શકે છે.",
        reply_markup=home_keyboard(),
    )

async def add_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID == 0 or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("આ command ફક્ત bot admin માટે છે.")
        return

    raw = update.message.text.partition(" ")[2].strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 10:
        await update.message.reply_text(
            "Format:\n/addmovie Title|Year|Language|Genre1,Genre2|Description|PosterURL|OfficialURL|480pURL|720pURL|1080pURL\n\n"
            "Example (use only links you are authorized to share):\n"
            "/addmovie Sample Film|2024|English|Drama,Thriller|A sample description||https://example.com/info|https://example.com/480|https://example.com/720|https://example.com/1080"
        )
        return

    title, year_text, language, genres, description, poster_url, official_url, download_480, download_720, download_1080 = parts
    try:
        year = int(year_text) if year_text else None
        if year and not (1888 <= year <= 2100):
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Year ખોટું છે. ઉદાહરણ: 2024")
        return

    for url in (poster_url, official_url, download_480, download_720, download_1080):
        if url and urlparse(url).scheme not in ("http", "https"):
            await update.message.reply_text("URL http:// અથવા https:// થી શરૂ થવો જોઈએ.")
            return

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO movies (title, year, language, genres, description, poster_url, official_url,
                                    download_480, download_720, download_1080)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (title, year, language, genres, description, poster_url, official_url,
                  download_480, download_720, download_1080))
        conn.commit()

    await update.message.reply_text(f"✅ '{title}' database માં ઉમેરાઈ ગઈ.")

async def delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID == 0 or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("આ command ફક્ત bot admin માટે છે.")
        return
    raw = update.message.text.partition(" ")[2].strip()
    if not raw.isdigit():
        await update.message.reply_text("ઉપયોગ: /deletemovie MOVIE_ID")
        return
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM movies WHERE id = %s RETURNING title", (int(raw),))
            row = cur.fetchone()
        conn.commit()
    await update.message.reply_text(
        f"🗑️ Deleted: {row['title']}" if row else "આ ID ની ફિલ્મ મળી નથી."
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "🔎 Search movie":
        context.user_data["mode"] = "search"
        await update.message.reply_text("ફિલ્મનું નામ લખો:")
    elif text == "🎭 Browse genres":
        await update.message.reply_text("Genre પસંદ કરો:", reply_markup=list_keyboard(GENRES, "genre"))
    elif text == "🌍 Browse languages":
        await update.message.reply_text("Language પસંદ કરો:", reply_markup=list_keyboard(LANGUAGES, "language"))
    elif text == "🆕 Latest movies":
        await show_movies(update, find_movies())
    elif text == "ℹ️ Help":
        await help_command(update, context)
    else:
        await show_movies(update, find_movies(search_text=text))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kind, value = query.data.split(":", 1)
    if kind == "genre":
        movies = find_movies(field="genre", value=value)
        await query.message.reply_text(f"🎭 Genre: {value}")
        await show_movies(query, movies)
    elif kind == "language":
        movies = find_movies(field="language", value=value)
        await query.message.reply_text(f"🌍 Language: {value}")
        await show_movies(query, movies)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addmovie", add_movie))
    app.add_handler(CommandHandler("deletemovie", delete_movie))
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
            
