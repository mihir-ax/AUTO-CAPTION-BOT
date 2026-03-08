#!/usr/bin/env python3
# bot.py - Is file ko run karo bot start karne ke liye

import asyncio
from caption import main

if __name__ == "__main__":
    print("🚀 Bot ko start kiya ja raha hai via bot.py...")
    asyncio.get_event_loop().run_until_complete(main())
