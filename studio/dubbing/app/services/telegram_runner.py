import asyncio
import os
import logging
from typing import Optional, Dict, Any

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from app.core import database_convex as convex_db
from app.core import database as sqlite_db

logger = logging.getLogger("telegram_runner")
logger.setLevel(logging.INFO)

# =====================================================================
# 1. CONFIGURATION
# =====================================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "pird_internal_dubbing_key_2026")
TELEGRAM_ADMIN_IDS = [x.strip() for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()]
BASE_API_URL = os.getenv("BASE_API_URL", "http://127.0.0.1:8000")

# =====================================================================
# 2. KEYBOARDS
# =====================================================================
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

# =====================================================================
# 3. HELPERS
# =====================================================================
async def create_telegram_payment_link(chat_id: int, tier: Optional[str] = None, minutes: Optional[int] = None, amount_usd: Optional[float] = None) -> Optional[Dict[str, Any]]:
    from app.core.wayl_client import WaylClient
    from app.core import database as db
    
    workspace_id = await db.get_workspace_by_telegram_id(str(chat_id))
    if not workspace_id:
        workspace_id = f"tg_{chat_id}"
        
    TIER_PRICING = {
        "starter": {"minutes": 5, "amount_usd": 10.0, "amount_iqd": 15000, "name": "Starter Package"},
        "pro": {"minutes": 15, "amount_usd": 20.0, "amount_iqd": 30000, "name": "Pro Package"},
        "creator": {"minutes": 120, "amount_usd": 99.0, "amount_iqd": 148500, "name": "Creator Package"},
        "test_1000iqd": {"minutes": 1, "amount_usd": 0.67, "amount_iqd": 1000, "name": "Test Package (1,000 IQD)"}
    }
    
    if tier and tier in TIER_PRICING:
        t_info = TIER_PRICING[tier]
        pkg_name = t_info["name"]
        mins = t_info["minutes"]
        usd = t_info["amount_usd"]
        iqd = t_info["amount_iqd"]
    elif minutes and amount_usd:
        pkg_name = f"Custom Deal: {minutes} Minutes"
        mins = minutes
        usd = amount_usd
        iqd = int(amount_usd * 1500)
    else:
        t_info = TIER_PRICING["test_1000iqd"]
        pkg_name = t_info["name"]
        mins = t_info["minutes"]
        usd = t_info["amount_usd"]
        iqd = t_info["amount_iqd"]

    wayl = WaylClient()
    link_data = await wayl.create_payment_link(
        amount=iqd,
        currency="IQD",
        title=f"Doblaj - {pkg_name}",
        description=f"Add +{mins} minutes to workspace {workspace_id} (Telegram @{chat_id})",
        redirect_url="https://doblaj.com/dubbing?payment=success",
        expires_in="30m",
        metadata={
            "workspace_id": workspace_id,
            "telegram_chat_id": str(chat_id),
            "tier": tier or "custom",
            "minutes": mins,
            "amount_usd": usd,
            "amount_iqd": iqd
        }
    )
    
    if link_data and ("checkout_url" in link_data or "url" in link_data):
        checkout_url = link_data.get("checkout_url") or link_data.get("url")
        return {
            "checkout_url": checkout_url,
            "minutes": mins,
            "amount_usd": usd,
            "amount_iqd": iqd
        }
    return None

async def query_telegram_balance(chat_id: int) -> Dict[str, Any]:
    try:
        workspace_id = await sqlite_db.get_workspace_by_telegram_id(str(chat_id))
        if not workspace_id:
            return {"is_linked": False, "remaining_minutes": 0}
        minutes = await convex_db.get_workspace_minutes(workspace_id=workspace_id)
        return {"is_linked": True, "remaining_minutes": int(minutes)}
    except Exception as e:
        logger.error(f"[TELEGRAM_BALANCE] Error querying balance: {e}")
        return {"is_linked": False, "remaining_minutes": 0}

import re

def clean_ai_output(text: str) -> str:
    if not text:
        return ""
    # 1. Remove explicit <think> tags
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. If the model outputted an explicit or informal thinking process, extract or clean it
    if any(k in text.lower() for k in ("thinking process", "analyze user input", "wait, let's", "let's count", "let's check", "let's analyze")):
        parts = re.split(r"(?:response:|final response:|direct answer:|\n\n(?=[A-Z\u0600-\u06FF][a-z\u0600-\u06FF]))", text, flags=re.IGNORECASE)
        non_thoughts = [
            p.strip() for p in parts 
            if p.strip() and not p.lower().startswith(("wait,", "let's", "first,", "okay, so", "thinking process"))
        ]
        if non_thoughts:
            return non_thoughts[-1]
            
        lines = [
            l for l in text.split("\n") 
            if not re.search(r"^(?:\d+\.|\*|-|Here's a thinking process|Analyze User Input|Check Constraints|Determine Response|Evaluate if|Wait,|Let's count|Let's check|Let's analyze)", l.strip(), re.IGNORECASE)
        ]
        cleaned = "\n".join(lines).strip()
        if cleaned and not cleaned.lower().startswith(("wait,", "let's")):
            return cleaned
        return ""

    return text.strip()

def format_admin_sales_report(links: list) -> str:
    paid = [l for l in links if str(l.get("status", "")).lower() in ("complete", "paid")]
    refunded = [l for l in links if str(l.get("status", "")).lower() in ("returned", "refunded")]
    pending = [l for l in links if str(l.get("status", "")).lower() in ("created", "pending")]
    
    paid_iqd = sum(int(float(l.get("amount", 0) or 0)) for l in paid)
    refunded_iqd = sum(int(float(l.get("amount", 0) or 0)) for l in refunded)
    
    rows = []
    for l in links[:12]:
        st = str(l.get("status", ""))
        amt = int(float(l.get("amount", 0) or 0))
        ref = str(l.get("referenceId") or l.get("id") or "")[:12]
        date_str = str(l.get("createdAt") or "")[:10]
        
        if st.lower() in ("complete", "paid"):
            badge = "✅ Paid"
        elif st.lower() in ("returned", "refunded"):
            badge = "↩️ Refunded"
        else:
            badge = "⏳ Pending"
            
        rows.append(f"• `{ref}` | **{amt:,} IQD** | {date_str} | {badge}")
        
    return (
        f"📊 **Doblaj Live Orders & Revenue Report (Last 7 Days)**\n\n"
        f"💰 **Total Gross Revenue:** {paid_iqd:,} IQD\n"
        f"💳 **Paid / Completed Orders:** {len(paid)}\n"
        f"↩️ **Refunded Orders:** {len(refunded)} ({refunded_iqd:,} IQD)\n"
        f"⏳ **Pending Sessions:** {len(pending)}\n"
        f"📦 **Total Orders Generated:** {len(links)}\n\n"
        f"**Recent Orders:**\n" + "\n".join(rows)
    )

AI_EXECUTIVE_SYSTEM_PROMPT = """You are the personal Executive AI Assistant for the Founder & Owner of Doblaj Studio (AI Video Dubbing Platform).

You have full authority to assist the Founder with:
1. Live Business Intelligence & Orders: Answering questions about total sales volume, orders created this week, refunds, revenue, and customer activity using the LIVE STORE SALES & ORDERS CONTEXT provided below.
2. Pricing Packages:
   - Test Package: 1 minute for 1,000 IQD (~$0.67)
   - Starter Package: 5 minutes for $10 (15,000 IQD)
   - Pro Package: 15 minutes for $20 (30,000 IQD)
   - Creator Package: 120 minutes for $99 (148,500 IQD)
3. Payment Gateway: Wayl (supports FIB, Qi Card, Visa, Mastercard, and local bank cards).
4. Custom Client Deals: Helping structure and quote custom deals via /deal <minutes> <amount_usd>.

CRITICAL INSTRUCTIONS:
- You are speaking directly to the FOUNDER. Answer all questions directly, accurately, and without hesitation.
- NEVER output reasoning notes, thinking processes, monologue, or phrases like "Wait, let's count" or "Here's a thinking process".
- Respond in the EXACT language and dialect the Founder writes in:
  - If Kurdish Sorani -> Respond warmly and naturally in Kurdish Sorani.
  - If Iraqi Arabic -> Respond naturally in Iraqi Arabic (العامية العراقية).
  - If English -> Respond in professional English.
- Be concise, direct, and structured.
"""

async def get_live_store_context() -> tuple[str, list]:
    from app.core.wayl_client import WaylClient
    try:
        wayl = WaylClient()
        links = await wayl.list_links() or []
        paid = [l for l in links if l.get("status", "").lower() in ("complete", "paid")]
        refunded = [l for l in links if l.get("status", "").lower() in ("returned", "refunded")]
        pending = [l for l in links if l.get("status", "").lower() in ("created", "pending")]
        
        paid_iqd = sum(int(float(l.get("amount", 0) or 0)) for l in paid)
        refunded_iqd = sum(int(float(l.get("amount", 0) or 0)) for l in refunded)
        
        orders_snippet = "\n".join([
            f"  - Ref: {str(l.get('referenceId') or l.get('id') or '')[:12]} | Amount: {int(float(l.get('amount', 0) or 0)):,} IQD | Status: {l.get('status')} | Date: {str(l.get('createdAt') or '')[:10]}"
            for l in links
        ])
        
        ctx = (
            f"\nLIVE STORE SALES & ORDERS CONTEXT:\n"
            f"- Total Orders/Links Created (Last 7 Days): {len(links)}\n"
            f"- Completed/Paid Orders: {len(paid)} (Total Gross Revenue: {paid_iqd:,} IQD)\n"
            f"- Refunded Orders: {len(refunded)} (Total Refunded: {refunded_iqd:,} IQD)\n"
            f"- Pending Sessions: {len(pending)}\n"
            f"- All Recent Orders List:\n{orders_snippet}\n"
        )
        return ctx, links
    except Exception as e:
        return f"\n(Store context unavailable: {e})\n", []

async def call_payment_ai(user_message: str) -> str:
    msg_lower = user_message.lower()
    analytics_keywords = [
        "order", "orders", "sale", "sales", "revenue", "week", "profit", 
        "refund", "refunds", "stats", "history", "ئۆردەر", "داواکاری", 
        "داهات", "طلبات", "مبيعات", "ارباح", "تقرير", "داتا", "data"
    ]
    
    store_context, links = await get_live_store_context()
    
    # 1. If it's a direct analytics/orders question, return instant 100% verified accurate report
    if any(k in msg_lower for k in analytics_keywords) and links:
        return format_admin_sales_report(links)
    
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    clean_key = openrouter_api_key.strip().strip('"').strip("'")
    clean_model = openrouter_model.strip().strip('"').strip("'") if openrouter_model else "deepseek/deepseek-chat"
    
    dynamic_prompt = f"{AI_EXECUTIVE_SYSTEM_PROMPT}\n{store_context}"
    
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
                    {"role": "system", "content": dynamic_prompt},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.2,
                "max_tokens": 800
            }
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 400:
                    merged_payload = {
                        "model": clean_model,
                        "messages": [
                            {"role": "user", "content": f"{dynamic_prompt}\n\nUser Question: {user_message}\n\nDirect Answer (no thinking notes):"}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 800
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
                else:
                    logger.error(f"[AI_OPENROUTER] Error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[AI_OPENROUTER] Exception: {e}")

    if gemini_api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key.strip()}"
            payload = {
                "system_instruction": {"parts": [{"text": dynamic_prompt}]},
                "contents": [{"parts": [{"text": user_message}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
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
            logger.warning(f"[AI_GEMINI] Error: {e}")

    # Fallback to direct computed context
    if links:
        return format_admin_sales_report(links)
    return f"📊 **Doblaj Live Orders & Revenue:**\n{store_context.strip()}"

# =====================================================================
# 4. ROUTER & HANDLERS (STRICT ADMIN ACCESS ONLY)
# =====================================================================
def is_admin_user(chat_id: int) -> bool:
    admin_ids = [
        x.strip() for x in (
            os.getenv("TELEGRAM_ADMIN_IDS", "") + "," + os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
        ).split(",") if x.strip()
    ]
    if not admin_ids:
        return True
    return str(chat_id) in admin_ids

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
    args = message.text.split()
    
    if len(args) > 1:
        nonce = args[1]
        try:
            res = await sqlite_db.verify_and_link_telegram(nonce, str(chat_id))
            if res:
                await message.answer("✅ Your Telegram account has been successfully linked to your Doblaj workspace!\nYou can now upload videos here to dub them.", reply_markup=get_main_keyboard())
            else:
                await message.answer("⚠️ Invalid or expired link token. Please generate a new one from the dashboard.", reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error(f"[TELEGRAM_VERIFY] Error: {e}")
            await message.answer("⚠️ Error communicating with the server. Please try again later.", reply_markup=get_main_keyboard())
        return

    welcome_text = (
        "👋 **Welcome Boss! / بەخێربێن بەڕێزم**\n\n"
        "👑 **Doblaj Private Admin & AI Assistant**\n"
        "⚡ You have full control over orders, analytics, packages, and custom deals.\n\n"
        "Choose an option below or type any question:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@router.message(Command("stats"))
@router.message(Command("orders"))
async def handle_admin_stats(message: Message):
    from app.core.wayl_client import WaylClient
    wayl = WaylClient()
    try:
        links = await wayl.list_links() or []
    except Exception as e:
        await message.answer(f"⚠️ Error querying Wayl: {e}")
        return
        
    paid_count = 0
    returned_count = 0
    pending_count = 0
    total_paid_iqd = 0
    
    rows = []
    for l in links:
        st = str(l.get("status", ""))
        amt = int(float(l.get("amount", 0) or 0))
        ref = str(l.get("referenceId") or l.get("id") or "")[:12]
        date_str = str(l.get("createdAt") or "")[:10]
        
        if st.lower() in ("complete", "paid"):
            paid_count += 1
            total_paid_iqd += amt
            badge = "✅ Paid"
        elif st.lower() in ("returned", "refunded"):
            returned_count += 1
            badge = "↩️ Refunded"
        else:
            pending_count += 1
            badge = "⏳ Pending"
            
        rows.append(f"• `{ref}` | {amt:,} IQD | {date_str} | {badge}")
        
    summary_text = (
        f"📊 **Doblaj Live Orders & Revenue (Last 7 Days)**\n\n"
        f"💰 **Total Gross Revenue:** {total_paid_iqd:,} IQD\n"
        f"💳 **Paid Orders:** {paid_count}\n"
        f"↩️ **Refunded Orders:** {returned_count}\n"
        f"⏳ **Pending Sessions:** {pending_count}\n"
        f"📦 **Total Generated:** {len(links)}\n\n"
        f"**Recent Orders:**\n" + "\n".join(rows[:10])
    )
    await message.answer(summary_text, parse_mode="Markdown")

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

    link_data = await create_telegram_payment_link(message.chat.id, minutes=minutes, amount_usd=amount_usd)
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
    
    link_data = await create_telegram_payment_link(callback.message.chat.id, tier=tier)
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

@router.message(F.text)
async def handle_text_questions(message: Message, state: FSMContext):
    """Handle general user questions using the Scoped Payment AI Assistant."""
    user_text = (message.text or "").strip()
    if not user_text or user_text.startswith("/"):
        return
        
    logger.info(f"[AI_CHAT] Chat {message.chat.id}: {user_text}")
    
    bot = message.bot
    if bot:
        try:
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception:
            pass
            
    try:
        ai_response = await call_payment_ai(user_text)
    except Exception as e:
        logger.error(f"[AI_CHAT] Error: {e}")
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
# 5. POLLING RUNNER
# =====================================================================
async def start_telegram_bot_task():
    """Starts the Telegram bot polling loop as a background task."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        logger.warning("[TELEGRAM_RUNNER] TELEGRAM_BOT_TOKEN not set. Bot polling disabled.")
        return
        
    logger.info(f"[TELEGRAM_RUNNER] Starting Telegram bot polling with token {bot_token[:6]}...")
    bot = Bot(token=bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("[TELEGRAM_RUNNER] Telegram bot polling task cancelled.")
    except Exception as e:
        logger.exception(f"[TELEGRAM_RUNNER] Telegram bot polling error: {e}")
    finally:
        await bot.session.close()
