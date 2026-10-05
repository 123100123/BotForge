# BotForge

BotForge lets a small-business owner describe a business in Persian and get a working Telegram bot.
An AI agent turns the conversation into a validated BotSpec (data, not code); a deterministic runtime
executes it. The owner tests the bot in a web simulator, approves each version, edits live data in a
dashboard, and asks for changes in plain language. Every change is a reviewable, reversible revision.

The V1 demo scenario is a workshop-registration bot (capacity, waitlist with automatic promotion,
cancellation). `IMPLEMENTATION_ROADMAP.md` is the source of truth for scope, architecture and decisions;
this README only covers running and deploying the project.

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI app: `api/` routes, `agent/` (LLM orchestration), `botspec/` (contracts), `runtime/` (bot engines, `PgStore`), `integrations/telegram/`, `simulator/`, `revisions/`, `testing/`, `security/`, `db/` |
| `backend/alembic/` | Database migrations (schema `app`) |
| `backend/scripts/` | Operator and dev tools: `create_user.py`, `load_spec.py`, `seed_demo.py`, `dev_db.py`, `smoke_local.py`, `eval_golden.py` |
| `backend/tests/` | `unit/`, `golden/`, `integration/` (needs Postgres) |
| `backend/Dockerfile` | Production image (one container, one worker) |
| `frontend/` | Next.js web app (Persian, RTL) |
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
uv run pytest -q              # starts a temporary Postgres itself; about 1050 tests, a few minutes
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

Copy `deploy/backups/` off the server too (a dump on the same disk does not survive losing the server).
Restore with `docker compose stop backend`, then
`./restore.sh backups/<file>.dump.gz --yes-overwrite`, then `docker compose start backend`. Add
`--database scratch` to restore into a separate database instead and leave the live one untouched.

### 6. Changing the hostname later

Update `SITE_HOST` in `deploy/.env` (and point the new name's DNS A record at the server), then:

```sh
docker compose up -d
docker compose exec backend python scripts/reregister_webhooks.py   # once: Telegram webhooks contain the old host
```

`up -d` recreates the backend with the new `PUBLIC_BASE_URL` and `FRONTEND_ORIGIN` and makes Caddy request a
certificate for the new name. The Telegram webhooks of connected bots still point at the old host until
`reregister_webhooks.py` has run.

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
VPS.

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
