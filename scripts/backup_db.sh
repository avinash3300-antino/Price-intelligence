#!/usr/bin/env bash
# Nightly SQLite backup. Runs BEFORE the catalog refresh so the snapshot is
# always a known-good pre-write state.
#
# Why not `cp`: the API writes to this database whenever someone maps an
# option, and the nightly refresh rewrites ~1,900 rows. Copying a live SQLite
# file can capture a torn write and produce a backup that only fails when you
# try to restore it. SQLite's online backup API is safe with concurrent
# writers, so that is what this uses.
#
# Runs on the host, not inside the container — the database is bind-mounted at
# ./data, and SQLite's locking is filesystem-level, so a host-side backup
# coordinates correctly with the container's writes.
#
# Usage:  scripts/backup_db.sh [--retain-days N] [--out DIR]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$PROJECT_ROOT/data/market_intel.db"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
RETAIN_DAYS=14

while [[ $# -gt 0 ]]; do
    case "$1" in
        --retain-days) RETAIN_DAYS="$2"; shift 2 ;;
        --out)         BACKUP_DIR="$2";  shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

PY="$PROJECT_ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/market_intel_${STAMP}.db"

mkdir -p "$BACKUP_DIR"

echo "=========================================="
echo "backup_db START $(date -Iseconds)"
echo "  source: $DB_PATH"
echo "  dest:   ${OUT}.gz"
echo "=========================================="

if [[ ! -f "$DB_PATH" ]]; then
    echo "FATAL: database not found at $DB_PATH" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Snapshot + verify in one step. The verify is the point: a backup nobody has
# read is a guess. These five tables are the ones that cannot be regenerated —
# products and Rayna options are rebuilt nightly from the feed, but mappings
# are human work and price_observations are historical.
# ---------------------------------------------------------------------------
"$PY" - "$DB_PATH" "$OUT" <<'PYEOF'
import sqlite3, sys

src_path, dst_path = sys.argv[1], sys.argv[2]
CRITICAL = ["mappings", "competitors", "competitor_listings",
            "options", "price_observations", "products"]

src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
before = {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in CRITICAL}

dst = sqlite3.connect(dst_path)
src.backup(dst)          # online backup API — safe with concurrent writers
dst.close()
src.close()

# Re-open the backup independently and prove it is readable and complete.
chk = sqlite3.connect(f"file:{dst_path}?mode=ro", uri=True)
integrity = chk.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    print(f"FATAL: integrity_check returned {integrity!r}", file=sys.stderr)
    sys.exit(1)

after = {t: chk.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in CRITICAL}
chk.close()

bad = {t: (before[t], after[t]) for t in CRITICAL if before[t] != after[t]}
if bad:
    # A mismatch here means someone wrote mid-backup and the snapshot is not
    # the consistent point-in-time we think it is. Fail loudly.
    print(f"FATAL: row count mismatch {bad}", file=sys.stderr)
    sys.exit(1)

print("  integrity_check: ok")
for t in CRITICAL:
    print(f"    {t:<22} {after[t]:>8} rows")
PYEOF

gzip -f "$OUT"
echo "  compressed: $(du -h "${OUT}.gz" | cut -f1)"

# ---------------------------------------------------------------------------
# Prune. Only ever touches files this script created — the hand-made
# market_intel.db.bak-* snapshots from past migrations are left alone.
# ---------------------------------------------------------------------------
PRUNED=$(find "$BACKUP_DIR" -name 'market_intel_*.db.gz' -type f -mtime "+${RETAIN_DAYS}" -print -delete | wc -l | tr -d ' ')
echo "  pruned $PRUNED backup(s) older than ${RETAIN_DAYS} days"
echo "  kept:   $(find "$BACKUP_DIR" -name 'market_intel_*.db.gz' -type f | wc -l | tr -d ' ') backup(s)"

echo "=========================================="
echo "backup_db DONE  $(date -Iseconds)"
echo "=========================================="
