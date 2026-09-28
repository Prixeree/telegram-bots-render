import os
import re
import io
import asyncio
import logging
from typing import Dict, Any, List
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import unified_db
from scraper import SerpApiScraper

logger = logging.getLogger("LeadHunterBot")
scraper = SerpApiScraper(unified_db)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🔍 Find Leads"), KeyboardButton("📊 Database Stats")],
        [KeyboardButton("📥 Export CSV"), KeyboardButton("❓ Help & Guide")],
    ],
    resize_keyboard=True,
)

def get_auth_users() -> List[str]:
    raw = os.getenv("AUTHORIZED_USERS", "8884232483,Piyush35567")
    return [u.strip().lower().lstrip("@") for u in raw.split(",") if u.strip()]

def is_authorized(user) -> bool:
    auth_list = get_auth_users()
    if not auth_list:
        return True
    uid = str(user.id)
    username = (getattr(user, "username", "") or "").lower().lstrip("@")
    return uid in auth_list or username in auth_list

def parse_lead_query(text: str) -> Dict[str, Any]:
    clean = re.sub(r"^/leads\s*", "", text.strip(), flags=re.IGNORECASE)
    res = {
        "niche": "Dentists",
        "city": "Pune",
        "count": 10,
        "min_reviews": None,
        "min_rating": None,
    }
    rev_m = re.search(r"(\d+)\s*\+\s*reviews?", clean, re.IGNORECASE) or re.search(r"reviews?\s*[:=]?\s*(\d+)\+?", clean, re.IGNORECASE)
    if rev_m:
        res["min_reviews"] = int(rev_m.group(1))

    m = re.search(r"^(.*?)\s+in\s+([a-zA-Z\s]+?)(?:\s+(\d+))?$", clean, re.IGNORECASE)
    if m:
        res["niche"] = m.group(1).strip()
        res["city"] = m.group(2).strip()
        if m.group(3):
            res["count"] = min(int(m.group(3)), 20)
    return res

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Telegram User ID is `{user.id}`. Ask the admin to authorize you.", parse_mode=ParseMode.MARKDOWN)
        return

    text = (
        f"👋 *Welcome to Lead Hunter, {user.first_name}!*\n\n"
        "I find high-quality local business leads with verified phone numbers & direct WhatsApp links.\n\n"
        "⚡ *Instant In-Memory/Database Deduplication*: No business is ever sent twice.\n\n"
        "💡 *How to search:*\n"
        "Simply send a message like:\n"
        "• `Dentists in Pune 10 20+ reviews`\n"
        "• `Cafes in Bandra Mumbai 15`\n"
        "• `Gyms in Bangalore 10`\n\n"
        "Or use commands:\n"
        "/leads `<niche> in <city> [count]`\n"
        "/stats - View database metrics\n"
        "/export - Download CSV file"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Lead Hunter Guide & Examples*\n\n"
        "🔍 *Query Format:*\n"
        "`<niche> in <city> [how many] [reviews threshold]`\n\n"
        "📌 *Examples:*\n"
        "• `Dental clinics in Pune 10 20+ reviews`\n"
        "• `Bakeries in Bangalore 10`\n"
        "• `Car repair in Indore 8`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        return
    stats = await unified_db.get_lead_stats()
    top_n = "\n".join([f"  • {n}: {c} leads" for n, c in stats["top_niches"]]) or "  _None yet_"
    top_c = "\n".join([f"  • {ci}: {c} leads" for ci, c in stats["top_cities"]]) or "  _None yet_"

    text = (
        "📊 *Lead Hunter Database Stats*\n\n"
        f"📁 *Total Unique Leads Delivered:* `{stats['total_leads']}`\n"
        f"📞 *Unique Phone Numbers:* `{stats['unique_phones']}`\n"
        "⚡ *Database:* Supabase PostgreSQL / Cloud Synced\n\n"
        f"🏷️ *Top Niches:*\n{top_n}\n\n"
        f"🏙️ *Top Cities:*\n{top_c}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    csv_data = await unified_db.export_leads_csv()
    file_bytes = io.BytesIO(csv_data.encode("utf-8"))
    file_bytes.name = "leads_export.csv"
    await update.message.reply_document(
        document=file_bytes,
        filename=file_bytes.name,
        caption="📁 Here is your verified leads export from the database.",
    )

async def search_leads_worker(chat_id: int, user_id: int, query_text: str, context: ContextTypes.DEFAULT_TYPE):
    """Asynchronous background worker to prevent Telegram webhook timeouts."""
    parsed = parse_lead_query(query_text)
    niche = parsed["niche"]
    city = parsed["city"]
    count = parsed["count"]
    min_rev = parsed.get("min_reviews")

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔎 *Searching Google Maps for {niche} in {city}...*\n_Filtering businesses without websites..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        leads = await scraper.fetch_fresh_leads(
            niche=niche,
            city=city,
            count=count,
            min_reviews=min_rev,
            require_phone=True,
            require_no_website=True,
        )

        if not leads:
            await status_msg.edit_text("ℹ️ No new uncontacted leads found without websites in this location.")
            return

        # Persist to database
        await unified_db.save_leads(leads, user_id=user_id, niche=niche, city=city)

        header = f"🎯 *Found {len(leads)} fresh leads for {niche} in {city}:*\n\n"
        current_msg = header
        messages_to_send = []

        for i, lead in enumerate(leads, 1):
            lid = lead.get("lead_id") or f"LEAD-{lead.get('db_id', i)}"
            block = (
                f"━━━━━━━━━━━━━━━━━━\n"
                f"*{i}. {lead['name']}*\n"
                f"🆔 Lead ID: `{lid}` _(tap to copy for Website Bot)_\n"
                f"📞 Phone: `{lead['phone']}`\n"
                f"⭐ Rating: {lead['rating']} ({lead['reviews']} reviews)\n"
                f"📍 Address: {lead['address']}\n"
                f"💬 [Open WhatsApp Chat]({lead['whatsapp_url']})\n\n"
            )
            if len(current_msg) + len(block) > 3800:
                messages_to_send.append(current_msg)
                current_msg = block
            else:
                current_msg += block

        if current_msg:
            messages_to_send.append(current_msg)

        await status_msg.delete()
        for msg in messages_to_send:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

    except Exception as e:
        logger.error(f"Error in search worker: {e}")
        await status_msg.edit_text(f"❌ Search error: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Telegram User ID is `{user.id}`.", parse_mode=ParseMode.MARKDOWN)
        return

    text = (update.message.text or "").strip()
    if text == "🔍 Find Leads":
        await update.message.reply_text("💡 Simply send what you're looking for, e.g.:\n`Dentists in Pune 10 20+ reviews`")
        return
    elif text == "📊 Database Stats":
        await stats_handler(update, context)
        return
    elif text == "📥 Export CSV":
        await export_handler(update, context)
        return
    elif text == "❓ Help & Guide":
        await help_handler(update, context)
        return

    # Trigger background worker immediately so webhook returns in ~5ms
    asyncio.create_task(search_leads_worker(update.effective_chat.id, user.id, text, context))

def setup_lead_bot(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("export", export_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    return app
