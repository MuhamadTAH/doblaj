import os
import sys
import time
import uuid
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

from app.mcp.pipeline_engine import DubbingPipelineEngine
from app.mcp.storage import ScratchManager
from app.core import database_convex
from app.services import r2

logger = logging.getLogger("doblaj.telegram.bot")

# Track active jobs to prevent duplicate processing
_active_tg_jobs = set()


async def handle_video_dubbing(message: Message, bot: Bot):
    """Processes a video sent by a user on Telegram through the complete Doblaj pipeline."""
    chat_id = message.chat.id
    user_name = message.from_user.first_name if message.from_user else "User"
    
    # 1. Identify video object (video, animation, or video document)
    video_obj = message.video or message.animation or message.document
    if not video_obj:
        await message.reply("⚠️ تکایە فایلێکی ڤیدیۆ بنێرە. / Please send a valid video file.")
        return

    # Check file size (Telegram standard bot limit is 20MB for downloads)
    file_size_mb = (video_obj.file_size or 0) / (1024 * 1024)
    if file_size_mb > 50.0:
        await message.reply("⚠️ قەبارەی ڤیدیۆکە زۆر گەورەیە (زیاترە لە 50 مێگابایت). تکایە ڤیدیۆیەکی کورتتر بنێرە.")
        return

    job_id = str(uuid.uuid4())
    _active_tg_jobs.add(job_id)

    status_msg = await message.reply(
        "🎬 **ڤیدیۆکە وەرگیرا! / تم استلام الفيديو!**\n"
        "⏳ خەریکی داگرتن و ئامادەکردنی پرۆسەی دۆبلاژین...\n"
        f"🆔 `Job: {job_id[:8]}`",
        parse_mode=ParseMode.MARKDOWN
    )

    scratch_dir = ScratchManager.get_job_dir(job_id)
    local_source_path = str(scratch_dir / "source_video.mp4")

    try:
        # Step 1: Download from Telegram
        file_info = await bot.get_file(video_obj.file_id)
        if not file_info.file_path:
            raise RuntimeError("Telegram did not return a valid file_path.")

        await bot.download_file(file_info.file_path, destination=local_source_path)

        if not os.path.exists(local_source_path) or os.path.getsize(local_source_path) == 0:
            raise FileNotFoundError("Failed to save downloaded Telegram video to disk.")

        logger.info(f"[TG-BOT] Video downloaded successfully ({os.path.getsize(local_source_path)} bytes) for chat {chat_id}")

        # Step 2: Upload raw video to R2 for archive & register in Convex
        r2_input_key = f"dubbing/telegram_uploads/{job_id}.mp4"
        try:
            await asyncio.to_thread(r2.upload_file, r2_input_key, local_source_path)
        except Exception as e:
            logger.warning(f"[TG-BOT] R2 upload notice: {e}")

        # Step 3: STAGE 1 - GPU Stem Separation & VAD Chunking
        try:
            await status_msg.edit_text(
                "⏳ **قۆناغی ١/٤: جیاکردنەوەی دەنگ لە مۆسیقا (Demucs)... (25%)**\n"
                "🎙️ جیاکردنەوەی دەنگی قسەکەر لە ژاوەژاو و پارچەکردنی بەپێی وەستانەکان...",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        sep_res = await DubbingPipelineEngine.separate_and_chunk(job_id, local_source_path)
        chunks_count = sep_res["chunks_count"]
        logger.info(f"[TG-BOT] Chunks created: {chunks_count}")

        # Step 4: STAGE 2 - Kurdish Transcription (Gemini 3.1 Pro Dual-Pass)
        try:
            await status_msg.edit_text(
                f"⏳ **قۆناغی ٢/٤: دەرهێنانی دەقی کوردی سۆرانی... (45%)**\n"
                f"📝 دەرهێنانی دەق بۆ {chunks_count} بەش بە کوردیی سۆرانیی ڕەسەن...",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        await DubbingPipelineEngine.transcribe_kurdish(job_id)

        # Step 5: STAGE 3 - Kurdish -> Spoken Iraqi Arabic Translation
        try:
            await status_msg.edit_text(
                f"⏳ **قۆناغی ٣/٤: وەرگێڕان بۆ عەرەبی عێراقی... (65%)**\n"
                f"🇮🇶 وەرگێڕانی {chunks_count} بەش بە شێوەزاری عێراقی و بەپێی کاتی وتار...",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        await DubbingPipelineEngine.translate_and_calibrate(job_id)

        # Step 6: STAGE 4 - Neural Voice Cloning & Mastering
        try:
            await status_msg.edit_text(
                f"⏳ **قۆناغی ٤/٤: دروستکردنەوەی دەنگ و ماستەرینگ... (85%)**\n"
                f"🔊 کۆپیکردنی دەنگی قسەکەر بە تەکنەلۆژیای Fish Audio و تێکەڵکردنی مۆسیقا...",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        master_res = await DubbingPipelineEngine.synthesize_and_master(job_id, local_source_path)
        final_mp4_path = master_res["final_video_path"]

        # Step 7: Delivery - Send the dubbed video back to Telegram
        try:
            await status_msg.edit_text("✅ **دۆبلاژ بە سەرکەوتوویی تەواو بوو! ناردنی ڤیدیۆ... (100%)**", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

        video_input = FSInputFile(final_mp4_path)
        await message.answer_video(
            video=video_input,
            caption=(
                "✨ **ڤیدیۆی دۆبلاژکراو ئامادەیە! / تم الدبلجة بنجاح!**\n\n"
                "🗣️ **زمان:** کوردی سۆرانی ➔ العامية العراقية\n"
                "🎙️ **دەنگ:** بە هەمان تۆنی دەنگی قسەکەر لەگەڵ پاراستنی مۆسیقای باکگراوند.\n\n"
                "🚀 *بەرهەمهێنراوە لەلایەن Doblaj Studio (doblaj.com)*"
            ),
            parse_mode=ParseMode.MARKDOWN
        )

        logger.info(f"[TG-BOT] Successfully delivered dubbed video to chat {chat_id}")

        # Cleanup scratch
        ScratchManager.cleanup_job(job_id)

    except Exception as e:
        logger.exception(f"[TG-BOT] Error processing Telegram job {job_id}: {e}")
        try:
            await status_msg.edit_text(
                f"⚠️ **داوای لێبوردن دەکەین، هەڵەیەک ڕوویدا لە کاتی پرۆسێسکردندا:**\n`{str(e)[:200]}`\n\nتکایە دووبارە هەوڵ بدەرەوە.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        ScratchManager.cleanup_job(job_id)
    finally:
        _active_tg_jobs.discard(job_id)


def setup_telegram_dispatcher() -> Dispatcher:
    """Sets up the aiogram router and message handlers."""
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        welcome_text = (
            "👋 **بەخێربێن بۆ بۆتی فەرمی دۆبلاژ ستۆدیۆ (Doblaj Studio)!**\n\n"
            "🎬 **چۆنێتی کارکردن:**\n"
            "١. هەر ڤیدیۆیەکی کوردیی سۆرانی بۆ بۆتەکە بنێرە.\n"
            "٢. سیستەم بە شێوەیەکی ئۆتۆماتیکی دەنگەکان لە مۆسیقا جیا دەکاتەوە.\n"
            "٣. دەقەکە وەردەگێڕێت بۆ **عەرەبیی عێراقی (العامية العراقية)**.\n"
            "٤. بە **هەمان تۆنی دەنگی قسەکەرەکە** ڤیدیۆکە دۆبلاژ دەکاتەوە و بۆت دەنێرێتەوە!\n\n"
            "👇 **ئێستا ڤیدیۆیەک بنێرە بۆ دەستپێکردن!**"
        )
        await message.reply(welcome_text, parse_mode=ParseMode.MARKDOWN)

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await message.reply(
            "ℹ️ **یارمەتی / Help:**\n\n"
            "تەنها ڤیدیۆیەکی کوردی ڕەوانەی ئەم چاتە بکە، سیستەمەکە ڕاستەوخۆ دەست دەکات بە دۆبلاژکردنی بۆ عەرەبی عێراقی.",
            parse_mode=ParseMode.MARKDOWN
        )

    @dp.message(F.video | F.animation | (F.document & F.document.mime_type.startswith("video/")))
    async def on_video_received(message: Message, bot: Bot):
        asyncio.create_task(handle_video_dubbing(message, bot))

    @dp.message(F.text)
    async def on_text_received(message: Message):
        await message.reply(
            "🎬 تکایە **فایلێکی ڤیدیۆ** بنێرە تاکو بە دەنگی خۆت دۆبلاژی بکەین بۆ عەرەبی عێراقی!\n\n"
            "Send any Kurdish video to dub it to Iraqi Arabic with original voice cloning.",
            parse_mode=ParseMode.MARKDOWN
        )

    return dp


async def start_telegram_bot(bot_token: str):
    """Starts the Telegram bot polling loop in the background."""
    if not bot_token:
        logger.warning("[TG-BOT] No TELEGRAM_BOT_TOKEN provided. Telegram bot disabled.")
        return

    logger.info(f"[TG-BOT] Initializing Telegram bot with token {bot_token[:10]}...")
    bot = Bot(token=bot_token)
    dp = setup_telegram_dispatcher()

    try:
        # Delete any old webhook to allow clean long-polling
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.get_me()
        logger.info(f"✨ [TG-BOT] Telegram Bot @{me.username} ({me.first_name}) is LIVE and polling!")
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"[TG-BOT] Telegram bot crashed: {e}")
