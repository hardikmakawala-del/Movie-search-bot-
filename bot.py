import os
import re
import logging
import asyncio
from contextlib import contextmanager
from urllib.parse import urlparse

from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------
# Configuration: set these as Render Environment Variables.
# Never put real tokens or passwords directly in this file.
# ---------------------------------------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "").strip()

RENDER_EXTERNAL_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "movie-search-hook-2026").strip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is missing")
if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", WEBHOOK_SECRET):
    raise RuntimeError("WEBHOOK_SECRET must contain only letters, numbers, _ or -")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("movie_search_bot")

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
    "download_480": re.compile(r"480p.*?(https?://\S+)", re.I),
    "download_720": re.compile(r"720p.*?(https?://\S+)", re.I),
    "download_1080": re.compile(r"1080p.*?(https?://\S+)", re.I),
}
YEAR_RE = re.compile(r"\b(18[8-9]\d|19\d{2}|20\d{2}|2100)\b")
LANGUAGE_TAGS = {
    "hindi": "Hindi",
    "gujarati": "Gujarati",
    "english": "English",
    "tamil": "Tamil",
    "telugu": "Telugu",
    "telegu": "Telugu",
    "malayalam": "Malayalam",
    "kannada": "Kannada",
    "kan": "Kannada",
    "bengali": "Bengali",
    "korean": "Korean",
    "japanese": "Japanese",
}


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------
def init_pool():
    global DB_POOL
    dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    DB_POOL = ThreadedConnectionPool(
        minconn=1,
        maxconn=8,
        dsn=dsn,
        cursor_factory=RealDictCursor,
        connect_timeout=15,
    )
    log.info("PostgreSQL connection pool initialized")


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
            cur.execute("""
                ALTER TABLE movies
                ADD COLUMN IF NOT EXISTS download_480 TEXT NOT NULL DEFAULT ''
            """)
            cur.execute("""
                ALTER TABLE movies
                ADD COLUMN IF NOT EXISTS download_720 TEXT NOT NULL DEFAULT ''
            """)
            cur.execute("""
                ALTER TABLE movies
                ADD COLUMN IF NOT EXISTS download_1080 TEXT NOT NULL DEFAULT ''
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS movies_title_idx
                ON movies USING GIN (to_tsvector('simple', title))
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS movies_created_at_idx
                ON movies (created_at DESC)
            """)
    log.info("Database tables checked/initialized")


def find_movies_db(search_text=None, field=None, value=None, limit=8):
    with db_connection() as conn:
        with conn.cursor() as cur:
            if search_text:
                term = search_text.strip()
                pattern = f"%{term}%"
                cur.execute("""
                    SELECT * FROM movies
                    WHERE title ILIKE %s
                       OR to_tsvector('simple', title)
                          @@ plainto_tsquery('simple', %s)
                    ORDER BY year DESC NULLS LAST, title
                    LIMIT %s
                """, (pattern, term, limit))
            elif field == "genre":
                cur.execute("""
                    SELECT * FROM movies
                    WHERE genres ILIKE %s
                    ORDER BY year DESC NULLS LAST, title
                    LIMIT %s
                """, (f"%{value}%", limit))
            elif field == "language":
                cur.execute("""
                    SELECT * FROM movies
                    WHERE language ILIKE %s
                    ORDER BY year DESC NULLS LAST, title
                    LIMIT %s
                """, (value, limit))
            else:
                cur.execute("""
                    SELECT * FROM movies
                    ORDER BY created_at DESC, year DESC NULLS LAST
                    LIMIT %s
                """, (limit,))
            return cur.fetchall()


def save_channel_movie_db(
    title, year, language, genres, description, poster_id, links
):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM movies
                WHERE LOWER(title) = LOWER(%s)
                  AND year IS NOT DISTINCT FROM %s
                ORDER BY id DESC
                LIMIT 1
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
                    language,
                    genres, genres,
                    description,
                    poster_id, poster_id,
                    links.get("download_480", ""),
                    links.get("download_480", ""),
                    links.get("download_720", ""),
                    links.get("download_720", ""),
                    links.get("download_1080", ""),
                    links.get("download_1080", ""),
                    existing["id"],
                ))
                return existing["id"]

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
            return cur.fetchone()["id"]


def add_movie_db(values):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO movies (
                    title, year, language, genres, description, poster_url,
                    official_url, download_480, download_720, download_1080
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, values)
            return cur.fetchone()["id"]


def delete_movie_db(movie_id):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM movies WHERE id = %s RETURNING id", (movie_id,))
            return cur.fetchone()


# ---------------------------------------------------------------------
# Keyboards and movie display
# ---------------------------------------------------------------------
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


def format_movie(movie):
    title = movie.get("title") or "Unknown title"
    year = movie.get("year") or "N/A"
    language = movie.get("language") or "Other"
    genres = movie.get("genres") or "N/A"
    description = movie.get("description") or ""
    lines = [
        f"🍿 {title}",
        f"📅 Year: {year}",
        f"🌐 Language: {language}",
        f"🎭 Genre: {genres}",
    ]
    if description:
        lines.append("")
        lines.append(description[:900])
    return "\n".join(lines)


def download_keyboard(movie):
    buttons = []
    for label, key in (
        ("480p", "download_480"),
        ("720p", "download_720"),
        ("1080p", "download_1080"),
    ):
        url = (movie.get(key) or "").strip()
        if url.startswith(("https://", "http://")):
            buttons.append(InlineKeyboardButton(label, url=url))

    official_url = (movie.get("official_url") or "").strip()
    if official_url.startswith(("https://", "http://")):
        buttons.append(InlineKeyboardButton("Official link", url=official_url))

    if not buttons:
        return None
    return InlineKeyboardMarkup([buttons])


async def show_movies(message, movies):
    if not movies:
        await message.reply_text(
            "માફ કરશો, આ નામની કોઈ ફિલ્મ મળી નથી. બીજું નામ try કરો."
        )
        return

    for movie in movies:
        text = format_movie(movie)
        keyboard = download_keyboard(movie)
        poster = (movie.get("poster_url") or "").strip()

        if poster:
            try:
                await message.reply_photo(
                    photo=poster,
                    caption=text[:1024],
                    reply_markup=keyboard,
                )
                continue
            except Exception:
                log.exception("Could not send movie poster; sending text instead")

        await message.reply_text(text, reply_markup=keyboard)


# ---------------------------------------------------------------------
# Channel post parsing and saving
# ---------------------------------------------------------------------
def parse_movie_post(caption):
    lines = [
        line.strip()
        for line in (caption or "").splitlines()
        if line.strip()
    ]
    if not lines:
        return None

    title = ""
    for line in lines:
        if re.fullmatch(r"[\W_]+", line, flags=re.UNICODE):
            continue
        if re.search(r"\b(480|720|1080)\s*p\b", line, re.I):
            continue
        if (
            YEAR_RE.search(line)
            and len(line) < 16
            and not re.search(r"[A-Za-z]{3}", line)
        ):
            continue

        cleaned = re.sub(r"^[^\w]+", "", line, flags=re.UNICODE).strip()
        cleaned = re.sub(r"[*_`]", "", cleaned).strip()
        if cleaned and not cleaned.startswith("#"):
            title = cleaned
            break

    if not title:
        title = lines[0]

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

    description_lines = []
    for line in lines:
        if line == lines[0] or re.fullmatch(r"[\W_]+", line, flags=re.UNICODE):
            continue
        if re.search(r"\b(480|720|1080)\s*p\b", line, re.I):
            continue
        if "http://" in line or "https://" in line:
            continue
        stripped = re.sub(r"^[^\d]*|[^\d]*$", "", line)
        if YEAR_RE.fullmatch(stripped):
            continue
        if line.startswith(("⊰", "⏬", "♻️")):
            continue
        description_lines.append(line)

    description = "\n".join(description_lines).strip()
    return {
        "title": title[:250],
        "year": year,
        "language": language,
        "genres": "Action/Comedy",
        "description": description[:2000],
        "links": links,
    }


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if message is None:
        return

    if LOG_CHANNEL_ID and str(message.chat_id) != LOG_CHANNEL_ID:
        return

    caption = message.caption or message.text or ""
    parsed = parse_movie_post(caption)
    if not parsed:
        log.warning("Channel post did not contain a parsable movie caption")
        return

    poster_id = ""
    if message.photo:
        poster_id = message.photo[-1].file_id

    try:
        movie_id = await asyncio.to_thread(
            save_channel_movie_db,
            parsed["title"],
            parsed["year"],
            parsed["language"],
            parsed["genres"],
            parsed["description"],
            poster_id,
            parsed["links"],
        )
        log.info("Saved channel movie with database id %s", movie_id)

        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"✅ Movie saved/updated: {parsed['title']} (ID: {movie_id})",
                )
            except Exception:
                log.exception("Could not send admin channel-save notification")
    except Exception:
        log.exception("Failed to save movie from channel post")


# ---------------------------------------------------------------------
# Telegram command handlers
# ---------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    log.info("/start received")
    await update.effective_message.reply_text(
        "નમસ્તે! 🍿 Movie Search Bot માં આપનું સ્વાગત છે.\n\n"
        "ફિલ્મ શોધવા માટે Search movie દબાવો અથવા નીચેના options પસંદ કરો.",
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "મદદ:\n"
        "• 🔎 Search movie: ફિલ્મનું નામ લખો\n"
        "• 🎭 Browse genres: genre પ્રમાણે શોધો\n"
        "• 🌍 Browse languages: ભાષા પ્રમાણે શોધો\n"
        "• 🆕 Latest movies: તાજેતરમાં ઉમેરેલી ફિલ્મો\n\n"
        "Admin commands:\n"
        "/addmovie - ફિલ્મ ઉમેરો\n"
        "/deletemovie ID - ફિલ્મ કાઢી નાખો",
        reply_markup=home_keyboard(),
    )


async def add_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("આ command ફક્ત admin માટે છે.")
        return

    raw = update.effective_message.text.partition(" ")[2].strip()
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 10:
        await update.effective_message.reply_text(
            "Format:\n"
            "/addmovie title | year | language | genres | description | "
            "poster_url | official_url | 480p_url | 720p_url | 1080p_url"
        )
        return

    title, year_text, language, genres, description, poster, official, q480, q720, q1080 = parts
    try:
        year = int(year_text) if year_text else None
        values = (
            title, year, language or "Other", genres, description,
            poster, official, q480, q720, q1080,
        )
        movie_id = await asyncio.to_thread(add_movie_db, values)
        await update.effective_message.reply_text(
            f"✅ Movie added successfully. ID: {movie_id}"
        )
    except ValueError:
        await update.effective_message.reply_text("Year સાચું number હોવું જોઈએ.")
    except Exception:
        log.exception("Admin addmovie failed")
        await update.effective_message.reply_text(
            "Movie add કરતી વખતે error આવ્યો. Logs તપાસો."
        )


async def delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("આ command ફક્ત admin માટે છે.")
        return

    if not context.args:
        await update.effective_message.reply_text("Use: /deletemovie ID")
        return

    try:
        movie_id = int(context.args[0])
        deleted = await asyncio.to_thread(delete_movie_db, movie_id)
        if deleted:
            await update.effective_message.reply_text(
                f"🗑️ Movie ID {movie_id} deleted."
            )
        else:
            await update.effective_message.reply_text("આ IDની movie મળી નથી.")
    except ValueError:
        await update.effective_message.reply_text("ID number હોવો જોઈએ.")
    except Exception:
        log.exception("Admin deletemovie failed")
        await update.effective_message.reply_text(
            "Movie delete કરતી વખતે error આવ્યો."
        )


# ---------------------------------------------------------------------
# Search, menu, callback and inline handlers
# ---------------------------------------------------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return

    text = message.text.strip()
    log.info("Text message received")

    if text == "🔎 Search movie":
        context.user_data["mode"] = "search"
        await message.reply_text("ફિલ્મનું નામ લખો:")
        return

    if text == "🎭 Browse genres":
        context.user_data.pop("mode", None)
        await message.reply_text(
            "Genre પસંદ કરો:",
            reply_markup=list_keyboard(GENRES, "genr
