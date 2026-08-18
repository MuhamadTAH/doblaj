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
import re
import logging
import asyncio
from pathlib import Path
import httpx
from dotenv import load_dotenv

# Auto-load envs from bot and dubbing studio
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / "dubbing" / ".env")
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

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

DUBBING_BACKEND_URL = os.getenv("DUBBING_BACKEND_URL", "https://api.doblaj.com").rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "pird_internal_dubbing_key_2026")


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


async def query_balance(chat_id: int) -> dict:
    """Query live user balance from the backend."""
    if not chat_id:
        return {"is_linked": False, "remaining_minutes": 0}
    
    urls = [
        f"{DUBBING_BACKEND_URL}/api/telegram/balance/{chat_id}",
        f"https://api.doblaj.com/api/telegram/balance/{chat_id}",
        f"http://127.0.0.1:8002/api/telegram/balance/{chat_id}"
    ]
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            continue
    return {"is_linked": False, "remaining_minutes": 0}


def detect_language(text: str) -> str:
    """Detect whether user text is Kurdish Sorani, Arabic, or English."""
    kurdish_chars = set("ۆێڵڕڤپچژگ")
    if any(c in text for c in kurdish_chars):
        return "kurdish"
    
    kurdish_words = [
        "سڵاو", "سلاو", "چۆنی", "باشی", "دەنگ", "خولەک", "پارە", "چۆن",
        "کورد", "کوردی", "سۆرانی", "سوپاس", "دەتوانیت", "بکەم", "دەستپێکردن",
        "باڵانس", "نرخ", "بکە", "فایلی", "ڤیدیۆ"
    ]
    if any(re.search(r'\b' + re.escape(w) + r'\b', text, re.IGNORECASE) for w in kurdish_words):
        return "kurdish"
    
    arabic_chars = set("أإآءئؤةىصضطظثذخغعفق")
    arabic_words = [
        "شلونك", "شلون", "هلا", "مرحبا", "دبلجة", "عراقي", "رصيد", "دقائق", "دقيقة",
        "فيديو", "اريد", "شكد", "فلوس", "باقات", "حساب", "تسجيل", "شكرا", "سلام"
    ]
    if any(c in text for c in arabic_chars) or any(w in text for w in arabic_words):
        return "arabic"
    
    return "english"


async def generate_response(user_text: str, chat_id: int) -> str:
    """Generate intelligent response using available LLM API or smart dynamic heuristics."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPEN_ROUTER_API_KEY") or ""
    gemini_key = os.getenv("GEMINI_API_KEY") or ""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or ""

    # Filter placeholder keys
    if "REPLACE" in openrouter_key or len(openrouter_key) < 15:
        openrouter_key = ""
    if "REPLACE" in gemini_key or len(gemini_key) < 15:
        gemini_key = ""
    if "REPLACE" in anthropic_key or len(anthropic_key) < 15:
        anthropic_key = ""

    # 1. OpenRouter
    if openrouter_key:
        try:
            model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-pro")
            async with httpx.AsyncClient(timeout=20.0) as client:
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
            async with httpx.AsyncClient(timeout=20.0) as client:
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
            async with httpx.AsyncClient(timeout=20.0) as client:
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

    # 4. Intelligent Trilingual Dynamic Heuristics Engine
    lower = user_text.lower().strip()
    lang = detect_language(lower)

    # --- 1. Thanks / Gratitude ---
    if any(w in lower for w in ["سوپاس", "دەستت خۆش", "دەست خۆش", "ممنون", "سەركەوتوو"]):
        return "🌸 **شایەنی نییە!** هەمیشە لە خزمەتتاندام بۆ هەر هاوکاری و دۆبلاژێک. سەرکەوتوو بیت! 🎙️"

    if any(w in lower for w in ["شكرا", "عاشت ايدك", "تسلم", "مشكور", "يسلمو", "الله يبارك"]):
        return "🌸 **تدلل، بخدمتك بأي وقت!** أرسل الفيديو بأي لحظة حتى ندبلجه إلك بأعلى جودة. 🎙️"

    if any(w in lower for w in ["thanks", "thank you", "thx", "appreciate"]):
        return "🌟 **You're very welcome!** Feel free to upload any video whenever you're ready to dub. 🎙️"

    # --- 2. Greetings & Salutations ---
    if any(re.search(r'\b' + re.escape(w) + r'\b', lower) for w in ["سڵاو", "سلاو", "چۆنی", "باشی", "چۆنیت", "هەواڵ", "سڵاوو"]):
        return (
            "☀️ **سڵاو! بەخێربێیت بۆ دۆبلاژ ئەی ئای (Doblaj AI)** 🎙️\n\n"
            "من یاریدەدەری زیرەکی دۆبلاژم، لێرەم بۆ ئەوەی یارمەتیت بدەم لە دۆبلاژکردنی ڤیدیۆکانت لە **کوردی سۆرانی بۆ عەرەبی عێراقی** بە دەنگی زیرەکی دەستکرد.\n\n"
            "💡 دەتوانیت هەر ئێستا ڤیدیۆیەک بنێریت، یان پرسیار لەبارەی باڵانس و پاکێجەکان بکەیت!"
        )

    if any(re.search(r'\b' + re.escape(w) + r'\b', lower) for w in ["مرحبا", "هلا", "شلونك", "شلونكم", "سلام عليكم", "السلام عليكم", "مساء الخير", "صباح الخير", "أهلاً", "اهلا"]):
        return (
            "🇮🇶 **أهلاً وسهلاً بك في بوت دبلجة (Doblaj AI)!** 🎙️\n\n"
            "أنا المساعد الذكي لدبلجة وترجمة الفيديوهات من **الكردية السورانية إلى العامية العراقية** مع استنساخ نبرة الصوت بدقة.\n\n"
            "💡 أرسل الفيديو الخاص بك هنا للبدء مباشرة، أو اسألني عن الرصيد والباقات!"
        )

    if any(re.search(r'\b' + re.escape(w) + r'\b', lower) for w in ["hello", "hi", "hey", "how are you", "good morning", "good evening"]):
        return (
            "👋 **Hello! Welcome to Doblaj AI Assistant!** 🎙️\n\n"
            "I'm here to assist you with dubbing Kurdish Sorani videos into natural **Spoken Iraqi Arabic** with AI voice cloning.\n\n"
            "💡 Send me any video (up to 2GB) to start dubbing, or ask me about your balance & pricing plans!"
        )

    # --- 3. Pricing, Plans & Purchasing Inquiries ---
    pricing_keywords = ["price", "pricing", "plan", "plans", "cost", "buy", "pay", "rates", "package", "packages", "نرخ", "پاکێج", "کڕین", "پارە", "کڕینی", "اسعار", "سعر", "باقات", "باقة", "اشتراك", "شراء", "دفع", "شكد السعر", "شكد سعر"]
    if any(k in lower for k in pricing_keywords):
        if lang == "kurdish":
            return (
                "💳 **پاکێجەکانی دۆبلاژ (Doblaj Studio Plans):**\n\n"
                "• ⚡ **Starter:** 5 خولەک ($10 / 15,000 IQD)\n"
                "• 🚀 **Pro:** 15 خولەک ($20 / 30,000 IQD)\n"
                "• 👑 **Creator:** 120 خولەک ($99 / 148,500 IQD)\n"
                "• 🧪 **Test:** 1 خولەک (1,000 IQD)\n\n"
                "💳 **شێوازی پارەدان:** لە ڕێگەی دەروازەی پارەدانی Wayl (FIB، کارتی کی، ماستەرکارت، ڤیزا).\n\n"
                "🔗 بۆ کڕینی ڕاستەوخۆ: https://doblaj.com/pricing یان فەرمانی /plans بنووسە."
            )
        elif lang == "arabic":
            return (
                "💳 **باقات وأسعار دبلجة (Doblaj Studio):**\n\n"
                "• ⚡ **باقة البداية (Starter):** 5 دقائق ($10 / 15,000 دينار)\n"
                "• 🚀 **باقة المحترفين (Pro):** 15 دقيقة ($20 / 30,000 دينار)\n"
                "• 👑 **باقة صناع المحتوى (Creator):** 120 دقيقة ($99 / 148,500 دينار)\n"
                "• 🧪 **باقة التجربة (Test):** 1 دقيقة (1,000 دينار)\n\n"
                "💳 **طرق الدفع:** بوابة Wayl العراقية (FIB، كي كارد، ماستركارد، فيزا).\n\n"
                "🔗 للشراء المباشر زور: https://doblaj.com/pricing أو اكتب /plans"
            )
        else:
            return (
                "💳 **Doblaj Studio Dubbing Plans:**\n\n"
                "• ⚡ **Starter:** 5 minutes ($10 / 15,000 IQD)\n"
                "• 🚀 **Pro:** 15 minutes ($20 / 30,000 IQD)\n"
                "• 👑 **Creator:** 120 minutes ($99 / 148,500 IQD)\n"
                "• 🧪 **Test:** 1 minute (1,000 IQD)\n\n"
                "💳 **Payment Gateway:** Wayl (supports FIB, Qi Card, Visa, Mastercard).\n\n"
                "🔗 Purchase directly at https://doblaj.com/pricing or type /plans."
            )

    # --- 4. Balance Inquiries ---
    balance_keywords = ["balance", "باڵانس", "رصيد", "رصيدي", "كم دقيقة", "كم دقيقه", "چەند خولەک", "چەند خولەکم", "خولەکی بەردەست", "خولەکم"]
    if any(k in lower for k in balance_keywords):
        bal_data = await query_balance(chat_id)
        is_linked = bal_data.get("is_linked", False)
        minutes = bal_data.get("remaining_minutes", 0)

        if lang == "kurdish":
            if is_linked:
                return (
                    f"📊 **باڵانسی هەژمارەکەت:**\n\n"
                    f"✨ خولەکی بەردەست: **{minutes} خولەک**\n\n"
                    f"💡 دەتوانیت هەر ئێستا ڤیدیۆیەک بنێریت بۆ دۆبلاژکردن، یان بۆ کڕینی خولەکی زیاتر سەردانی https://doblaj.com/pricing بکەیت."
                )
            else:
                return (
                    "⚠️ **هەژمارەکەت هێشتا نەبەستراوەتەوە بە وێبسایت.**\n\n"
                    "بۆ بەستنەوەی باڵانسەکەت:\n"
                    "1️⃣ بڕۆ بۆ https://doblaj.com/settings\n"
                    "2️⃣ کرتە لەسەر **'Connect Telegram'** بکە.\n\n"
                    "یان دەتوانیت پاکێجێک بکڕیت لە ڕێگەی فەرمانی /plans."
                )
        elif lang == "arabic":
            if is_linked:
                return (
                    f"📊 **رصيد حسابك الحالي:**\n\n"
                    f"✨ الدقائق المتبقية: **{minutes} دقيقة**\n\n"
                    f"💡 تكدر ترسل أي مقطع فيديو للدبلجة مباشرة، أو لشراء دقائق إضافية زور: https://doblaj.com/pricing"
                )
            else:
                return (
                    "⚠️ **حسابك غير مربوط بموقع دۆبلاژ بعد.**\n\n"
                    "لربط حسابك وتفعيل الرصيد:\n"
                    "1️⃣ افتح الرابط: https://doblaj.com/settings\n"
                    "2️⃣ اضغط على زر **'Connect Telegram'**.\n\n"
                    "أو تكدر تشوف الباقات وتشتري مباشرة عبر الأمر /plans."
                )
        else:
            if is_linked:
                return (
                    f"📊 **Your Account Balance:**\n\n"
                    f"✨ Remaining Minutes: **{minutes} min**\n\n"
                    f"💡 Send any Kurdish video to start dubbing, or top up at https://doblaj.com/pricing."
                )
            else:
                return (
                    "⚠️ **Your Telegram account is not yet linked to Doblaj Studio.**\n\n"
                    "To link your account:\n"
                    "1️⃣ Go to https://doblaj.com/settings\n"
                    "2️⃣ Click **'Connect Telegram'**.\n\n"
                    "Or explore plans by typing /plans."
                )

    # --- 5. How it works / Dubbing instructions & Supported formats ---
    dub_keywords = ["how", "start", "dub", "dubbing", "work", "format", "formats", "size", "video", "دۆبلاژ", "فۆرمات", "شلون", "كيف", "طريقة", "شرح", "صيغ", "خطوات", "فيديو", "ڤیدیۆ"]
    if any(k in lower for k in dub_keywords):
        if lang == "kurdish":
            return (
                "🎬 **دۆبلاژکردنی ڤیدیۆ بە 3 هەنگاوی سادە:**\n\n"
                "1️⃣ **ڤیدیۆکەت بنێرە:** هەر ڤیدیۆیەکی کوردی سۆرانی (MP4, MOV, MKV, WEBM تاکو قەبارەی 2GB) وەک فایل لە تێلیگرام لێرە بنێرە.\n"
                "2️⃣ **سیستەمی زیرەک:** دەنگ جیا دەکرێتەوە، دەق وەردەگێڕدرێتە سەر عەرەبی عێراقی، و هەمان دەنگی قسەکەر کۆپی دەکرێتەوە.\n"
                "3️⃣ **وەرگرتنەوە:** لە چەند خولەکێکدا ڤیدیۆیەکی تەواو ئامادە و سینکرۆنکراو وەردەگریتەوە!\n\n"
                "🔗 بۆ بەستنەوەی هەژمار و بینینی ڕێکخستنەکان: https://doblaj.com/settings"
            )
        elif lang == "arabic":
            return (
                "🎬 **كيفية دبلجة الفيديو بثلاث خطوات بسيطة:**\n\n"
                "1️⃣ **أرسل الفيديو:** أرسل أي مقطع فيديو باللغة الكردية السورانية (MP4, MOV, MKV, WEBM بحجم يصل إلى 2GB) مباشرة للبوت.\n"
                "2️⃣ **المعالجة الذكية:** يقوم الذكاء الاصطناعي بعزل الصوت، ترجمة الحوار للعامية العراقية، واستنساخ نبرة الصوت الأصلية مع مزامنة الشفاه.\n"
                "3️⃣ **استلام الفيديو:** تستلم الفيديو المدبلج بجودة عالية وجاهز للنشر خلال دقائق!\n\n"
                "🔗 لربط حسابك والإعدادات: https://doblaj.com/settings"
            )
        else:
            return (
                "🎬 **How to Dub Videos with Doblaj AI:**\n\n"
                "1️⃣ **Send your Video:** Send any Kurdish Sorani video (MP4, MOV, MKV, WEBM up to 2GB) directly into this chat.\n"
                "2️⃣ **AI Processing:** Our pipeline isolates vocals, translates speech to natural Iraqi Arabic, clones the speaker's voice, and synchronizes audio.\n"
                "3️⃣ **Get Dubbed Video:** Receive your fully dubbed video within minutes ready to share!\n\n"
                "🔗 Link your account & manage settings at https://doblaj.com/settings"
            )

    # --- 6. General Fallback ---
    if lang == "kurdish":
        return (
            "🤖 **یاریدەدەری دۆبلاژ (Doblaj AI):**\n\n"
            "ئەگەر دەتەوێت ڤیدیۆیەک دۆبلاژ بکەیت لە **کوردی سۆرانی بۆ عەرەبی عێراقی**، تەنها ڤیدیۆکە وەک فایل بنێرە بۆ ئێرە.\n\n"
            "📌 **فەرمانە بەردەستەکان:**\n"
            "• /balance - بینینی باڵانسی بەردەست\n"
            "• /plans - پاکێجەکانی کڕینی خولەک\n"
            "• https://doblaj.com - ماڵپەڕی سەرەکی"
        )
    elif lang == "arabic":
        return (
            "🤖 **مساعد دبلجة الذكي (Doblaj AI):**\n\n"
            "لدبلجة أي فيديو من **الكردية السورانية إلى العامية العراقية**، أرسل ملف الفيديو هنا مباشرة وسيتولى البوت المعالجة فوراً.\n\n"
            "📌 **الأوامر السريعة:**\n"
            "• /balance - فحص رصيد الدقائق\n"
            "• /plans - باقات الشراء والدفع\n"
            "• https://doblaj.com - الموقع الرسمي"
        )
    else:
        return (
            "🤖 **Doblaj AI Assistant:**\n\n"
            "To dub any video from **Kurdish Sorani to natural Iraqi Arabic**, simply send your video file into this chat.\n\n"
            "📌 **Quick Commands:**\n"
            "• /balance - Check remaining minutes\n"
            "• /plans - View pricing and top-up\n"
            "• https://doblaj.com - Official Website"
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

