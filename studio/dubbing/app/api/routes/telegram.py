import logging
import os
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.auth.clerk_auth import require_user, require_user_or_internal, AuthenticatedUser
from app.core import database as db
from app.core import database_convex as convex_db

logger = logging.getLogger(__name__)

router = APIRouter()

class LinkNonceResponse(BaseModel):
    nonce: str
    expires_in_minutes: int

class LinkVerifyRequest(BaseModel):
    nonce: str
    telegram_chat_id: str

class JobReserveRequest(BaseModel):
    telegram_chat_id: str
    video_duration_seconds: int

class JobReserveResponse(BaseModel):
    reservation_id: str
    workspace_id: str
    minutes_reserved: int

class JobRefundRequest(BaseModel):
    reservation_id: str
    telegram_chat_id: str
    minutes_to_refund: int


@router.post("/link-nonce", response_model=LinkNonceResponse)
@router.post("/link-nonce/", response_model=LinkNonceResponse, include_in_schema=False)
async def generate_link_nonce(user: AuthenticatedUser = Depends(require_user)):
    """Generate a short-lived nonce for linking a Telegram account to the user's workspace."""
    expires_in = 10
    nonce = await db.create_telegram_nonce(user.workspace_id, expires_in)
    return LinkNonceResponse(nonce=nonce, expires_in_minutes=expires_in)


@router.post("/link-verify")
async def verify_link_nonce(req: LinkVerifyRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """Consume a nonce and link the provided telegram chat ID to the workspace."""
    if user.email != "bot@internal.doblaj.com":
        raise HTTPException(status_code=403, detail="Only internal bot can call this endpoint.")
        
    workspace_id = await db.consume_telegram_nonce(req.nonce)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="Invalid or expired nonce.")
        
    success = await db.link_telegram_account(req.telegram_chat_id, workspace_id)
    if not success:
        raise HTTPException(status_code=409, detail="This workspace is already linked to another Telegram account.")
        
    return {"status": "success", "workspace_id": workspace_id}


MAX_RESERVATION_SECONDS = int(os.getenv("MAX_RESERVATION_SECONDS", "1800"))

@router.post("/jobs/reserve", response_model=JobReserveResponse)
async def reserve_job_minutes(req: JobReserveRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """Reserve minutes for a job upfront."""
    if user.email != "bot@internal.doblaj.com":
        raise HTTPException(status_code=403, detail="Only internal bot can call this endpoint.")

    if req.video_duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="video_duration_seconds must be > 0")
    if req.video_duration_seconds > MAX_RESERVATION_SECONDS:
        raise HTTPException(status_code=400, detail=f"video_duration_seconds exceeds maximum allowed limit of {MAX_RESERVATION_SECONDS}s ({MAX_RESERVATION_SECONDS // 60} mins)")

    workspace_id = await db.get_workspace_by_telegram_id(req.telegram_chat_id)
    if not workspace_id:
        raise HTTPException(status_code=404, detail="Telegram account not linked to any workspace.")
        
    # Calculate required minutes: ceiling of duration / 60
    import math
    required_minutes = math.ceil(req.video_duration_seconds / 60.0)
    if required_minutes <= 0:
        required_minutes = 1  # Minimum 1 minute charge
        
    # Check if user has enough minutes (this could be racy, but deduct_workspace_minutes is atomic in Convex)
    current_minutes = await convex_db.get_workspace_minutes(workspace_id=workspace_id)
    if current_minutes < required_minutes:
        raise HTTPException(status_code=402, detail=f"Insufficient minutes. Required: {required_minutes}, Available: {current_minutes}")
        
    # Deduct minutes via Convex
    await convex_db.deduct_workspace_minutes(workspace_id=workspace_id, minutes=required_minutes)
    
    # Generate a reservation ID (the bot can use this as a job ID if it wants)
    reservation_id = str(uuid.uuid4())
    
    return JobReserveResponse(
        reservation_id=reservation_id,
        workspace_id=workspace_id,
        minutes_reserved=required_minutes
    )


@router.post("/jobs/refund")
async def refund_job_minutes(req: JobRefundRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """Refund minutes if the job failed before or during submission to backend."""
    if user.email != "bot@internal.doblaj.com":
        raise HTTPException(status_code=403, detail="Only internal bot can call this endpoint.")

    if req.minutes_to_refund <= 0:
        raise HTTPException(status_code=400, detail="minutes_to_refund must be > 0")
    if req.minutes_to_refund > 30:
        raise HTTPException(status_code=400, detail="minutes_to_refund exceeds maximum single refund limit of 30 minutes.")

    workspace_id = await db.get_workspace_by_telegram_id(req.telegram_chat_id)
    if not workspace_id:
        raise HTTPException(status_code=404, detail="Telegram account not linked to any workspace.")
        
    # Refund minutes via Convex
    await convex_db.add_workspace_minutes(workspace_id=workspace_id, minutes=req.minutes_to_refund)
    return {"status": "ok", "refunded_minutes": req.minutes_to_refund, "workspace_id": workspace_id}


@router.get("/balance/{telegram_chat_id}")
async def get_telegram_user_balance(telegram_chat_id: str):
    """Retrieve remaining minutes balance for a Telegram user."""
    workspace_id = await db.get_workspace_by_telegram_id(telegram_chat_id)
    if not workspace_id:
        return {
            "is_linked": False,
            "remaining_minutes": 0,
            "workspace_id": None,
            "message": "Account not linked to a Doblaj workspace"
        }
        
    try:
        minutes = await convex_db.get_workspace_minutes(workspace_id=workspace_id)
        return {
            "is_linked": True,
            "remaining_minutes": int(minutes),
            "workspace_id": workspace_id
        }
    except Exception as e:
        logger.error(f"[TELEGRAM_BALANCE] Error getting minutes for {workspace_id}: {e}")
        return {
            "is_linked": True,
            "remaining_minutes": 0,
            "workspace_id": workspace_id,
            "error": str(e)
        }


class TelegramChatRequest(BaseModel):
    telegram_chat_id: str
    message: str

class TelegramChatResponse(BaseModel):
    reply: str
    is_linked: bool = False
    remaining_minutes: Optional[int] = None


async def _generate_agent_reply(user_message: str, is_linked: bool, remaining_minutes: int, workspace_id: Optional[str]) -> str:
    """Generate an intelligent trilingual response for the Telegram Doblaj AI agent."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPEN_ROUTER_API_KEY") or ""
    gemini_key = os.getenv("GEMINI_API_KEY") or ""

    system_prompt = (
        "You are the official Doblaj AI Assistant (دۆبلاژ ئەی ئای / مساعد دبلجة), a friendly and expert AI assistant for Doblaj Studio.\n\n"
        "USER CONTEXT:\n"
        f"- Account Linked: {'Yes (Workspace: ' + str(workspace_id) + ')' if is_linked else 'No (Guest / Unlinked)'}\n"
        f"- Remaining Video Dubbing Minutes: {remaining_minutes} minutes\n\n"
        "PLATFORM KNOWLEDGE:\n"
        "- Doblaj Studio (doblaj.com) is an AI video dubbing platform translating Kurdish Sorani (کوردی سۆرانی) videos into natural Spoken Iraqi Arabic (العامية العراقية) with AI voice cloning.\n"
        "- How to Dub a Video: Upload any video (MP4, MOV, MKV, WEBM, max 2000 MB) directly to this Telegram bot or on the web dashboard (doblaj.com/dubbing). The pipeline automatically separates vocals (Demucs), transcribes Kurdish audio, localizes to Iraqi Arabic, clones the speaker voice with Fish Audio, and delivers the final synced video.\n"
        "- Account Linking: To link Telegram, users click 'Connect Telegram' in Settings (doblaj.com/settings) or send /start <nonce>.\n"
        "- Pricing & Minutes: Users can top up their dubbing minutes at doblaj.com/pricing.\n\n"
        "COMMUNICATION RULES:\n"
        "1. Detect and reply in the EXACT language of the user: Kurdish Sorani (کوردی سۆرانی), Spoken Iraqi Arabic (العامية العراقية), or English.\n"
        "2. Keep responses concise, clear, and formatted nicely with emojis (perfect for Telegram reading).\n"
        "3. If the user asks about their balance or minutes, accurately report their remaining minutes.\n"
        "4. If unlinked and asking to dub, politely guide them to link their account from doblaj.com/settings.\n"
        "5. Be polite, helpful, and natural."
    )

    # 1. Try OpenRouter
    if openrouter_key:
        try:
            model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-pro")
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.5,
                    "max_tokens": 800
                }
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "HTTP-Referer": "https://doblaj.com",
                        "X-Title": "Doblaj Telegram Bot",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if content and content.strip():
                        return content.strip()
                else:
                    logger.warning(f"[AI_AGENT] OpenRouter returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"[AI_AGENT] OpenRouter error: {e}")

    # 2. Fallback to Gemini Direct API
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": system_prompt + "\n\nUser Question:\n" + user_message}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.5,
                        "maxOutputTokens": 800
                    }
                }
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
        except Exception as e:
            logger.warning(f"[AI_AGENT] Gemini fallback error: {e}")

    # 3. Static Smart Fallback if no LLM key is configured
    lower_msg = user_message.lower()
    if any(w in lower_msg for w in ["balance", "minutes", "credit", "خاڵ", "باڵانس", "دقائق", "دقيقة", "رصيد"]):
        if is_linked:
            return f"📊 **باڵانسی هەژمارەکەت / رصيد حسابك / Account Balance:**\n\n✨ Remaining Dubbing Minutes: **{remaining_minutes} دقيقة / خولەک**\n\n🔗 Manage plan & top up at: https://doblaj.com/pricing"
        else:
            return "⚠️ هەژمارەکەت هێشتا نەبەستراوەتەوە بە دۆبلاژ ستۆدیۆ.\nحسابك غير مربوط بعد بـ Doblaj Studio.\n\nتکایە لە بەشی ڕێکخستنەکان (Settings) لە https://doblaj.com/settings هەژماری تێلیگرامەکەت ببەستەرەوە."

    return (
        "👋 سڵاو! من یاریدەدەری زیرەکی دەستکردی دۆبلاژم (Doblaj AI Assistant).\n"
        "دەتوانیت ڤیدیۆ بنێریت بۆ ئەوەی دۆبلاژی بکەم لە کوردی سۆرانی بۆ عەرەبی عێراقی، یاخود هەر پرسیارێکت هەیە لێرە لێم بپرسە!\n\n"
        "مرحباً بك! أنا مساعد الذكاء الاصطناعي لمنصة دبلجة (Doblaj AI).\n"
        "يمكنك إرسال مقاطع الفيديو لدبلجتها فورياً من الكردية السورانية إلى العامية العراقية، أو طرح أي استفسار هنا!"
    )


@router.post("/chat", response_model=TelegramChatResponse)
async def handle_telegram_chat(req: TelegramChatRequest, user: AuthenticatedUser = Depends(require_user_or_internal)):
    """AI Agent endpoint for answering user text questions on Telegram."""
    workspace_id = await db.get_workspace_by_telegram_id(req.telegram_chat_id)
    is_linked = bool(workspace_id)
    remaining_minutes = 0

    if is_linked and workspace_id:
        try:
            remaining_minutes = int(await convex_db.get_workspace_minutes(workspace_id=workspace_id))
        except Exception as e:
            logger.warning(f"[TELEGRAM_CHAT] Could not fetch minutes for {workspace_id}: {e}")

    reply = await _generate_agent_reply(
        user_message=req.message,
        is_linked=is_linked,
        remaining_minutes=remaining_minutes,
        workspace_id=workspace_id
    )

    return TelegramChatResponse(
        reply=reply,
        is_linked=is_linked,
        remaining_minutes=remaining_minutes
    )


@router.get("/status")
async def get_telegram_status():
    """Diagnostic endpoint to inspect Telegram bot runtime configuration."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openrouter_model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free").strip()
    
    bot_info = None
    bot_error = None
    if token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                if resp.status_code == 200:
                    bot_info = resp.json().get("result")
                else:
                    bot_error = f"Telegram API error {resp.status_code}: {resp.text}"
        except Exception as e:
            bot_error = str(e)
            
    return {
        "status": "ready" if (token and not bot_error) else "needs_config",
        "token_configured": bool(token),
        "token_prefix": token[:6] + "..." if token else None,
        "bot_info": bot_info,
        "bot_error": bot_error,
        "openrouter_configured": bool(openrouter_key),
        "openrouter_model": openrouter_model,
        "admin_ids": [x.strip() for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()]
    }

