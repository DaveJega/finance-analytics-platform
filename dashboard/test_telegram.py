try:
    from telegram import Bot
    print("telegram library OK")
except ImportError:
    print("telegram library NOT installed")

import os
print("TOKEN:", os.getenv("TELEGRAM_BOT_TOKEN", "NOT SET"))
print("CHAT ID:", os.getenv("TELEGRAM_CHAT_ID", "NOT SET"))