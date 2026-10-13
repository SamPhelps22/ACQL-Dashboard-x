#!/usr/bin/env bash
# Weekly automation: refresh data, grade submitted weeks, predict the next slate, export CSV.
# Schedule with cron, e.g. every day at 14:00 UTC during the season:
#   0 14 * * * /path/to/nfl_pickem/scripts/weekly_job.sh >> /path/to/nfl_pickem/data/weekly.log 2>&1
# Add --freeze to lock the run as your submitted picks (never overwrites an existing submission).
set -euo pipefail
cd "$(dirname "$0")/.."
python -m nflpickem weekly "$@"
