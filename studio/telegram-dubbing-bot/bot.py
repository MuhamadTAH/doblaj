#!/usr/bin/env python3
"""
Pird AI Video Dubbing Telegram Bot
Architecture: Aiogram 3.x (Polling local API server) + aiohttp Webhook (Internal callbacks) + SQLite (State)
"""

import asyncio
import io
import os
import signal
import sys
import time
import logging
import traceback
from typing import Dict, Any, Optional

import aiosqlite
import httpx
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pythonjsonlogger import jsonlogger

# =====================================================================
# 1. STRUCTURED LOGGING
# =====================================================================
logger = logging.getLogger("telegram_dubbing_bot")
logger.setLevel(logging.INFO)
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

# =====================================================================
# 2. CONFIGURATION & SECRETS
# =====================================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOCAL_API_SERVER_URL = os.getenv("LOCAL_API_SERVER_URL", "http://telegram-bot-api:8081")
DUBBING_BACKEND_URL = os.getenv("DUBBING_BACKEND_URL", "http://backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "pird_internal_dubbing_key_2026")

DB_PATH = os.getenv("BOT_DB_PATH", "/app/state/jobs.db")
OUTPUTS_DIR = os.getenv("BOT_OUTPUTS_DIR", "/var/lib/telegram-bot-api/pird_outputs")

# Fallback to local script directory if root /app or /var/lib paths are not writable
_base_dir = os.path.dirname(os.path.abspath(__file__))

try:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
except (PermissionError, OSError):
    DB_PATH = os.path.join(_base_dir, "bot-state", "jobs.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

try:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
except (PermissionError, OSError):
    OUTPUTS_DIR = os.path.join(_base_dir, "outputs")
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Globals for shutdown sequence
is_shutting_down = False
db_connection: Optional[aiosqlite.Connection] = None
job_queue: asyncio.Queue = asyncio.Queue()
bot_instance: Optional[Bot] = None
dispatcher_instance: Optional[Dispatcher] = None
webhook_app_runner: Optional[web.AppRunner] = None

# =====================================================================
# 3. SQLITE DATABASE STATE MACHINE
# =====================================================================
# States: PENDING -> READY_FOR_DOWNLOAD -> DOWNLOADING -> SENDING -> DELIVERED

async def init_db():
    global db_connection
    db_connection = await aiosqlite.connect(DB_PATH, timeout=10.0)
    await db_connection.execute('PRAGMA journal_mode=WAL;')
    await db_connection.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            status TEXT,
            input_file_path TEXT,
            target_lang TEXT,
            voice TEXT,
            created_at INTEGER
        )
    ''')
    await db_connection.commit()
    logger.info({"service": "database", "message": "SQLite initialized with WAL."})

async def update_job_status(job_id: str, status: str):
    if db_connection:
        await db_connection.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
        await db_connection.commit()

async def get_job(job_id: str):
    if db_connection:
        async with db_connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "job_id": row[0],
                    "chat_id": row[1],
                    "status": row[2],
                    "input_file_path": row[3],
                    "target_lang": row[4],
                    "voice": row[5]
                }
    return None

# =====================================================================
# 4. BACKGROUND QUEUE WORKER
# =====================================================================
async def process_job_queue():
    while not is_shutting_down or not job_queue.empty():
        try:
            job_id = await job_queue.get()
        except asyncio.CancelledError:
            break
            
        try:
            job = await get_job(job_id)
            if not job:
                continue
                
            chat_id = job["chat_id"]
            
            # 1. DOWNLOAD PHASE
            await update_job_status(job_id, "DOWNLOADING")
            result_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/video/internal/jobs/{job_id}/download"
            local_out_path = os.path.join(OUTPUTS_DIR, f"{job_id}_dubbed.mp4")
            
            # Check if file is already there (from a SENDING crash)
            if not os.path.exists(local_out_path):
                logger.info({"service": "worker", "message": f"Downloading dubbed video for {job_id}"})
                headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
                async with httpx.AsyncClient(timeout=1800.0) as client:
                    async with client.stream('GET', result_url, headers=headers) as resp:
                        if resp.status_code == 200:
                            with open(local_out_path, 'wb') as f:
                                async for chunk in resp.aiter_bytes():
                                    f.write(chunk)
                        else:
                            raise Exception(f"Failed to download video: HTTP {resp.status_code}")
                            
            # 2. SENDING PHASE
            await update_job_status(job_id, "SENDING")
            logger.info({"service": "worker", "message": f"Sending dubbed video to user {chat_id}"})
            if bot_instance:
                video = FSInputFile(local_out_path)
                await bot_instance.send_message(
                    chat_id=chat_id,
                    text="✅ **Dubbing Complete! / تمت الدبلجة بنجاح! / دۆبلاژکردن تەواو بوو!**\nHere is your dubbed video:"
                )
                await bot_instance.send_video(
                    chat_id=chat_id, 
                    video=video, 
                    caption=f"🗣️ Lang: {job['target_lang'].upper()} | 🎙️ Voice: {job['voice'].title()}",
                    request_timeout=1800 # 30 min timeout for massive uploads
                )
                
            # 3. DELIVERED PHASE
            await update_job_status(job_id, "DELIVERED")
            
            # Hygiene
            try:
                os.remove(local_out_path)
                logger.info({"service": "worker", "message": f"Deleted output file {local_out_path}"})
            except OSError as e:
                logger.warning({"service": "worker", "message": f"Output file locked, deferring to sweeper: {e}"})

        except Exception as e:
            logger.error({"service": "worker", "message": f"Error processing job {job_id}", "error": str(e), "traceback": traceback.format_exc()})
            if bot_instance and 'chat_id' in locals():
                try:
                    await bot_instance.send_message(
                        chat_id=chat_id,
                        text="⚠️ **Error during processing / خطأ في المعالجة / هەڵەیەک روویدا**"
                    )
                except:
                    pass
        finally:
            job_queue.task_done()
            
# =====================================================================
# 5. STARTUP RECONCILIATION
# =====================================================================
async def startup_reconciliation():
    logger.info({"service": "startup", "message": "Running startup reconciliation for lost jobs..."})
    if not db_connection:
        return
        
    async with db_connection.execute("SELECT job_id, status FROM jobs WHERE status IN ('PENDING', 'DOWNLOADING', 'SENDING')") as cursor:
        rows = await cursor.fetchall()
        
    for row in rows:
        job_id, status = row[0], row[1]
        logger.info({"service": "startup", "message": f"Reconciling job {job_id} (State: {status})"})
        
        if status == 'SENDING':
            # Job crashed during Telegram upload, try to resume if file exists
            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
            job_queue.put_nowait(job_id)
        elif status == 'DOWNLOADING':
            # Job crashed during download, restart download
            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
            job_queue.put_nowait(job_id)
        elif status == 'PENDING':
            # Query backend to see if it's done
            try:
                status_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/video/internal/jobs/{job_id}/status"
                headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(status_url, headers=headers)
                    if resp.status_code == 200:
                        sdata = resp.json()
                        if sdata.get("status") == "completed":
                            logger.info({"service": "startup", "message": f"Job {job_id} is completed on backend, queueing."})
                            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
                            job_queue.put_nowait(job_id)
            except Exception as e:
                logger.warning({"service": "startup", "message": f"Failed to check pending job {job_id} status: {e}"})

# =====================================================================
# 6. INTERNAL WEBHOOK RECEIVER (FastAPI to Bot)
# =====================================================================
async def internal_webhook(request: web.Request):
    try:
        data = await request.json()
        job_id = data.get("job_id")
        status = data.get("status")
        
        if job_id and status == "completed":
            logger.info({"service": "webhook", "message": f"Backend signaled completion for {job_id}"})
            await update_job_status(job_id, "READY_FOR_DOWNLOAD")
            job_queue.put_nowait(job_id)
            return web.Response(status=202, text="Accepted")
        return web.Response(status=400, text="Bad Request")
    except Exception as e:
        logger.error({"service": "webhook", "message": f"Webhook error: {e}"})
        return web.Response(status=500, text="Internal Error")

# =====================================================================
# 7. HYBRID UI & PAYMENT / AI LOGIC
# =====================================================================
TELEGRAM_ADMIN_IDS = [x.strip() for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()]

def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Pricing Plans / پاکێجەکان", callback_data="view_plans"),
            InlineKeyboardButton(text="💳 Buy Minutes / کڕینی باڵانس", callback_data="buy_menu")
        ],
        [
            InlineKeyboardButton(text="📊 My Balance / باڵانسی من", callback_data="check_balance"),
            InlineKeyboardButton(text="💬 Payment AI / پرسیارکردن", callback_data="ask_ai")
        ]
    ])

def get_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡ Starter: 5 min ($10 / 15,000 IQD)", callback_data="buy_tier:starter")
        ],
        [
            InlineKeyboardButton(text="🚀 Pro: 15 min ($20 / 30,000 IQD)", callback_data="buy_tier:pro")
        ],
        [
            InlineKeyboardButton(text="👑 Creator: 120 min ($99 / 148,500 IQD)", callback_data="buy_tier:creator")
        ],
        [
            InlineKeyboardButton(text="🧪 Test Package: 1 min (1,000 IQD)", callback_data="buy_tier:test_1000iqd")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Menu / گەڕانەوە", callback_data="main_menu")
        ]
    ])

async def request_telegram_payment_link(chat_id: int, tier: Optional[str] = None, minutes: Optional[int] = None, amount_usd: Optional[float] = None) -> Optional[Dict[str, Any]]:
    url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/payments/create-telegram-link"
    headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
    payload = {
        "telegram_chat_id": str(chat_id),
        "tier": tier,
        "minutes": minutes,
        "amount_usd": amount_usd,
        "expires_in": "30m"
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            logger.error({"service": "payments", "message": f"Create link error: {resp.status_code} {resp.text}"})
    except Exception as e:
        logger.error({"service": "payments", "message": f"Failed to call create-telegram-link: {e}"})
    return None

async def query_telegram_balance(chat_id: int) -> Dict[str, Any]:
    url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/balance/{chat_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.error({"service": "balance", "message": f"Failed to query balance: {e}"})
    return {"is_linked": False, "remaining_minutes": 0}

import re

def clean_ai_output(text: str) -> str:
    if not text:
        return ""
    # 1. Remove explicit <think> tags from reasoning models
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. If the model outputted a raw thinking list ("Here's a thinking process:..."), clean it
    if "thinking process" in text.lower():
        lines = text.split("\n")
        cleaned_lines = []
        is_in_thought_block = False
        for line in lines:
            if "thinking process" in line.lower() or "analyze user input" in line.lower():
                is_in_thought_block = True
                continue
            if is_in_thought_block and (line.strip().startswith(("*", "-", "1.", "2.", "3.", "4.", "5.")) or not line.strip()):
                continue
            else:
                is_in_thought_block = False
                cleaned_lines.append(line)
        cleaned_text = "\n".join(cleaned_lines).strip()
        if cleaned_text:
            text = cleaned_text

    return text.strip()

AI_PAYMENT_SYSTEM_PROMPT = """You are the official Doblaj Payment & Pricing AI Assistant.
Your role is EXCLUSIVELY to assist users with Doblaj video dubbing pricing, packages, minutes, and payments.

Doblaj packages:
- Test Package: 1 minute for 1,000 IQD (~$0.67)
- Starter Package: 5 minutes for $10 (15,000 IQD)
- Pro Package: 15 minutes for $20 (30,000 IQD)
- Creator Package: 120 minutes for $99 (148,500 IQD)
Payment methods: Wayl Payment Gateway (supports local Iraqi bank cards, FIB, Qi Card, Visa, Mastercard).
How minutes work: 1 minute of balance = 1 minute of video dubbing with AI voice cloning (preserving original voice & tone) from Kurdish Sorani to Iraqi Arabic.
Links expire in 30 minutes.

GREETINGS:
- If the user says "hello", "hi", "slaw", "marhaba", "salam", or greets you, warmly greet them back in the same language and ask how you can assist them with Doblaj packages or minutes!

CRITICAL INSTRUCTIONS:
- Output ONLY your direct, final response to the user. NEVER output thinking process, internal notes, step-by-step analysis, or "Here's a thinking process".
- You must ONLY discuss Doblaj pricing, plans, minutes, and payments.
- If a user asks about anything unrelated (such as writing code, recipes, weather, general world news, competitors, or other topics), politely decline and state:
  "I am the Doblaj Payment Assistant. I can only assist you with our pricing packages, dubbing minutes, and payment methods."
- Always respond in the EXACT language and dialect the user writes in:
  - If Kurdish Sorani -> Respond warmly and naturally in Kurdish Sorani.
  - If Iraqi Arabic -> Respond naturally in Iraqi Arabic (العامية العراقية).
  - If English -> Respond in professional English.
- Keep answers concise, clear, and helpful.
"""

async def call_payment_ai(user_message: str) -> str:
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    clean_key = openrouter_api_key.strip().strip('"').strip("'")
    clean_model = openrouter_model.strip().strip('"').strip("'") if openrouter_model else "nvidia/nemotron-3.5-lightning:free"
    
    # 1. OpenRouter (Supports all models: nvidia, deepseek, llama, etc.)
    if clean_key:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "HTTP-Referer": "https://doblaj.com",
                "X-Title": "Doblaj Telegram Bot",
                "Content-Type": "application/json"
            }
            payload = {
                "model": clean_model,
                "messages": [
                    {"role": "system", "content": AI_PAYMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.3,
                "max_tokens": 600
            }
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                logger.info({"service": "ai", "message": f"OpenRouter [{clean_model}] response code: {resp.status_code}"})
                
                if resp.status_code == 400:
                    logger.warning({"service": "ai", "message": f"Retrying OpenRouter with merged prompt for {clean_model}"})
                    merged_payload = {
                        "model": clean_model,
                        "messages": [
                            {"role": "user", "content": f"{AI_PAYMENT_SYSTEM_PROMPT}\n\nUser Message: {user_message}\n\nDirect Response (do NOT show thinking process):"}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 600
                    }
                    resp = await client.post(url, json=merged_payload, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        raw_content = choices[0].get("message", {}).get("content", "")
                        cleaned = clean_ai_output(raw_content)
                        if cleaned:
                            return cleaned
                        elif raw_content:
                            return raw_content.strip()
                else:
                    logger.error({"service": "ai", "message": f"OpenRouter returned {resp.status_code}: {resp.text}"})
        except Exception as e:
            logger.error({"service": "ai", "message": f"OpenRouter call error: {e}"})

    # 2. Gemini fallback
    if gemini_api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key.strip()}"
            payload = {
                "system_instruction": {"parts": [{"text": AI_PAYMENT_SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": user_message}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 400}
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
        except Exception as e:
            logger.warning({"service": "ai", "message": f"Gemini call notice: {e}"})

    # 3. Anthropic fallback
    if anthropic_api_key:
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": anthropic_api_key.strip(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 400,
                "system": AI_PAYMENT_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}]
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("content", [])
                    if content:
                        return content[0].get("text", "").strip()
        except Exception as e:
            logger.warning({"service": "ai", "message": f"Anthropic call notice: {e}"})

    return (
        "💡 **Doblaj Packages / پاکێجەکانی دۆبلاژ:**\n\n"
        "• ⚡ **Starter:** 5 min for $10 (15,000 IQD)\n"
        "• 🚀 **Pro:** 15 min for $20 (30,000 IQD)\n"
        "• 👑 **Creator:** 120 min for $99 (148,500 IQD)\n"
        "• 🧪 **Test:** 1 min for 1,000 IQD\n\n"
        "Click /plans to choose your package and pay securely via Wayl!"
    )

def is_admin_user(chat_id: int) -> bool:
    admin_ids = [
        x.strip() for x in (
            os.getenv("TELEGRAM_ADMIN_IDS", "") + "," + os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
        ).split(",") if x.strip()
    ]
    if not admin_ids:
        return True
    return str(chat_id) in admin_ids

class DubbingConfig(StatesGroup):
    waiting_for_video = State()

router = Router()

@router.message.outer_middleware()
async def admin_guard_message_middleware(handler, event: Message, data: dict):
    if not is_admin_user(event.chat.id):
        logger.warning(f"[SECURITY] Unauthorized access blocked: chat_id={event.chat.id}")
        await event.answer("🔒 **Access Denied.**\nThis bot is private and restricted to verified administrators.")
        return
    return await handler(event, data)

@router.callback_query.outer_middleware()
async def admin_guard_callback_middleware(handler, event: CallbackQuery, data: dict):
    chat_id = event.message.chat.id if event.message else event.from_user.id
    if not is_admin_user(chat_id):
        await event.answer("🔒 Unauthorized.", show_alert=True)
        return
    return await handler(event, data)

@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    chat_id = message.chat.id
    username = message.from_user.username if message.from_user else "unknown"

    args = message.text.split()
    if len(args) > 1:
        nonce = args[1]
        headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
        verify_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/link-verify"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(verify_url, json={"nonce": nonce, "telegram_chat_id": str(chat_id)}, headers=headers)
                if resp.status_code == 200:
                    await message.answer("✅ Your Telegram account has been successfully linked to your Doblaj workspace!\nYou can now upload videos here to dub them.", reply_markup=get_main_keyboard())
                elif resp.status_code == 409:
                    await message.answer("⚠️ This workspace is already linked to another Telegram account.", reply_markup=get_main_keyboard())
                else:
                    await message.answer(f"⚠️ Invalid or expired link token. Please generate a new one from the dashboard.", reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error({"service": "auth", "message": f"Error calling verify endpoint: {e}"})
            await message.answer("⚠️ Error communicating with the server. Please try again later.", reply_markup=get_main_keyboard())
        return

    welcome_text = (
        "👋 **Welcome to Doblaj Studio! / بەخێربێن بۆ دۆبلاژ ستۆدیۆ**\n\n"
        "🎬 The #1 AI Video Dubbing platform for Kurdish Sorani to Iraqi Arabic.\n"
        "💎 Fast, seamless, with original voice preservation.\n\n"
        "Choose an option below to buy minutes, check your balance, or chat with our Payment AI:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@router.message(Command("plans"))
async def handle_plans_cmd(message: Message):
    text = (
        "📦 **Doblaj Official Pricing Packages / پاکێجەکانی دۆبلاژ**\n\n"
        "⚡ **Starter Package:** 5 Minutes — **$10** (15,000 IQD)\n"
        "🚀 **Pro Package:** 15 Minutes — **$20** (30,000 IQD)\n"
        "👑 **Creator Package:** 120 Minutes — **$99** (148,500 IQD)\n"
        "🧪 **Test Package:** 1 Minute — **1,000 IQD**\n\n"
        "🔒 *All payments processed securely via Wayl. Links expire in 30 minutes.*"
    )
    await message.answer(text, reply_markup=get_plans_keyboard())

@router.message(Command("buy"))
async def handle_buy_cmd(message: Message):
    await message.answer("💳 **Select a package to generate your secure Wayl payment link:**", reply_markup=get_plans_keyboard())

@router.message(Command("balance"))
async def handle_balance_cmd(message: Message):
    chat_id = message.chat.id
    bal_data = await query_telegram_balance(chat_id)
    rem = bal_data.get("remaining_minutes", 0)
    is_linked = bal_data.get("is_linked", False)
    
    if is_linked:
        text = f"📊 **Your Balance / باڵانسی تۆ:**\n\n🎙️ **{rem} Minutes** remaining in your workspace.\n\nReady to dub videos or top up anytime!"
    else:
        text = f"📊 **Your Balance:**\n\n⚠️ Your Telegram account is not yet linked to a web account.\nYou can still purchase minutes by tapping **Buy Minutes** below, and they will be linked to your chat ID!"
        
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(Command("deal"))
async def handle_deal_cmd(message: Message):
    chat_id = str(message.chat.id)
    if TELEGRAM_ADMIN_IDS and chat_id not in TELEGRAM_ADMIN_IDS:
        await message.answer("⛔ Access Denied. This command is restricted to administrators.")
        return
        
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("ℹ️ **Usage:** `/deal <minutes> <amount_usd>`\n*Example:* `/deal 500 200` (500 minutes for $200)")
        return
        
    try:
        minutes = int(parts[1])
        amount_usd = float(parts[2])
    except ValueError:
        await message.answer("⚠️ Please provide valid numbers for minutes and USD amount.")
        return

    link_data = await request_telegram_payment_link(message.chat.id, minutes=minutes, amount_usd=amount_usd)
    if link_data and "checkout_url" in link_data:
        checkout_url = link_data["checkout_url"]
        iqd = link_data.get("amount_iqd", int(amount_usd * 1500))
        text = (
            f"🎉 **Custom Deal Link Generated!**\n\n"
            f"🎙️ **Minutes:** {minutes} min\n"
            f"💵 **Price:** ${amount_usd} ({iqd:,} IQD)\n"
            f"⏳ **Expires in:** 30 Minutes\n\n"
            f"👉 [Click here to Pay on Wayl]({checkout_url})\n\n"
            f"Once completed, {minutes} minutes will be credited automatically!"
        )
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("⚠️ Failed to generate custom payment link. Please check backend connection.")

@router.callback_query(F.data == "view_plans")
async def on_view_plans(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📦 **Doblaj Official Pricing Packages / پاکێجەکانی دۆبلاژ**\n\n"
        "⚡ **Starter Package:** 5 Minutes — **$10** (15,000 IQD)\n"
        "🚀 **Pro Package:** 15 Minutes — **$20** (30,000 IQD)\n"
        "👑 **Creator Package:** 120 Minutes — **$99** (148,500 IQD)\n"
        "🧪 **Test Package:** 1 Minute — **1,000 IQD**\n\n"
        "Tap a package to get your instant payment link:"
    )
    await callback.message.edit_text(text, reply_markup=get_plans_keyboard())

@router.callback_query(F.data == "buy_menu")
async def on_buy_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("💳 **Choose a package to generate your 30-minute Wayl payment link:**", reply_markup=get_plans_keyboard())

@router.callback_query(F.data == "check_balance")
async def on_check_balance(callback: CallbackQuery):
    await callback.answer()
    bal_data = await query_telegram_balance(callback.message.chat.id)
    rem = bal_data.get("remaining_minutes", 0)
    is_linked = bal_data.get("is_linked", False)
    
    if is_linked:
        text = f"📊 **Your Live Balance / باڵانسی تۆ:**\n\n🎙️ **{rem} Minutes** remaining in your workspace."
    else:
        text = f"📊 **Your Balance:**\n\n🎙️ **{rem} Minutes** available."
        
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())

@router.callback_query(F.data.startswith("buy_tier:"))
async def on_buy_tier(callback: CallbackQuery):
    await callback.answer("Generating payment link...")
    tier = callback.data.split(":", 1)[1]
    
    link_data = await request_telegram_payment_link(callback.message.chat.id, tier=tier)
    if link_data and "checkout_url" in link_data:
        checkout_url = link_data["checkout_url"]
        iqd = link_data.get("amount_iqd", 1000)
        usd = link_data.get("amount_usd", 0.67)
        mins = link_data.get("minutes", 1)
        
        text = (
            f"✅ **Payment Link Ready! / لینکی پارەدان ئامادەیە**\n\n"
            f"📦 **Package:** {tier.replace('_', ' ').title()}\n"
            f"🎙️ **Credits:** +{mins} Dubbing Minutes\n"
            f"💵 **Total:** {iqd:,} IQD (${usd})\n"
            f"⏳ **Expires in:** 30 Minutes\n\n"
            f"👉 [Click here to complete payment on Wayl]({checkout_url})\n\n"
            f"🔒 *Supports local Bank Cards, FIB, Qi Card, Visa & Mastercard.*"
        )
        pay_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay Now on Wayl", url=checkout_url)],
            [InlineKeyboardButton(text="🔙 Back to Packages", callback_data="buy_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=pay_kb, parse_mode="Markdown")
    else:
        await callback.message.answer("⚠️ Could not generate payment link. Please try again in a few moments.")

@router.callback_query(F.data == "ask_ai")
async def on_ask_ai(callback: CallbackQuery):
    await callback.answer()
    text = (
        "💬 **Payment & Pricing AI Assistant**\n\n"
        "Type any question about our plans, pricing, minutes, or payment methods in **Kurdish**, **Arabic**, or **English**!\n\n"
        "Example questions:\n"
        "• *\"چۆن دەتوانم باڵانس بکڕم بە FIB؟\"*\n"
        "• *\"كم سعر باقة الـ 15 دقيقة؟\"*\n"
        "• *\"How does voice cloning and minutes work?\"*"
    )
    await callback.message.answer(text)

@router.callback_query(F.data == "main_menu")
async def on_main_menu(callback: CallbackQuery):
    await callback.answer()
    welcome_text = (
        "👋 **Doblaj Studio Main Menu / مینیوی سەرەکی**\n\n"
        "Choose an option below to buy minutes, check your balance, or chat with our Payment AI:"
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_keyboard())

@router.message(F.video | F.document)
async def handle_video_upload(message: Message, state: FSMContext):
    if is_shutting_down:
        await message.reply("⚠️ Service is shutting down for updates. Please try again later.")
        return
        
    video_obj = message.video or message.document
    max_bytes = 2000 * 1024 * 1024
    
    if not video_obj.file_size or video_obj.file_size > max_bytes:
        await message.reply("⚠️ File too large (max 2000 MB).")
        return

    duration_seconds = getattr(video_obj, 'duration', 0)
    if duration_seconds <= 0:
        # Fallback for documents: assume 1 minute per 15MB
        duration_seconds = int((video_obj.file_size / (15 * 1024 * 1024)) * 60)
        if duration_seconds <= 0:
            duration_seconds = 60

    await state.clear()
    await message.answer("⏳ Checking account balance...")
    
    # Pre-flight reservation
    headers = {"x-internal-key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
    reserve_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/jobs/reserve"
    reservation_id = None
    minutes_reserved = 0
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(reserve_url, json={
                "telegram_chat_id": str(message.chat.id),
                "video_duration_seconds": duration_seconds
            }, headers=headers)
            
            if resp.status_code == 404:
                await message.answer("⚠️ Your Telegram account is not linked to a workspace. Please link it from the Doblaj dashboard first.")
                return
            elif resp.status_code == 402:
                err_detail = resp.json().get("detail", "Insufficient minutes.")
                await message.answer(f"⚠️ {err_detail}\nPlease top up your balance on the dashboard.")
                return
            elif resp.status_code != 200:
                await message.answer("⚠️ Error verifying account balance. Please try again later.")
                return
                
            data = resp.json()
            reservation_id = data.get("reservation_id")
            minutes_reserved = data.get("minutes_reserved")
            
    except Exception as e:
        logger.error({"service": "upload", "message": f"Error reserving minutes: {e}"})
        await message.answer("⚠️ Error verifying account balance. Please try again later.")
        return

    await message.answer("✅ Balance verified. Processing... submitting to dubbing pipeline.")
    
    # 1. Submit to Backend
    try:
        file_info = await bot_instance.get_file(video_obj.file_id)
        local_input_path = file_info.file_path
        
        # Check if file exists locally on the shared volume
        if not os.path.exists(local_input_path):
            raise Exception(f"Local file not found at {local_input_path}")
            
        logger.info({"service": "upload", "message": "Streaming upload to backend..."})
        
        # Open file to stream it directly via httpx, preventing OOM
        f = open(local_input_path, 'rb')
        
        bot_webhook_url = os.getenv("BOT_WEBHOOK_URL")
        form_data = {
            "chat_id": str(message.chat.id),
            "source": "telegram",
        }
        if bot_webhook_url:
            form_data["webhook_url"] = bot_webhook_url
        files = {"file": (os.path.basename(local_input_path), f, "video/mp4")}
        
        async with httpx.AsyncClient(timeout=1800.0) as client:
            backend_jobs_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/video/internal/jobs"
            resp = await client.post(backend_jobs_url, data=form_data, files=files, headers=headers)
            f.close()
            
            if resp.status_code not in (200, 201, 202):
                raise RuntimeError(f"Backend rejected job: {resp.text}")
                
            data = resp.json()
            job_id = data.get("id")
            
            # Insert to DB
            if db_connection:
                await db_connection.execute('''
                    INSERT INTO jobs (job_id, chat_id, status, input_file_path, target_lang, voice, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (job_id, message.chat.id, "PENDING", local_input_path, "ar_iq", "auto_clone", int(time.time())))
                await db_connection.commit()
                
            # Input Hemorrhage Fix: Explicitly delete the input immediately
            try:
                os.remove(local_input_path)
                logger.info({"service": "upload", "message": f"Successfully deleted input file {local_input_path}"})
            except OSError as err:
                logger.warning({"service": "upload", "message": f"Input file locked, deferring to sweeper: {err}"})

    except Exception as e:
        logger.error({"service": "upload", "message": "Error submitting job", "error": str(e)})
        await message.answer("⚠️ Error submitting your video. Please try again.")
        # Refund minutes if reserved
        if reservation_id and minutes_reserved > 0:
            try:
                refund_url = f"{DUBBING_BACKEND_URL.rstrip('/')}/api/telegram/jobs/refund"
                async with httpx.AsyncClient() as client:
                    await client.post(refund_url, json={
                        "reservation_id": reservation_id,
                        "telegram_chat_id": str(message.chat.id),
                        "minutes_to_refund": minutes_reserved
                    }, headers=headers)
                logger.info({"service": "upload", "message": f"Refunded {minutes_reserved} minutes for failed job."})
            except Exception as refund_e:
                logger.error({"service": "upload", "message": f"Failed to refund minutes: {refund_e}"})

@router.message(F.text)
async def handle_text_questions(message: Message, state: FSMContext):
    """Handle general user questions using the Scoped Payment AI Assistant."""
    user_text = (message.text or "").strip()
    if not user_text or user_text.startswith("/"):
        return
        
    logger.info({"service": "ai_chat", "chat_id": message.chat.id, "text": user_text})
    
    if bot_instance:
        try:
            await bot_instance.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception:
            pass
            
    try:
        ai_response = await call_payment_ai(user_text)
    except Exception as e:
        logger.error({"service": "ai_chat", "error": str(e)})
        ai_response = (
            "💡 **Doblaj Packages / پاکێجەکانی دۆبلاژ:**\n\n"
            "• ⚡ **Starter:** 5 min for $10 (15,000 IQD)\n"
            "• 🚀 **Pro:** 15 min for $20 (30,000 IQD)\n"
            "• 👑 **Creator:** 120 min for $99 (148,500 IQD)\n"
            "• 🧪 **Test:** 1 min for 1,000 IQD\n\n"
            "Click /plans to choose your package and pay securely via Wayl!"
        )
    
    quick_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Buy Minutes / کڕینی باڵانس", callback_data="buy_menu"),
            InlineKeyboardButton(text="📦 Pricing Plans", callback_data="view_plans")
        ]
    ])
    await message.answer(ai_response, reply_markup=quick_kb)

# =====================================================================
# 8. SHUTDOWN SEQUENCE
# =====================================================================
async def graceful_shutdown(sig):
    global is_shutting_down
    logger.info({"service": "devops", "message": f"Received signal {sig.name}. Starting Graceful Shutdown..."})
    is_shutting_down = True
    
    # 1. Stop webhook server
    if webhook_app_runner:
        logger.info({"service": "devops", "message": "Stopping webhook receiver (rejecting new incoming webhooks)..."})
        await webhook_app_runner.cleanup()
        
    # 2. Stop aiogram polling
    if dispatcher_instance and bot_instance:
        logger.info({"service": "devops", "message": "Stopping aiogram polling (rejecting new user messages)..."})
        await dispatcher_instance.stop_polling()
        
    # 3. Drain asyncio.Queue
    logger.info({"service": "devops", "message": "Waiting for active downloads and Telegram uploads to finish..."})
    await job_queue.join()
    
    # 4. Close DB
    if db_connection:
        logger.info({"service": "devops", "message": "Closing SQLite connection safely..."})
        await db_connection.close()
        
    logger.info({"service": "devops", "message": "Graceful Shutdown complete. Exiting."})
    sys.exit(0)

# =====================================================================
# 9. MAIN LIFECYCLE
# =====================================================================
async def main():
    global bot_instance, dispatcher_instance, webhook_app_runner
    
    # Setup Signal Handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(graceful_shutdown(s)))

    # Init SQLite
    await init_db()
    
    # Startup Reconciliation
    await startup_reconciliation()
    
    # Start Queue Worker
    worker_task = asyncio.create_task(process_job_queue())

    # Start Aiohttp Webhook Server
    app = web.Application()
    app.router.add_post("/callback", internal_webhook)
    webhook_app_runner = web.AppRunner(app)
    await webhook_app_runner.setup()
    site = web.TCPSite(webhook_app_runner, '0.0.0.0', 8000)
    await site.start()
    logger.info({"service": "devops", "message": "Internal Webhook Receiver started on 0.0.0.0:8000/callback"})

    # Start Aiogram Polling
    use_local_api = os.getenv("USE_LOCAL_TELEGRAM_API", "false").lower() == "true"
    if use_local_api:
        logger.info({"service": "devops", "message": f"Starting Telegram Polling via Local API Server {LOCAL_API_SERVER_URL}..."})
        api_server = TelegramAPIServer.from_base(LOCAL_API_SERVER_URL, is_local=True)
        session = AiohttpSession(api=api_server, timeout=1800.0) # 30 mins
        bot_instance = Bot(token=BOT_TOKEN, session=session)
    else:
        logger.info({"service": "devops", "message": "Starting Telegram Polling via official Telegram API (https://api.telegram.org)..."})
        bot_instance = Bot(token=BOT_TOKEN)
        
    dispatcher_instance = Dispatcher(storage=MemoryStorage())
    dispatcher_instance.include_router(router)
    
    try:
        await bot_instance.delete_webhook(drop_pending_updates=True) # Ensure we aren't using webhooks for Telegram
        await dispatcher_instance.start_polling(bot_instance)
    except asyncio.CancelledError:
        pass
    finally:
        await bot_instance.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
