import os
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, CallbackQueryHandler
)

from bot.utils import tg_call

# ===== ENV =====
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")         # https://<your-service>.onrender.com
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

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

startup_lock = asyncio.Lock()

# ===== Data Loading =====
from bot.state import DataSource

DATA: DataSource


def load_data() -> DataSource:
    import pathlib

    path = pathlib.Path(__file__).parent / "data" / "capitals.json"
    if not path.exists():
        raise RuntimeError("data/capitals.json missing")
    return DataSource.load(path)


DATA = load_data()

# ===== Keyboards & Handlers =====
from bot.keyboards import main_menu_kb
from bot.handlers_menu import cmd_start, cb_menu
from bot.handlers_cards import cb_cards
from bot.handlers_sprint import cb_sprint
from bot.handlers_coop import cb_coop, cmd_coop_capitals, cmd_coop_test
from bot.handlers_stats import cmd_stats

# Register handlers
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CallbackQueryHandler(cb_menu, pattern="^menu:"))
application.add_handler(CallbackQueryHandler(cb_cards, pattern="^cards:"))
application.add_handler(CallbackQueryHandler(cb_sprint, pattern="^sprint:"))
application.add_handler(CallbackQueryHandler(cb_coop, pattern="^coop:"))
application.add_handler(CommandHandler("coop_capitals", cmd_coop_capitals))
application.add_handler(CommandHandler("coop_test", cmd_coop_test))
application.add_handler(CommandHandler("stats", cmd_stats))


async def check_webhook(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically verify webhook status and log anomalies."""
    if not PUBLIC_URL:
        return

    expected_url = f"{PUBLIC_URL}{WEBHOOK_PATH}?secret_token={WEBHOOK_SECRET}"
    info = await tg_call(context.bot.get_webhook_info)

    if info.url != expected_url:
        logger.warning(
            "Webhook URL mismatch: expected %s, got %s", expected_url, info.url
        )
    if info.pending_update_count:
        logger.warning(
            "Webhook has %d pending updates", info.pending_update_count
        )
    if info.last_error_message:
        logger.error(
            "Webhook error: %s (since %s)",
            info.last_error_message,
            info.last_error_date,
        )

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
    await tg_call(application.bot.set_webhook, url=url, allowed_updates=[])
    logger.info("Webhook registered at %s", url)
    return {"ok": True, "url": url}

@app.get("/reset_webhook")
async def reset_webhook():
    await tg_call(application.bot.delete_webhook, drop_pending_updates=False)
    logger.info("Webhook deleted")
    return {"ok": True}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    # Secret check (Render passes query string)
    token = request.query_params.get("secret_token")
    if token != WEBHOOK_SECRET:
        raise HTTPException(403, "forbidden")

    if not getattr(application, "_initialized", False) or not application.running:
        raise HTTPException(503, "service unavailable")

    data = await request.json()
    update = Update.de_json(data, application.bot)

    if not application.running:
        raise HTTPException(503, "service unavailable")
    await application.process_update(update)
    return {"ok": True}

# ===== Lifespan =====
@app.on_event("startup")
async def on_startup():
    logger.info("Application startup")
    async with startup_lock:
        if not getattr(application, "_initialized", False):
            await application.initialize()
        if not application.running:
            await application.start()

    if PUBLIC_URL:
        expected_url = f"{PUBLIC_URL}{WEBHOOK_PATH}?secret_token={WEBHOOK_SECRET}"
        info = await tg_call(application.bot.get_webhook_info)
        if info.url != expected_url:
            logger.info(
                "Re-registering webhook: expected %s, got %s",
                expected_url,
                info.url,
            )
            await tg_call(
                application.bot.set_webhook,
                url=expected_url,
                allowed_updates=[],
            )
    else:
        logger.warning("PUBLIC_URL is not set; webhook check skipped")

    if application.job_queue:
        application.job_queue.run_repeating(
            check_webhook, interval=600, first=600
        )
    else:
        logger.warning(
            "Job queue is not available; skipping webhook check scheduling"
        )

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Application shutdown")
    await application.stop()
    await application.shutdown()
