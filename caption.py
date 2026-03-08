import asyncio
import time
import re
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, MessageNotModified, ChatAdminRequired, UsernameNotOccupied
from motor.motor_asyncio import AsyncIOMotorClient

# ============= Config se credentials import karo =============
from config import API_ID, API_HASH, BOT_TOKEN, MONGO_URI
# ==============================================================

# Database Setup
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["AutoCaptionBot"]
users_collection = db["users_data"]       # User ki settings ke liye
queue_collection = db["message_queue"]    # Pending messages track karne ke liye
state_collection = db["user_states"]      # Temporary states for button flows

# Bot Setup
app = Client("my_autocaption_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ----------------- Helper Functions -----------------

async def extract_channel_id_from_input(client, message):
    # 1. Agar kisi channel se message forward kiya hai
    if message.forward_from_chat and str(message.forward_from_chat.type) in ["ChatType.CHANNEL", "ChatType.SUPERGROUP", "channel", "supergroup"]:
        return message.forward_from_chat.id

    if message.text:
        text = message.text.strip()

        # 2. PRIVATE LINK Handle karna (t.me/c/123456789/...)
        private_match = re.search(r't\.me/c/(\d+)', text)
        if private_match:
            ch_id = private_match.group(1)
            # Agar id me -100 nahi hai, toh automatically laga dega
            if not ch_id.startswith("-100"):
                return int(f"-100{ch_id}")
            return int(ch_id)

        # 3. PUBLIC LINK Handle karna (t.me/username/...)
        public_match = re.search(r't\.me/([a-zA-Z0-9_]+)', text)
        if public_match and public_match.group(1).lower() != "c":
            username = public_match.group(1)
            try:
                chat = await client.get_chat(username)
                return chat.id  # Pyrogram public channels me khud -100 lagakar deta hai
            except Exception:
                pass

        # 4. DIRECT ID Handle karna (-100123456789 ya 123456789)
        # Check if text doesn't contain a link
        if "t.me" not in text and "http" not in text:
            cleaned = re.sub(r'[^\d-]', '', text)
            if cleaned and cleaned.lstrip('-').isdigit():
                raw_num = cleaned.lstrip('-') # Minus hatao check karne ke liye

                # Agar start me 100 nahi hai toh add karo
                if not raw_num.startswith("100"):
                    raw_num = "100" + raw_num

                # Wapas minus laga ke int bana do
                return int(f"-{raw_num}")

    return None

# ----------------- COMMANDS -----------------

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    text = (
        """👋Hi I am **OM Auto Caption Bot**.

🚀 **Features:**
✅ Safe Rate Limits (19 messages per minute)
✅ Smart Queue System (Koi bhi message lost nahi hoga)
✅ Automatic Error Handling
✅ Multiple Channels Support
✅ Easy Button Setup

⚙️ **Commands:**
/setchannel – Channel set karo (ID, forward ya link se)
/setbutton – Button create karo (text | link format)
/status – Apni current settings check karo

👇 Ya phir neeche diye gaye buttons use karke bhi easily setup kar sakte ho!"""
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
        [InlineKeyboardButton("🔘 Set Button", callback_data="set_button")],
        [InlineKeyboardButton("📊 Status", callback_data="check_status")]
    ])
    await message.reply_text(text, reply_markup=buttons)

@app.on_message(filters.command("setchannel") & filters.private)
async def set_channel(client, message):
    # Enhanced channel detection (same as before)
    channel_id = None

    if len(message.command) > 1:
        arg = message.text.split(" ", 1)[1]
        class Dummy:
            def __init__(self, text):
                self.text = text
                self.forward_from_chat = None
        dummy_msg = Dummy(arg)
        channel_id = await extract_channel_id_from_input(client, dummy_msg)
    elif message.reply_to_message:
        channel_id = await extract_channel_id_from_input(client, message.reply_to_message)

    if channel_id:
        # ---------- MULTI-CHANNEL FIX: $addToSet ----------
        await users_collection.update_one(
            {"user_id": message.from_user.id},
            {"$addToSet": {"channel_ids": channel_id}},
            upsert=True
        )
        await message.reply_text(f"✅ Channel ID `{channel_id}` successfully set ho gaya!")
    else:
        await message.reply_text(
            "❌ Mujhe channel ID nahi mili.\n\n"
            "Tum ya to:\n"
            "• Command ke saath channel ID likho: `/setchannel -100123456789`\n"
            "• Kisi channel ki koi post forward karo is message ke reply mein\n"
            "• Kisi channel ki post ka link bhejo is message ke reply mein\n"
            "• Ya phir /start karke 'Add Channel' button use karo."
        )

@app.on_message(filters.command("setbutton") & filters.private)
async def set_button(client, message):
    try:
        btn_data = message.text.split(" ", 1)[1]
        btn_text, btn_link = btn_data.split("|")
        btn_text = btn_text.strip()
        btn_link = btn_link.strip()
    except Exception:
        return await message.reply_text(
            "❌ Galat format! Aise use kar:\n`/setbutton Click Here | https://google.com`\n\n"
            "Ya phir /start karke 'Set Button' button use karo."
        )

    if not btn_link.startswith(("http://", "https://", "t.me/")):
        return await message.reply_text("❌ Link invalid hai. Link me http:// ya https:// hona chahiye.")

    await users_collection.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"btn_text": btn_text, "btn_link": btn_link}},
        upsert=True
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, url=btn_link)]])
    await message.reply_text("✅ Button set ho gaya! Ye aisa dikhega:", reply_markup=markup)

@app.on_message(filters.command("status") & filters.private)
async def check_status(client, message):
    data = await users_collection.find_one({"user_id": message.from_user.id})
    pending_count = await queue_collection.count_documents({})

    if not data:
        return await message.reply_text("❌ Tune abhi tak kuch set nahi kiya hai.")

    # ---------- MULTI-CHANNEL FIX: show list ----------
    channels_list = data.get("channel_ids", [])
    if channels_list:
        ch_text = "\n".join([f"• `{ch}`" for ch in channels_list])
    else:
        ch_text = "Not set"

    b_text = data.get("btn_text", "Not set")
    b_link = data.get("btn_link", "Not set")

    await message.reply_text(
        f"📊 **Tera Status:**\n\n"
        f"**Linked Channels:**\n{ch_text}\n\n"
        f"**Button Text:** `{b_text}`\n"
        f"**Button Link:** `{b_link}`\n\n"
        f"🔄 **Pending Messages in Queue:** `{pending_count}`"
    )

# ----------------- CALLBACK QUERIES -----------------

@app.on_callback_query()
async def handle_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if data == "add_channel":
        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {"step": "waiting_for_channel"}},
            upsert=True
        )
        await callback_query.message.edit_text(
            "📢 **Add Channel**\n\n"
            "Ab mujhe channel ki jankari do. Tum ye kar sakte ho:\n"
            "• Channel ID bhejo (jaise `-100123456789`)\n"
            "• Channel ki koi post forward karo yahan\n"
            "• Channel ki kisi post ka link bhejo\n\n"
            "Jaise hi mujhe information milegi, main channel set kar dunga."
        )
        await callback_query.answer()

    elif data == "set_button":
        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {"step": "waiting_for_button_text"}},
            upsert=True
        )
        await callback_query.message.edit_text(
            "🔘 **Set Button**\n\n"
            "Sabse pehle mujhe button ka **text** bhejo.\n"
            "Jaise: `Visit Website`"
        )
        await callback_query.answer()

    elif data == "check_status":
        # Show status (same as /status but in callback)
        data = await users_collection.find_one({"user_id": user_id})
        pending_count = await queue_collection.count_documents({})

        if not data:
            await callback_query.message.edit_text("❌ Tune abhi tak kuch set nahi kiya hai.")
        else:
            channels_list = data.get("channel_ids", [])
            if channels_list:
                ch_text = "\n".join([f"• `{ch}`" for ch in channels_list])
            else:
                ch_text = "Not set"
            b_text = data.get("btn_text", "Not set")
            b_link = data.get("btn_link", "Not set")
            await callback_query.message.edit_text(
                f"📊 **Tera Status:**\n\n"
                f"**Linked Channels:**\n{ch_text}\n\n"
                f"**Button Text:** `{b_text}`\n"
                f"**Button Link:** `{b_link}`\n\n"
                f"🔄 **Pending Messages in Queue:** `{pending_count}`"
            )
        await callback_query.answer()

# ----------------- STATE HANDLER (FIXED FILTER) -----------------

@app.on_message(filters.private & ~filters.command(["start", "setchannel", "setbutton", "status"]))
async def handle_state_input(client, message):
    user_id = message.from_user.id
    state = await state_collection.find_one({"user_id": user_id})

    if not state:
        return

    step = state.get("step")

    if step == "waiting_for_channel":
        channel_id = await extract_channel_id_from_input(client, message)
        if channel_id:
            # ---------- MULTI-CHANNEL FIX ----------
            await users_collection.update_one(
                {"user_id": user_id},
                {"$addToSet": {"channel_ids": channel_id}},
                upsert=True
            )
            await state_collection.delete_one({"user_id": user_id})
            await message.reply_text(f"✅ Channel ID `{channel_id}` successfully set ho gaya!")
        else:
            await message.reply_text(
                "❌ Mujhe channel ID nahi mili. Dubara try karo:\n"
                "• Sahi channel ID bhejo (jaise `-100123456789`)\n"
                "• Channel ki koi post forward karo\n"
                "• Channel ki kisi post ka link bhejo"
            )

    elif step == "waiting_for_button_text":
        btn_text = message.text.strip()
        if not btn_text:
            await message.reply_text("❌ Button text empty nahi ho sakta. Dobara bhejo.")
            return

        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {"step": "waiting_for_button_link", "temp_text": btn_text}}
        )
        await message.reply_text(
            f"✅ Button text set: `{btn_text}`\n\n"
            "Ab button ka **link** bhejo.\n"
            "Jaise: `https://google.com` ya `t.me/username`"
        )

    elif step == "waiting_for_button_link":
        btn_link = message.text.strip()
        if not btn_link.startswith(("http://", "https://", "t.me/")):
            await message.reply_text("❌ Link invalid hai. Link http://, https://, ya t.me/ se shuru hona chahiye. Dobara bhejo.")
            return

        temp_text = state.get("temp_text")
        if not temp_text:
            await state_collection.delete_one({"user_id": user_id})
            await message.reply_text("❌ Kuch gadbad hui. /start karke dobara try karo.")
            return

        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"btn_text": temp_text, "btn_link": btn_link}},
            upsert=True
        )

        await state_collection.delete_one({"user_id": user_id})

        markup = InlineKeyboardMarkup([[InlineKeyboardButton(temp_text, url=btn_link)]])
        await message.reply_text("✅ Button set ho gaya! Ye aisa dikhega:", reply_markup=markup)

# ----------------- MESSAGE TRACKER (FIXED: array search) -----------------

@app.on_message(filters.channel)
async def track_upcoming_messages(client, message):
    # ab channel_ids array me check karo
    data = await users_collection.find_one({"channel_ids": message.chat.id})
    if data and data.get("btn_text") and data.get("btn_link"):
        await queue_collection.insert_one({
            "chat_id": message.chat.id,
            "message_id": message.id
        })

# ----------------- BACKGROUND WORKER (FIXED: array search) -----------------

async def message_processor():
    edit_timestamps = []
    while True:
        try:
            current_time = time.time()
            edit_timestamps = [t for t in edit_timestamps if current_time - t < 60]
            if len(edit_timestamps) >= 19:
                sleep_time = 60 - (current_time - edit_timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                continue

            msg_data = await queue_collection.find_one_and_delete({})
            if not msg_data:
                await asyncio.sleep(2)
                continue

            chat_id = msg_data["chat_id"]
            message_id = msg_data["message_id"]
            # array search
            user_data = await users_collection.find_one({"channel_ids": chat_id})

            if user_data and user_data.get("btn_text") and user_data.get("btn_link"):
                markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton(user_data["btn_text"], url=user_data["btn_link"])
                ]])

                try:
                    await app.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
                    edit_timestamps.append(time.time())
                    await asyncio.sleep(2)
                except FloodWait as e:
                    print(f"⚠️ FloodWait! Waiting {e.value}s")
                    await queue_collection.insert_one(msg_data)
                    await asyncio.sleep(e.value)
                except MessageNotModified:
                    pass
                except ChatAdminRequired:
                    print(f"❌ Admin Rights nahi hain Chat ID: {chat_id} me.")
                except Exception as e:
                    print(f"❌ Error: {e} (Msg ID: {message_id})")

        except Exception as e:
            print(f"Worker Loop Error: {e}")
            await asyncio.sleep(5)

# ----------------- MAIN -----------------

async def main():
    await app.start()
    print("🤖 Bot Start ho gaya hai...")
    asyncio.create_task(message_processor())
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
