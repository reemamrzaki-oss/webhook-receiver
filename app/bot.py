from typing import List
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

application: Application = None

async def init_bot() -> Application:
    global application
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")
    
    application = (
        Application.builder().token(BOT_TOKEN).build()
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("bind", bind))
    application.add_handler(CommandHandler("unbind", unbind))
    application.add_handler(CommandHandler("pause", pause))
    application.add_handler(CommandHandler("resume", resume))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("recent", recent))
    application.add_handler(CommandHandler("get", get_webhook))
    
    return application

async def send_to_bound_chats(msg: str):
    global application
    if not application:
        return
    
    from .storage import get_bound_chats
    chats: List[int] = await get_bound_chats()
    
    for chat_id in chats:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=msg,
                disable_web_page_preview=True,
                parse_mode=None  # Safe for Telegram
            )
        except Exception as e:
            print(f"Failed to notify chat {chat_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = """
🔔 *Webhook Receiver Bot*

Commands:
/bind - Bind this chat
/unbind - Unbind this chat
/pause - Pause notifications
/resume - Resume notifications
/status - Check status
/stats - Show stats
/recent - Last 5 webhooks
/get <id> - Download full webhook
""".strip()
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    from .storage import load_data, save_data
    data = await load_data()
    if chat_id not in data["chats"]:
        data["chats"].append(chat_id)
        await save_data(data)
        await update.message.reply_text("✅ Bound to webhook notifications!")
    else:
        await update.message.reply_text("Already bound.")

async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    from .storage import load_data, save_data
    data = await load_data()
    if chat_id in data["chats"]:
        data["chats"].remove(chat_id)
    if chat_id in data["paused_chats"]:
        data["paused_chats"].remove(chat_id)
    await save_data(data)
    await update.message.reply_text("❌ Unbound.")

async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    from .storage import load_data, save_data
    data = await load_data()
    if chat_id in data["chats"] and chat_id not in data["paused_chats"]:
        data["paused_chats"].append(chat_id)
        await save_data(data)
        await update.message.reply_text("⏸️ Notifications paused.")
    else:
        await update.message.reply_text("Not bound or already paused.")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    from .storage import load_data, save_data
    data = await load_data()
    if chat_id in data["paused_chats"]:
        data["paused_chats"].remove(chat_id)
        await save_data(data)
        await update.message.reply_text("▶️ Notifications resumed.")
    else:
        await update.message.reply_text("Not paused.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    from .storage import load_data
    data = await load_data()
    if chat_id in data["chats"]:
        status_text = "✅ Active" if chat_id not in data["paused_chats"] else "⏸️ Paused"
    else:
        status_text = "❌ Not bound"
    await update.message.reply_text(f"Status: {status_text}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .storage import load_data
    data = await load_data()
    stats_text = f"📊 Stats:\nTotal: {data['stats']['total']}\nDaily: {data['stats']['daily']}"
    await update.message.reply_text(stats_text)

async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .storage import load_data
    data = await load_data()
    recents = data["recent"][:5]
    if not recents:
        await update.message.reply_text("No recent webhooks.")
        return
    text = "📋 Recent webhooks:\n" + "\n".join([f"🆔 {r['id']} ⏱️ {r['ts']}" for r in recents])
    await update.message.reply_text(text)

async def get_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /get <request_id>")
        return
    req_id = context.args[0]
    from .storage import find_request_file
    file_path = await find_request_file(req_id)
    if not file_path or not file_path.exists():
        await update.message.reply_text("❌ Webhook not found.")
        return
    try:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_path,
            filename=file_path.name,
            caption=f"🆔 Full webhook: {req_id}"
        )
    except Exception as e:
        await update.message.reply_text(f"Failed to send file: {e}")