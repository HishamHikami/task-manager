# Task Manager — Plan

A self-hosted, single-owner task tracker built around one question:
**where is this task right now, who has it, and what happened along the way?**

It covers more than one part of life (e.g. a company and a volunteer/religious
organization), tracks tasks as they move between departments and people, and
keeps a timeline of updates taken from emails, WhatsApp messages and meeting
minutes, with optional short AI summaries.

Each person runs their **own copy** with their own data and their own AI key.
Nothing in this repository contains or uses anyone's credentials.

---

## 1. Concepts

| Concept | Meaning |
|---|---|
| **Workspace** | A separate area of life, e.g. "Company", "Religious Org". Own people, units and stages. One dashboard can show all workspaces or one. |
| **Unit / Person** | A department, committee or individual who can hold a task. |
| **Task** | Title, description, workspace, priority, due date, **my role** (assigned it / following up / executing), stage, **current holder**. |
| **Stage** | Configurable per workspace (e.g. Registered → Assigned → In progress → Waiting approval → Done). |
| **Hand-off** | A record that a task moved from one holder to another, with date and note. Builds the "whose desk" history. |
| **Update** | A timeline entry: note, pasted email/WhatsApp text, meeting minutes, call. Keeps the original text, an optional AI summary, and the source. |
| **Follow-up** | "Check back with X by date." Drives the *Needs a nudge* list. |

### Main screens
- **Dashboard** — open tasks grouped by current holder; overdue and follow-ups due today at the top.
- **Task page** — details, current holder, and a single timeline of hand-offs and updates.
- **Quick capture** — paste or share any text; get a summary and a suggested task to attach it to.
- **Workspace settings** — units/people, stages.
- **Settings** — AI key, AI on/off per workspace, backups info.

---

## 2. Getting information in

| Source | Approach | Notes |
|---|---|---|
| **Paste** | Paste text into Quick capture. | Always works. First thing built. |
| **Android share** | The app is an installable PWA with a **Web Share Target**, so it appears in Android's Share menu (WhatsApp, Outlook, Gmail, etc.). | No unofficial WhatsApp tooling — those violate WhatsApp's terms and risk a ban. |
| **Email (later)** | Optional: the app polls a dedicated mailbox (IMAP) and puts new mail into a *To sort* queue. | Many companies (incl. Microsoft 365 tenants) block auto-forwarding to external addresses; manual forward or share remains the fallback. |
| **Attachments (later)** | Upload PDFs/photos of minutes to a task. | Text extraction optional. |

---

## 3. AI summaries (optional)

- **Provider:** Anthropic Claude API, model **Claude Haiku 5.5** (`claude-haiku-5-5`), via the official `anthropic` Python SDK.
- **Key handling:** the owner enters their own API key in **Settings**. It is stored **encrypted** in the database using a master secret that lives only in the server's environment file (never in the repo). `.env` is git-ignored; `.env.example` has no real values.
- **App works fully without a key** — summaries are just skipped.
- **Per-workspace switch** "never send this workspace to AI" for sensitive contexts.
- **One call per message**, returning structured output: short summary, suggested status, current holder, next action, due date. The owner **confirms or edits** before anything is saved — AI never changes a task on its own.
- **Token hygiene before sending:** strip quoted reply chains, signatures, disclaimers and boilerplate; cap length; cap output tokens; never re-summarize identical text (hash cache).
- **Cost:** Haiku 5.5 is $0.10 / 1M input and $0.50 / 1M output tokens (check current pricing). ~1,000 summaries/month at ~1,200 tokens in and ~100 out ≈ **$0.20/month**.
- Token usage is recorded per call and shown in Settings.
- Set a spend limit in the Anthropic Console as a backstop.

---

## 4. Tech stack

Chosen to be light enough for a **1 GB RAM** server shared with other apps, and
easy for anyone to self-host.

- **Backend:** Python 3.12, **Django**, served by **gunicorn** (1 worker, 4 threads) behind **nginx**, run as a **systemd** service under its own user.
- **Database:** **SQLite** (WAL mode) — one file, zero extra memory.
- **Frontend:** server-rendered Django templates + **HTMX** for interactivity; small hand-written CSS; no heavy JS build step.
- **PWA:** web app manifest, service worker, Web Share Target (Android).
- **Auth:** single owner account (Django auth), strong password, login rate limiting; optional TOTP later.
- **TLS:** Let's Encrypt via certbot.
- **No Docker required** (Docker remains an option for others later).
- **No GitHub Actions** in this repo unless each workflow is reviewed.

Expected footprint: roughly 70 MB RAM.

---

## 5. Deployment (self-hosted)

Generic Ubuntu + nginx + certbot + systemd layout, matching common single-droplet setups:

1. DNS `A` record for the subdomain → server IP.
2. Dedicated system user; code in `/srv/<app>` (root-owned), data dir writable by the app user.
3. Python virtualenv; `gunicorn` on a Unix socket; `systemd` unit.
4. nginx server block for the subdomain → socket; static files served by nginx.
5. `certbot --nginx -d <subdomain>`.
6. `deploy/update.sh`: `git pull`, install deps, migrate, collectstatic, restart service.
7. **Backups:** nightly `sqlite3 .backup` to a dated file with rotation (e.g. 14 days); optional off-server copy.

---

## 6. Costs

| Item | Cost |
|---|---|
| Server | Existing droplet — $0 extra |
| Subdomain + TLS | $0 |
| Database | $0 (SQLite) |
| AI (Haiku 5.5) | ≈ $0–1 / month at personal volume |
| Off-server backups (optional) | $0–5 / month |

---

## 7. Limitations and risks

1. **Privacy / company policy** — summaries send text to Anthropic. Use the per-workspace AI switch where needed.
2. **WhatsApp** — share-based only; no automatic reading.
3. **Outlook** — auto-forwarding may be blocked by IT.
4. **AI can be wrong** — every suggestion is confirmed by the owner.
5. **Single server** — backups are essential.
6. **Small server memory** — keep workers low; avoid heavy background processes.

---

## 8. Phases

1. **MVP** — workspaces, units/people, stages, tasks, hand-offs, timeline updates, follow-ups, dashboard by holder, owner login.
2. **AI** — Quick capture with Haiku 5.5 summary + suggested task; encrypted key in Settings; usage tracking.
3. **Mobile** — PWA install, Android Share target, mobile-friendly layouts.
4. **Email intake** — optional IMAP polling into a *To sort* queue.
5. **Extras** — search, attachments, daily digest, reports (e.g. "held by Finance > 7 days"), TOTP.
