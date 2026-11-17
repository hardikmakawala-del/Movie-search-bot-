import os
import base64
from pyrogram import Client, filters
from pyrogram.types import Message

# --- CONFIG ---
API_ID = 29181523  # Tamaro API_ID nakho
API_HASH = "ba9b8c523e7a8714785bb5480ace5089"  # Tamaro API_HASH nakho
BOT_TOKEN = "9094525892:AAEK_DGomyfOFdZlDJnM2UUYHzmojvLXdMg"  # @BotFather mathi lidhelo token
LOG_CHANNEL = -1003957933627  # Tamari private log channel ni ID (Bot ne admin banavvo jaruri che)
ADMINS = [8723214887]  # Tamari Telegram User ID (je bot ne file mokli shake)

app = Client(
    "FileShareBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Encode & Decode helper functions
def encode(string: str) -> str:
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    return base64_bytes.decode("ascii").strip("=")

def decode(base64_string: str) -> str:
    base64_string = base64_string.strip("=")
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes)
    return string_bytes.decode("ascii")

# 1. Start Command (Link open thay tyare file moklva mate)
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    if len(message.command) > 1:
        try:
            encoded_data = message.command[1]
            decoded_data = decode(encoded_data)
            # Format: get-<msg_id>
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

    await message.reply_text(
        "👋 **Namaste!**\n\nHu ek File Sharing Bot chu. Mane koi pan file forward karo (Admin only) ane hu tamne teni shareable link aapi dais."
    )

# 2. Admin jyare bot ne private ma file mokle tyare
@app.on_message(filters.private & filters.user(ADMINS) & (filters.document | filters.video | filters.audio))
async def handle_admin_file(client: Client, message: Message):
    # File ne Log Channel ma copy karvi
    log_msg = await message.copy(chat_id=LOG_CHANNEL)
    
    # Unique Link generate karvi
    encoded_id = encode(f"get-{log_msg.id}")
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me{bot_username}?start={encoded_id}"
    
    await message.reply_text(
        f"✅ **File Log Channel ma save thai gai che!**\n\n🔗 **Share Link:**\n`{share_link}`",
        quote=True
    )

# 3. Direct Log Channel ma upload thay to pan link generate karva mate
@app.on_message(filters.chat(LOG_CHANNEL) & (filters.document | filters.video | filters.audio))
async def handle_channel_post(client: Client, message: Message):
    encoded_id = encode(f"get-{message.id}")
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me{bot_username}?start={encoded_id}"
    
    # Admin ne link DM kari dese
    for admin in ADMINS:
        try:
            await client.send_message(
                chat_id=admin,
                text=f"📥 **Log Channel ma navi file aavi!**\n\n🔗 **Share Link:**\n`{share_link}`"
            )
        except Exception:
            pass

print("Bot chalu thai gayo che...")
app.run()
