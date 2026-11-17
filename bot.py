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

    # Links filter out kari didhi che jethi text/description ma links na dekhay
    description_lines = []  
    for line in lines:  
        if line == lines[0] or re.fullmatch(r"[\W_]+", line, flags=re.UNICODE):  
            continue  
        if re.search(r"\b(480|720|1080)\s*p\b", line, re.I):  
            continue  
        if "http://" in line or "https://" in line:  
            continue
        if YEAR_RE.fullmatch(re.sub(r"^[^\d]*|[^\d]*$", "", line)):  
            continue  
        if line.startswith("⊰") or line.startswith("⏬") or line.startswith("♻️"):  
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
