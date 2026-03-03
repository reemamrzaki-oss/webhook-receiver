from typing import List
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID")

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
    application.add_handler(CommandHandler("bind_other", bind_other))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    return application

async def send_to_bound_chats(msg: str, req_id: str = None, site: str = "default"):
    global application
    if not application:
        print("No application")
        return

    from .storage import get_bound_chats
    chats: List[int] = await get_bound_chats(site)
    if not chats and DEFAULT_CHAT_ID:
        chats = [int(DEFAULT_CHAT_ID)]
        print(f"Using default chat: {chats}")

    print(f"Sending to chats: {chats}")
    reply_markup = None
    if req_id:
        keyboard = [[InlineKeyboardButton("Download File", callback_data=f"download_{req_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    for chat_id in chats:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=msg,
                disable_web_page_preview=True,
                parse_mode=None,  # Safe for Telegram
                reply_markup=reply_markup
            )
            print(f"Message sent to {chat_id}")
        except Exception as e:
            print(f"Failed to notify chat {chat_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = """
🔔 *Webhook Receiver Bot*

Use the buttons below or type commands:
/bind [site] - Bind this chat
/bind_other <chat_id> [site] - Bind another chat
/unbind [site] - Unbind this chat
/pause - Pause notifications
/resume - Resume notifications
/status - Check status
/stats - Show stats
/recent - Last 5 webhooks
/get <id> - Download full webhook
""".strip()
    keyboard = [
        [InlineKeyboardButton("Bind Chat", callback_data="bind")],
        [InlineKeyboardButton("Unbind Chat", callback_data="unbind")],
        [InlineKeyboardButton("Pause", callback_data="pause")],
        [InlineKeyboardButton("Resume", callback_data="resume")],
        [InlineKeyboardButton("Status", callback_data="status")],
        [InlineKeyboardButton("Stats", callback_data="stats")],
        [InlineKeyboardButton("Recent", callback_data="recent")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=reply_markup)

async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    site = context.args[0] if context.args else "default"
    from .storage import load_data, save_data
    data = await load_data()
    site_data = data["sites"].setdefault(site, {"chats": [], "paused_chats": []})
    if chat_id not in site_data["chats"]:
        site_data["chats"].append(chat_id)
        await save_data(data)
        await update.message.reply_text(f"✅ Bound to webhook notifications for site '{site}'!")
    else:
        await update.message.reply_text("Already bound.")

async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    site = context.args[0] if context.args else "default"
    from .storage import load_data, save_data
    data = await load_data()
    site_data = data["sites"].setdefault(site, {"chats": [], "paused_chats": []})
    if chat_id in site_data["chats"]:
        site_data["chats"].remove(chat_id)
    if chat_id in site_data["paused_chats"]:
        site_data["paused_chats"].remove(chat_id)
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    if data.startswith("download_"):
        req_id = data.split("_", 1)[1]
        from .storage import find_request_file
        file_path = await find_request_file(req_id)
        if not file_path or not file_path.exists():
            await query.edit_message_text("❌ Webhook file not found.")
            return
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=file_path,
                filename=file_path.name,
                caption=f"🆔 Full webhook: {req_id}"
            )
        except Exception as e:
            await query.edit_message_text(f"Failed to send file: {e}")
    elif data == "bind":
        site = "default"
        from .storage import load_data, save_data
        data_dict = await load_data()
        site_data = data_dict["sites"].setdefault(site, {"chats": [], "paused_chats": []})
        if chat_id not in site_data["chats"]:
            site_data["chats"].append(chat_id)
            await save_data(data_dict)
            await query.edit_message_text("✅ Bound to webhook notifications!")
        else:
            await query.edit_message_text("Already bound.")
    elif data == "unbind":
        site = "default"
        from .storage import load_data, save_data
        data_dict = await load_data()
        site_data = data_dict["sites"].setdefault(site, {"chats": [], "paused_chats": []})
        if chat_id in site_data["chats"]:
            site_data["chats"].remove(chat_id)
        if chat_id in site_data["paused_chats"]:
            site_data["paused_chats"].remove(chat_id)
        await save_data(data_dict)
        await query.edit_message_text("❌ Unbound.")
    elif data == "pause":
        from .storage import load_data, save_data
        data_dict = await load_data()
        site_data = data_dict["sites"].setdefault("default", {"chats": [], "paused_chats": []})
        if chat_id in site_data["chats"] and chat_id not in site_data["paused_chats"]:
            site_data["paused_chats"].append(chat_id)
            await save_data(data_dict)
            await query.edit_message_text("⏸️ Notifications paused.")
        else:
            await query.edit_message_text("Not bound or already paused.")
    elif data == "resume":
        from .storage import load_data, save_data
        data_dict = await load_data()
        site_data = data_dict["sites"].setdefault("default", {"chats": [], "paused_chats": []})
        if chat_id in site_data["paused_chats"]:
            site_data["paused_chats"].remove(chat_id)
            await save_data(data_dict)
            await query.edit_message_text("▶️ Notifications resumed.")
        else:
            await query.edit_message_text("Not paused.")
    elif data == "status":
        from .storage import load_data
        data_dict = await load_data()
        site_data = data_dict["sites"].setdefault("default", {"chats": [], "paused_chats": []})
        if chat_id in site_data["chats"]:
            status_text = "✅ Active" if chat_id not in site_data["paused_chats"] else "⏸️ Paused"
        else:
            status_text = "❌ Not bound"
        await query.edit_message_text(f"Status: {status_text}")
    elif data == "stats":
        from .storage import load_data
        data_dict = await load_data()
        stats_text = f"📊 Stats:\nTotal: {data_dict['stats']['total']}\nDaily: {data_dict['stats']['daily']}"
        await query.edit_message_text(stats_text)
    elif data == "recent":
        from .storage import load_data
        data_dict = await load_data()
        recents = data_dict["recent"][:5]
        if not recents:
            await query.edit_message_text("No recent webhooks.")
            return
        text = "📋 Recent webhooks:\n" + "\n".join([f"🆔 {r['id']} ⏱️ {r['ts']}" for r in recents])
        await query.edit_message_text(text)

async def bind_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /bind_other <chat_id> [site]")
        return
    try:
        other_chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid chat ID.")
        return
    site = context.args[1] if len(context.args) > 1 else "default"
    from .storage import load_data, save_data
    data = await load_data()
    site_data = data["sites"].setdefault(site, {"chats": [], "paused_chats": []})
    if other_chat_id not in site_data["chats"]:
        site_data["chats"].append(other_chat_id)
        await save_data(data)
        await update.message.reply_text(f"✅ Bound chat {other_chat_id} to webhook notifications for site '{site}'!")
    else:
        await update.message.reply_text("Already bound.")