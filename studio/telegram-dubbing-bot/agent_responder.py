#!/usr/bin/env python3
"""
Doblaj Telegram Chat AI Agent Responder
========================================
Autonomous agent worker that monitors `chat_queue/inbox` for user messages from Telegram,
generates high-quality trilingual answers (Kurdish Sorani, Iraqi Arabic, English),
and writes the responses to `chat_queue/outbox` for instant delivery to Telegram.
"""

import os
import sys
import json
import time
import glob
import logging
import asyncio
from pathlib import Path
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CHAT_AGENT]: %(message)s"
)
logger = logging.getLogger("chat_agent")

QUEUE_DIR = Path(__file__).resolve().parent / "chat_queue"
INBOX_DIR = QUEUE_DIR / "inbox"
OUTBOX_DIR = QUEUE_DIR / "outbox"

INBOX_DIR.mkdir(parents=True, exist_ok=True)
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = (
    "You are the official Doblaj AI Assistant (مساعد دۆبلاژ / دبلجة), an expert AI assistant for Doblaj Studio (doblaj.com).\n\n"
    "ABOUT DOBLAJ STUDIO:\n"
    "- Doblaj Studio is an AI-powered platform that automatically dubs and translates Kurdish Sorani (کوردی سۆرانی) videos into natural Spoken Iraqi Arabic (العامية العراقية) with AI voice cloning.\n"
    "- Pipeline Steps: 1. Video Upload (up to 2GB) -> 2. Vocal Separation (Demucs) -> 3. Kurdish Speech-to-Text -> 4. Localization to Spoken Iraqi Arabic -> 5. Neural Voice Cloning (Fish Audio) -> 6. Video Muxing & Lip-sync.\n"
    "- Supported video formats: MP4, MOV, MKV, WEBM, AVI (max 2000 MB).\n"
    "- Account Linking: Users click 'Connect Telegram' at https://doblaj.com/settings to link their account.\n"
    "- Pricing Plans: Starter (5 min for $10 / 15,000 IQD), Pro (15 min for $20 / 30,000 IQD), Creator (120 min for $99 / 148,500 IQD), Test (1 min for 1,000 IQD) at https://doblaj.com/pricing.\n\n"
    "RESPONSE RULES:\n"
    "1. Always detect and reply in the EXACT language of the user: Kurdish Sorani (کوردی سۆرانی), Spoken Iraqi Arabic (العامية العراقية), or English.\n"
    "2. Be concise, friendly, helpful, and natural (perfect for Telegram reading with clear formatting & emojis).\n"
    "3. Answer any general question, greeting, or platform question accurately.\n"
)


async def generate_response(user_text: str, chat_id: int) -> str:
    """Generate intelligent response using available API or smart dynamic heuristics."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPEN_ROUTER_API_KEY") or ""
    gemini_key = os.getenv("GEMINI_API_KEY") or ""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or ""

    # 1. OpenRouter
    if openrouter_key:
        try:
            model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-pro")
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key.strip()}",
                        "HTTP-Referer": "https://doblaj.com",
                        "X-Title": "Doblaj Telegram Agent",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_text}
                        ],
                        "temperature": 0.4,
                        "max_tokens": 700
                    }
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    if content and content.strip():
                        return content.strip()
        except Exception as e:
            logger.warning(f"OpenRouter call failed: {e}")

    # 2. Direct Gemini
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key.strip()}"
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "contents": [
                            {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\nUser Question:\n" + user_text}]}
                        ],
                        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 700}
                    }
                )
                if resp.status_code == 200:
                    parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
        except Exception as e:
            logger.warning(f"Gemini call failed: {e}")

    # 3. Direct Anthropic
    if anthropic_key:
        try:
            url = "https://api.anthropic.com/v1/messages"
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "x-api-key": anthropic_key.strip(),
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-3-5-haiku-20241022",
                        "max_tokens": 600,
                        "system": SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_text}]
                    }
                )
                if resp.status_code == 200:
                    content = resp.json().get("content", [])
                    if content:
                        return content[0].get("text", "").strip()
        except Exception as e:
            logger.warning(f"Anthropic call failed: {e}")

    # 4. Intelligent Dynamic Heuristics Fallback
    lower = user_text.lower().strip()
    
    # Greetings
    if any(w in lower for w in ["سڵاو", "سلاو", "چۆنی", "باشی", "چۆنیت"]):
        return (
            "☀️ **سڵاو! بەخێربێیت بۆ دۆبلاژ ئەی ئای (Doblaj AI)** 🎙️\n\n"
            "من لێرەم بۆ ئەوەی یارمەتیت بدەم لە دۆبلاژکردنی ڤیدیۆکانت لە **کوردی سۆرانی بۆ عەرەبی عێراقی** بە دەنگی زیرەکی دەستکرد.\n\n"
            "💡 دەتوانیت هەر ئێستا ڤیدیۆیەک بباربکەیت، یان پرسیارێکم لێ بکەیت!"
        )
    
    if any(w in lower for w in ["مرحبا", "هلا", "شلونك", "سلام عليكم", "شلونكم"]):
        return (
            "🇮🇶 **أهلاً وسهلاً بك في بوت دبلجة (Doblaj AI)!** 🎙️\n\n"
            "أنا المساعد الذكي لمساعدتك في ترجمة ودبلجة الفيديوهات من **الكردية السورانية إلى العامية العراقية** مع استنساخ نبرة الصوت.\n\n"
            "💡 أرسل مقطع الفيديو هنا للبدء مباشرة، أو اسألني أي سؤال!"
        )

    if any(w in lower for w in ["hello", "hi", "hey", "how are you"]):
        return (
            "👋 **Hello! Welcome to Doblaj AI Assistant!** 🎙️\n\n"
            "I'm here to help you dub and translate videos from **Kurdish Sorani to natural Iraqi Arabic** with AI voice cloning.\n\n"
            "💡 Send me any video (up to 2GB) to start dubbing, or ask me anything!"
        )

    # How to dub
    if any(w in lower for w in ["how", "start", "dub", "دۆبلاژ", "چۆن", "شلون", "كيف", "طريقة"]):
        return (
            "🎬 **ڕێنمایی دۆبلاژکردنی ڤیدیۆ / طريقة دبلجة الفيديو:**\n\n"
            "1️⃣ **ڤیدیۆکەت بنێرە:** هەر مقطعە ڤیدیۆیەک (MP4, MOV, MKV تاکو 2000MB) لێرە بنێرە.\n"
            "2️⃣ **سیستەم دەستپێدەکات:** جیاکردنەوەی دەنگ، وەرگێڕان بۆ عەرەبی عێراقی، و کۆپیکردنی دەنگ بە شێوازی سروشتی.\n"
            "3️⃣ **وەرگرتنەوە:** لە ماوەیەکی کەمدا ڤیدیۆ دۆبلاژکراوەکەت بۆ دەگەڕێتەوە ئامادەکراو!\n\n"
            "🔗 دەتوانیت هەژمارەکەت ببەستیتەوە لە https://doblaj.com/settings"
        )

    # Balance / Pricing
    if any(w in lower for w in ["balance", "price", "plan", "credits", "نرخ", "باڵانس", "اسعار", "رصيد"]):
        return (
            "💳 **پاکێجەکانی دۆبلاژ / باقات دبلجة:**\n\n"
            "• ⚡ **Starter:** 5 خولەک / دقائق ($10 / 15,000 IQD)\n"
            "• 🚀 **Pro:** 15 خولەک / دقائق ($20 / 30,000 IQD)\n"
            "• 👑 **Creator:** 120 خولەک / دقائق ($99 / 148,500 IQD)\n"
            "• 🧪 **Test:** 1 خولەک (1,000 IQD)\n\n"
            "👉 بەستەری پارەدان لە ڕێگەی Wayl بەردەستە لە https://doblaj.com/pricing یان بنووسە /plans"
        )

    # Default Answer
    return (
        f"🤖 **Doblaj AI Assistant:**\n\n"
        f"وەڵام بۆ پرسیارەکەت:\n\n"
        f"ئەگەر دەتەوێت ڤیدیۆیەک دۆبلاژ بکەیت لە **کوردی بۆ عەرەبی عێراقی**، تەنها ڤیدیۆکە وەک فایل بنێرە بۆ ئێرە.\n"
        f"بۆ هەر زانیارییەکی تر یان بینینی باڵانس، دەتوانیت سەردانی https://doblaj.com بکەیت."
    )


async def process_inbox():
    """Poll inbox directory for pending user requests and generate answers."""
    req_files = glob.glob(str(INBOX_DIR / "REQ_*.json"))
    for rf in req_files:
        p = Path(rf)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            req_id = data.get("req_id")
            chat_id = data.get("chat_id", 0)
            user_text = data.get("text", "")
            
            logger.info(f"Processing message {req_id} from chat {chat_id}: '{user_text}'")
            reply = await generate_response(user_text, chat_id)
            
            out_file = OUTBOX_DIR / f"RESP_{req_id}.json"
            out_file.write_text(json.dumps({"req_id": req_id, "reply": reply}, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Wrote reply for {req_id}")
            
            p.unlink(missing_ok=True)
        except Exception as e:
            logger.exception(f"Error processing {p.name}: {e}")
            p.unlink(missing_ok=True)


async def main():
    logger.info("=" * 60)
    logger.info("  DOBLAJ TELEGRAM CHAT AI AGENT WORKER ACTIVE")
    logger.info("=" * 60)
    logger.info(f"Monitoring inbox: {INBOX_DIR}")
    
    while True:
        try:
            await process_inbox()
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Agent stopped.")
