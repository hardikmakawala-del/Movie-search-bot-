import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())

import os
import base64
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message

# --- CONFIG ---
API_ID = 29181523
API_HASH = "ba9b8c523e7a8714785bb5480ace5089"
BOT_TOKEN = "9094525892:AAEK_DGomyfOFdZlDJnM2UUYHzmojvLXdMg"
LOG_CHANNEL = -1003957933627
ADMINS = [8723214887]

app = Client(
    "FileShareBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Render Web Service mate Dummy Web Server
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

def encode(string: str) -> str:
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    return base64_bytes.decode("ascii").strip("=")

def decode(base64_string: str) -> str:
    base64_string = base64_string.strip("=")
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes)
    return string_bytes.decode("ascii")

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    if len(message.command) > 1:
        try:
            encoded_data = message.command[1]
            decoded_data = decode(encoded_data)
            if decoded_data.startswith("get-"):
                msg_id = int(decoded_data.split("-")[1])
                await client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=LOG_CHANNEL,
                    message_id=msg_id
                )
                return
        except Exception as e:
            await message.reply_text(f"❌ Link expired che athva file delete thai gai che.\nError: `{e}`")
            return

    await message.reply_text("👋 **Namaste!** Mane koi pan file forward karo (Admin only) ane hu teni shareable link aapi dais.")

@app.on_message(filters.private & filters.user(ADMINS) & (filters.document | filters.video | filters.audio))
async def handle_admin_file(client: Client, message: Message):
    log_msg = await message.copy(chat_id=LOG_CHANNEL)
    encoded_id = encode(f"get-{log_msg.id}")
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me{bot_username}?start={encoded_id}"
    
    await message.reply_text(
        f"✅ **File Log Channel ma save thai gai che!**\n\n🔗 **Share Link:**\n`{share_link}`",
        quote=True
    )

@app.on_message(filters.chat(LOG_CHANNEL) & (filters.document | filters.video | filters.audio))
async def handle_channel_post(client: Client, message: Message):
    encoded_id = encode(f"get-{message.id}")
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me{bot_username}?start={encoded_id}"
    
    for admin in ADMINS:
        try:
            await client.send_message(
                chat_id=admin,
                text=f"📥 **Log Channel ma navi file aavi!**\n\n🔗 **Share Link:**\n`{share_link}`"
            )
        except Exception:
            pass

async def main():
    await start_web_server()
    await app.start()
    print("Bot ane Web Server chalu thai gaya che...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
