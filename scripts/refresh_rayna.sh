#!/usr/bin/env bash
# Daily Rayna catalog + options refresh.
# Runs the three-step chain: ingest_rayna -> feed_cache -> sync_options_from_feed.
# Meant to be triggered by cron at 00:00 Asia/Dubai daily.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/refresh_rayna_${STAMP}.log"

# Use the project's own venv Python so cron picks up the right deps regardless
# of the invoking shell's PATH.
PY="$PROJECT_ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

cd "$PROJECT_ROOT"

exec >>"$LOG_FILE" 2>&1

echo "=========================================="
echo "refresh_rayna START $(date -Iseconds)"
echo "python: $PY"
echo "cwd:    $PROJECT_ROOT"
echo "=========================================="

echo ""
echo "[1/3] ingest_rayna (products)"
echo "------------------------------------------"
"$PY" -m src.ingest_rayna

echo ""
echo "[2/3] feed_cache (per-product options)"
echo "------------------------------------------"
"$PY" -m src.feed_cache

echo ""
echo "[3/3] sync_options_from_feed (options table)"
echo "------------------------------------------"
"$PY" -m src.sync_options_from_feed

echo ""
echo "=========================================="
echo "refresh_rayna DONE  $(date -Iseconds)"
echo "=========================================="
