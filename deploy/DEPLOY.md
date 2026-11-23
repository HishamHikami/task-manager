# Deploying on Ubuntu with nginx + systemd

Tested layout for a small (1 GB) Ubuntu 24.04 server that already runs nginx and
certbot. Replace `tasks.example.com` with your subdomain. Run everything as root.

| What | Where |
|---|---|
| Code (root-owned) | `/srv/taskmanager` |
| Settings / secrets | `/etc/taskmanager/env` (root:root, 600) |
| Database + backups | `/var/lib/taskmanager` (app user only, 700) |
| Socket | `/run/taskmanager/gunicorn.sock` |

## 1. DNS
Create an `A` record for `tasks.example.com` pointing to the server.

## 2. User, code, settings

```bash
useradd --system --user-group --home-dir /var/lib/taskmanager --shell /usr/sbin/nologin taskmanager
git clone https://github.com/<you>/task-manager.git /srv/taskmanager
cd /srv/taskmanager && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

install -d -m 700 /etc/taskmanager
install -m 600 .env.example /etc/taskmanager/env
# Generate a secret key and paste it into /etc/taskmanager/env:
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(50))"
nano /etc/taskmanager/env      # set SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, TIME_ZONE
```

## 3. Service

```bash
cp deploy/taskmanager.service deploy/taskmanager-backup.service deploy/taskmanager-backup.timer /etc/systemd/system/
chmod 755 deploy/*.sh
systemctl daemon-reload
systemctl enable --now taskmanager          # creates /var/lib/taskmanager and the socket
BRANCH=main deploy/update.sh                # static files, migrations, restart
deploy/manage.sh createsuperuser            # your login
systemctl enable --now taskmanager-backup.timer
```

## 4. nginx + HTTPS

```bash
sed 's/tasks.example.com/YOUR.DOMAIN/' deploy/nginx.conf.example > /etc/nginx/sites-available/taskmanager
ln -s /etc/nginx/sites-available/taskmanager /etc/nginx/sites-enabled/taskmanager
nginx -t && systemctl reload nginx
certbot --nginx -d YOUR.DOMAIN
```

## Updating

```bash
BRANCH=main /srv/taskmanager/deploy/update.sh
```

It backs up the database first, pulls, installs dependencies, migrates and restarts.

## Backups

`taskmanager-backup.timer` writes a compressed copy to `/var/lib/taskmanager/backups`
every night and keeps 14 days. Copy that folder off the server from time to time
(or enable your host's server backups) — a backup on the same disk doesn't protect
against losing the server.

Restore:
```bash
systemctl stop taskmanager
gunzip -c /var/lib/taskmanager/backups/db-YYYYMMDD-HHMMSS.sqlite3.gz > /var/lib/taskmanager/db.sqlite3
rm -f /var/lib/taskmanager/db.sqlite3-wal /var/lib/taskmanager/db.sqlite3-shm
chown taskmanager:taskmanager /var/lib/taskmanager/db.sqlite3
systemctl start taskmanager
```

## Memory
One gunicorn worker with 4 threads uses roughly 70 MB. The unit caps the service at 300 MB.
