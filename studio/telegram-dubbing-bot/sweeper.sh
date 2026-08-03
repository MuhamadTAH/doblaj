#!/bin/bash
# sweeper.sh
# Hourly GC for pird_outputs and input files that might be stuck.

# Find files older than 24 hours (1440 minutes) in the outputs directory and delete them
find /var/lib/telegram-bot-api/pird_outputs -type f \( -name "*.mp4" -o -name "*.mkv" \) -mmin +1440 -exec rm -f {} \;

# Fallback: cleanup input files in the main telegram-data volume if they've been abandoned for > 24 hours.
find /var/lib/telegram-bot-api -type f \( -name "*.mp4" -o -name "*.mkv" \) -mmin +1440 -exec rm -f {} \;
