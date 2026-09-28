import os
import re
import io
import asyncio
import logging
from typing import Dict, Any, List
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

# In-memory storage for step-by-step wizard sessions: {user_id: {"niche": ..., "city": ..., "count": ..., "min_reviews": ...}}
USER_WIZARD_SESSIONS: Dict[int, Dict[str, Any]] = {}

POPULAR_NICHES = [
    ["Dental Clinics", "Cafes & Bakeries"],
    ["Gyms & Fitness", "Beauty Salons & Spa"],
    ["Car Repair & Garages", "Interior Designers"],
    ["Restaurants", "Plumbers & Electricians"],
]

COUNT_OPTIONS = [
    [InlineKeyboardButton("5 Leads", callback_data="wizard_count_5"), InlineKeyboardButton("10 Leads", callback_data="wizard_count_10")],
    [InlineKeyboardButton("15 Leads", callback_data="wizard_count_15"), InlineKeyboardButton("20 Leads", callback_data="wizard_count_20")],
]

REVIEW_OPTIONS = [
    [InlineKeyboardButton("Any Reviews", callback_data="wizard_rev_0"), InlineKeyboardButton("10+ Reviews", callback_data="wizard_rev_10")],
    [InlineKeyboardButton("25+ Reviews", callback_data="wizard_rev_25"), InlineKeyboardButton("50+ Reviews", callback_data="wizard_rev_50")],
]

def build_niche_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for row in POPULAR_NICHES:
        buttons.append([InlineKeyboardButton(n, callback_data=f"wizard_niche_{n}") for n in row])
    buttons.append([InlineKeyboardButton("✍️ Type Custom Niche", callback_data="wizard_niche_custom")])
    return InlineKeyboardMarkup(buttons)

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
        "🎯 *Two Easy Ways to Search:*\n"
        "1. 🔘 *Step-by-Step*: Tap *🔍 Find Leads* to pick niche, count & reviews interactively\n"
        "2. ⚡ *Fast One-Liner*: Just send e.g. `Dentists in Pune 10 20+ reviews`\n\n"
        "📌 *Other Commands:*\n"
        "/stats - View database metrics\n"
        "/export - Download CSV file\n"
        "/clearleads - Wipe unused leads"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Lead Hunter Guide & Examples*\n\n"
        "🔘 *Interactive Step-by-Step Mode:*\n"
        "Tap the *🔍 Find Leads* button below to pick:\n"
        "• Business Niche (or type your own)\n"
        "• Target City\n"
        "• How many leads (5, 10, 15, 20)\n"
        "• Minimum reviews threshold (Any, 10+, 25+, 50+)\n\n"
        "⚡ *Quick One-Liner Mode:*\n"
        "Send everything at once if you prefer:\n"
        "• `Dentists in Pune 10 20+ reviews`\n"
        "• `Bakeries in Bangalore 10`\n"
        "• `Car repair in Indore 8`\n\n"
        "🗑️ *Database Cleanup:*\n"
        "• `/clearleads` - Wipe all unused leads (preserves leads with websites)\n"
        "• `/clearleads 1 2 5` - Delete specific lead IDs (`LEAD-1`, etc.)"
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

async def clearleads_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clearleads command to delete unused leads or specific IDs."""
    user = update.effective_user
    if not is_authorized(user):
        return

    args = context.args or []
    # If arguments provided: parse specific lead IDs
    if args:
        raw_text = " ".join(args).upper()
        # Find all numbers or LEAD-X patterns
        # e.g. "LEAD-1 2", "1, 2, 5", "LEAD-10"
        ids_to_del = []
        tokens = re.split(r"[\s,]+", raw_text)
        for t in tokens:
            m = re.search(r"^(?:LEAD-?|#)?(\d+)$", t, re.IGNORECASE)
            if m:
                ids_to_del.append(int(m.group(1)))

        if not ids_to_del:
            await update.message.reply_text(
                "ℹ️ *Usage for specific deletion:*\n"
                "• `/clearleads 1 2 5`\n"
                "• `/clearleads LEAD-1 LEAD-2`\n"
                "• Or just `/clearleads` to wipe all unused leads!",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        deleted = await unified_db.delete_leads(ids_to_del)
        id_str = ", ".join([f"`LEAD-{i}`" for i in ids_to_del])
        await update.message.reply_text(
            f"🗑️ *Deleted {deleted} lead(s):*\n{id_str}\n\n"
            f"⚡ These IDs are now removed from your database.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # If no args: delete all unused leads (where demo_website_url is empty)
    deleted = await unified_db.delete_unused_leads()
    await update.message.reply_text(
        f"🧹 *Cleaned up {deleted} unused lead(s)!*\n\n"
        f"✅ Kept all leads that have demo websites attached.\n"
        f"🗑️ Removed leads without websites to keep your database tidy.",
        parse_mode=ParseMode.MARKDOWN
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

async def start_wizard(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Start step 1: Select business niche."""
    USER_WIZARD_SESSIONS[user_id] = {"step": "niche"}
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🏢 *Step 1/4: What type of business are you looking for?*\n\n"
            "Choose a popular category or tap 'Type Custom Niche':"
        ),
        reply_markup=build_niche_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )

async def wizard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button presses during the step-by-step lead search."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not is_authorized(user):
        return

    data = query.data or ""
    session = USER_WIZARD_SESSIONS.get(user.id, {})

    # Step 1: Niche selection
    if data.startswith("wizard_niche_"):
        niche_val = data.replace("wizard_niche_", "").strip()
        if niche_val == "custom":
            session["step"] = "awaiting_custom_niche"
            USER_WIZARD_SESSIONS[user.id] = session
            await query.edit_message_text(
                "✍️ *Please type the business niche you want to search for:*\n_(e.g. Yoga Studios, Pet Grooming, Car Detailing)_",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        session["niche"] = niche_val
        session["step"] = "awaiting_city"
        USER_WIZARD_SESSIONS[user.id] = session
        await query.edit_message_text(
            f"✅ Business: *{niche_val}*\n\n"
            "📍 *Step 2/4: Which city or neighborhood?*\n"
            "Please send the city name (e.g. `Pune`, `Bandra Mumbai`, `South Delhi`, `Indore`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Step 3: Count selection
    if data.startswith("wizard_count_"):
        count_val = int(data.replace("wizard_count_", ""))
        session["count"] = count_val
        session["step"] = "reviews"
        USER_WIZARD_SESSIONS[user.id] = session

        await query.edit_message_text(
            f"✅ Business: *{session.get('niche')}*\n"
            f"✅ City: *{session.get('city')}*\n"
            f"✅ Lead Count: *{count_val} leads*\n\n"
            "⭐ *Step 4/4: Minimum Google Reviews filter:*\n"
            "Pick a reviews threshold to target established businesses:",
            reply_markup=InlineKeyboardMarkup(REVIEW_OPTIONS),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Step 4: Reviews selection -> Trigger search!
    if data.startswith("wizard_rev_"):
        rev_val = int(data.replace("wizard_rev_", ""))
        session["min_reviews"] = rev_val if rev_val > 0 else None
        niche = session.get("niche", "Dentists")
        city = session.get("city", "Pune")
        count = session.get("count", 10)
        min_rev = session.get("min_reviews")

        # Clear session
        USER_WIZARD_SESSIONS.pop(user.id, None)

        rev_label = f"{min_rev}+ reviews" if min_rev else "Any rating/reviews"
        await query.edit_message_text(
            f"🚀 *Starting Search with your criteria:*\n"
            f"• 🏢 Business: *{niche}*\n"
            f"• 📍 City: *{city}*\n"
            f"• 🎯 Count: *{count} leads*\n"
            f"• ⭐ Reviews: *{rev_label}*\n\n"
            f"🔎 _Querying Google Maps via SerpAPI..._",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Trigger search worker
        query_str = f"{niche} in {city} {count}"
        if min_rev:
            query_str += f" {min_rev}+ reviews"
        asyncio.create_task(search_leads_worker(query.message.chat_id, user.id, query_str, context))
        return

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Telegram User ID is `{user.id}`.", parse_mode=ParseMode.MARKDOWN)
        return

    text = (update.message.text or "").strip()

    # Main keyboard commands
    if text == "🔍 Find Leads":
        await start_wizard(update.effective_chat.id, user.id, context)
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

    # Check if user is currently inside a step-by-step wizard
    session = USER_WIZARD_SESSIONS.get(user.id)
    if session:
        step = session.get("step")

        # Handling custom niche text input
        if step == "awaiting_custom_niche":
            session["niche"] = text
            session["step"] = "awaiting_city"
            USER_WIZARD_SESSIONS[user.id] = session
            await update.message.reply_text(
                f"✅ Business: *{text}*\n\n"
                "📍 *Step 2/4: Which city or area?*\n"
                "Please send the city name (e.g. `Pune`, `Koramangala Bangalore`, `Delhi`):",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Handling city text input
        if step == "awaiting_city":
            session["city"] = text
            session["step"] = "count"
            USER_WIZARD_SESSIONS[user.id] = session
            await update.message.reply_text(
                f"✅ Business: *{session.get('niche')}*\n"
                f"✅ City: *{text}*\n\n"
                "🎯 *Step 3/4: How many leads do you want to find?*",
                reply_markup=InlineKeyboardMarkup(COUNT_OPTIONS),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    # If not in wizard, support fast one-liner search (e.g. "Dentists in Pune 10 20+ reviews")
    asyncio.create_task(search_leads_worker(update.effective_chat.id, user.id, text, context))

def setup_lead_bot(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("export", export_handler))
    app.add_handler(CommandHandler("clearleads", clearleads_handler))
    app.add_handler(CallbackQueryHandler(wizard_callback_handler, pattern=r"^wizard_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    return app
