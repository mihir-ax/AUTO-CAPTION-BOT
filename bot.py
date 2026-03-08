#!/usr/bin/env python3
# bot.py - Is file ko run karo bot start karne ke liye

import asyncio
import aiohttp
from aiohttp import web
from config import API  # Config se dusre bot ka URL import kiya
from caption import main as bot_main  # Tera pyrogram bot

# ================= SERVER & PINGER LOGIC =================

async def health_check(request):
    """Dummy server for Free Hosting (Render/Koyeb)"""
    return web.Response(text="Caption Bot is Alive!")

async def ping_other_bot():
    """Ye function background me har 20 sec pe dusre bot ko jagayega"""
    if not API:
        print("⚠️ API URL set nahi hai. Pinger kaam nahi karega.")
        return
        
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API) as response:
                    # pass # Chup-chaap ping karega, terminal spam nahi karega
                    print(f"🔄 Pinged {API} - Status: {response.status}") 
        except Exception as e:
            print(f"❌ Ping failed: {e}")
            
        await asyncio.sleep(20) # 20 second ka gap

# ================= MAIN RUNNER =================

async def run_all_services():
    print("🚀 Web Server aur Pinger start kiya ja raha hai...")
    
    # 1. Start Dummy Web Server on port 8080 (Kyunki Bot 1 8000 pe hai)
    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("🌐 Health Check Server started on port 8080")
    
    # 2. Start Background Pinger
    asyncio.create_task(ping_other_bot())
    
    # 3. Start Tera Original Caption Bot (caption.py ka code run hoga)
    print("🚀 Telegram Bot start ho raha hai...")
    await bot_main()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_all_services())
    except KeyboardInterrupt:
        print("\n🛑 Bot ko roka gaya.")

