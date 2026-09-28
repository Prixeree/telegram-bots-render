import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from telegram import Update

from database import unified_db
from bot_leads import setup_lead_bot
from bot_websites import setup_website_bot

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("UnifiedServer")

MODE = os.getenv("MODE", "webhook").strip().lower()
PORT = int(os.getenv("PORT", "8000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

BOT1_TOKEN = os.getenv("BOT1_TOKEN", "")
BOT1_SECRET = os.getenv("BOT1_SECRET", "secret_token_bot1")

BOT2_TOKEN = os.getenv("BOT2_TOKEN", "")
BOT2_SECRET = os.getenv("BOT2_SECRET", "secret_token_bot2")

# Initialize Telegram application objects
lead_app = setup_lead_bot(BOT1_TOKEN) if BOT1_TOKEN else None
website_app = setup_website_bot(BOT2_TOKEN) if BOT2_TOKEN else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup: Connect to Supabase Postgres or fallback SQLite
    await unified_db.init()

    # 2. Initialize both Telegram bots
    if lead_app:
        await lead_app.initialize()
        await lead_app.start()
    if website_app:
        await website_app.initialize()
        await website_app.start()

    # 3. Configure Webhooks or Local Polling
    if MODE == "webhook":
        if RENDER_URL:
            if lead_app:
                w1 = f"{RENDER_URL}/webhook/bot1"
                await lead_app.bot.set_webhook(url=w1, secret_token=BOT1_SECRET, drop_pending_updates=True)
                logger.info(f"🚀 Set Webhook for Bot 1 (Lead Hunter) -> {w1}")
            if website_app:
                w2 = f"{RENDER_URL}/webhook/bot2"
                await website_app.bot.set_webhook(url=w2, secret_token=BOT2_SECRET, drop_pending_updates=True)
                logger.info(f"🚀 Set Webhook for Bot 2 (Website Generator) -> {w2}")
        else:
            logger.warning("⚠️ RENDER_EXTERNAL_URL is not set yet. Set it in Render dashboard or wait for initial deployment.")
    else:
        logger.info("⚡ MODE=local detected. Starting local polling...")
        if lead_app:
            await lead_app.bot.delete_webhook()
            await lead_app.updater.start_polling()
        if website_app:
            await website_app.bot.delete_webhook()
            await website_app.updater.start_polling()

    yield

    # Shutdown
    if lead_app:
        if MODE == "local" and lead_app.updater.running:
            await lead_app.updater.stop()
        await lead_app.stop()
        await lead_app.shutdown()

    if website_app:
        if MODE == "local" and website_app.updater.running:
            await website_app.updater.stop()
        await website_app.stop()
        await website_app.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/health", response_class=PlainTextResponse)
async def health_check():
    """UptimeRobot ping target to keep Render service awake 24/7."""
    return "ok"

@app.post("/webhook/bot1")
async def bot1_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    """Webhook route for Bot 1 (Lead Hunter). Validates Telegram secret token."""
    if not lead_app:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bot 1 not configured")
    if x_telegram_bot_api_secret_token != BOT1_SECRET:
        logger.warning("Unauthorized secret token received on Bot 1 webhook")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    payload = await request.json()
    update = Update.de_json(payload, lead_app.bot)
    await lead_app.process_update(update)
    return {"status": "ok"}

@app.post("/webhook/bot2")
async def bot2_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    """Webhook route for Bot 2 (Website Generator). Validates Telegram secret token."""
    if not website_app:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bot 2 not configured")
    if x_telegram_bot_api_secret_token != BOT2_SECRET:
        logger.warning("Unauthorized secret token received on Bot 2 webhook")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    payload = await request.json()
    update = Update.de_json(payload, website_app.bot)
    await website_app.process_update(update)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
