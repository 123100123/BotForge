# Local rehearsal checklist

Prove everything on your own machine before you move to the VPS. Tick each box as you go. If a step
does not show what it says it should, stop there and fix it first: every later stage builds on the
earlier ones.

What this rehearsal proves: the Docker stack, login, the agent building a bot, the Simulator, real
Telegram (in polling mode: the backend fetches updates, so no tunnel and no public address are
needed), backup and restore, and restarts. What it cannot prove: the Iranian network, the Iranian LLM
mirror, the real certificate on the sslip.io name, and webhook mode (Telegram cannot reach this
machine, so the hostname switch of Stage 3b is skipped). Those are in "What changes for the VPS" at
the end.

Conventions:

- "From `deploy/`" means `cd` to the `deploy/` folder of this repository first. Every `./local.sh`
  command runs from there.
- `./local.sh` is a thin wrapper around `docker compose` that always uses `docker-compose.yml`,
  `docker-compose.local.yml` and `.env.local`. Use it instead of typing `docker compose` yourself.
- Persian text is meant to be copied exactly. Copy it from this file; do not retype it.
- When something fails, the first thing to look at is `./local.sh logs backend` (press Ctrl-C to stop
  following the log).

---

## Stage 0: Prerequisites

### 0.1 Docker works

- [ ] Run `docker compose version`. You should see a version number, not an error.
- [ ] Your proxy listens on the host at port 10808 (the local setup assumes `host.docker.internal:10808`)
  and accepts connections from containers, not only from `127.0.0.1`. If you are not behind a proxy,
  see "If you are not behind a proxy" at the end of this file.

### 0.2 The backend environment has the Claude CLI

The rehearsal runs the agent through your Claude login instead of an API key, so it needs a long-lived
token made by the Claude CLI that ships inside the backend's Python environment.

- [ ] From `backend/`, run `uv sync --group dbtest --group headless`. It ends without an error.
- [ ] Check the CLI is there:
  `ls .venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude`
  The path prints back (no "No such file").

### 0.3 Create `deploy/.env.local`

- [ ] From `deploy/`: `cp .env.local.example .env.local`. Git ignores this file; never commit it.
- [ ] Make the Claude token. From `backend/`:

  ```sh
  .venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude setup-token
  ```

  Follow what it prints (it may open a browser to log in to Claude). At the end it prints a long token.
  Paste it into `deploy/.env.local` as `CLAUDE_CODE_OAUTH_TOKEN=...` (no quotes, no spaces).
- [ ] Make the encryption key. From `backend/`:

  ```sh
  uv run python -m app.security.crypto generate-key
  ```

  Paste the output into `deploy/.env.local` as `TOKEN_ENC_KEY=...`. Keep a copy somewhere safe: the bot
  tokens stored in the database can only be read with this key, and Stage 4 (restore) needs the same key.
- [ ] Leave the other lines as they are (`SITE_HOST=localhost`, the Postgres values,
  `AUTH_COOKIE_SECURE=true`).
- [ ] From `deploy/`, check the file is complete: `./local.sh config > /dev/null && echo OK`.
  You should see `OK`. An error such as `set TOKEN_ENC_KEY in deploy/.env` means a value is missing.

### 0.4 Telegram

- [ ] Create two test bots with `@BotFather` in Telegram: send `/newbot`, choose a name and a username
  ending in `bot`. BotFather replies with a token like `123456789:AA...`. Save both tokens somewhere
  private. Bot A is for the workshop bot (Stages 2 to 4). Bot B is only for Stage 5.
- [ ] Have two Telegram accounts you can use at the same time (two phones, or a phone plus Telegram
  Desktop or web). Account 1 plays the owner, account 2 plays a customer.
- No tunnel tool is needed: the local stack runs in Telegram polling mode (`TELEGRAM_MODE=polling` in
  `docker-compose.local.yml`), so the backend only makes outbound calls to Telegram, through your proxy.

---

## Stage 1: Bring the stack up

- [ ] From `deploy/`: `./local.sh up`. The first run builds the backend and frontend images and takes
  several minutes (the frontend build is the slow part). It ends with lines like `Container
  botforge-caddy-1  Started`. No red errors.
- [ ] Run `./local.sh ps`. You should see `db`, `backend` and `frontend` as `healthy` (or `running`) and
  `caddy` as `running`. If `backend` keeps restarting, run `./local.sh logs backend`.
- [ ] Check the API: `curl -k https://localhost/api/healthz`. You should see `{"status":"ok"}`.
  (`-k` is needed because Caddy signs `localhost` with its own local certificate authority.)
- [ ] Open `https://localhost` in your browser. It shows a certificate warning. Either click
  "Advanced", then "Proceed to localhost", or trust the certificate once (optional):

  ```sh
  docker cp botforge-caddy-1:/data/caddy/pki/authorities/local/root.crt ./caddy-local-root.crt
  ```

  and import `caddy-local-root.crt` into your browser's certificate authorities. After the page loads you
  see the BotForge login page (ورود به بات‌فورج).
- [ ] Create the owner account from the command line. It asks you for a password twice (at least 10
  characters):

  ```sh
  ./local.sh exec backend python scripts/create_user.py --email owner@example.com
  ```

  You should see `created owner@example.com (<id>)`.
- [ ] Log in at `https://localhost/login` with that email and password. You land on the bot list
  (ربات‌های من), empty. Log out again.
- [ ] Optional, to see a ready-made bot: load the sample workshop bot into the owner account:

  ```sh
  ./local.sh exec backend python scripts/load_spec.py --spec /examples/workshop.botspec.json \
      --owner-email owner@example.com --sample-data scripts/workshop.sample_data.json
  ```

  Log in as the owner: the bot list now shows one bot. Remember this for Stage 2: a different account
  must NOT see it.

---

## Stage 2: The golden path in the browser (the Gate E rehearsal)

This is steps 1 to 5 and 7 to 10 of the roadmap's Demo Golden Path. The Telegram parts use the
Simulator (شبیه‌ساز) tab instead of a phone; the real Telegram check is Stage 3. Use a private
browser window so you are not logged in as the owner.

The six tabs of a bot are: Agent (ایجنت), Simulator (شبیه‌ساز), Tests (تست‌ها), Data (داده‌ها),
Versions (نسخه‌ها), Settings (تنظیمات).

### Step 1: Sign up as a new account and create a bot

- [ ] Open `https://localhost/signup`, enter a NEW email (for example `demo@example.com`) and a password
  of at least 10 characters, and press ثبت‌نام. You land on the bot list. It is empty. If you did the
  optional `load_spec` step, this proves a second account cannot see the owner's bot.
- [ ] Press ربات جدید (or ساخت اولین ربات), give the bot a name, and open it. You see the Agent tab with
  an empty chat.
- [ ] Paste this golden prompt into the Agent tab and send it (the button «استفاده از پیام نمونه» may
  also fill it in; compare it with this text):

  ```
  من یک آموزشگاه دارم و کارگاه‌های آموزشی برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام لیست کارگاه‌ها را ببینند و ثبت‌نام کنند. ظرفیت هر کارگاه ۱۰ نفر است. اگر ظرفیت پر شد وارد لیست انتظار شوند و اگر کسی انصراف داد، نفر اول لیست انتظار خودکار جایگزین شود. امکان لغو ثبت‌نام هم باشد.
  ```

### Step 2: Requirements and questions

- [ ] **Agent tab:** a requirements card appears, listing what the agent understood (capacity 10 per
  workshop, waiting list, automatic promotion, cancellation) and its assumptions.
- [ ] The agent asks at most one or two blocking questions in a questions card. Answer them in Persian
  (any sensible answer) and press ارسال پاسخ‌ها.

### Step 3: The build and the tests

- [ ] **Agent tab:** the activity timeline moves through understanding, building, validating, generating
  tests, running tests, ending with everything green. A run takes about one to three minutes.
- [ ] **Tests tab:** a list of scenarios written as Persian stories, for example capacity 2; Ali and
  Sara confirmed; Reza waitlisted; Ali cancels; Reza promoted. All are green (passed).
- [ ] The Agent tab shows a review card (بازبینی ربات) with the result line "N of N tests passed".

### Step 4: Try the draft in the Simulator

- [ ] **Simulator tab:** a phone frame with persona buttons for three customers (علی، سارا، رضا) and the
  owner. As Ali, send `/start`. You see the bot's welcome and a way to browse the workshops. Reserve a
  place; open "my reservations" and see it; cancel it. Switch to Sara and Reza and do the same.
  Messages for another persona show a badge on that persona's button. (What the list contains depends on
  the sample data the agent generated. The Simulator uses sandbox data, never your live data.)

### Step 5: Approve, add data (skip the token for now)

- [ ] **Agent tab:** press تأیید و فعال‌سازی on the review card. The badge says تأیید شد. The bot now has
  an active revision.
- [ ] **Data tab:** press the add button (افزودن ...) and create two workshops with a title, and a start
  date and time in the picker. Both appear in the table. (Do not put a workshop that starts within two
  hours yet; that is a Stage 3 test.)
- [ ] **Settings tab:** it shows the Telegram connection as not connected (وصل نیست). Do not connect
  yet. That is Stage 3 (step 5's token and step 6).

### Step 7: Live data changes

- [ ] **Data tab:** add a third workshop, edit its title, then delete it. The table updates each time. (The
  real "it appears in Telegram at once" check is in Stage 3.)

### Step 8: Modification 1

- [ ] **Agent tab:** send exactly this:

  ```
  ظرفیت هر کارگاه را ۱۲ نفر کن.
  ```

- [ ] A new review card (بازبینی تغییر) appears. The changes list shows capacity going from 10 to 12 and
  the affected capability. Tests are shown as carried over (منتقل‌شده) and new (جدید). The risk is
  low. All tests pass.
- [ ] Press تأیید و فعال‌سازی.

### Step 9: Modification 2

- [ ] **Agent tab:** send exactly this:

  ```
  لغو ثبت‌نام فقط تا ۲ ساعت قبل از شروع کارگاه ممکن باشد.
  ```

- [ ] The review card shows a new cancellation deadline of two hours. **Tests tab** has a new scenario
  about cancelling too late (it uses simulated time) and the old scenarios still pass.
- [ ] Press تأیید و فعال‌سازی.

### Step 10: Versions

- [ ] **Versions tab:** three revisions: the first build, capacity 12, and the cancellation deadline.
  The newest is marked active.

### Isolation check

- [ ] Log in as `owner@example.com` in another browser profile. This account does not see the bot you
  just built. (If you skipped `load_spec` it sees an empty list.)

---

## Stage 3: Real Telegram (polling mode)

Telegram cannot reach your machine (inbound connections from Telegram are blocked, and so are tunnels
such as cloudflared and ngrok). Polling mode is on in the local override (`TELEGRAM_MODE=polling` in
`docker-compose.local.yml`): the backend asks Telegram for new messages itself, using only outbound
connections through your proxy. There is no tunnel and no address to configure: just connect the bot in
Settings. Your browser keeps using `https://localhost`.

### 3.1 Check that polling mode is on

- [ ] From `deploy/`: `./local.sh exec backend printenv TELEGRAM_MODE` prints `polling`.

### 3.2 Connect bot A

- [ ] In the browser, open your bot, then **Settings tab**, and paste bot A's BotFather token into the
  token box (توکن ربات), then press اتصال. The status changes to وصل است and shows the bot's username
  and link. If you see an error saying Telegram is unreachable, the backend cannot reach Telegram
  through the proxy.
- [ ] Within about 10 seconds the backend starts polling bot A; 3.3 below shows it answering. If it
  does not answer, `./local.sh logs backend` shows why, for example
  `bot <id>: getUpdates failed (network error (ConnectError)); retrying in 4.0s` when the proxy is
  down. The log never shows the bot token.
- [ ] The owner link box (دریافت اعلان‌ها در تلگرام) now shows a link. On the OWNER phone (account 1)
  press باز کردن در تلگرام, or open the link, and press Start in Telegram. The bot greets you as the
  owner. In the browser press بررسی وضعیت: it says متصل شد. The link works once only.

### 3.3 Customer and owner behaviour

On the CUSTOMER phone (account 2), open bot A and send `/start`.

- [ ] **Browse:** the bot lists the workshops you added in the Data tab.
- [ ] **Book:** reserve a place in one workshop. The bot confirms.
- [ ] **My reservations:** it shows that booking.
- [ ] **Cancel:** cancel it. The bot confirms, and the reservation is gone from the list. (This works
  because the workshop starts more than two hours from now.)
- [ ] **Owner alerts:** on the owner phone you receive a message when the customer books or cancels.
  Which notifications exist depends on the generated spec; the owner can also use the owner view of the
  bot. If you see none, check the Tests tab for scenarios that mention the owner.
- [ ] **Data tab live update (step 7):** in the browser Data tab add a new workshop. On the customer
  phone browse again: it appears at once, with no restart.
- [ ] **Modification 2 on a real phone:** in the Data tab add a workshop that starts in about one hour
  (use the Jalali date-time picker: today's date, one hour ahead). On the customer phone reserve it,
  then try to cancel. The bot REFUSES the cancellation (it is within two hours). Then cancel a booking for
  a workshop that starts days away: that works.
- [ ] **Data tab shows bookings:** the bookings made on Telegram appear in the Data tab.

---

## Stage 3b: Hostname switch (webhook mode only; skipped locally)

Moving webhooks to a new host name (`scripts/reregister_webhooks.py`) only applies in webhook mode, which
cannot run on this machine because Telegram cannot reach it. In polling mode the host name plays no part
for Telegram, and the script says `nothing to re-register` and changes nothing. If the VPS runs in
webhook mode, the procedure is in the README ("Changing the hostname later").

What polling mode should do instead, and you can check here:

- [ ] Messages sent while the backend is down are answered when it is back. From `deploy/`:
  `./local.sh stop backend`; on the customer phone send bot A `/start` and a browse request (no answer);
  `./local.sh start backend`. Within a few seconds the customer phone receives both answers, once each
  and in order. The owner is still linked (Settings still says متصل شد).

---

## Stage 4: Operations

Run these with the stack up and some data in it (the bot from Stage 2 and 3, with a few bookings).

### 4.1 Backup, wipe, restore

- [ ] From `deploy/`: `./local.sh backup`. It prints `backup written: .../backups/botforge-<time>.dump.gz`
  with a size. Note the file name.
- [ ] Wipe the database on purpose:

  ```sh
  ./local.sh down
  docker volume rm botforge_pgdata
  ./local.sh up
  ```

  The stack starts with an empty database. Log in at `https://localhost/login` with your demo account: it
  is refused, because the account no longer exists. (The Caddy certificate volume is kept, so the browser
  warning does not come back.)
- [ ] Restore. Use your own file name:

  ```sh
  ./local.sh stop backend
  ./local.sh restore backups/botforge-<time>.dump.gz --yes-overwrite
  ./local.sh start backend
  ```

  The restore ends with `restore finished`.
- [ ] The data is back: log in with the demo account, the bot is there with its three revisions, the Data
  tab shows your workshops and bookings, Settings shows the Telegram connection, and bot A answers on the
  customer phone (the restore also brought back its polling position). That the stored bot
  token still works proves your `TOKEN_ENC_KEY` was the same.

### 4.2 Restart in the middle of an agent run

- [ ] In the browser, create a second bot and send it the golden prompt (Stage 2, step 1). When the
  activity timeline shows it is working (for example "building"), immediately run:

  ```sh
  ./local.sh restart backend
  ```

- [ ] After the backend is back (10 to 30 seconds), the run shows as interrupted (قطع شد) and the live
  event stream closes; reload the page if the browser was still reconnecting. The run does not stay
  "running" forever, and no half-built revision is active. Your first bot is untouched.

### 4.3 Full down and up

- [ ] `./local.sh down`, then `./local.sh up`. (Plain `down`, without `-v`: it keeps the volumes.)
- [ ] Everything comes back: you are still logged in or can log in, the bots and revisions are there,
  the Data tab has its records, and bot A answers on Telegram.

---

## Stage 5 (optional): The repair-request bot

This is step 11 of the golden path: a second bot from a different prompt, where the owner approves a
request from a Telegram alert. The roadmap does not fix the exact prompt, so this one is a suggestion;
the repair spec in `examples/repair.botspec.json` shows what is expected.

- [ ] In the browser create a new bot and send:

  ```
  من خدمات تعمیر لوازم خانگی انجام می‌دهم. می‌خواهم مشتری‌ها در ربات تلگرام درخواست تعمیر ثبت کنند و نوع دستگاه و توضیح مشکل را بنویسند. من هر درخواست را در تلگرام ببینم و تأیید یا رد کنم. مشتری وضعیت درخواستش را ببیند.
  ```

  Answer any questions, check Tests are green, press تأیید و فعال‌سازی.
- [ ] Connect it to bot B in the Settings tab (polled like bot A in Stage 3) and link the owner phone.
- [ ] On the customer phone, send bot B a repair request. The owner phone receives an alert with
  approve and reject buttons. Tap approve: the customer is told the request was approved, and the status
  in the Data tab changes.

---

## Exit criteria

You are ready to move to the VPS when ALL of these are ticked:

- [ ] Stage 1: the stack builds, health check answers, owner account created from the command line.
- [ ] Stage 2: the golden path (steps 1 to 5, 7 to 10) ran end to end as a new account, with three
  revisions and green tests.
- [ ] Stage 3: bot A worked on real Telegram on two accounts, including the two-hour cancellation refusal
  and the live Data tab update.
- [ ] Stage 3b (polling check): messages sent while the backend was down were answered once each after
  it came back, and the owner stayed linked.
- [ ] Stage 4: backup, wipe and restore got everything back; a restart interrupted the agent run
  cleanly; full down and up lost nothing.
- [ ] You have a copy of `TOKEN_ENC_KEY` that is not on this machine only.

## What changes for the VPS

Do not copy `.env.local`, `docker-compose.local.yml` or `local.sh` to the server. On the server you use
`deploy/.env` (copy `.env.example`) and plain `docker compose` from `deploy/`.

- `SITE_HOST` is the sslip.io name made from the server's IP, for example `203-0-113-7.sslip.io`
  (dots to dashes). `PUBLIC_BASE_URL` and `FRONTEND_ORIGIN` follow from it automatically; there is no
  override. Ports 80 and 443 must be reachable from the internet so Caddy can get the certificate.
- `TELEGRAM_MODE` in `deploy/.env`: `webhook` (the default) only if Telegram's servers can reach the VPS
  over https; on a VPS in Iran that is unlikely, so set `TELEGRAM_MODE=polling`, as in this rehearsal.
  The site's host name is then not used by Telegram at all.
- `LLM_PROVIDER=anthropic`, with `ANTHROPIC_API_KEY` set to the mirror's key and `ANTHROPIC_BASE_URL`
  set to the Iranian mirror's address. This path was NOT exercised here (the rehearsal used your Claude
  login). Before relying on the mirror, run both of these on the server and check they pass:

  ```sh
  docker compose exec backend python scripts/spike_structured_output.py
  docker compose exec backend python scripts/eval_golden.py --create --runs 1 --provider anthropic
  ```

  The mirror may not support structured output, adaptive thinking or effort, or the server-side
  fallback beta, and it sees every prompt.
- No local override: no `docker-compose.local.yml`, no `CLAUDE_CODE_OAUTH_TOKEN`, no `UV_EXTRA_GROUPS`
  and no published Postgres port.
- The Docker registry mirror in `/etc/docker/daemon.json` on the server (for example
  `{ "registry-mirrors": ["https://docker.arvancloud.ir"] }`), then `sudo systemctl restart docker`.
- The proxy and mirror variables in `deploy/.env`, as needed: `OUTBOUND_HTTP_PROXY` and
  `OUTBOUND_HTTPS_PROXY` (Telegram, the LLM, and Caddy's certificate requests), `OUTBOUND_NO_PROXY`,
  `BUILD_PROXY`, `PIP_INDEX_URL`, `NPM_CONFIG_REGISTRY`. The README section "Restricted networks (Iran)"
  explains each.
- `AUTH_COOKIE_SECURE=true` stays on (the site is https). Set `AUTH_ALLOW_SIGNUP=false` after your own
  account exists.
- After the first start: create your account with `create_user.py`, connect your real bot, and run
  `backup.sh` once to prove it works on the server. When the hostname later changes: change `SITE_HOST`
  and run `docker compose up -d`; in webhook mode only, then run `reregister_webhooks.py --dry-run` and
  the real run (README, "Changing the hostname later").

## If you are not behind a proxy

`docker-compose.local.yml` points downloads and outbound calls at `host.docker.internal:10808`. On a
machine without a proxy at that address, the build and the backend's calls to Telegram fail. Edit the
four proxy lines in `docker-compose.local.yml` (the `http_proxy`, `https_proxy`, `HTTP_PROXY` and
`HTTPS_PROXY` entries) to your own proxy, or delete them if you have direct internet access. Do not
commit that edit.
