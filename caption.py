import asyncio
import time
import re
import math
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, MessageNotModified, ChatAdminRequired, UsernameNotOccupied
from motor.motor_asyncio import AsyncIOMotorClient

# ============= CONFIG =============
from config import API_ID, API_HASH, BOT_TOKEN, MONGO_URI
# ==================================

# Database Setup
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["AdvancedAutoBot"]
channels_collection = db["channels_data"]  # Har channel ki setting alag store hogi
queue_collection = db["message_queue"]     # Pending messages
state_collection = db["user_states"]       # User inputs track karne ke liye

app = Client("my_autocaption_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= HELPER FUNCTIONS =================

def get_readable_size(size_bytes):
    if not size_bytes:
        return "0 B"
    if size_bytes == 0:
        return "0 B"
    unit_names = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {unit_names[i]}"

def get_readable_time(seconds):
    if not seconds:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def clean_text(text, preserve_links=False):
    """Apply filters: remove @mentions, replace _ . with space, optionally remove URLs and [brackets] content."""
    if not text:
        return ""
    text = re.sub(r'@\w+', '', text)
    text = text.replace('_', ' ').replace('.', ' ')
    if not preserve_links:
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r't\.me/\S+', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

async def extract_channel_id_from_input(client, message):
    if message.forward_from_chat and str(message.forward_from_chat.type) in ["ChatType.CHANNEL", "ChatType.SUPERGROUP", "channel", "supergroup"]:
        return message.forward_from_chat.id, message.forward_from_chat.title

    if message.text:
        text = message.text.strip()
        private_match = re.search(r't\.me/c/(\d+)', text)
        if private_match:
            ch_id = private_match.group(1)
            return (int(f"-100{ch_id}") if not ch_id.startswith("-100") else int(ch_id)), None

        public_match = re.search(r't\.me/([a-zA-Z0-9_]+)', text)
        if public_match and public_match.group(1).lower() != "c":
            try:
                chat = await client.get_chat(public_match.group(1))
                return chat.id, chat.title
            except Exception:
                pass

        if "t.me" not in text and "http" not in text:
            cleaned = re.sub(r'[^\d\-]', '', text)
            if cleaned and cleaned.lstrip('-').isdigit():
                raw_num = cleaned.lstrip('-')
                if not raw_num.startswith("100"):
                    raw_num = "100" + raw_num
                return int(f"-{raw_num}"), None
    return None, None

# ================= BOT COMMANDS & MAIN MENU =================

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await state_collection.delete_one({"user_id": message.from_user.id})
    text = (
        "👋 Welcome to Advanced Auto-Caption Bot!\n\n"
        "Main tumhare channels me Auto-Caption aur Auto-Button add kar sakta hu.\n"
        "HTML format, Size, File Name sab support karta hu.\n"
        "Ab unlimited buttons bhi daal sakte ho!\n\n"
        "👇 Options select karo:"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add New Channel", callback_data="add_channel")],
        [InlineKeyboardButton("📂 My Channels (Settings)", callback_data="my_channels")]
    ])
    await message.reply_text(text, reply_markup=buttons)

# ================= CALLBACK QUERIES =================

@app.on_callback_query()
async def handle_callback(client, cb: CallbackQuery):
    user_id = cb.from_user.id
    data = cb.data

    if data == "main_menu":
        await state_collection.delete_one({"user_id": user_id})
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add New Channel", callback_data="add_channel")],
            [InlineKeyboardButton("📂 My Channels (Settings)", callback_data="my_channels")]
        ])
        await cb.message.edit_text("🏠 **Main Menu:**", reply_markup=buttons)

    elif data == "add_channel":
        await state_collection.update_one({"user_id": user_id}, {"$set": {"step": "waiting_for_channel"}}, upsert=True)
        await cb.message.edit_text(
            "📢 **Add Channel**\n\n"
            "Channel ID bhejo (`-100123...`) ya channel ki koi post forward karo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )

    elif data == "my_channels":
        user_channels = await channels_collection.find({"owner_id": user_id}).to_list(length=100)
        if not user_channels:
            return await cb.message.edit_text("❌ Tumne abhi tak koi channel add nahi kiya hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]))

        buttons = []
        for ch in user_channels:
            title = ch.get('title', str(ch['channel_id'])[:8] + "...")
            buttons.append([InlineKeyboardButton(f"📢 {title}", callback_data=f"settings_{ch['channel_id']}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        await cb.message.edit_text("📂 **Tumhare Channels:**\nSelect a channel to edit its settings:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("settings_"):
        ch_id = int(data.split("_")[1])
        ch_data = await channels_collection.find_one({"channel_id": ch_id, "owner_id": user_id})
        if not ch_data:
            return await cb.answer("❌ Data not found!", show_alert=True)

        buttons_list = ch_data.get('buttons', [])
        btn_status = f"{len(buttons_list)} button(s) set" if buttons_list else "Not Set"
        cap_status = "Custom Set" if ch_data.get('custom_caption') != "{caption}" else "Default ({caption})"
        title = ch_data.get('title', str(ch_id))

        text = (
            f"⚙️ **Settings for:** `{title}`\n\n"
            f"**🔘 Buttons:** {btn_status}\n"
            f"**📝 Caption:** {cap_status}\n\n"
            "👇 Kya edit karna chahte ho?"
        )
        buttons = [
            [InlineKeyboardButton("📝 Edit Caption", callback_data=f"editcap_{ch_id}"),
             InlineKeyboardButton("🔘 Edit Buttons", callback_data=f"editbtn_{ch_id}")],
            [InlineKeyboardButton("➕ Add Button (Easy)", callback_data=f"easybtn_{ch_id}"),
             InlineKeyboardButton("🗑 Remove All Buttons", callback_data=f"rmbtn_{ch_id}")],
            [InlineKeyboardButton("❌ Remove Channel", callback_data=f"rmch_{ch_id}")],
            [InlineKeyboardButton("🔄 Reset Settings", callback_data=f"reset_{ch_id}"),
            InlineKeyboardButton("🔙 Back to Channels", callback_data="my_channels")]
        ]
        await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # --- Edit Buttons (Advanced: multiline with |) ---
    elif data.startswith("editbtn_"):
        ch_id = int(data.split("_")[1])
        await state_collection.update_one({"user_id": user_id}, {"$set": {"step": f"waiting_btn_{ch_id}"}}, upsert=True)
        await cb.message.edit_text(
            "🔘 **Set Channel Buttons (Advanced)**\n\n"
            "Har button ko **alag line** me bhejo, format:\n"
            "`Button Name | Link`\n\n"
            "Example:\n"
            "`Join Channel | https://t.me/mychannel`\n"
            "`Download Now | https://example.com/file`\n\n"
            "Sirf ek button chahte ho to ek hi line bhejo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"settings_{ch_id}")]])
        )

    elif data.startswith("easybtn_done_"):
        ch_id = int(data.split("_")[2])
        state = await state_collection.find_one({"user_id": user_id})
        temp_buttons = state.get(f"temp_buttons_{ch_id}", [])
        if temp_buttons:
            existing = await channels_collection.find_one({"channel_id": ch_id})
            current_buttons = existing.get("buttons", [])
            current_buttons.extend(temp_buttons)
            await channels_collection.update_one({"channel_id": ch_id}, {"$set": {"buttons": current_buttons}})
        await state_collection.delete_one({"user_id": user_id})
        await cb.answer("✅ Buttons saved!", show_alert=True)

        # FIX 1: Proper recursive call
        cb.data = f"settings_{ch_id}"
        await handle_callback(client, cb)

    elif data.startswith("easybtn_more_"):
        ch_id = int(data.split("_")[2])
        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {f"step": f"easybtn_text_{ch_id}"}}
        )
        await cb.message.edit_text(
            "➕ **Next Button**\n\n"
            "Agle button ka **text** bhejo.\n"
            "Agar bas karna hai to 'Done' button dabao.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Done", callback_data=f"easybtn_done_{ch_id}")]])
        )
        
    # --- Easy Add Button (Step-by-step) ---
    elif data.startswith("easybtn_"):
        ch_id = int(data.split("_")[1])
        temp_key = f"temp_buttons_{ch_id}"
        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {f"step": f"easybtn_text_{ch_id}", temp_key: []}},
            upsert=True
        )
        await cb.message.edit_text(
            "➕ **Easy Button Setup**\n\n"
            "Pehle button ka **text** bhejo (jaise: `Join Channel`).\n\n"
            "Baad mein link puchunga.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"settings_{ch_id}")]])
        )


    # --- Remove all buttons ---
    elif data.startswith("rmbtn_"):
        ch_id = int(data.split("_")[1])
        await channels_collection.update_one({"channel_id": ch_id}, {"$set": {"buttons": []}})
        await cb.answer("✅ All Buttons Removed!", show_alert=True)

        # FIX 1
        cb.data = f"settings_{ch_id}"
        await handle_callback(client, cb)

    # --- Edit Caption ---
    elif data.startswith("editcap_"):
        ch_id = int(data.split("_")[1])
        await state_collection.update_one({"user_id": user_id}, {"$set": {"step": f"waiting_cap_{ch_id}"}}, upsert=True)
        text = (
            "📝 **Set Custom Caption (HTML Supported)**\n\n"
            "Variables:\n"
            "`{caption}` - Cleaned original caption\n"
            "`{file_name}` - Cleaned file name\n"
            "`{size}` - File size\n"
            "`{duration}` - Video duration\n\n"
            "**Templates (copy karo):**\n"
            "1. **Simple**\n"
            "`<b>{file_name}</b>\n\n{size} | {duration}`\n\n"
            "2. **With Original**\n"
            "`{caption}\n\n📁 {file_name}\n📊 {size}`\n\n"
            "3. **No Caption**\n"
            "`{file_name} - {size}`\n\n"
            "Apna caption yahan paste karo:"
        )
        await cb.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"settings_{ch_id}")]])
        )

    elif data.startswith("reset_"):
        ch_id = int(data.split("_")[1])
        await channels_collection.update_one(
            {"channel_id": ch_id, "owner_id": user_id},
            {"$set": {"buttons": [], "custom_caption": "{caption}"}}
        )
        await cb.answer("✅ Channel settings default pe reset ho gayi!", show_alert=True)

        # FIX 1
        cb.data = f"settings_{ch_id}"
        await handle_callback(client, cb)

    # --- Remove Channel ---
    elif data.startswith("rmch_"):
        ch_id = int(data.split("_")[1])
        await channels_collection.delete_one({"channel_id": ch_id, "owner_id": user_id})
        await cb.answer("✅ Channel database se remove ho gaya!", show_alert=True)

        # FIX 1
        cb.data = "my_channels"
        await handle_callback(client, cb)

# ================= STATE HANDLERS =================

@app.on_message(filters.private & ~filters.command(["start"]))
async def handle_states(client, message):
    user_id = message.from_user.id
    state = await state_collection.find_one({"user_id": user_id})
    if not state: return
    step = state.get("step", "")

    # --- ADD CHANNEL ---
    if step == "waiting_for_channel":
        ch_id, title = await extract_channel_id_from_input(client, message)
        if not ch_id:
            return await message.reply_text("❌ Valid Channel ID nahi mili. Wapas try karo.")

        await channels_collection.update_one(
            {"channel_id": ch_id},
            {"$set": {"owner_id": user_id, "title": title or str(ch_id), "custom_caption": "{caption}", "buttons": []}},
            upsert=True
        )
        await state_collection.delete_one({"user_id": user_id})

        # FIX 2: Bot_msg save kiya taaki MessageIdInvalid error na aaye
        bot_msg = await message.reply_text(f"✅ Channel `{title or ch_id}` successfully added!", quote=True)
        dummy_cb = CallbackQuery(
            id="0", from_user=message.from_user, message=bot_msg,
            data=f"settings_{ch_id}", chat_instance="0"
        )
        dummy_cb._client = client
        await handle_callback(client, dummy_cb)

    # --- Advanced Buttons (multiline with |) ---
    elif step.startswith("waiting_btn_"):
        ch_id = int(step.split("_")[2])
        lines = message.text.strip().split('\n')
        buttons = []
        error_lines = []
        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue
            if '|' not in line:
                error_lines.append(f"Line {i}: missing '|'")
                continue
            parts = line.split('|', 1)
            btn_text = parts[0].strip()
            btn_link = parts[1].strip()
            if not btn_text or not btn_link:
                error_lines.append(f"Line {i}: empty text or link")
                continue
            if not btn_link.startswith(("http://", "https://", "t.me/")):
                error_lines.append(f"Line {i}: link invalid (must start with http://, https://, or t.me/)")
                continue
            buttons.append({"text": btn_text, "url": btn_link})

        if error_lines:
            err_msg = "\n".join(error_lines)
            return await message.reply_text(f"❌ Errors:\n{err_msg}\n\nPlease correct and send again.")
        if not buttons:
            return await message.reply_text("❌ Koi valid button nahi mila. Dobara try karo.")

        await channels_collection.update_one({"channel_id": ch_id}, {"$set": {"buttons": buttons}})
        await state_collection.delete_one({"user_id": user_id})

        # FIX 2
        bot_msg = await message.reply_text(f"✅ {len(buttons)} button(s) set successfully!")
        dummy_cb = CallbackQuery(
            id="0", from_user=message.from_user, message=bot_msg,
            data=f"settings_{ch_id}", chat_instance="0"
        )
        dummy_cb._client = client
        await handle_callback(client, dummy_cb)

    # --- Easy Button: waiting for text ---
    elif step.startswith("easybtn_text_"):
        ch_id = int(step.split("_")[2])
        btn_text = message.text.strip()
        if not btn_text:
            return await message.reply_text("❌ Button text empty nahi ho sakta. Dobara bhejo.")

        temp_key = f"temp_buttons_{ch_id}"
        temp_list = state.get(temp_key, [])
        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {f"step": f"easybtn_link_{ch_id}", "temp_btn_text": btn_text, temp_key: temp_list}}
        )
        await message.reply_text(
            f"✅ Text set: `{btn_text}`\n\nAb button ka **link** bhejo.\n"
            "Jaise: `https://t.me/xyz` ya `https://google.com`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"settings_{ch_id}")]])
        )

    # --- Easy Button: waiting for link ---
    elif step.startswith("easybtn_link_"):
        ch_id = int(step.split("_")[2])
        btn_link = message.text.strip()
        if not btn_link.startswith(("http://", "https://", "t.me/")):
            return await message.reply_text("❌ Link invalid hai. Link http://, https://, ya t.me/ se shuru hona chahiye. Dobara bhejo.")

        temp_text = state.get("temp_btn_text")
        if not temp_text:
            await state_collection.delete_one({"user_id": user_id})
            return await message.reply_text("❌ Kuch gadbad hui. Phir se try karo.")

        temp_key = f"temp_buttons_{ch_id}"
        temp_list = state.get(temp_key, [])
        temp_list.append({"text": temp_text, "url": btn_link})

        await state_collection.update_one(
            {"user_id": user_id},
            {"$set": {f"step": f"easybtn_confirm_{ch_id}", temp_key: temp_list}}
        )
        await message.reply_text(
            f"✅ Button saved! Ab aur buttons add karne hain?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Another", callback_data=f"easybtn_more_{ch_id}")],
                [InlineKeyboardButton("✅ Done", callback_data=f"easybtn_done_{ch_id}")]
            ])
        )

    elif step.startswith("easybtn_confirm_"):
        await message.reply_text("Please use the buttons below to continue.", reply_markup=message.reply_markup)

    # --- Caption Setup ---
    elif step.startswith("waiting_cap_"):
        ch_id = int(step.split("_")[2])
        custom_cap = message.text.html
        await channels_collection.update_one({"channel_id": ch_id}, {"$set": {"custom_caption": custom_cap}})
        await state_collection.delete_one({"user_id": user_id})

        # FIX 2
        bot_msg = await message.reply_text("✅ Custom Caption set ho gaya! HTML format saved.")
        dummy_cb = CallbackQuery(
            id="0", from_user=message.from_user, message=bot_msg,
            data=f"settings_{ch_id}", chat_instance="0"
        )
        dummy_cb._client = client
        await handle_callback(client, dummy_cb)

# ================= LISTENER (TRACK INCOMING MESSAGES) =================

@app.on_message(filters.channel)
async def track_upcoming_messages(client, message):
    ch_data = await channels_collection.find_one({"channel_id": message.chat.id})
    if not ch_data: return

    file_name = "Unknown"
    size_bytes = 0
    duration_sec = 0
    msg_type = "text"

    media = message.document or message.video or message.audio or message.photo or None
    if media:
        msg_type = "media"
        file_name = getattr(media, "file_name", "Media_File")
        size_bytes = getattr(media, "file_size", 0)
        duration_sec = getattr(media, "duration", 0)

    original_cap = message.caption.html if message.caption else (message.text.html if message.text else "")
    
    # YEH IMPORTANT CHANGE:
    # Original caption se SIRF mentions aur special characters hatenge, links nahi
    cleaned_cap = clean_text(original_cap, preserve_links=True)
    
    # File name se bhi links nahi hatenge, lekin file name mein generally links nahi hote
    cleaned_file_name = clean_text(file_name, preserve_links=True)

    await queue_collection.insert_one({
        "chat_id": message.chat.id,
        "message_id": message.id,
        "msg_type": msg_type,
        "original_cap": cleaned_cap,  # Ab isme links safe rahenge
        "file_name": cleaned_file_name,
        "size_bytes": size_bytes,
        "duration_sec": duration_sec
    })

# ================= BACKGROUND WORKER =================

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

            msg_data = await queue_collection.find_one_and_delete({}, sort=[("_id", 1)])
            if not msg_data:
                await asyncio.sleep(2)
                continue

            chat_id = msg_data["chat_id"]
            message_id = msg_data["message_id"]
            ch_data = await channels_collection.find_one({"channel_id": chat_id})
            if not ch_data: continue

            raw_caption = ch_data.get("custom_caption", "{caption}")
            final_caption = raw_caption.replace("{caption}", msg_data["original_cap"])
            final_caption = final_caption.replace("{file_name}", msg_data["file_name"])
            final_caption = final_caption.replace("{size}", get_readable_size(msg_data["size_bytes"]))
            final_caption = final_caption.replace("{duration}", get_readable_time(msg_data["duration_sec"]))

            if msg_data["msg_type"] == "media" and len(final_caption) > 1024:
                final_caption = final_caption[:1020] + "..."

            reply_markup = None
            buttons_list = ch_data.get("buttons", [])
            if buttons_list:
                keyboard = [[InlineKeyboardButton(btn["text"], url=btn["url"])] for btn in buttons_list]
                reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                if msg_data["msg_type"] == "media":
                    await app.edit_message_caption(chat_id, message_id, caption=final_caption, reply_markup=reply_markup)
                else:
                    await app.edit_message_text(chat_id, message_id, text=final_caption, reply_markup=reply_markup, disable_web_page_preview=True)
                edit_timestamps.append(time.time())
                await asyncio.sleep(2)
            except FloodWait as e:
                await queue_collection.insert_one(msg_data)
                await asyncio.sleep(e.value)
            except MessageNotModified:
                pass
            except ChatAdminRequired:
                print(f"❌ Admin Rights needed in {chat_id}")
            except Exception as e:
                print(f"❌ Error editing msg {message_id}: {e}")

        except Exception as e:
            print(f"Worker Loop Error: {e}")
            await asyncio.sleep(5)

# ================= RUN BOT =================

async def main():
    await app.start()
    print("🤖 Advanced Auto-Caption Bot Start Ho Gaya Hai!")
    asyncio.create_task(message_processor())
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
