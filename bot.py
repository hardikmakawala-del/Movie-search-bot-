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
    InlineQueryResultArticle, InputTextMessageContent,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    InlineQueryHandler, ContextTypes, filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# Direct Credentials Setup
BOT_TOKEN = "9094525892:AAEK_DGomyfOFdZlDJnM2UUYHzmojvLXdMg"
DATABASE_URL = "postgresql://movie_search_db_icdn_user:WR85z0QEg1sxQunFEeFkQP2dBp33AfQk@dpg-dbq4kh2jnfac73f3iivg-a/movie_search_db_icdn"
ADMIN_ID = 8723214887
LOG_CHANNEL_ID = "-1004443842685".strip()

GENRES = [
    "Action", "Comedy", "Drama", "Horror", "Romance",
    "Thriller", "Sci-Fi", "Animation", "Adventure", "Crime",
]
LANGUAGES = [
    "Hindi", "Gujarati", "English", "Tamil", "Telugu",
    "Malayalam", "Kannada", "Bengali", "Korean", "Japanese", "Other",
]

DB_POOL = None

# Improved patterns to easily catch quality links from channel captions
QUALITY_PATTERNS = {
    "download_480": re.compile(r"480p.*?['\"]?(https?://\S+)['\"]?", re.I),
    "download_720": re.compile(r"720p.*?['\"]?(https?://\S+)['\"]?", re.I),
    "download_1080": re.compile(r"1080p.*?['\"]?(https?://\S+)['\"]?", re.I),
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

def parse_movie_post(caption):
    lines = [line.strip() for line in (caption or "").splitlines() if line.strip()]
    if not lines:
        return None

    title = ""  
    for line in lines:  
        if re.fullmatch(r"[\W_]+", line, flags=re.UNICODE):  
            continue  
        if re.search(r"\b(480|720|1080)\s*p\b", line, re.I):  
            continue  
        if YEAR_RE.search(line) and len(line) < 16 and not re.search(r"[A-Za-z]{3}", line):  
            continue  
        cleaned = re.sub(r"^[^\w]+", "", line, flags=re.UNICODE).strip()  
        cleaned = re.sub(r"[*_`]", "", cleaned).strip()  
        if cleaned and not cleaned.startswith("#"):  
            title = cleaned  
            break  

    if not title:  
        title = lines[0] # Fallback to first line if regex misses

    year_match = YEAR_RE.search(caption or "")  
    year = int(year_match.group(1)) if year_match else None  

    language = "Other"  
    tags = re.findall(r"#([A-Za-z]+)", caption or "")  
    for tag in tags:  
        if tag.lower() in LANGUAGE_TAGS:  
            language = LANGUAGE_TAGS[tag.lower()]  
            break  

    links = {}  
    for field, pattern in QUALITY_PATTERNS.items():  
        match = pattern.search(caption or "")  
        if match:  
            url = match.group(1).rstrip(".,;)]}>")  
            if urlparse(url).scheme in ("http", "https"):  
                links[field] = url  

    description = "\n".join(lines).strip()  
    return {  
        "title": title[:250],  
        "year": year,  
        "language": language,  
        "genres": "Action/Comedy", # Default or extract if possible
        "description": description[:2000],  
        "links": links,  
    }

def save_channel_movie_db(title, year, language, genres, description, poster_id, links):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM movies
                WHERE LOWER(title) = LOWER(%s)
                AND year IS NOT DISTINCT FROM %s
                ORDER BY id DESC LIMIT 1
            """, (title, year))
            existing = cur.fetchone()

            if existing:  
                cur.execute("""  
                    UPDATE movies SET  
                        language = %s,  
                        genres = CASE WHEN %s <> '' THEN %s ELSE genres END,  
                        description = %s,  
                        poster_url = CASE WHEN %s <> '' THEN %s ELSE poster_url END,  
                        download_480 = CASE WHEN %s <> '' THEN %s ELSE download_480 END,  
                        download_720 = CASE WHEN %s <> '' THEN %s ELSE download_720 END,  
                        download_1080 = CASE WHEN %s <> '' THEN %s ELSE download_1080 END  
                    WHERE id = %s  
                """, (  
                    language, genres, genres, description,  
                    poster_id, poster_id,  
                    links.get("download_480", ""), links.get("download_480", ""),  
                    links.get("download_720", ""), links.get("download_720", ""),  
                    links.get("download_1080", ""), links.get("download_1080", ""),  
                    existing["id"],  
                ))  
                return existing["id"], False  

            cur.execute("""  
                INSERT INTO movies (  
                    title, year, language, genres, description, poster_url,  
                    download_480, download_720, download_1080  
                )  
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)  
                RETURNING id  
            """, (  
                title, year, language, genres, description, poster_id,  
                links.get("download_480", ""),  
                links.get("download_720", ""),  
                links.get("download_1080", ""),  
            ))  
            return cur.fetchone()["id"], True

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
        "નમસ્તે! 🎬 AutoFilter Movie Bot માં સ્વાગત છે.\n\n"
        "ફિલ્મનું નામ શોધો અથવા ગમે તે chat માં `@botusername movie_name` લખીને search કરો!",
        reply_markup=home_keyboard(),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ઉપયોગ:\n"
        "• Search movie: ફિલ્મનું નામ લખો\n"
        "• Inline Search: ગમે તે group/chat માં `@your_bot_username movie_name` લખો\n"
        "• Browse genres / languages: બટનથી શોધો\n"
        "• AutoFilter: Channel માં પોસ્ટ મૂકતાની સાથે bot માં આવી જશે.",
        reply_markup=home_keyboard(),
    )

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        return

    movies = await asyncio.to_thread(find_movies_db, query, None, None, 10)
    results = []
    for movie in movies:
        text = format_movie(movie)
        results.append(
            InlineQueryResultArticle(
                id=str(movie["id"]),
                title=f"{movie['title']} ({movie['year'] or 'N/A'})",
                description=f"Language: {movie['language']} | Click to get links",
                input_message_content=InputTextMessageContent(text),
                reply_markup=download_keyboard(movie),
            )
        )
    await update.inline_query.answer(results, cache_time=5)

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:  
        return  
    if not LOG_CHANNEL_ID:  
        return  
    if str(chat.id) != LOG_CHANNEL_ID and (chat.username or "").lower() != LOG_CHANNEL_ID.lstrip("@").lower():  
        return  

    caption = message.caption or message.text or ""  
    parsed = parse_movie_post(caption)  
    if not parsed:  
        return  

    poster_id = message.photo[-1].file_id if message.photo else ""  
    try:  
        movie_id, is_new = await asyncio.to_thread(  
            save_channel_movie_db,  
            parsed["title"], parsed["year"], parsed["language"],  
            parsed["genres"], parsed["description"], poster_id, parsed["links"],  
        )
        
        # OPTIONAL: If you want the bot to automatically add buttons to the original channel post if it has links
        if parsed["links"]:
            # Fetch saved movie details to build markup
            with db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM movies WHERE id = %s", (movie_id,))
                    movie_row = cur.fetchone()
                    if movie_row:
                        markup = download_keyboard(movie_row)
                        if markup and message.photo:
                            try:
                                await context.bot.edit_message_caption(
                                    chat_id=chat.id,
                                    message_id=message.message_id,
                                    caption=message.caption,
                                    reply_markup=markup
                                )
                            except Exception:
                                pass
    except Exception:  
        log.exception("Failed to import channel post")

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
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_post))  
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))  

    log.info("Starting bot with AutoFilter & Inline features...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
                
