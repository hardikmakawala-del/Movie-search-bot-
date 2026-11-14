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

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
RENDER_EXTERNAL_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_PATH = os.environ["WEBHOOK_PATH"].strip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].strip()
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "").strip()

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
    
