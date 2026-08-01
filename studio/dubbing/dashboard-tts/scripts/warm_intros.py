"""Warm-cache TTS voice intros: render 12 brand-intro MP3s off-platform and
upload them to Convex storage via the dev-only `voices:uploadIntro` mutation.

Run from D:\\pird with:
    $env:PYTHONPATH = "D:\\pird\\studio\\dubbing"
    python D:\\pird\\studio\\dubbing\\dashboard-tts\\scripts\\warm_intros.py

The Fish Audio key stays on the dev box — never reaches the dashboard-tts
deploy. The `uploadIntro` mutation is a one-shot backdoor to be removed
after this script runs successfully.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import sys
import traceback

from convex import ConvexClient

from app.services.tts.fish_audio import render_tts


BRAND_TEXT = (
    "\u0635\u0648\u062a \u0639\u0644\u0627\u0645\u062a\u0643 \u0627\u0644\u062a\u062c\u0627\u0631\u064a\u0629 "
    "\u0647\u0648 \u0647\u0648\u064a\u062a\u0643. \u0646\u062d\u0646 \u0646\u0636\u0645\u0646 \u0644\u0643 "
    "\u062f\u0628\u0644\u062c\u0629 \u0627\u062d\u062a\u0631\u0627\u0641\u064a\u0629\u060c \u0633\u0644\u0633\u0629\u060c "
    "\u0648\u0637\u0628\u064a\u0639\u064a\u0629\u060c \u0644\u0646\u0648\u0635\u0644 \u0631\u0633\u0627\u0644\u062a\u0643 "
    "\u0625\u0644\u0649 \u0627\u0644\u062c\u0645\u0647\u0648\u0631 \u0627\u0644\u0639\u0631\u0628\u064a \u0628\u0623\u0639\u0644\u0649 "
    "\u062f\u0631\u062c\u0627\u062a \u0627\u0644\u062f\u0642\u0629 \u0648\u0627\u0644\u062a\u0623\u062b\u064a\u0631."
)


def main() -> int:
    convex_url = os.environ.get("CONVEX_URL", "http://127.0.0.1:3210")
    client = ConvexClient(convex_url)

    rows = client.query("voices:list", {})
    print(f"Fetched {len(rows)} voices from Convex")

    pending = [r for r in rows if r.get("providerVoiceId") and not r.get("introStorageId")]
    print(f"Pending warm: {len(pending)}/{len(rows)}")
    print()

    text_hash = hashlib.sha256(BRAND_TEXT.encode("utf-8")).hexdigest()

    succeeded = 0
    failed = 0

    for row in pending:
        name = row.get("name") or row.get("legacyId") or row.get("_id")
        checkpoint = row["providerVoiceId"]
        try:
            audio = asyncio.run(
                render_tts(
                    text=BRAND_TEXT,
                    voice_checkpoint=checkpoint,
                    speed=1.0,
                    volume=0,
                    fmt="mp3",
                )
            )
            b64 = base64.b64encode(audio).decode("ascii")
            result = client.action(
                "voices:uploadIntro",
                {
                    "voiceRowId": row["_id"],
                    "audioBase64": b64,
                    "contentType": "audio/mpeg",
                    "textHash": text_hash,
                },
            )
            print(f"OK {name} -> {len(audio)} bytes (storageId={result.get('storageId', '?')})")
            succeeded += 1
        except Exception as e:
            print(f"FAIL {name}: {e}")
            traceback.print_exc()
            failed += 1

    print()
    try:
        cache = client.query("voices:getCachedCount", {})
        total = cache.get("total", "?")
        cached = cache.get("cached", "?")
        print(f"Cache: {cached}/{total}")
    except Exception as e:
        print(f"Cache: <unavailable>: {e}")

    print(f"\nSucceeded: {succeeded}  Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
