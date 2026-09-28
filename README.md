# Unified Telegram Bots: Lead Hunter & Demo Website Generator

Single-service FastAPI web application hosting two production Telegram bots with Telegram Webhooks, Supabase PostgreSQL persistence, and Vercel edge deployment.

## Bots
1. **Bot 1 (`@leadhunter2834bot`)**: Lead Hunter Bot for finding uncontacted local businesses with Google Reviews, addresses, and 1-tap WhatsApp links.
2. **Bot 2 (`@Websitedemo2489bot`)**: Demo Website Generator Bot for generating mobile-first, image-rich Tailwind landing pages deployed instantly to Vercel CDN.

## Architecture
- **Webhooks**: Handles Telegram updates asynchronously via `/webhook/bot1` and `/webhook/bot2` with `secret_token` validation.
- **Fast Response**: Dispatches background async tasks (`asyncio.create_task`) so webhook responses return to Telegram in `<15ms`, eliminating 15s timeout errors.
- **24/7 Keep-Alive**: Includes `GET /health` designed for UptimeRobot to ping every 5 minutes, preventing Render free-tier spin-down.
- **Database**: Connects to **Supabase PostgreSQL** via `DATABASE_URL` with automatic schema generation and connection pooling (`asyncpg`). Falls back smoothly to SQLite for local development.

## Local Development
```bash
cp .env.example .env
# Set MODE=local in .env
pip install -r requirements.txt
python main.py
```
