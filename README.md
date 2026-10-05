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
| `backend/scripts/` | Operator and dev tools: `load_spec.py`, `seed_demo.py`, `dev_db.py`, `dev_token.py`, `smoke_local.py`, `eval_golden.py` |
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
$env:SUPABASE_JWT_SECRET = 'local-dev-secret-at-least-32-characters-long'   # any 32+ chars, local only
$env:TOKEN_ENC_KEY = (uv run python -m app.security.crypto generate-key)
$env:PUBLIC_BASE_URL = 'http://localhost:8000'
$env:FRONTEND_ORIGIN = 'http://localhost:3000'
```

`ANTHROPIC_API_KEY`, `LLM_MODEL_STRONG` and `LLM_MODEL_FAST` are needed only for agent runs. With
`SUPABASE_JWKS_URL` unset the backend verifies HS256 tokens signed with `SUPABASE_JWT_SECRET`.

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
# in another shell, with the same SUPABASE_JWT_SECRET:
uv run python scripts/dev_token.py          # prints a user id and a development-only token
curl.exe -H "Authorization: Bearer <token>" http://localhost:8000/me
```

Load the golden spec into a bot for that user and seed the demo data:

```powershell
curl.exe -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{\"name\":\"Demo\"}' http://localhost:8000/bots
uv run python scripts/load_spec.py --spec ../examples/workshop.botspec.json --owner-id <user id> --bot-id <bot id> --sample-data scripts/workshop.sample_data.json
uv run python scripts/seed_demo.py --bot-id <bot id>            # --reset removes it again
```

### Smoke test of the whole HTTP stack

```powershell
uv run python scripts/dev_db.py start
$env:DATABASE_URL = '<printed url>'
uv run python scripts/smoke_local.py --local-defaults
uv run python scripts/dev_db.py stop
```

It needs no LLM, no Telegram and no Supabase: it mints its own tokens, drives the real ASGI app
in-process (no port is opened; Telegram is the in-memory fake client) and prints PASS or FAIL per
step (exit code 1 on any failure). It creates and deletes its own bot, and refuses a non-local
`DATABASE_URL` unless `--allow-remote` is given. If `DATABASE_URL` is unset it uses the running dev
database. `--local-defaults` fills in unset `SUPABASE_JWT_SECRET`, `TOKEN_ENC_KEY`, `PUBLIC_BASE_URL`
and `FRONTEND_ORIGIN`; `SUPABASE_JWKS_URL` must be unset.

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev                  # http://localhost:3000
```

With `NEXT_PUBLIC_MOCK=1` (the default, also used whenever the Supabase variables are empty) the web
app runs entirely on fixtures: fake sign-in and a scripted agent stream, no backend needed. Real mode
(`NEXT_PUBLIC_MOCK=0`) needs a Supabase project, because sign-in goes through Supabase Auth.

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

Then set `AUTH_ALLOW_SIGNUP=false` in `deploy/.env` and run `docker compose up -d` if you do not want
strangers registering. To load the golden workshop spec with its sample data as a bot of that user
(`examples/` is mounted read-only into the backend container at `/examples`):

```sh
docker compose exec backend python scripts/load_spec.py --spec /examples/workshop.botspec.json \
    --owner-id <user id> --sample-data scripts/workshop.sample_data.json
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

### Updating

`git pull`, then `docker compose up -d --build` from `deploy/`. Keep `docker compose` runs on the one
backend container; do not scale it.

### Fallback

The Render and Vercel checklist below is now the fallback deployment. It is unchanged.

## Deployment checklist (fallback: Render and Vercel)

Architecture: the frontend (Vercel) calls the backend (one always-on Render container) with a Supabase
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
     IPv4 hosts such as Render). Replace the password placeholder. Do not use the transaction pooler
     (port 6543): asyncpg's prepared statements do not work through it. This is `DATABASE_URL`.
2. **Generate `TOKEN_ENC_KEY`** (encrypts Telegram bot tokens; losing it orphans stored tokens):
   `uv run python -m app.security.crypto generate-key` in `backend/`. Keep a copy in a password manager.
3. **Render.** New, Blueprint, pick this repository; it reads `render.yaml` (one Docker web service,
   root directory `backend`, health check `/healthz`, paid always-on plan, auto-deploy off). Fill the
   `sync: false` variables: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWKS_URL` (or
   `SUPABASE_JWT_SECRET`), `TOKEN_ENC_KEY`, `ANTHROPIC_API_KEY`, `LLM_MODEL_STRONG`, `LLM_MODEL_FAST`,
   `PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`. Check in the service settings that the Dockerfile path
   resolves to `backend/Dockerfile`. The container runs `alembic upgrade head` on every start. Deploy
   and confirm `https://<service>.onrender.com/healthz` returns `{"status":"ok"}`.
4. **Vercel.** Import the repository as a Next.js project; set **Root Directory** to `frontend` (no
   `vercel.json` is needed; build and output settings are the defaults). Environment variables:
   `NEXT_PUBLIC_MOCK=0`, `NEXT_PUBLIC_API_BASE_URL=https://<service>.onrender.com` (no trailing slash),
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Deploy.
5. **Close the loop.** Set on Render `PUBLIC_BASE_URL=https://<service>.onrender.com` (Telegram
   webhooks are registered under it, so it must be the public https address) and
   `FRONTEND_ORIGIN=https://<your-app>.vercel.app` (no trailing slash; CORS allows only the listed origins).
   `FRONTEND_ORIGIN` accepts several origins separated by commas, for example
   `https://<your-app>.vercel.app,https://<your-app>-git-<branch>-<team>.vercel.app`; add a preview
   deployment's URL there to let it call the backend. Redeploy the backend. Origins not listed are rejected by CORS.
6. **Seed the demo** (after a bot with the workshop spec is active; see Gate B):
   point `DATABASE_URL` at Supabase in your shell, then
   `uv run python scripts/seed_demo.py --bot-id <bot id>`. `--reset` removes the seeded data.

## Manual gates

Gate definitions are in `IMPLEMENTATION_ROADMAP.md`, Milestone Gates. Both need the real deployment.

**Gate B: the golden spec serves a real Telegram bot.**
1. Sign up in the deployed web app and create a bot. Note your user id (`sub`) and the bot id (the URL).
2. `uv run python scripts/load_spec.py --spec ../examples/workshop.botspec.json --owner-id <user id> --bot-id <bot id> --sample-data scripts/workshop.sample_data.json` with `DATABASE_URL` pointing at Supabase.
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
