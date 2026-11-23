#!/usr/bin/env bash
# Pull the latest code and restart. Run as root.
# Usage: deploy/update.sh [branch]      (default: $BRANCH or main)
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/taskmanager}"
APP_USER="${APP_USER:-taskmanager}"
BRANCH="${1:-${BRANCH:-main}}"
SERVICE="${SERVICE:-taskmanager}"
HEALTH_URL="${HEALTH_URL:-}"   # e.g. https://tasks.example.com/login/

fail() { echo "FAILED: $*" >&2; exit 1; }

set -a; . /etc/taskmanager/env; set +a
cd "$APP_DIR"

echo "==> Back up database before updating"
if [ -f "${DATA_DIR:-/var/lib/taskmanager}/db.sqlite3" ]; then
    runuser -u "$APP_USER" -- "$APP_DIR/deploy/backup.sh"
else
    echo "   (no database yet — skipping)"
fi

echo "==> Fetch $BRANCH"
git fetch --quiet origin "$BRANCH"

# This app needs no CI. Refuse to deploy code that adds GitHub workflows,
# so a planted workflow is noticed instead of silently shipped.
if git ls-tree -r --name-only "origin/$BRANCH" | grep -q '^\.github/workflows/'; then
    fail "origin/$BRANCH contains .github/workflows/ — review it before deploying."
fi

git checkout --quiet "$BRANCH" 2>/dev/null || git checkout --quiet -b "$BRANCH" "origin/$BRANCH"
git merge --ff-only --quiet "origin/$BRANCH" || fail "local branch has diverged from origin/$BRANCH"
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

echo "==> Health check"
for _ in $(seq 1 15); do
    systemctl is-active --quiet "$SERVICE" && [ -S /run/taskmanager/gunicorn.sock ] && break
    sleep 1
done
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 30 --no-pager; fail "$SERVICE is not running"; }
code="$(curl -s -o /dev/null -w '%{http_code}' --unix-socket /run/taskmanager/gunicorn.sock \
    -H "Host: ${ALLOWED_HOSTS%%,*}" -H 'X-Forwarded-Proto: https' http://localhost/login/ || true)"
[ "$code" = "200" ] || { journalctl -u "$SERVICE" -n 30 --no-pager; fail "app returned HTTP $code on /login/"; }
if [ -n "$HEALTH_URL" ]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
    [ "$code" = "200" ] || fail "$HEALTH_URL returned HTTP $code"
fi
echo "OK: $SERVICE is running and answering (deployed $(git rev-parse --short HEAD))"
