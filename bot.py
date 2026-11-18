import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message

# --- CONFIG ---
API_ID = 29181523
API_HASH = "ba9b8c523e7a8714785bb5480ace5089"
BOT_TOKEN = "9094525892:AAEj2C4tFkUeJ36GaDzDK03sdio48iU_xqY"
LOG_CHANNEL = -1003957933627
ADMINS =

DB_FILE = "movies_db.json"

app = Client(
    "MovieLinkSearchBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Simple JSON Database (No MongoDB needed)
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

movies_db = load_db()

# Render Web Service mate Dummy Web Server
async def handle(request):
    return web.Response(text="Movie Link Search Bot is running!")

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# 1. Start Command
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "🎬 **Namaste! Movie Search Bot ma tamaru swagat che.**\n\n"
        "Tamare je movie ni link joiti hoy tenu naam lakho (jem ke: `Jailer 2`), hu tarat j download link mokli aapis!"
    )

# 2. Log Channel ma navi post aave etle save karva mate
@app.on_message(filters.chat(LOG_CHANNEL))
async def save_channel_post(client: Client, message: Message):
    text_content = message.caption or message.text
    if not text_content:
        return

    # Duplicate check
    for item in movies_db:
        if item["msg_id"] == message.id:
            item["text"] = text_content.lower()
            save_db(movies_db)
            return

    movies_db.append({
        "msg_id": message.id,
        "text": text_content.lower()
    })
    save_db(movies_db)
    print(f"Saved post ID: {message.id}")

# 3. Admin bot ne direct forward kare to pan Log Channel ma save kari le
@app.on_message(filters.private & filters.user(ADMINS) & ~filters.command("start") & (filters.photo | filters.video | filters.document))
async def admin_forward_post(client: Client, message: Message):
    copied = await message.copy(chat_id=LOG_CHANNEL)
    text_content = message.caption or message.text or ""
    if text_content:
        movies_db.append({
            "msg_id": copied.id,
            "text": text_content.lower()
        })
        save_db(movies_db)
    await message.reply_text("✅ **Tamari movie post Log Channel ma save thai gai che!** Have koi pan user naam lakhshe to aa post mali jashe.")

# 4. User jyare movie nu naam lakhe tyare search karva mate
@app.on_message(filters.private & filters.text & ~filters.command("start"))
async def search_movie(client: Client, message: Message):
    query = message.text.strip().lower()
    if len(query) < 2:
        await message.reply_text("⚠️ Kripya movie nu puro naam lakho.")
        return

    matched_ids = [item["msg_id"] for item in movies_db if query in item["text"]]

    if not matched_ids:
        await message.reply_text(
            f"❌ **'{message.text}'** naam ni koi movie mali nathi.\n\n"
            "Spelling check karine fari try karo athva thodi var pachi check karo."
        )
        return

    # Latest 3 matching posts moklse
    for msg_id in reversed(matched_ids[-3:]):
        try:
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=LOG_CHANNEL,
                message_id=msg_id
            )
        except Exception as e:
            print(f"Error copying {msg_id}: {e}")

async def main():
    await start_web_server()
    await app.start()
    print("Movie Link Search Bot chalu thai gayo che...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
