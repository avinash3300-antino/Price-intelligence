#!/usr/bin/env bash
# Nightly PostgreSQL backup. Runs BEFORE the catalog refresh so the snapshot is
# always a known-good pre-write state.
#
# Every run restores the dump into a scratch database and compares row counts
# against the live one before keeping it. A backup nobody has restored is a
# guess, and the failure mode of an unverified backup is discovering it was
# useless on the day you need it.
#
# Runs from the host against the postgres container. pg_dump lives in the
# image, so nothing needs installing on the box.
#
# Usage:  scripts/backup_db.sh [--retain-days N] [--out DIR]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
RETAIN_DAYS=14
PG_SERVICE=postgres
PG_USER=mi
PG_DB=market_intel

while [[ $# -gt 0 ]]; do
    case "$1" in
        --retain-days) RETAIN_DAYS="$2"; shift 2 ;;
        --out)         BACKUP_DIR="$2";  shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

cd "$PROJECT_ROOT"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/market_intel_${STAMP}.dump"
SCRATCH="verify_${STAMP}"

mkdir -p "$BACKUP_DIR"

echo "=========================================="
echo "backup_db START $(date -Iseconds)"
echo "  source: postgres/${PG_DB}"
echo "  dest:   ${OUT}.gz"
echo "=========================================="

dc() { docker compose "$@"; }

if ! dc ps --status running --services | grep -qx "$PG_SERVICE"; then
    echo "FATAL: the $PG_SERVICE container is not running" >&2
    exit 1
fi

# These six are the ones worth proving. products and Rayna options rebuild
# nightly from the feed; mappings are human work, competitor listings cost
# real Claude and Firecrawl spend, and price_observations are historical.
TABLES="products competitors competitor_listings options mappings price_observations users"

counts_of() {
    local db="$1" out=""
    for t in $TABLES; do
        n=$(dc exec -T "$PG_SERVICE" psql -U "$PG_USER" -d "$db" -tA \
              -c "SELECT COUNT(*) FROM $t" 2>/dev/null | tr -d '[:space:]')
        out="${out}${t}=${n} "
    done
    echo "$out"
}

BEFORE="$(counts_of "$PG_DB")"
echo "  live:   $BEFORE"

# Custom format so the verify step can use pg_restore directly.
dc exec -T "$PG_SERVICE" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$OUT"
echo "  dumped: $(du -h "$OUT" | cut -f1)"

# ---------------------------------------------------------------------------
# Restore into a scratch database and compare. Dropped again either way — the
# trap fires on failure too, so a bad run never leaves debris behind.
# ---------------------------------------------------------------------------
cleanup() {
    dc exec -T "$PG_SERVICE" dropdb -U "$PG_USER" --if-exists "$SCRATCH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

dc exec -T "$PG_SERVICE" createdb -U "$PG_USER" "$SCRATCH"
dc exec -T "$PG_SERVICE" pg_restore -U "$PG_USER" -d "$SCRATCH" --no-owner < "$OUT" >/dev/null 2>&1

AFTER="$(counts_of "$SCRATCH")"
echo "  restored: $AFTER"

if [[ "$BEFORE" != "$AFTER" ]]; then
    echo "FATAL: restored counts differ from live." >&2
    echo "  live:     $BEFORE" >&2
    echo "  restored: $AFTER" >&2
    rm -f "$OUT"
    exit 1
fi
echo "  verified: restored copy matches the live database"

gzip -f "$OUT"
echo "  compressed: $(du -h "${OUT}.gz" | cut -f1)"

# Prune. Only ever touches files this script created — the pre-cutover SQLite
# snapshots and the .bak-* files are left alone.
PRUNED=$(find "$BACKUP_DIR" -name 'market_intel_*.dump.gz' -type f -mtime "+${RETAIN_DAYS}" -print -delete | wc -l | tr -d ' ')
echo "  pruned $PRUNED backup(s) older than ${RETAIN_DAYS} days"
echo "  kept:   $(find "$BACKUP_DIR" -name 'market_intel_*.dump.gz' -type f | wc -l | tr -d ' ') backup(s)"

echo "=========================================="
echo "backup_db DONE  $(date -Iseconds)"
echo "=========================================="
