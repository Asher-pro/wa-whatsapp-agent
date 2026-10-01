# Volatile facts registry

Everything the wa-* skills rely on that can change **without our code changing**: screen
paths, button labels, prices, free-tier limits, model IDs, API field names.
Skills cite facts by ID (`F-…`) instead of restating them. How to use this file at runtime
is defined in [`freshness-protocol.md`](freshness-protocol.md).

Format (parsed by `scripts/check_freshness.py` — keep it):

```
### F-ID
- value: what is true
- verified: YYYY-MM-DD
- source: https://official-doc (one or more, space-separated)
- live-check: the fastest way to re-check it right now
- volatile: high | medium | low
```

Last full verification pass: **2026-10-01** (against official docs and live APIs).

---

## Green API

### F-GREENAPI-PLANS
- value: **Developer** = free, up to **3 chats per month per instance** (counter resets on the 1st; extra chats trigger a `quotaExceeded` webhook and API errors), plus monthly method quotas (e.g. 300 `getChatHistory`, 100 `checkWhatsapp`). **Business** = **$12/month** per instance, no chat limit — required for a customer-service bot. A "Chatbot" plan ($24/month) also exists; not needed for this course.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/about-tariffs/
- live-check: open the tariffs page; or the instance's plan shown in https://console.green-api.com
- volatile: high

### F-GREENAPI-CONSOLE
- value: Register/login at https://console.green-api.com → **Create an instance** (choose the plan) → scan the QR from the bot's phone (WhatsApp → Settings → Linked devices → Link a device) → copy three values: `idInstance`, `apiTokenInstance`, `apiUrl`.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/before-start/
- live-check: screenshot the console the student is looking at
- volatile: medium

### F-GREENAPI-SETTINGS-DELAY
- value: `setSettings` returns `{"saveSettings": true}` immediately, **reboots the instance**, and the new settings can take **up to 5 minutes** to show in `getSettings`. Limit ~1 request/second.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/account/SetSettings/
- live-check: `wa_ops.py green settings`
- volatile: low

### F-GREENAPI-SETTINGS-FIELDS
- value: Fields we set: `webhookUrl`, `webhookUrlToken`, `incomingWebhook`, `outgoingWebhook`, `outgoingMessageWebhook`, `outgoingAPIMessageWebhook`, `stateWebhook`, `incomingCallWebhook`, `pollMessageWebhook`, `enableLidMode`. `deviceWebhook` is "temporarily not working" — don't send it. Deprecated: `sharedSession`, `countryInstance`, `statusInstanceWebhook`, `enableMessagesHistory`.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/account/SetSettings/
- live-check: `wa_ops.py green settings` (shows the keys the instance actually has)
- volatile: medium

### F-GREENAPI-LID
- value: Since release 5.44.36.19 (2026-07-09) WhatsApp's internal ids (`…@lid`) are supported. Senders arrive as `…@lid` **only if** the instance setting `enableLidMode` is `"yes"` (beta, requires logout + rescan). With it `"no"` (our standard), `senderData.sender`/`chatId` stay `972…@c.us`. Lids can change; `getChats` then shows `newChatId`. `checkWhatsapp {"chatId": "<lid>"}` returns `phoneNumber` (empty if the user hides it).
- verified: 2026-10-01
- source: https://green-api.com/en/docs/release/5.44.36.19/ https://green-api.com/en/docs/faq/lid-important-differences/ https://green-api.com/en/docs/api/service/CheckWhatsapp/
- live-check: `wa_ops.py green settings` → `enableLidMode`; bot logs show the raw `sender` of rejected messages
- volatile: high

### F-GREENAPI-WEBHOOK-AUTH
- value: If `webhookUrlToken` is set, Green API sends it in the `Authorization` header of every webhook. Store it **with** the scheme: `"Bearer <secret>"` → header `Authorization: Bearer <secret>`. The bot must compare after stripping the `Bearer ` prefix (tolerate one or two prefixes).
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/receiving/technology-webhook-endpoint/
- live-check: bot log line on a rejected webhook shows whether the header arrived
- volatile: low

### F-GREENAPI-WEBHOOK-DELIVERY
- value: Green API waits up to **180 s** for HTTP 200, then retries **every 60 s**; delivery is guaranteed within 24 h. So: dedupe by `idMessage`, and a sleeping free Render service (≈1 min wake) still gets the message on a retry.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/receiving/technology-webhook-endpoint/
- live-check: —
- volatile: low

### F-GREENAPI-HTTP-QUEUE
- value: `receiveNotification` / `deleteNotification` (polling) only work while `webhookUrl` is **empty**; notifications wait 24 h; `receiveTimeout` 5–60 s. We use it only in wa-setup, before deploy.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/receiving/technology-http-api/
- live-check: `wa_ops.py green wait-incoming`
- volatile: low

### F-GREENAPI-STATES
- value: `getStateInstance` → `authorized`, `notAuthorized`, `blocked`, `sleepMode`, `starting`, `suspended`. (Release 5.44.37.12 renamed `yellowCard` → `suspended`, `yellowCardUntil` → `suspendedUntil`.)
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/account/GetStateInstance/ https://green-api.com/en/docs/release/5.44.37.12/
- live-check: `wa_ops.py green state`
- volatile: medium

### F-GREENAPI-MESSAGE-TYPES
- value: Text lives in different places by `messageData.typeMessage`: `textMessage` → `textMessageData.textMessage`; `extendedTextMessage` (links, previews) and `quotedMessage` (replies) → `extendedTextMessageData.text`; images/videos/documents → `fileMessageData.caption`; voice notes → `audioMessage` (no text). A bot that only reads `textMessage` silently ignores every reply-with-quote.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/receiving/notifications-format/incoming-message/ExtendedTextMessage/ https://green-api.com/en/docs/api/receiving/notifications-format/incoming-message/QuotedMessage/
- live-check: log `typeMessage` of every incoming webhook
- volatile: low

### F-GREENAPI-METHODS
- value: `getChats` (GET, optional `count`) → `[{id, name, type, newChatId?…}]`; `getChatHistory` (POST `{chatId, count}`, newest first, may lag up to 2 min; 300/month on Developer); `getGroupData` (POST `{groupId}`); `sendMessage` (POST `{chatId, message}`, ≤50 req/s). URL shape `{apiUrl}/waInstance{idInstance}/{method}/{apiTokenInstance}` — take `apiUrl` from the console.
- verified: 2026-10-01
- source: https://green-api.com/en/docs/api/service/GetChats/ https://green-api.com/en/docs/api/journals/GetChatHistory/
- live-check: `wa_ops.py green chats --groups`
- volatile: medium

---

## Render

### F-RENDER-API-KEY
- value: Account Settings → **API Keys** → Create API key. Direct link: https://dashboard.render.com/u/settings?add-api-key . Shown once.
- verified: 2026-10-01
- source: https://render.com/docs/api
- live-check: `wa_ops.py render owners` (401 = bad key)
- volatile: medium

### F-RENDER-GIT-CONNECT
- value: One-time GitHub connection: Account Settings → **Account Security** → **Git Deployment Credentials** → **Add credential** → GitHub (https://dashboard.render.com/u/settings#account-security). To grant access to more repos: https://github.com/apps/render/installations/new . The old `/settings#git-providers` link is obsolete.
- verified: 2026-10-01
- source: https://render.com/docs/git-provider https://render.com/docs/github
- live-check: `render create-service` error mentioning repo/credentials ⇒ not connected
- volatile: high

### F-RENDER-FREE-LIMITS
- value: Free web service **spins down after 15 min without inbound traffic**; spin-up takes **about one minute**; **the local filesystem is wiped on every spin-down, restart and redeploy** (a SQLite file there loses everything after each idle period); may restart at any time; 750 free instance hours per workspace per month (spun-down time doesn't count); **no disks**, no SSH, outbound SMTP blocked. Requests to `/robots.txt` don't wake it.
- verified: 2026-10-01
- source: https://render.com/docs/free
- live-check: open https://render.com/docs/free
- volatile: high

### F-RENDER-COLD-START
- value: about one minute (not ~30 s).
- verified: 2026-10-01
- source: https://render.com/docs/free
- live-check: `wa_ops.py health` prints how many attempts it took
- volatile: medium

### F-RENDER-PLANS
- value: **Starter = $7/month** (renamed `0.5c-512mb` on 2026-08-26; the API still accepts `starter`). Persistent disk **$0.25/GB/month**, paid plans only; a disk turns off zero-downtime deploys (a few seconds of downtime per deploy) and pins the service to one instance. Mount anywhere except `/`, `/opt`, `/opt/render`, `/opt/render/project`, `/opt/render/project/src`, `/home`, `/home/render`, `/etc`, `/etc/secrets` (we use `/data`).
- verified: 2026-10-01
- source: https://render.com/pricing https://render.com/docs/disks https://render.com/docs/compute-plans
- live-check: open the pricing page
- volatile: high

### F-RENDER-POSTGRES-FREE
- value: Free Render Postgres **expires 30 days after creation** (+14-day grace, then deleted); one per workspace; 1 GB; no backups. Cheapest paid: `basic-256mb` (`0.1c-256mb`) **$6/month**. ⇒ Don't use free Render Postgres for anything that must last (tokens, memory).
- verified: 2026-10-01
- source: https://render.com/docs/free https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90
- live-check: `GET /v1/postgres/{id}` → `expiresAt`
- volatile: medium

### F-RENDER-PYTHON-VERSION
- value: New Python services default to **3.14.x** (since 2026-02-11). Pin with a `.python-version` file containing `3.12` (major.minor is enough); a `PYTHON_VERSION` env var (full version) overrides it. `runtime.txt` is not supported.
- verified: 2026-10-01
- source: https://render.com/docs/python-version
- live-check: build log line "Using Python version …"
- volatile: medium

### F-RENDER-REGIONS
- value: `frankfurt`, `oregon`, `ohio`, `virginia`, `singapore`. Israel → `frankfurt`.
- verified: 2026-10-01
- source: https://render.com/docs/regions
- live-check: —
- volatile: low

### F-RENDER-API-SHAPES
- value: `POST /v1/services` → `201 {service:{id, dashboardUrl, serviceDetails:{url}}, deployId}`; `autoDeploy` is deprecated → `autoDeployTrigger: "commit"`. Env vars: per-key `PUT/DELETE /v1/services/{id}/env-vars/{KEY}` (safe); collection `PUT …/env-vars` **replaces all** (never use). `POST …/deploys` → `201 deploy` **or `202` with empty body**. `POST /v1/services/{id}/rollback {deployId}`. `GET /v1/logs?ownerId&resource&type&text&limit≤100`. Env-var and disk changes apply on the next deploy.
- verified: 2026-10-01
- source: https://api-docs.render.com/openapi/render-public-api-1.json
- live-check: `python3 -m unittest discover -s tests` (request shapes) + any `wa_ops.py render` call
- volatile: low

### F-RENDER-KEEPALIVE
- value: Render's docs don't address external keep-alive pings. Any inbound HTTP request resets the 15-minute idle timer. One always-on free service uses ≤744 of the 750 monthly hours. Treat pinging as a student-chosen workaround, not an official feature; the reliable answer for reminders is Starter.
- verified: 2026-10-01
- source: https://render.com/docs/free
- live-check: re-read the "Spinning down on idle" section
- volatile: high

---

## Supabase

### F-SUPABASE-CONNECT-UI
- value: The connection string is behind the **Connect** button at the top of the project dashboard (not Project Settings → Database). Tabs: Framework / Server / **Direct** / ORM / MCP. In **Direct**, set **Connection Method → Session pooler**. Deep link: https://supabase.com/dashboard/project/_?showConnect=true&connectTab=direct&method=session (from the dashboard source; docs use `?showConnect=true&method=session`).
- verified: 2026-10-01
- source: https://supabase.com/docs/guides/database/connecting-to-postgres
- live-check: open the deep link while logged in; screenshot
- volatile: high

### F-SUPABASE-POOLER-HOST
- value: Session pooler: `postgresql://postgres.<project-ref>:<password>@aws-<N>-<region>.pooler.supabase.com:5432/postgres`. `<N>` is **0 or 1** (new projects are often `aws-1`) and cannot be derived from the region — **always copy the string from Connect, never build it**. A wrong host or a username without `.<project-ref>` → `FATAL: Tenant or user not found`. Transaction pooler = port 6543 (not for APScheduler).
- verified: 2026-10-01
- source: https://supabase.com/docs/guides/troubleshooting/tenant-or-user-not-found
- live-check: `python -c "import psycopg; psycopg.connect(URL)"`
- volatile: high

### F-SUPABASE-IPV4
- value: Direct connections (`db.<ref>.supabase.co`) are IPv6-only unless the paid IPv4 add-on is bought; the shared pooler is IPv4 on every plan. Render free has no outbound IPv6 ⇒ direct URL fails with `Network is unreachable`.
- verified: 2026-10-01
- source: https://supabase.com/docs/guides/database/connecting-to-postgres
- live-check: —
- volatile: low

### F-SUPABASE-PASSWORD-CHARS
- value: Reserved characters in the password (`@ # ? & / : %` and space) must be percent-encoded inside the URL. Simplest: a password of letters and digits only (Supabase → Project Settings → Database → Reset password).
- verified: 2026-10-01
- source: https://supabase.com/docs/guides/database/connecting-to-postgres
- live-check: —
- volatile: low

### F-SUPABASE-FREE-PAUSE
- value: Free projects with low database activity for **7 days are paused** (warning email first); restore with **Resume project** in the dashboard. A few database queries a day keep it active. 2 active free projects per account; 500 MB database each.
- verified: 2026-10-01
- source: https://supabase.com/docs/guides/platform/free-project-pausing https://supabase.com/docs/guides/platform/billing-on-supabase
- live-check: project dashboard banner
- volatile: high

---

## Google (Calendar / Gmail)

### F-GOOGLE-AUTH-PLATFORM
- value: OAuth setup lives in **Google Auth Platform**: https://console.cloud.google.com/auth/overview with sections **Overview, Branding, Audience, Clients, Data Access, Verification Center** (paths `/auth/branding`, `/auth/audience`, `/auth/clients`, `/auth/scopes`, `/auth/verification`).
- verified: 2026-10-01
- source: https://support.google.com/cloud/answer/15549945
- live-check: open https://console.cloud.google.com/auth/overview
- volatile: high

### F-GOOGLE-TESTING-EXPIRY
- value: An External app in **Testing** gets refresh tokens that **expire 7 days after consent** (unless only name/email/profile scopes). Symptom: the bot reads the calendar/mail for a week, then `invalid_grant`.
- verified: 2026-10-01
- source: https://developers.google.com/identity/protocols/oauth2 https://support.google.com/cloud/answer/15549945
- live-check: re-read "Refresh token expiration" in the oauth2 page
- volatile: medium

### F-GOOGLE-PUBLISH
- value: Fix for the 7-day expiry: **Audience → Publishing status → Publish app** (→ "In production"). No verification is needed for personal use (<100 users): users click through the unverified-app warning. 100 new users per project **for its whole lifetime**. Tokens issued while in Testing still die at day 7 ⇒ **run the consent script again after publishing**.
- verified: 2026-10-01
- source: https://support.google.com/cloud/answer/15549945 https://support.google.com/cloud/answer/13464323
- live-check: Audience page shows "In production"
- volatile: medium

### F-GOOGLE-UNVERIFIED-SCREEN
- value: Warning screen ("Google hasn't verified this app" / "This app isn't verified"): click **Advanced** → **Go to <app name> (unsafe)** → Continue.
- verified: 2026-10-01
- source: https://developers.google.com/apps-script/api/troubleshoot-authentication-authorization
- live-check: screenshot during consent
- volatile: medium

### F-GOOGLE-SCOPES
- value: Calendar: `https://www.googleapis.com/auth/calendar.events`. Gmail: `gmail.readonly` (read; **restricted**), `gmail.modify` (read + mark read/labels; restricted — required for mark-as-read), `gmail.send` (sensitive). Restricted scopes need verification + security assessment **only** for public apps; personal-use apps just see the warning.
- verified: 2026-10-01
- source: https://developers.google.com/workspace/gmail/api/auth/scopes https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify
- live-check: —
- volatile: low

### F-GOOGLE-INVALID-GRANT
- value: `invalid_grant` = refresh token dead. Causes: Testing-mode 7-day expiry; user revoked access; unused 6 months; password change (Gmail scopes); >100 refresh tokens for the same account+client (oldest silently invalidated — don't re-run consent in a loop); account disabled; Workspace session-control policy (`invalid_rapt`).
- verified: 2026-10-01
- source: https://developers.google.com/identity/protocols/oauth2
- live-check: —
- volatile: low

### F-GOOGLE-OAUTHLIB
- value: `google-auth-oauthlib` 1.5.0 (Python ≥3.10). `InstalledAppFlow.run_console()` was **removed in 1.0.0** (Google killed the copy-paste/OOB flow). Use a **Desktop app** client with `run_local_server(port=0, access_type="offline", prompt="consent")` — any free localhost port works for Desktop clients. If the browser can't open by itself, `open_browser=False` prints the URL to open on the same computer. No device-code flow for Gmail/Calendar scopes.
- verified: 2026-10-01
- source: https://pypi.org/project/google-auth-oauthlib/ https://developers.google.com/identity/protocols/oauth2/resources/oob-migration
- live-check: `python -m pip index versions google-auth-oauthlib`
- volatile: medium

---

## Microsoft (Outlook)

### F-MS-REFRESH-LIFETIME
- value: Refresh tokens live **90 days of inactivity** (24 h for single-page apps), no maximum age, and **rotate on every use** (store the new one each time). The old "14 days" figure was retired in 2021.
- verified: 2026-10-01
- source: https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens https://learn.microsoft.com/en-us/entra/identity-platform/configurable-token-lifetimes
- live-check: —
- volatile: low

### F-MS-ENTRA-REGISTRATION
- value: https://entra.microsoft.com → **Entra ID → App registrations → New registration**. Account type for personal + work accounts: **"Any Entra ID Tenant + Personal Microsoft accounts"**. Redirect URI for our server-side script with a client secret: platform **Web**, `http://localhost:8765/callback`. Secret: Certificates & secrets → New client secret → copy the **Value** immediately.
- verified: 2026-10-01
- source: https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app
- live-check: screenshot the registration form
- volatile: high

### F-MSAL
- value: `msal` 1.39.0. **Don't pass `offline_access`/`openid`/`profile` in scopes — MSAL adds them and raises `ValueError`.** Use `initiate_auth_code_flow()` + `acquire_token_by_auth_code_flow()` for the one-time consent, a `SerializableTokenCache` persisted in the bot's database, and `acquire_token_silent()` at runtime. `acquire_token_by_refresh_token` is for migration only.
- verified: 2026-10-01
- source: https://learn.microsoft.com/en-us/entra/msal/python/advanced/msal-python-token-cache-serialization https://pypi.org/project/msal/
- live-check: `python -m pip index versions msal`
- volatile: medium

---

## LLM providers

### F-ANTHROPIC-KEY-DIALOG
- value: https://platform.claude.com/settings/keys (console.anthropic.com redirects) → **Create key**: Name; **Expiration → choose "Never"** (options: 3 hours, 1 day, 7 days, 30 days, custom, Never — an expired key returns 401 and **cannot be revived**); **Linked account → yourself**; Workspace → **Default**. Key starts with `sk-ant-` and is shown once. The dialog's *default* expiration is unverified — always look.
- verified: 2026-10-01
- source: https://platform.claude.com/docs/en/get-api-key https://platform.claude.com/docs/en/manage-claude/authentication
- live-check: `wa_ops.py llm check`
- volatile: high

### F-ANTHROPIC-ERRORS
- value: 401 `authentication_error` = wrong/revoked/**expired** key. 400 "anthropic-workspace-id is required…" = key linked to several workspaces → create a key scoped to one workspace. 402 `billing_error` = no credit → https://platform.claude.com/settings/billing (Settings → Billing → Buy credits).
- verified: 2026-10-01
- source: https://platform.claude.com/docs/en/api/errors
- live-check: `wa_ops.py llm check --ping`
- volatile: medium

### F-LLM-MODELS
- value: Claude — `claude-haiku-4-5` **$1/$5** per MTok (active; retirement "not sooner than 2026-10-15", ≥60 days' notice), `claude-sonnet-5-5` **$2/$10** (released 2026-09-28), `claude-opus-5-5` $4/$20, `claude-sonnet-4-6` legacy $3/$15. OpenAI — `gpt-6-luna` $0.10/$0.50 (most efficient), `gpt-6.1-sol` $2/$10. Google — `gemini-3.5-flash-lite` $0.30/$2.50, `gemini-3.8-flash` $0.75/$3.75 (until 2026-12-31). `gemini-2.5-flash` is limited to existing users.
- verified: 2026-10-01
- source: https://platform.claude.com/docs/en/about-claude/pricing https://platform.claude.com/docs/en/about-claude/model-deprecations https://developers.openai.com/api/docs/pricing https://ai.google.dev/gemini-api/docs/pricing
- live-check: `wa_ops.py llm models` (lists what the student's key can actually use)
- volatile: high

### F-LLM-REQUEST-RULES
- value: For code that must work across current Claude models: no `temperature`/`top_p`/`top_k` (removed from the `anthropic` 1.x SDK; 400 on Opus 4.7+ and non-default on Sonnet 5.5); no forced `tool_choice` (`any`/`tool` → 400 on Sonnet 5.5/Opus 5.5) — use `auto` + a clear instruction; no assistant prefill; Sonnet 5.5 thinks by default — reply with **text blocks only**, and inside a tool loop append `response.content` **unchanged** (thinking blocks included); store only final text in history. Don't put "now" in the system prompt (busts caching; editing it mid-loop invalidates thinking) — put the timestamp in the user turn.
- verified: 2026-10-01
- source: https://platform.claude.com/docs/en/api/errors https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5
- live-check: `wa_ops.py llm check --ping`
- volatile: medium

### F-PY-PACKAGES
- value: `anthropic` 1.11.0, `openai` 3.22.1, `google-genai` 2.26.0 (old `google-generativeai` is dead) — all need Python ≥3.10. Pin to what `pip index versions` shows at build time.
- verified: 2026-10-01
- source: https://pypi.org/project/anthropic/ https://pypi.org/project/openai/ https://pypi.org/project/google-genai/
- live-check: `python -m pip index versions anthropic`
- volatile: high

---

## Claude Code (where the student runs the plugin)

### F-CC-PLUGIN-UPDATE
- value: A new plugin version reaches students only when `version` in plugin.json changes. Third-party marketplaces **don't auto-update by default**; enable it via `/plugin` → Marketplaces → practice-ai-plugins → enable auto-update. Manual: `/plugin marketplace update practice-ai-plugins`. New/updated plugins are active in the **next session** or after `/reload-plugins`. Desktop app, VS Code and terminal on one computer share `~/.claude`.
- verified: 2026-10-01
- source: https://code.claude.com/docs/en/plugins/install https://code.claude.com/docs/en/plugins/manifest-reference
- live-check: `wa_ops.py plugin check-update`
- volatile: medium

### F-CC-WINDOWS-SHELL
- value: On native Windows, Git for Windows is optional: without it Claude Code runs commands in **PowerShell**; with it, Git Bash. Tools installed with winget aren't on the app's PATH until the app restarts. Plugins don't load in WSL sessions of the desktop app.
- verified: 2026-10-01
- source: https://code.claude.com/docs/en/setup https://code.claude.com/docs/en/desktop
- live-check: `wa_ops.py doctor`
- volatile: medium
