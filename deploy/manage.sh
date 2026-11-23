#!/usr/bin/env bash
# Run a Django management command as the app user with the production env.
# Usage (as root): /srv/taskmanager/deploy/manage.sh <command> [args...]
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/taskmanager}"
APP_USER="${APP_USER:-taskmanager}"
ENV_FILE="${ENV_FILE:-/etc/taskmanager/env}"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

cd "$APP_DIR"
exec runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" "$@"
