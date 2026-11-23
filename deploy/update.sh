#!/usr/bin/env bash
# Pull the latest code and restart. Run as root.
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/taskmanager}"
APP_USER="${APP_USER:-taskmanager}"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-taskmanager}"

set -a; . /etc/taskmanager/env; set +a
cd "$APP_DIR"

echo "==> Back up database before updating"
if [ -f "${DATA_DIR:-/var/lib/taskmanager}/db.sqlite3" ]; then
    runuser -u "$APP_USER" -- "$APP_DIR/deploy/backup.sh"
else
    echo "   (no database yet — skipping)"
fi

echo "==> Pull $BRANCH"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git merge --ff-only --quiet "origin/$BRANCH"
git log -1 --oneline

echo "==> Python dependencies"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "==> Static files"
.venv/bin/python manage.py collectstatic --noinput --verbosity 0

echo "==> Migrate"
"$APP_DIR/deploy/manage.sh" migrate --noinput
"$APP_DIR/deploy/manage.sh" check --deploy --fail-level ERROR

echo "==> Restart"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" && echo "OK: $SERVICE is running"
