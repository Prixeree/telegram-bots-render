import os
import re
import urllib.parse
import asyncio
import logging
from typing import Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import unified_db, clean_phone_number
from generator import create_demo_for_business

logger = logging.getLogger("WebsiteGeneratorBot")

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📜 Recent Sites"), KeyboardButton("📊 Stats")],
        [KeyboardButton("❓ Help & Examples")],
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

def parse_lead_input(text: str) -> Dict[str, Any]:
    lines = text.strip().split("\n")
    data: Dict[str, Any] = {}
    for line in lines:
        line_clean = line.strip()
        m_name = re.search(r"🏢\s*(?:Business:)?\s*\*?([^\*\n]+)\*?", line_clean)
        if m_name:
            data["name"] = m_name.group(1).strip()
        m_phone = re.search(r"📞\s*(?:Phone:)?\s*`?([+\d\s\(\)-]+)`?", line_clean)
        if m_phone:
            data["phone"] = m_phone.group(1).strip()
        m_rating = re.search(r"⭐\s*(?:Rating:)?\s*([\d\.]+)\s*(?:\(([\d\+]+)\s*reviews?\))?", line_clean)
        if m_rating:
            data["rating"] = float(m_rating.group(1))
            if m_rating.group(2):
                data["reviews"] = int(re.sub(r"[^\d]", "", m_rating.group(2)))
        m_addr = re.search(r"📍\s*(?:Address:)?\s*(.+)", line_clean)
        if m_addr:
            data["address"] = m_addr.group(1).strip()

    if data.get("name"):
        data.setdefault("niche", "Services")
        data.setdefault("city", "India")
        return data

    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 2:
        return {
            "name": parts[0],
            "niche": parts[1] if len(parts) > 1 else "Services",
            "city": parts[2] if len(parts) > 2 else "India",
            "phone": parts[3] if len(parts) > 3 else "",
        }

    return {"name": text.strip(), "niche": "Services", "city": "India", "phone": ""}

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Telegram User ID is `{user.id}`. Ask the admin to authorize you.", parse_mode=ParseMode.MARKDOWN)
        return

    text = (
        f"👋 *Welcome to Demo Website Builder, {user.first_name}!*\n\n"
        "I turn local business leads into **production-grade, live Vercel websites** with pre-written WhatsApp outreach pitches in seconds.\n\n"
        "⚡ *What I do:*\n"
        "• Generates clean Tailwind CSS landing pages with verified photography\n"
        "• Deploys live to Vercel CDN (`https://demo-xxx.vercel.app`)\n"
        "• Pre-writes a high-converting WhatsApp message to pitch the owner\n\n"
        "💡 *How to generate a website (Pick any):*\n"
        "1. 🆔 *Send a Lead ID from Lead Hunter:* Just reply with `LEAD-1` or `18`!\n"
        "2. 📋 *Paste a Lead Card:* Copy any lead from @leadhunter2834bot and paste it here\n"
        "3. ✍️ *One-Liner:* `<Business Name>, <Niche>, <City>, <Phone>`\n\n"
        "_Try sending a Lead ID like `LEAD-1`!_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Demo Website Generator Guide*\n\n"
        "📌 *Option 1: Lead ID from Lead Hunter (Fastest)*\n"
        "Send the ID shown on any lead: e.g. `LEAD-1`, `18`, or `#5`.\n"
        "The bot will fetch the exact business details directly from the Supabase database!\n\n"
        "📌 *Option 2: Direct Paste from Lead Hunter Bot*\n"
        "Copy any lead card message from `@leadhunter2834bot` and paste it here directly!\n\n"
        "📌 *Option 3: Comma Separated*\n"
        "`Pune Dentaland, Dental Clinic, Pune, +91 75593 56392`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        return
    stats = await unified_db.get_site_stats()
    top_n = "\n".join([f"  • {n}: {c} sites" for n, c in stats["top_niches"]]) or "  _None yet_"
    top_c = "\n".join([f"  • {ci}: {c} sites" for ci, c in stats["top_cities"]]) or "  _None yet_"

    text = (
        "📊 *Website Generator Stats*\n\n"
        f"🚀 *Total Sites Deployed to Vercel:* `{stats['total_sites']}`\n"
        "⚡ *Engine:* Gemini + Vercel CDN\n"
        "🎨 *Design System:* Tailwind CSS + Google Fonts\n"
        "🛡️ *Database:* Supabase PostgreSQL\n\n"
        f"🏷️ *Top Niches:*\n{top_n}\n\n"
        f"🏙️ *Top Cities:*\n{top_c}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def recent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        return
    sites = await unified_db.get_recent_sites(limit=8)
    if not sites:
        await update.message.reply_text("ℹ️ No demo websites generated yet. Send a Lead ID to create one!")
        return

    lines = ["📜 *Recent Demo Websites Deployed on Vercel:*\n"]
    buttons = []
    for i, s in enumerate(sites, 1):
        bname = s.get("business_name", "Business")
        niche = s.get("niche", "Services")
        city = s.get("city", "")
        url = s.get("live_url", "")
        lines.append(f"*{i}. {bname}* ({niche} • {city})")
        lines.append(f"   🔗 [View Site]({url})\n")
        buttons.append([InlineKeyboardButton(f"🌐 #{i} {bname[:18]}", url=url)])

    text = "\n".join(lines)
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard, disable_web_page_preview=True)

async def generate_site_worker(chat_id: int, user_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    """Asynchronous background worker to prevent Telegram webhook timeouts."""
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="⚡ *Checking Lead Details...*",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        # Check if ID in database
        db_lead = await unified_db.get_lead(text)
        if db_lead:
            business = db_lead
            bname = db_lead.get("name")
            await status_msg.edit_text(
                f"🎯 *Found Lead #{db_lead.get('id')} in Database!*\n"
                f"🏢 *{bname}*\n"
                f"🎨 Generating image-rich website and deploying to Vercel...",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            business = parse_lead_input(text)
            bname = business.get("name") or "Business"
            await status_msg.edit_text(
                f"🏢 *Generating demo website for {bname}...*\n"
                f"🎨 Crafting Tailwind layout & deploying to Vercel CDN...",
                parse_mode=ParseMode.MARKDOWN,
            )

        res = await create_demo_for_business(business, user_id=user_id)
        if not res.get("success"):
            await status_msg.edit_text(f"❌ Failed to generate website: {res.get('error')}")
            return

        live_url = res["live_url"]
        pitch = res["pitch"]
        phone = business.get("phone", "")
        clean_ph = clean_phone_number(phone)

        buttons = [
            [InlineKeyboardButton("🌐 Open Live Demo Website", url=live_url)]
        ]
        if clean_ph:
            encoded_pitch = urllib.parse.quote(pitch)
            wa_pitch_link = f"https://wa.me/{clean_ph}?text={encoded_pitch}"
            buttons.append([InlineKeyboardButton("💬 Send Pitch on WhatsApp", url=wa_pitch_link)])

        keyboard = InlineKeyboardMarkup(buttons)

        delivered_text = (
            f"🎉 *Demo Website Live on Vercel!*\n\n"
            f"🏢 *Business:* {business.get('name')}\n"
            f"🌐 *Live URL:* {live_url}\n\n"
            f"📋 *WhatsApp Outreach Pitch (Tap block to copy):*\n"
            f"```text\n{pitch}\n```"
        )

        await status_msg.edit_text(
            delivered_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error(f"Error in website generation worker: {e}")
        await status_msg.edit_text(f"❌ An error occurred: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user):
        await update.message.reply_text(f"⛔ Unauthorized access. Your Telegram User ID is `{user.id}`.", parse_mode=ParseMode.MARKDOWN)
        return

    text = (update.message.text or "").strip()
    if text == "📜 Recent Sites":
        await recent_handler(update, context)
        return
    elif text == "📊 Stats":
        await stats_handler(update, context)
        return
    elif text == "❓ Help & Examples":
        await help_handler(update, context)
        return

    # Trigger worker immediately
    asyncio.create_task(generate_site_worker(update.effective_chat.id, user.id, text, context))

def setup_website_bot(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("recent", recent_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    return app
