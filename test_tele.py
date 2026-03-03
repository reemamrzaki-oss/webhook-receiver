import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID")

from telegram import Bot
import asyncio

async def test():
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=int(DEFAULT_CHAT_ID), text="Test message from VPS")
    print("Test message sent to Telegram")

asyncio.run(test())