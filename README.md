# BotForge

**One bot. Your entire business. Built and maintained by AI.**

BotForge is a Persian AI Business OS for Telegram: the owner describes the business, and an AI agent
builds and maintains a modular bot (orders, bookings, events, forms, reports, spreadsheet analysis) from
a validated BotSpec that a deterministic runtime executes with no LLM calls for routine operations.
The owner runs it from the Business Control Center; every change is a reviewable, reversible revision.

The V1 demo scenario is a workshop-registration bot (capacity, waitlist with automatic promotion,
cancellation). `IMPLEMENTATION_ROADMAP.md` is the source of truth for scope, architecture and decisions
(the Business OS expansion is merged into `main`); this README only covers running and deploying
the project.

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI app: `api/` routes, `agent/` (LLM orchestration), `botspec/` (contracts), `runtime/` (bot engines, `PgStore`), `integrations/telegram/`, `simulator/`, `revisions/`, `testing/`, `security/`, `db/` |
| `backend/alembic/` | Database migrations (schema `app`) |
| `backend/scripts/` | Operator and dev tools: `create_user.py`, `load_spec.py`, `seed_demo.py`, `dev_db.py`, `smoke_local.py`, `eval_golden.py` |
| `backend/tests/` | `unit/`, `golden/`, `integration/` (needs Postgres) |
| `backend/Dockerfile` | Production image (one container, one worker) |
| `frontend/` | Business Control Center (Next.js, Persian, RTL) |
| `examples/` | Golden workshop BotSpec, scenarios and prompts |
| `render.yaml` | Render Blueprint for the backend |
| `conductor/` | Claude Code orchestration config used to build this project (not part of the product); install with `conductor/install/AGENT-INSTALL.md` |

## Local setup (Linux, macOS or Windows; no Docker, no cloud)

Prerequisites: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 itself) and, for the frontend,
Node 20.9 or newer. Commands run from `backend/` unless stated. The `uv run ...` commands are the same
on every platform; the examples below are PowerShell, and the Linux/macOS differences are listed next.

### On Linux or macOS

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh       # installs uv
cd backend && uv sync --group dbtest
uv run pytest -q                                       # starts a temporary Postgres itself (pgserver)
```

- Set environment variables with `export NAME=value` instead of `$env:NAME = 'value'`,
  e.g. `export TOKEN_ENC_KEY="$(uv run python -m app.security.crypto generate-key)"`.
- Use `curl` instead of `curl.exe`, `cp .env.example .env.local` instead of `copy`, and
  `.venv/bin/python` instead of `.venv/Scripts/python`.
- A system Postgres works too: point `TEST_DATABASE_URL` (tests; the schema `app` is dropped and
  rebuilt, so use a throwaway database) or `DATABASE_URL` (dev) at it instead of using `pgserver`.

```powershell
cd backend
uv sync --group dbtest        # app + dev tools + pgserver (a pip-installed Postgres for tests and dev)
```

### Tests

```powershell
uv run ruff check app tests scripts alembic
uv run pytest -q              # starts a temporary Postgres itself; about 1800 tests
```

The test database lives in a temp directory and is removed afterwards. It never touches the dev
database below. Without `pgserver` (and without `TEST_DATABASE_URL`) database tests are skipped.

### A persistent development database

```powershell
uv run python scripts/dev_db.py start    # starts Postgres, runs alembic upgrade head, prints DATABASE_URL
uv run python scripts/dev_db.py status
uv run python scripts/dev_db.py stop     # data stays in backend/.devdb/ (git-ignored)
```

The port is chosen at start, so the URL can change between starts. Set it for the current shell:
`$env:DATABASE_URL = '<the printed url>'`.

### Environment

Settings are read from the process environment or from `backend/.env` (git-ignored; see
`.env.example` for every name). A minimal local setup:

```powershell
$env:DATABASE_URL = '<from dev_db.py>'
$env:AUTH_COOKIE_SECURE = 'false'   # plain-http local development only: the session cookie works over http
$env:TOKEN_ENC_KEY = (uv run python -m app.security.crypto generate-key)
$env:PUBLIC_BASE_URL = 'http://localhost:8000'
$env:FRONTEND_ORIGIN = 'http://localhost:3000'
```

`ANTHROPIC_API_KEY`, `LLM_MODEL_STRONG` and `LLM_MODEL_FAST` are needed only for agent runs. Owners
sign in with the backend's own accounts (email and password, a `bf_session` cookie); see Run the API.

### Business OS settings and operator notes

The Business OS modules (notifications, spreadsheet analysis, Copilot) are configured with these
environment variables (all optional; the defaults work locally, and `deploy/.env.example` lists them for
the VPS):

| Variable | Default | What it does |
|---|---|---|
| `NOTIFICATIONS_TICKER` | `false` (compose: `true`) | Runs the background ticker that sends queued Telegram notifications: event reminders, announcements, scheduled reports. Off means nothing is ever sent. Run it in exactly one backend process. |
| `NOTIFICATIONS_TICK_SECONDS` | `20` | How often (seconds, 1 to 3600) the ticker looks for due messages. |
| `NOTIFICATIONS_SEND_RATE_PER_SECOND` | `15` | Global ceiling of messages sent per second across all bots (1 to 30; Telegram allows about 30 per bot token). |
| `UPLOAD_DIR` | `./uploads` (compose: `/data/uploads`) | Where uploaded spreadsheets are stored on disk. |
| `UPLOAD_MAX_BYTES` | `5242880` | Largest accepted upload (5 MB), applied to the raw request body. |
| `SPREADSHEET_MAX_ROWS` | `50000` | Rows read from a sheet; the rest is ignored. |
| `SPREADSHEET_MAX_COLUMNS` | `100` | Columns read from a sheet. |
| `COPILOT_DAILY_CAP` | `50` | Copilot questions per owner account per rolling 24 hours (cost control; 0 disables). |

Uploads are limited further to 4 at once per process and 120 seconds to receive a file; an xlsx is
structure-checked before it is parsed, and macro workbooks are refused. The Copilot and scheduled reports
only work for a bot whose module is enabled in the Capability Center, and scheduled reports are sent only
while the ticker is on.

**Uploads volume (VPS).** In `deploy/docker-compose.yml` the backend stores uploads on the named volume
`uploads` mounted at `/data/uploads` (`UPLOAD_DIR` is fixed there); a one-shot `uploads-init` service hands
the volume to the backend's non-root user before it starts. Keep the volume: stored analysis runs point at
those files. `deploy/backup.sh` backs up the database only, so copy the uploads too, for example
`docker compose exec -T backend tar czf - -C /data uploads > uploads-$(date +%F).tgz` from `deploy/`.

**Telegram groups.** To use event cards in a group or channel:
1. Make sure the bot receives `my_chat_member` updates. In polling mode this is automatic. In webhook mode a
   bot connected before this version must be re-registered once (`docker compose exec backend python
   scripts/reregister_webhooks.py`, or `uv run python scripts/reregister_webhooks.py` locally) or
   disconnected and connected again; otherwise the Groups list in Settings stays empty.
2. Add the bot to the group (Telegram: group, Add member), preferably as an administrator. A channel needs
   the administrator right to post.
3. Privacy mode (BotFather, `/setprivacy`) can stay on: the bot only reads button presses on its own cards
   and its own membership changes, never group conversations. Group messages are ignored by design.
4. The group then appears in Settings, Groups; publish an event card from there. The card's buttons are
   checked against the pressed message's own keyboard, so a forged button press is ignored.

**Staff and managers.** Settings, Team creates a staff invite link; a person who opens it becomes staff.
Staff run order and request queues; on internal (staff or managers audience) workflows only managers
decide. Staff and managers may also send a spreadsheet to the bot as a file when Spreadsheet Intelligence
is enabled.

**Demo path (the Business OS story).** Use a bot with the workshop spec (or a new one) and the simulator;
steps marked (Telegram) need a connected bot and a phone:
- [ ] Capability Center: enable Events, read the dependency preview, confirm; a new active revision appears.
- [ ] Data tab: create an event with a capacity and a category.
- [ ] Simulator: RSVP to the event as a customer; a second customer joins the waitlist when it is full.
- [ ] Reports: the RSVP and category breakdowns show it (Reports is on by default).
- [ ] Data Analyst: upload a workbook (xlsx or csv); the profile is created (one LLM call, needs the API key
      or the headless login).
- [ ] Upload the same layout again: the run is deterministic, with metrics and any anomalies.
- [ ] Upload a file with a changed column: the run is `schema_changed` and says which column is missing.
- [ ] Copilot: ask a business question; the answer comes from reporting tools (enable Copilot first).
- [ ] Orders: enable Orders with a catalog, then browse, add to cart and check out in the simulator; change
      the order status as the owner; the order report counts it (a cancelled order does not count as revenue).
- [ ] (Telegram) Team: open the staff link on a second phone (that person becomes staff and sees the
      order queue); as the owner, who is a manager, open the manager panel (a button in the bot's main menu)
      and read a report. With the ticker on, an announcement or a scheduled report arrives.
- [ ] (Telegram) Add the bot to a group, publish the event card, RSVP from the group.

### Running the agent against headless Claude Code

For local development and live evals the agent can run on your Claude Code login instead of a paid
API key (production keeps the API provider):

```bash
uv sync --group headless          # claude-agent-sdk, with a bundled Claude Code CLI
# be logged in to Claude Code (run `claude` once and sign in)
export LLM_PROVIDER=claude_cli    # or put it in backend/.env; needs no ANTHROPIC_API_KEY
uv run python scripts/eval_golden.py --create --provider claude_cli
```

Each model call is an isolated headless session (`CLAUDE_CLI_MODEL`, default `claude-opus-5-5`, at
`CLAUDE_CLI_EFFORT`, default `medium`); `CLAUDE_CLI_PATH` points at another CLI binary if needed.
Reported costs are the notional API cost of the same tokens.

### Run the API

```powershell
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
# in another shell: sign up (or create the account with scripts/create_user.py, then log in);
# the cookie jar keeps the session, and every POST/PATCH/DELETE needs the CSRF header
curl.exe -c jar.txt -H "X-BotForge-CSRF: 1" -H "Content-Type: application/json" -d '{\"email\":\"me@example.com\",\"password\":\"at least 10 characters\"}' http://localhost:8000/auth/signup
curl.exe -b jar.txt http://localhost:8000/me          # your user id
```

`uv run python scripts/create_user.py --email me@example.com` creates an account (password prompt) or,
with `--reset-password`, sets a new password and signs the account out everywhere.

Load the golden spec into a bot for that user and seed the demo data:

```powershell
curl.exe -b jar.txt -H "X-BotForge-CSRF: 1" -H "Content-Type: application/json" -d '{\"name\":\"Demo\"}' http://localhost:8000/bots
uv run python scripts/load_spec.py --spec ../examples/workshop.botspec.json --owner-email me@example.com --bot-id <bot id> --sample-data scripts/workshop.sample_data.json
uv run python scripts/seed_demo.py --bot-id <bot id>            # --reset removes it again
```

### Smoke test of the whole HTTP stack

```powershell
uv run python scripts/dev_db.py start
$env:DATABASE_URL = '<printed url>'
uv run python scripts/smoke_local.py --local-defaults
uv run python scripts/dev_db.py stop
```

It needs no LLM and no Telegram: it signs up two throw-away accounts through `/auth/signup` (each
with its own cookie jar), drives the real ASGI app in-process (no port is opened; Telegram is the
in-memory fake client) and prints PASS or FAIL per step (exit code 1 on any failure). It creates and
deletes its own bot and accounts, and refuses a non-local `DATABASE_URL` unless `--allow-remote` is
given. If `DATABASE_URL` is unset it uses the running dev database. `--local-defaults` fills in unset
`TOKEN_ENC_KEY`, `PUBLIC_BASE_URL` and `FRONTEND_ORIGIN`.

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev                  # http://localhost:3000
```

With `NEXT_PUBLIC_MOCK=1` (the default in `.env.example`) the web app runs entirely on fixtures: fake
sign-in and a scripted agent stream, no backend needed. Real mode (`NEXT_PUBLIC_MOCK=0` or unset) talks to
the backend through `/api`, which `npm run dev` proxies to `http://localhost:8000` (so start the backend
first); sign-in uses the backend's own accounts (`/auth/signup`, or `scripts/create_user.py`).

## Deployment on Render + Supabase (from staging, 2026-10-07)

> Taken verbatim from the `staging` branch (the hosted test deployment: `render.yaml`, Supabase
> Postgres through the session pooler). It still describes staging's Supabase Auth sign-in; this
> branch uses the backend's own login until the `AUTH_PROVIDER` switch lands. A docs pass will merge
> it with the sections below.

### Deployment checklist

Architecture: the frontend (a Render Node service, or Vercel) calls the backend (one always-on Render container) with a Supabase
access token; the backend talks to Supabase Postgres, the Anthropic API and Telegram. The backend must
run as a single instance with a single worker (agent runs and rate limits are in-process).

1. **Supabase project.**
   - Authentication, Sign In / Providers, Email: turn **Confirm email off** (sign-up must give a session at once).
   - Project Settings, API: copy the project URL (`SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`) and the
     anon/publishable key (`NEXT_PUBLIC_SUPABASE_ANON_KEY`). Never put the service-role key anywhere.
   - JWKS URL: `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` (`SUPABASE_JWKS_URL`). Use a project with
     asymmetric JWT signing keys. For a legacy project, set `SUPABASE_JWT_SECRET` (Project Settings,
     API, JWT secret) and leave `SUPABASE_JWKS_URL` empty.
   - Database URL: the **Connect** button, then the **Session pooler** string (port 5432; it works on
     IPv4 hosts such as Render). Replace the password placeholder and append `?ssl=require`, e.g.
     `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?ssl=require`.
     This is `DATABASE_URL`. Do not use the transaction pooler (port 6543): asyncpg's prepared
     statements do not work through it. `postgres://`, `postgresql://` and `postgresql+asyncpg://`
     are all accepted, and a libpq `sslmode=require` is translated to asyncpg's `ssl=require`.
2. **Generate `TOKEN_ENC_KEY`** (encrypts Telegram bot tokens; losing it orphans stored tokens):
   `uv run python -m app.security.crypto generate-key` in `backend/`. Keep a copy in a password manager.
3. **Render.** New, Blueprint, pick this repository; it reads `render.yaml` (the API: one Docker web service,
   root directory `backend`, health check `/healthz`, auto-deploy off; the free plan for testing,
   `starter` (paid, always-on) for the demo; and the `botforge-web` service of step 4). Fill the
   `sync: false` variables: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWKS_URL` (or
   `SUPABASE_JWT_SECRET`), `TOKEN_ENC_KEY`, `ANTHROPIC_API_KEY`, `LLM_MODEL_STRONG`, `LLM_MODEL_FAST`,
   `PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`. Check in the service settings that the Dockerfile path
   resolves to `backend/Dockerfile`. The container runs `alembic upgrade head` on every start. Deploy
   and confirm `https://<service>.onrender.com/healthz` returns `{"status":"ok"}`.
4. **Vercel.** Import the repository as a Next.js project; set **Root Directory** to `frontend` (no
   `vercel.json` is needed; build and output settings are the defaults). Environment variables:
   `NEXT_PUBLIC_MOCK=0`, `NEXT_PUBLIC_API_BASE_URL=https://<service>.onrender.com` (no trailing slash),
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Deploy.
   **Or Render** (the `botforge-web` service in `render.yaml`): a Node web service with root directory
   `frontend`, build `npm ci && npm run build`, start `npm start`, `NODE_VERSION=22` and the same four
   variables. The `NEXT_PUBLIC_*` values are inlined at build time, so changing one needs a new build.
   With `NEXT_PUBLIC_MOCK=0` and a Supabase variable missing, the app shows a configuration-error page.
5. **Close the loop.** Set on Render `PUBLIC_BASE_URL=https://<service>.onrender.com` (Telegram
   webhooks are registered under it, so it must be the public https address) and `FRONTEND_ORIGIN`
   to the web app's origins, comma-separated, e.g.
   `https://<your-app>.vercel.app,https://bot-forge.ir,https://www.bot-forge.ir`. CORS allows only
   these. Each entry is `scheme://host[:port]` without a path (a trailing slash is dropped); an entry
   that is not an http(s) origin, `*` included, is ignored with a warning in the log. Redeploy the
   backend. Preview deployments have other URLs and are rejected by CORS unless they are listed or
   match `FRONTEND_ORIGIN_REGEX`.
   - `FRONTEND_ORIGIN_REGEX` (optional, unset by default) allows every https origin it matches as a
     whole, e.g. for Netlify deploy previews `https://deploy-preview-[0-9]+--<site>\.netlify\.app`.
     Name your own site in it and escape the dots; a pattern that also matches other sites (`.*`,
     `https://.*\.netlify\.app`) is ignored with a warning. Risk: whoever can get a page served at a
     matching origin (a site with a matching name, or a deploy preview built from their pull request)
     can call the API from a browser. Sign-in is a Bearer token, not a cookie, so such a page cannot
     act as a signed-in user without that user's token: low impact, but leave the variable unset
     unless previews must reach this backend, and then do not build previews for pull requests
     from forks.
6. **Seed the demo** (after a bot with the workshop spec is active; see Gate B):
   point `DATABASE_URL` at Supabase in your shell, then
   `uv run python scripts/seed_demo.py --bot-id <bot id>`. `--reset` removes the seeded data.

## Self-hosting on a VPS (Docker Compose)

One server runs everything: Postgres, the backend (one container, one worker), the frontend and Caddy,
which terminates HTTPS on port 443 (Telegram webhooks need valid HTTPS there) and routes by path:
`/api/*` goes to the backend with the prefix stripped, `/tg/*` goes to the backend unchanged, everything
else goes to the frontend. Login is BotForge's own (email and password, a server-side session in the
HttpOnly `bf_session` cookie); no outside auth service is involved. Files: `deploy/docker-compose.yml`,
`deploy/Caddyfile`, `deploy/.env.example`, `deploy/backup.sh`, `deploy/restore.sh`, `backend/Dockerfile`,
`frontend/Dockerfile`.

### 1. Prepare the server

- Install Docker Engine with the compose plugin (<https://docs.docker.com/engine/install/>), then check
  `docker compose version`. Clone this repository on the server.
- Log in with an SSH key and turn password login off (`PasswordAuthentication no` in
  `/etc/ssh/sshd_config`, then `sudo systemctl reload ssh`).
- Open only SSH, HTTP and HTTPS:

  ```sh
  sudo ufw default deny incoming
  sudo ufw allow 22/tcp
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw allow 443/udp   # HTTP/3, optional
  sudo ufw enable
  ```

  Only Caddy publishes ports (80 and 443). Postgres, the backend and the frontend have no published
  ports and are reachable only on the internal Docker network. This matters because Docker writes its own
  firewall rules that bypass ufw for published ports, so never add a `ports:` entry to those services.
  Port 80 must stay open: Caddy uses it to obtain and renew the certificate.
- Memory: building Next.js wants about 2 GB of RAM. On a smaller server add swap
  (`sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`),
  or build the images on another machine and move them:
  `docker compose build` there, then
  `docker save botforge-backend botforge-frontend | ssh user@server docker load`, and on the server run
  `docker compose up -d --no-build`.

### 2. Pick the hostname

Until you have a domain, use a free sslip.io name made from the server's IP: replace the dots with dashes
and add `.sslip.io`. IP `203.0.113.7` becomes `203-0-113-7.sslip.io`. It resolves to that IP and Caddy
gets a real certificate for it. sslip.io is shared by many people, so Let's Encrypt may rate-limit it;
Caddy then falls back to ZeroSSL on its own. Do not reinstall the stack repeatedly: certificates live in
the `caddy_data` volume, and re-issuing them is what trips the limits.

### 3. Configure and start

```sh
cd deploy
cp .env.example .env && chmod 600 .env
# generate the two secrets and paste them into .env
openssl rand -hex 24                    # POSTGRES_PASSWORD
TOKEN_ENC_KEY=x docker compose run --rm --no-deps backend python -m app.security.crypto generate-key   # TOKEN_ENC_KEY
$EDITOR .env                            # SITE_HOST, ANTHROPIC_API_KEY and the rest; every variable is commented
docker compose up -d --build
```

Back up `TOKEN_ENC_KEY` separately: without it every stored Telegram bot token becomes unreadable. The
backend runs `alembic upgrade head` on every start, so the database schema is migrated automatically.
`NEXT_PUBLIC_*` values are inlined into the frontend at build time, so after changing one run
`docker compose up -d --build` again.

Check it (all from `deploy/`):

```sh
docker compose ps                                  # db, backend and frontend healthy, caddy running
curl https://$SITE_HOST/api/healthz                # {"status":"ok"} (replace $SITE_HOST with your name)
docker compose logs -f caddy                       # certificate issuance, if the site does not come up
```

### 4. Create the first user and (optionally) load the sample bot

Create your account from the command line (the script prompts for a password, see its `--help`):

```sh
docker compose exec backend python scripts/create_user.py --email you@example.com
```

`AUTH_ALLOW_SIGNUP=false` is recommended in production once your account exists: signup answers 409 for an
email that is already registered (so it reveals which emails have accounts), and a single-owner deployment
does not need open registration. Set it in `deploy/.env` and run `docker compose up -d`. (For the Gate E
rehearsal, which signs up a new account, leave signup on.) To load the golden workshop spec with its sample data as a bot of that user
(`examples/` is mounted read-only into the backend container at `/examples`):

```sh
docker compose exec backend python scripts/load_spec.py --spec /examples/workshop.botspec.json \
    --owner-email you@example.com --sample-data scripts/workshop.sample_data.json
```

### 5. Backups

`deploy/backup.sh` writes a gzipped custom-format `pg_dump` to `deploy/backups/` and keeps the newest 14;
it exits non-zero on failure. Nightly at 03:15 (`crontab -e`, adjust the path):

```
15 3 * * * /home/deploy/BotForge/deploy/backup.sh >> /home/deploy/botforge-backup.log 2>&1
```

Copy `deploy/backups/` off the server too (a dump on the same disk does not survive losing the server). The dump covers the database only: also copy the `uploads` volume (see Business OS settings and operator notes).
Restore with `docker compose stop backend`, then
`./restore.sh backups/<file>.dump.gz --yes-overwrite`, then `docker compose start backend`. Add
`--database scratch` to restore into a separate database instead and leave the live one untouched.

### 6. Changing the hostname later

Update `SITE_HOST` in `deploy/.env` (and point the new name's DNS A record at the server), then (in
polling mode only the `up -d` is needed):

```sh
docker compose up -d
docker compose exec backend python scripts/reregister_webhooks.py   # once: Telegram webhooks contain the old host
```

`up -d` recreates the backend with the new `PUBLIC_BASE_URL` and `FRONTEND_ORIGIN` and makes Caddy request a
certificate for the new name. The Telegram webhooks of connected bots still point at the old host until
`reregister_webhooks.py` has run.

The script keeps updates that Telegram queued while the old address was unreachable (it sends
`setWebhook` with `drop_pending_updates=False`), so customer messages sent during the move are delivered
afterwards. `connect` still drops pending updates.

### Telegram: webhook or polling

By default (`TELEGRAM_MODE=webhook`) Telegram delivers updates to `https://SITE_HOST/tg/<bot id>`, so
Telegram's servers must be able to reach the VPS over HTTPS. Where they cannot (likely on a server in
Iran, and on a developer machine), set `TELEGRAM_MODE=polling` in `deploy/.env` and run
`docker compose up -d`: the backend then fetches each connected bot's updates with `getUpdates`, using
outbound connections only (through `OUTBOUND_HTTPS_PROXY` if set), and handles them exactly as the
webhook would. Connecting a bot then registers no webhook, `SITE_HOST` serves only the site, and
`reregister_webhooks.py` has nothing to do. Polling needs exactly one backend process (never scale it).
After switching back from polling to webhook mode, run `reregister_webhooks.py` once so every connected
bot gets its webhook.

### Restricted networks (Iran)

When Docker Hub, ghcr.io, PyPI, npm, Telegram or the Anthropic API are blocked or slow, use these
optional settings. Everything below is empty by default and then changes nothing.

- **Base images (Docker Hub).** Set a registry mirror in `/etc/docker/daemon.json` and restart Docker:

  ```json
  { "registry-mirrors": ["https://docker.arvancloud.ir"] }
  ```

  `sudo systemctl restart docker`. A registry mirror covers Docker Hub only (`python`, `node`,
  `postgres`, `caddy`), not ghcr.io. That is why the backend image installs `uv` from PyPI instead of
  copying it from `ghcr.io/astral-sh/uv`. If a mirror does not have an image, pull it elsewhere and move it
  with `docker save | ssh ... docker load`.
- **Proxy for downloads and outbound calls.** In `deploy/.env`: `BUILD_PROXY` is used only while building
  (pip, npm, uv downloads). `OUTBOUND_HTTP_PROXY` / `OUTBOUND_HTTPS_PROXY` (and extra bypass hosts in
  `OUTBOUND_NO_PROXY`) become `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` inside the backend and Caddy
  containers: Telegram API calls and the LLM call go through it, and so does Caddy's certificate
  request to Let's Encrypt or ZeroSSL, which may be blocked too. `db`, `backend`, `frontend`, `localhost`
  and `127.0.0.1` always bypass it. A proxy running on the server itself is reachable as
  `http://host.docker.internal:<port>` (compose maps that name to the host; the proxy must listen on
  an address the containers can reach, not only on 127.0.0.1).
- **Package mirrors.** `PIP_INDEX_URL` (a PyPI mirror, used by pip and uv for the backend build) and
  `NPM_CONFIG_REGISTRY` (an npm mirror for the frontend build). Pass them and the proxy to a build with
  `docker compose build` / `up -d --build`.
- **LLM through a mirror.** `ANTHROPIC_BASE_URL` points the backend at an Anthropic-compatible service,
  and `ANTHROPIC_API_KEY` is then that service's key. **Warning:** a third-party LLM mirror sees every
  prompt, including the owners' chat text and the bots' data, and may not support every API feature the
  agent uses: structured output through `output_config`, adaptive thinking and effort, and the
  server-side fallback beta. Before relying on it, run inside the container
  `docker compose exec backend python scripts/spike_structured_output.py` and
  `docker compose exec backend python scripts/eval_golden.py --create --runs 1 --provider anthropic`
  and check that both pass.

**Local rehearsal.** To try the whole stack on a developer machine behind a proxy (Caddy serves
`https://localhost` with its own CA; use `curl -k`): `cd deploy && cp .env.local.example .env.local`, fill it
in (`claude setup-token` gives the `CLAUDE_CODE_OAUTH_TOKEN`), then `./local.sh up`, `./local.sh logs`,
`./local.sh psql`, `./local.sh backup`, `./local.sh down -v`. It uses `docker-compose.local.yml`, which
assumes a proxy on the host at port 10808 and publishes Postgres on 127.0.0.1:55432. Never use it on the
VPS. It runs Telegram in polling mode, so real Telegram works with no tunnel. The step-by-step
checklist is `deploy/LOCAL-REHEARSAL.md`.

### Client IPs and rate limits

The backend rate-limits by client IP. Caddy has a fixed address on the compose network (`CADDY_IP`, in the
`CADDY_SUBNET` /24, default `10.250.77.10` in `10.250.77.0/24`), and the backend gets
`FORWARDED_ALLOW_IPS=<that address>`, so uvicorn takes the client IP from `X-Forwarded-For` only when Caddy
sent the request. The backend port is not published, so nothing else can reach it. Override both values in
`deploy/.env` only if the subnet collides with a network on your server.

### Updating

`git pull`, then `docker compose up -d --build` from `deploy/`. Keep `docker compose` runs on the one
backend container; do not scale it.

### Fallback

The Render and Vercel checklist below is now the fallback deployment. It is unchanged.

## Deployment checklist (fallback: Render and Vercel)

Architecture: the frontend (Vercel) and the backend (one always-on Render container) with an external
Postgres (`DATABASE_URL`: Render Postgres or any managed Postgres). Accounts are the backend's own
(`users` and `auth_sessions` tables, the HttpOnly `bf_session` cookie, `SameSite=Lax`). The cookie is
same-origin only, so the browser must reach the backend under the frontend's own origin: the frontend
host has to proxy `/api/*` to the backend with the prefix stripped (as Caddy does in the VPS stack).
This split-host setup has not been built or tested; the VPS stack above is the supported path. The
backend must run as a single instance with a single worker (agent runs and rate limits are in-process).

1. **Database.** Create a Postgres database and copy its connection string (`DATABASE_URL`). Use a direct
   or session-pooler connection, not a transaction pooler (port 6543): asyncpg's prepared statements do
   not work through it.
2. **Generate `TOKEN_ENC_KEY`** (encrypts Telegram bot tokens; losing it orphans stored tokens):
   `uv run python -m app.security.crypto generate-key` in `backend/`. Keep a copy in a password manager.
3. **Render.** New, Blueprint, pick this repository; it reads `render.yaml` (one Docker web service,
   root directory `backend`, health check `/healthz`, paid always-on plan, auto-deploy off). Fill the
   `sync: false` variables: `DATABASE_URL`, `TOKEN_ENC_KEY`, `ANTHROPIC_API_KEY`, `LLM_MODEL_STRONG`,
   `LLM_MODEL_FAST`, `PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`. Check in the service settings that the
   Dockerfile path resolves to `backend/Dockerfile`. The container runs `alembic upgrade head` on every
   start. Deploy and confirm `https://<service>.onrender.com/healthz` returns `{"status":"ok"}`.
   Create your account with `python scripts/create_user.py --email ...` from a Render shell, then
   consider `AUTH_ALLOW_SIGNUP=false`.
4. **Vercel.** Import the repository as a Next.js project; set **Root Directory** to `frontend`.
   Environment variables: `NEXT_PUBLIC_MOCK=0` and `NEXT_PUBLIC_API_BASE_URL=/api`, plus a rewrite of
   `/api/:path*` to `https://<service>.onrender.com/:path*` so the cookie stays same-origin. Deploy.
5. **Close the loop.** Set on Render `PUBLIC_BASE_URL=https://<service>.onrender.com` (Telegram
   webhooks are registered under it, so it must be the public https address) and
   `FRONTEND_ORIGIN=https://<your-app>.vercel.app` (no trailing slash; CORS allows only the listed origins).
   `FRONTEND_ORIGIN` accepts several origins separated by commas. Redeploy the backend.
6. **Seed the demo** (after a bot with the workshop spec is active; see Gate B): in a Render shell,
   `python scripts/seed_demo.py --bot-id <bot id>`. `--reset` removes the seeded data.

## Manual gates

Gate definitions are in `IMPLEMENTATION_ROADMAP.md`, Milestone Gates. Both need the real deployment.

**Gate B: the golden spec serves a real Telegram bot.**
1. Sign up in the deployed web app (or create the account with `scripts/create_user.py`) and create a bot. Note the account email and the bot id (the URL).
2. On the VPS, from `deploy/`: `docker compose exec backend python scripts/load_spec.py --spec /examples/workshop.botspec.json --owner-email <account email> --bot-id <bot id> --sample-data scripts/workshop.sample_data.json`.
3. Create a bot in BotFather, paste its token in the bot's Settings tab; the bot goes live.
4. Add two workshops in the Data tab (or run `seed_demo.py`).
5. With two Telegram accounts: browse, book, fill the capacity, join the waitlist, cancel one booking
   and check the waitlisted account is promoted and notified.
6. `uv run pytest tests/golden tests/integration/test_golden_pg.py -q` passes (scenarios on `PgStore`).

**Gate E: a new account completes golden path steps 1-10 in the deployed UI only.**
Use a clean browser profile and a new email. Follow "Demo Golden Path" in the roadmap: sign up, create a
bot, paste the golden prompt (`examples/prompts.fa.md`), answer the agent's questions, watch the tests go
green, try the draft in the Simulator with two personas, approve, add two workshops, connect Telegram,
book and cancel in Telegram, add a workshop while live, then make both golden modifications
(capacity 12; cancellation up to 2 hours before start) and check the Versions tab shows three
revisions. Do not use scripts or the database during this run.

## Notes

- `render.yaml` and `backend/Dockerfile` have not been built or deployed from this repository's
  development machine (no Docker there); the first Render deploy is the real test.
- Secrets live only in environment variables; `.env` is git-ignored.
