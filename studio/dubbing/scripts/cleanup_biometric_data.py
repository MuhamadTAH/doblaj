#!/usr/bin/env python3
"""
PIRD-014: cleanup script for biometric data intermediates.

Deletes any file under data/jobs/sessions/ or data/jobs/playground_ingest/
older than 7 days. These are voice recordings and rendered chunks that
are not safe to keep on disk indefinitely once processing is done.

Run via cron / Railway scheduled task once a day:
    0 3 * * *  cd /app && python scripts/cleanup_biometric_data.py
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cleanup_biometric_data")

# Biometric data roots. Voice recordings and chunk intermediates live here.
TARGET_DIRS = [
    Path("data/jobs/sessions"),
    Path("data/jobs/playground_ingest"),
]
MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _purge_under(root: Path, max_age: int) -> tuple[int, int]:
    if not root.exists():
        return (0, 0)
    files_removed = 0
    bytes_removed = 0
    cutoff = time.time() - max_age
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            continue
        size = stat.st_size
        try:
            path.unlink()
            files_removed += 1
            bytes_removed += size
        except OSError as e:
            logger.warning(f"could not delete {path}: {e}")
    # Remove now-empty directories.
    for d in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass
    return (files_removed, bytes_removed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=7.0,
        help="Delete files older than this many days. Default: 7",
    )
    args = parser.parse_args()
    max_age = int(args.max_age_days * 86400)
    total_files = 0
    total_bytes = 0
    for d in TARGET_DIRS:
        f, b = _purge_under(d, max_age)
        logger.info(f"{d}: removed {f} files ({b} bytes)")
        total_files += f
        total_bytes += b
    logger.info(f"DONE: removed {total_files} files, {total_bytes} bytes total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
