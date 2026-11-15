import os
import logging
import asyncio
from urllib.parse import urlparse
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "9094525892:AAEK_DGomyfOFdZlDJnM2UUYHzmojvLXdMg")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://movie_search_db_icdn_user:WR85z0QEg1sxQunFEeFkQP2dBp33AfQk@dpg-dbq4kh2jnfac73f3iivg-a/movie_search_db_icdn")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8723214887"))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://movie-search-bot-mm1.onrender.com").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "moviebot-hook-7x9k2").strip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "bfd93db54adbf04ccc8f76e6aaf3e5a7").strip()
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "-1004443842685").strip()

DB_POOL = None

def init_pool():
    global DB_POOL
    dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    DB_POOL = ThreadedConnectionPool(1, 8, dsn, cursor_factory=RealDictCursor)

def init_db():
    with DB_POOL.getconn() as conn:
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
                    download_480 TEXT NOT NULL DEFAULT '',
                    download_720 TEXT NOT NULL DEFAULT '',
                    download_1080 TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            conn.commit()
            DB_POOL.putconn(conn)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("નમસ્તે! Movie Bot ચાલુ છે.")

def main():
    init_pool()
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    webhook_url = f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}"
    log.info("Starting webhook at %s", webhook_url)
    
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET,
    )

if __name__ == "__main__":
    main()
    
