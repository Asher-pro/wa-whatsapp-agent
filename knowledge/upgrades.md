# Upgrades for bots that already exist

When the plugin improves, students who built their bot with an older version don't get the
fix by magic — their bot's code lives in *their* repo. This file is the list of fixes to
bring an existing bot up to the current plugin version. `wa-maintain` → **Upgrade audit**
walks it; `/wa` offers it whenever `.wa-state.json` has no `plugin_version` or an older
one than the installed plugin.

How to run an audit (the procedure lives in `wa-maintain`):

1. `wa_ops.py state migrate` (v1 → v2 state file, lossless).
2. For each upgrade below whose `applies-to` matches and whose ID is not in
   `upgrades_applied`: run its **detect** step. Detection is read-only.
3. Show the student a short Hebrew list of what was found — *what breaks if we don't fix
   it*, in one line each. Fix only what they approve, smallest risk first.
4. Batch all approved code changes into **one** commit + one redeploy, verify live, then
   `wa_ops.py state append upgrades_applied <ID>` for each and set `plugin_version`.

Never apply an upgrade the student didn't approve. Never rewrite files that aren't
involved — these are surgical edits to a bot the student may have customised.

---

## U300-GOOGLE-PUBLISH — Google connection dies after 7 days
- applies-to: bots with `google_calendar` or `gmail` in `connected_tools`
- detect: ask, or check `state.google.publishing_status`; symptom in logs: `invalid_grant` about a week after connecting. Facts: F-GOOGLE-TESTING-EXPIRY.
- fix: Audience → **Publish app** (F-GOOGLE-PUBLISH). **Replace** `scripts/google_auth.py` with the wa-connect A3 version (the v2 script prints tokens into the transcript and calls the removed `run_console`), run it, then `wa_ops.py render env-set GOOGLE_REFRESH_TOKEN` and deploy. Set `google.publishing_status = "in_production"`.
- student-facing: *"החיבור לגוגל נבנה במצב 'בדיקה' שבו גוגל מנתקת אחרי 7 ימים. נעביר למצב קבוע — 2 דקות."*

## U300-WEBHOOK-AUTH — anyone who knows the URL can pretend to be you
- applies-to: every deployed bot
- detect: `grep -n "Authorization" main.py` finds no check; or `wa_ops.py green settings` shows `webhookUrlToken: [empty]`.
- fix: `wa_ops.py env set WEBHOOK_TOKEN --generate` → add the header check to the webhook route (wa-build § main.py) → `render env-set WEBHOOK_TOKEN` → deploy → `green configure --webhook-url <url> --webhook-token-from-env WEBHOOK_TOKEN`.
- why: without it, a forged POST to `/webhook/green-api` with a whitelisted phone number reaches the LLM and its tools (calendar, mail).

## U300-MESSAGE-TYPES — bot ignores replies-with-quote and messages with links
- applies-to: every bot
- detect: `grep -n "extendedTextMessage\|quotedMessage" main.py` finds nothing.
- fix: extract text per F-GREENAPI-MESSAGE-TYPES (wa-build § main.py "text extraction").

## U300-LID-SAFE-WHITELIST — owner silently ignored if LID mode is ever on
- applies-to: `archetype == personal_assistant`
- detect: `wa_ops.py green settings` → `enableLidMode`; `grep -n "@lid" main.py`.
- fix: `green configure` (sets `enableLidMode: "no"`), and make the whitelist log every rejection with the raw sender and handle `…@lid` senders (wa-build § main.py "audience filter"). Facts: F-GREENAPI-LID.

## U300-LLM-REQUEST — SDK 1.x / newer models reject old request shapes
- applies-to: `LLM_PROVIDER=anthropic` in `.env` (v2 bots have no `llm` block in state)
- detect: `grep -n "temperature\|top_p\|tool_choice\|anthropic==0\." agent.py requirements.txt`; `wa_ops.py llm check` for the configured model.
- fix: remove sampling params, use `tool_choice` auto only, reply from text blocks, append `response.content` unchanged inside the tool loop, bump `anthropic` to 1.x (F-LLM-REQUEST-RULES, F-PY-PACKAGES). If the model is deprecated, offer the current replacement from `llm models`.

## U300-PYTHON-PIN — Render builds on Python 3.14 and fails
- applies-to: every bot
- detect: no `.python-version`, or a `runtime.txt`.
- fix: `.python-version` containing `3.12`; delete `runtime.txt`. Facts: F-RENDER-PYTHON-VERSION.

## U300-REMINDERS — reminders lost while the free server sleeps, or sent to the wrong chat
- applies-to: `reminders` in `connected_tools`
- detect: in `tools/reminders.py`: no `misfire_grace_time=None`; naive datetimes; jobstore on an ephemeral path; names in `FRAMEWORK_INJECTED_CHAT_ID` (agent.py) that don't match the registered tool names (v2 shipped `schedule_reminder` in the set but `create_reminder` as the tool).
- fix: per wa-build § reminders. Explain the keep-awake choice (wa-deploy § "Sleep and reminders").

## U300-FREE-TIER-MEMORY — bot forgets after 15 idle minutes
- applies-to: `render.plan == free` (refresh it with `wa_ops.py render status`) and `persistence_choice` **not** in (`disk`, `supabase`, `render_pg`, `ephemeral_accepted`)
- detect: `DATABASE_PATH` on Render points at a non-disk path. Facts: F-RENDER-FREE-LIMITS.
- fix: route to `wa-persistence` (Supabase).

## U300-HEALTH-DB — Supabase pauses after a quiet week; `/health` leaked the prompt
- applies-to: bots on Supabase/Postgres; any bot exposing `/health?debug=prompt`
- detect: `/health` doesn't query the DB; `grep -n "debug" main.py`.
- fix: `/health` runs `SELECT 1` through `database.py` and returns only `{"status":"ok","db":"ok"}`; remove any prompt-dump endpoint. Facts: F-SUPABASE-FREE-PAUSE.

## U300-GMAIL-SCOPES — "mark as read" fails with 403
- applies-to: `gmail` connected with `mode: read_only`
- detect: `tools/gmail.py` has `mark_read` but scopes only `gmail.readonly`.
- fix: remove `mark_read` from read-only bots, or switch to `gmail.modify` and re-consent. Facts: F-GOOGLE-SCOPES.

## U300-PROMPT-INJECTION — a crafted email or group message can make the bot act
- applies-to: bots with `gmail` (send mode), calendar invitations, `whatsapp_groups` or Outlook connected
- detect: `prompt.py` lacks the untrusted-content rule; `tools/gmail.py` sends in one step (`send_email` without a draft/confirm pair); no `FRAMEWORK_INJECTED_TURN_ID` in `agent.py`.
- fix: wa-build § prompt.py (untrusted-content rule) and § agent.py (`turn_id`), wa-connect A4 (draft → confirm in a later message; invitations the same way).

## U300-LOCAL-ISOLATION — a laptop run writes to production and double-fires reminders
- applies-to: bots whose `.env` has `DATABASE_URL`
- detect: `config.py` uses `DATABASE_URL` regardless of `APP_ENV`; `main.py` starts the scheduler unconditionally.
- fix: wa-build § config.py (`USE_POSTGRES` / `USE_REMOTE_DB_LOCALLY`) and § main.py (no scheduler when local + Postgres).

## U300-OUTLOOK-TOKENS — Outlook breaks (ValueError, or tokens deleted with free Render Postgres)
- applies-to: `outlook_calendar` / `outlook_mail` connected
- detect: `offline_access` inside a scopes list passed to MSAL; `DATABASE_URL_PG` pointing at a free Render Postgres (`expiresAt` set).
- fix: wa-connect Sub-flow E (token cache in the bot's main database). Facts: F-MSAL, F-RENDER-POSTGRES-FREE.

## U300-GREEN-STATES — code that checks `yellowCard`
- applies-to: any bot code or script that reads `stateInstance`
- detect: `grep -rn "yellowCard" .`
- fix: treat `suspended` the same way. Facts: F-GREENAPI-STATES.

---

## Adding a new upgrade (maintainers)

When a release fixes something that already-built bots also suffer from, add an entry here
with an ID `U<version-without-dots>-<SLUG>`, `applies-to`, read-only `detect`, `fix`, and
the facts it relies on. `wa-maintain` picks it up automatically — no skill edit needed.
