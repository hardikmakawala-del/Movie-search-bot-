import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())

import os
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.types import Message

# --- CONFIG ---
API_ID = 29181523
API_HASH = "ba9b8c523e7a8714785bb5480ace5089"
BOT_TOKEN = "9094525892:AAG4iOH12KHuJBLoekDBSfNtqPDxOrHjOPc"
LOG_CHANNEL = -1004443842685
ADMINS = [8723214887]

app = Client(
    "MovieLinkSearchBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

movies_db = []

async def handle(request):
    return web.Response(text=f"Bot is live! Movies: {len(movies_db)}")

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def index_old_posts():
    global movies_db
    try:
        await app.get_chat(LOG_CHANNEL)
        temp_msg = await app.send_message(LOG_CHANNEL, "Syncing...")
        last_id = temp_msg.id
        await temp_msg.delete()

        start_id = max(1, last_id - 300)
        msg_ids = list(range(start_id, last_id))
        
        seen_texts = set()
        indexed_list = []
        for i in range(0, len(msg_ids), 100):
            batch = msg_ids[i:i+100]
            messages = await app.get_messages(LOG_CHANNEL, batch)
            for msg in messages:
                if msg and not msg.empty:
                    text_content = msg.caption or msg.text
                    if text_content:
                        clean = text_content.strip().lower()
                        if clean not in seen_texts:
                            seen_texts.add(clean)
                            indexed_list.append({"msg_id": msg.id, "text": clean})
        
        movies_db = indexed_list
        print(f"Indexed {len(movies_db)} movies!")
    except Exception as e:
        print(f"Index error: {e}")

@app.on_message(filters.command(["start", "ping"]))
async def start_cmd(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    await message.reply_text(
        f"🎬 **Bot Chalu Che!**\n"
        f"📂 Total Movies Ready: **{len(movies_db)}**\n\n"
        "Movie nu naam lakho (jem ke: `Ramayana`), hu link mokli aapis!"
    )

@app.on_message(filters.chat(LOG_CHANNEL))
async def save_channel_post(client: Client, message: Message):
    text_content = message.caption or message.text
    if not text_content or text_content == "Syncing...":
        return

    clean_text = text_content.strip().lower()
    movies_db[:] = [item for item in movies_db if item["text"] != clean_text and item["msg_id"] != message.id]
    movies_db.append({"msg_id": message.id, "text": clean_text})

@app.on_message(filters.private & filters.user(ADMINS) & ~filters.command(["start", "ping"]) & (filters.photo | filters.video | filters.document))
async def admin_forward_post(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    try:
        copied = await message.copy(chat_id=LOG_CHANNEL)
        text_content = message.caption or message.text or ""
        if text_content:
            clean_text = text_content.strip().lower()
            movies_db[:] = [item for item in movies_db if item["text"] != clean_text]
            movies_db.append({"msg_id": copied.id, "text": clean_text})
        await message.reply_text("✅ **Movie post save thai gai che!**")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")

@app.on_message(filters.text & ~filters.command(["start", "ping"]))
async def search_movie(client: Client, message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    if message.chat.id == LOG_CHANNEL:
        return

    query = message.text.strip().lower()
    if len(query) < 2 or len(query) > 60:
        return

    matched_ids = []
    seen = set()
    for item in reversed(movies_db):
        if query in item["text"] and item["msg_id"] not in seen:
            matched_ids.append(item["msg_id"])
            seen.add(item["msg_id"])
            if len(matched_ids) >= 2:
                break

    if not matched_ids:
        if message.chat.type == enums.ChatType.PRIVATE:
            await message.reply_text(f"❌ **'{message.text}'** naam ni koi movie mali nathi.")
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
            print(f"Copy error {msg_id}: {e}")

async def main():
    await start_web_server()
    await app.start()
    await index_old_posts()
    print("Bot ready for Group and Private!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
