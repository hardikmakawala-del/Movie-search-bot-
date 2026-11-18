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
LOG_CHANNEL = -1004443842685
ADMINS =

DB_FILE = "movies_db.json"

app = Client(
    "MovieLinkSearchBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Simple JSON Database with Duplicate Prevention
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
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
    print(f"Web server started on port {port}")

# 1. Start Command (Private + Group)
@app.on_message(filters.command("start") & (filters.private | filters.group))
async def start_cmd(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    await message.reply_text(
        "🎬 **Namaste! Movie Search Bot ma tamaru swagat che.**\n\n"
        "Tamare je movie ni link joiti hoy tenu naam lakho (jem ke: `Death of a Unicorn`), hu tarat j download link mokli aapis!"
    )

# 2. Log Channel ma navi post aave etle save karva mate (No Duplicate)
@app.on_message(filters.chat(LOG_CHANNEL))
async def save_channel_post(client: Client, message: Message):
    text_content = message.caption or message.text
    if not text_content:
        return

    clean_text = text_content.strip().lower()
    # Jo aa msg_id ke same caption pehle thi save hoy to update karo, navu na banavo
    for item in movies_db:
        if item["msg_id"] == message.id or item["text"] == clean_text:
            item["msg_id"] = message.id
            item["text"] = clean_text
            save_db(movies_db)
            return

    movies_db.append({
        "msg_id": message.id,
        "text": clean_text
    })
    save_db(movies_db)
    print(f"Saved post ID: {message.id}")

# 3. Admin bot ne direct forward kare to pan Log Channel ma save kari le
@app.on_message(filters.private & filters.user(ADMINS) & ~filters.command("start") & (filters.photo | filters.video | filters.document))
async def admin_forward_post(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    try:
        copied = await message.copy(chat_id=LOG_CHANNEL)
        text_content = message.caption or message.text or ""
        if text_content:
            clean_text = text_content.strip().lower()
            # Remove old duplicate if exists
            movies_db[:] = [item for item in movies_db if item["text"] != clean_text]
            movies_db.append({
                "msg_id": copied.id,
                "text": clean_text
            })
            save_db(movies_db)
        await message.reply_text("✅ **Tamari movie post Log Channel ma save thai gai che!** Have koi pan user (Private ke Group ma) naam lakhshe to aa post mali jashe.")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")

# 4. User jyare Private ke Group ma movie nu naam lakhe tyare search karva mate
@app.on_message((filters.private | filters.group) & filters.text & ~filters.command("start") & ~filters.bot)
async def search_movie(client: Client, message: Message):
    # Bot na potana messages ignore karo (Infinite loop rokva mate)
    if not message.from_user or message.from_user.is_bot:
        return

    query = message.text.strip().lower()
    if len(query) < 2 or len(query) > 60:
        return

    # Unique matching msg_ids shodhva
    matched_ids = []
    seen = set()
    for item in reversed(movies_db):
        if query in item["text"] and item["msg_id"] not in seen:
            matched_ids.append(item["msg_id"])
            seen.add(item["msg_id"])
            if len(matched_ids) >= 2:  # Ek sathe max 2 unique results moklse
                break

    if not matched_ids:
        # Fakt private chat ma j "nathi mali" reply aapse (Group ma spam na thay etle)
        if message.chat.type.value == "private":
            await message.reply_text(
                f"❌ **'{message.text}'** naam ni koi movie mali nathi.\n\n"
                "Spelling check karine fari try karo athva thodi var pachi check karo."
            )
        return

    for msg_id in matched_ids:
        try:
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=LOG_CHANNEL,
                message_id=msg_id,
                reply_to_message_id=message.id
            )
        except Exception as e:
            print(f"Error copying {msg_id}: {e}")

async def main():
    await start_web_server()
    await app.start()
    try:
        await app.get_chat(LOG_CHANNEL)
        print("Log Channel connected successfully!")
    except Exception as e:
        print(f"Log Channel warning: {e}")
    print("Movie Link Search Bot chalu thai gayo che...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
