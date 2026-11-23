#!/usr/bin/env bash
# Consistent online backup of the SQLite database, compressed, with rotation.
# Safe to run while the app is running. Run as root or as the app user.
set -euo pipefail

DATA_DIR="${DATA_DIR:-/var/lib/taskmanager}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
DB="$DATA_DIR/db.sqlite3"

[ -f "$DB" ] || { echo "No database at $DB"; exit 1; }
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/db-$STAMP.sqlite3"

python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
gzip -9 "$OUT"
find "$BACKUP_DIR" -name 'db-*.sqlite3.gz' -mtime +"$KEEP_DAYS" -delete
echo "Backup written: $OUT.gz"
