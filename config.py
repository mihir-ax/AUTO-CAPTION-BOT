import os

# ================= KREDENTIALS (Environment Variables ya Direct) =================
# Agar environment variable set hai to use karo, nahi to default placeholder values
# Railway, Heroku ya kisi bhi hosting me environment variables set kar sakte ho.

API_ID = int(os.environ.get("API_ID", 25776734))          # Apna API ID yahan daal
API_HASH = os.environ.get("API_HASH", "9bb0c527d53d497506baf1bd17d7426c")   # Apna API HASH
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8464007781:AAFMqI8r2fo0ubXGuq_0rIFpt-jo28Z1Hqw") # Bot Token

MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://sjadba:jasbfas@cluster0.pxtm9vd.mongodb.net/?retryWrites=true&w=majority")
# =================================================================================
