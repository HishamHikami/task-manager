# Task Manager

A self-hosted, single-owner task tracker for following work as it moves between
departments and people: **who has it now, what stage it's in, and what happened
along the way.** It keeps separate workspaces (e.g. a company and a volunteer
organization) and a timeline per task for hand-offs, stage changes, emails,
WhatsApp messages and meeting minutes.

Built with Django + SQLite + HTMX. Light enough for a 1 GB server.

## Features
- Workspaces with their own departments/people and configurable stages
- Tasks with priority, due date, your role (assigned / following up / doing it), reference no.
- **Hand-offs** — move a task to someone else's desk; the full chain is kept
- **Timeline** — notes, pasted emails/WhatsApp/minutes, stage changes, follow-ups
- **Dashboard** — follow-ups due today, overdue tasks, and open tasks grouped by who holds them
- Search across tasks and timeline text; mobile-friendly; light/dark mode

- People inside departments with roles; assign tasks to a specific person; one-click copy of phone/email
- **Events** with your role (host, speaker, guest…), invitation status and add-to-calendar
- **Quick capture with AI** (optional): paste or share an email/WhatsApp message and Claude Haiku
  suggests a summary, the task, who has it and dates — you review before saving.
  Uses **your own** Anthropic API key, entered in Settings and stored encrypted.
- **Installable phone app** (PWA) with Android *Share → Tasks*

Next ideas: optional email intake, attachments, daily digest. See [docs/PLAN.md](docs/PLAN.md).

## Try it locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then set DEBUG=1 for local use
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo      # optional example data
python manage.py runserver
```

Run tests: `python manage.py test`

## Deploy

See [deploy/DEPLOY.md](deploy/DEPLOY.md) (Ubuntu + nginx + systemd + certbot).

## Your own copy, your own key

Each person runs their own instance. No API keys or credentials are included in
this repository.

## License

MIT
