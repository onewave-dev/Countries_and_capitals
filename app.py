import os
import asyncio
import orjson
from typing import Any, Dict
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, CallbackQueryHandler
)

# ===== ENV =====
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")         # https://<your-service>.onrender.com
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

# ===== FastAPI =====
app = FastAPI(title="Capitals Bot")

# ===== PTB Application =====
application: Application = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .concurrent_updates(True)
    .build()
)

# ===== Data Loading =====
DATA: Dict[str, Any] = {}
def load_data():
    import json, pathlib
    path = pathlib.Path(__file__).parent / "data" / "capitals.json"
    if not path.exists():
        raise RuntimeError("data/capitals.json missing")
    # orjson for speed; fallback to json if needed
    with open(path, "rb") as f:
        content = f.read()
    return orjson.loads(content)

DATA = load_data()

# ===== Keyboards & Handlers =====
from bot.keyboards import main_menu_kb
from bot.handlers_menu import cmd_start, cb_menu
from bot.handlers_cards import cb_cards
from bot.handlers_sprint import cb_sprint
from bot.handlers_coop import cb_coop

# Register handlers
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CallbackQueryHandler(cb_menu, pattern="^menu:"))
application.add_handler(CallbackQueryHandler(cb_cards, pattern="^cards:"))
application.add_handler(CallbackQueryHandler(cb_sprint, pattern="^sprint:"))
application.add_handler(CallbackQueryHandler(cb_coop, pattern="^coop:"))

# ===== FastAPI models =====
class TelegramUpdate(BaseModel):
    update_id: int | None = None

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/set_webhook")
async def set_webhook():
    if not PUBLIC_URL:
        raise HTTPException(400, "PUBLIC_URL is not set")
    url = f"{PUBLIC_URL}{WEBHOOK_PATH}?secret_token={WEBHOOK_SECRET}"
    await application.bot.set_webhook(url=url, allowed_updates=[])
    return {"ok": True, "url": url}

@app.get("/reset_webhook")
async def reset_webhook():
    await application.bot.delete_webhook(drop_pending_updates=False)
    return {"ok": True}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    # Secret check (Render passes query string)
    token = request.query_params.get("secret_token")
    if token != WEBHOOK_SECRET:
        raise HTTPException(403, "forbidden")

    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}

# ===== Lifespan =====
@app.on_event("startup")
async def on_startup():
    # Nothing special here; webhook is set by /set_webhook
    await application.initialize()
    await application.start()

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()
