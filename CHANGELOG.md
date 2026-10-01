# Changelog

Every version that changes what students experience gets a section here. `/wa` links to
this file when it tells a student an update is available, and `scripts/validate_plugin.py`
refuses a release whose version has no section.

## 3.0.0 — 2026-10-01

### בקצרה (לתלמידים)

- **החיבור לגוגל כבר לא נופל אחרי שבוע.** האפליקציה בגוגל עוברת למצב "פרסום" (בלי אימות של גוגל), אז ההרשאה ליומן ולמייל קבועה.
- **עובד גם בווינדוס.** שלב ההעלאה לשרת כבר לא דורש Homebrew, jq או Render CLI. כלי עזר אחד שעובד אותו דבר במק ובווינדוס.
- **הסוכן מוגן.** בין Green API לבוט יש עכשיו סיסמה, כך שמי שיודע את כתובת השרת לא יכול להתחזות אליך.
- **הבוט עונה גם כשמגיבים עם ציטוט** או שולחים קישור. קודם הוא התעלם מהודעות כאלה.
- **תזכורות לא הולכות לאיבוד** כשהשרת החינמי נרדם. הן נשלחות כשהוא מתעורר, ויש הסבר מסודר איך לגרום להן להגיע בזמן.
- **מודלים מעודכנים.** Claude Haiku 4.5 נשאר ברירת המחדל. Sonnet 5.5 החליף את 4.6, ומחירי OpenAI ו-Gemini עודכנו. מפתח אנתרופיק נוצר עם תוקף "Never", כדי שלא ימות בשקט.
- **Supabase:** ההוראות מובילות לכפתור Connect החדש, ויש טיפ לסיסמה שמונע את שגיאת "Tenant or user not found".
- **מייל זדוני לא יכול להפעיל את הבוט.** שליחת מייל או הזמנה לפגישה דורשת שתאשר בהודעה נפרדת. תוכן ממיילים ומקבוצות נחשב מידע, לא הוראות.
- **מפתחות לא עוברים בצ'אט.** מעתיקים את המפתח, אומרים "העתקתי", והוא נשמר ישר לקובץ הסודות.
- **בוט שכבר בנית מקבל את התיקונים.** `/wa` מזהה שהבוט נבנה בגרסה קודמת ומציע בדיקת שדרוג. היא מתקנת רק מה שאישרת.
- **המדריך מתעדכן מעצמו.** כשמסך אצל ספק משתנה, הסקיל עוקב אחרי המסך האמיתי. אחרי זה, באישורך, הוא שולח דיווח כדי שהמדריך יתעדכן לכל התלמידים.

### Fixed (verified against official docs, 2026-10-01)

- **Google OAuth**: apps left in *Testing* get refresh tokens that expire after 7 days. The skills now publish the app (Audience → Publish app) and re-consent afterwards. `run_console()` was removed from `google-auth-oauthlib` 1.x, so the fallback is now `run_local_server(port=0)`. The consent script writes tokens straight to `.env`. Gmail scopes now match the tools (mark-as-read needs `gmail.modify`).
- **Windows**: `wa-deploy` assumed macOS (`brew`, `jq`, bash). Claude Code on Windows may run PowerShell. All infrastructure work now goes through `scripts/wa_ops.py` (stdlib-only Python). Git and GitHub CLI install via winget, followed by an explicit app restart.
- **Render**:
  - env vars are now changed through per-key endpoints. The old read-modify-write on the collection `PUT` could wipe variables beyond the first page of 20.
  - Git connection path is now Account Security → Git Deployment Credentials.
  - Cold start is about 1 minute, not 30 seconds.
  - The free tier wipes files on every 15-minute idle spin-down, not "every ~12 hours".
  - A free Postgres database is deleted after 30 days plus a 14-day grace period, not 90 days. Outlook tokens no longer live there.
  - A disk needs a paid plan, which the student-facing text now says.
  - Default Python is 3.14, so the skills pin `.python-version` to `3.12`.
  - `autoDeploy` is replaced by `autoDeployTrigger`.
  - Deploys that return `202` with no body are handled. A previous live deploy is never mistaken for the new one.
- **Green API**:
  - the Business plan costs $12 a month. The Developer plan allows 3 chats a month.
  - `enableLidMode` is set to `no` explicitly, and the bot also handles `…@lid` senders defensively.
  - the webhook token is set to `Bearer <secret>`.
  - `deviceWebhook` is no longer sent.
  - `getChats` is now called with GET.
  - `yellowCard` is replaced by `suspended`.
  - settings can take up to 5 minutes to propagate.
  - webhooks retry every 60 seconds and wait 180 seconds for a response.
- **Bot code contract (`wa-build`)**:
  - Requests:
    - webhook `Authorization` check.
    - text read from `extendedTextMessage` and `quotedMessage` messages.
    - every rejected message logged with its reason.
    - fast `200`, then processing in the background.
    - `/health` pings the database, which keeps Supabase from pausing, and no longer exposes the prompt.
  - LLM calls (`anthropic` 1.x, current models):
    - no `temperature` and no forced `tool_choice`.
    - thinking blocks preserved inside the tool loop.
    - replies built from text blocks only.
    - the timestamp goes in the user turn, never in the system prompt.
    - top-level prompt caching.
  - Reminders:
    - `misfire_grace_time=None`, so late reminders are delivered instead of dropped.
    - timezone-aware times.
    - per-chat ownership.
    - the tool names in `FRAMEWORK_INJECTED_CHAT_ID` now match the registered tools. v2 had `schedule_reminder` in the set but `create_reminder` as the tool.
- **Handoff**: the tool is now named `request_human_handoff`, the name `prompt.py` looks for. `chat_id` is injected by the framework.
- **Outlook**:
  - `offline_access` is no longer passed to MSAL, which raised `ValueError`.
  - tokens are stored in an MSAL `SerializableTokenCache` in the bot's own database.
  - token lifetime is 90 days of inactivity, not 14 or 30.
  - the busy-wait loop is removed.
- **Anthropic API keys**: the skill walks through the new Create-key dialog (Expiration → Never, Default workspace). `wa_ops.py llm check --ping` validates key, model and credit, with hints for 401, 400-workspace and 402 errors.
- **Flow**:
  - deploy now consistently comes before connect.
  - `wa-connect` no longer sends students back to deploy.
  - the README listed 6 skills; there are 7.
  - added "installed but `/wa` doesn't appear" guidance (new session or `/reload-plugins`).

- **Review hardening** (an independent review of the whole plugin found 28 items; all addressed):
  - `render wait` waits for the deploy of the pushed commit, so the previous live deploy is never reported as success.
  - The Google consent script keeps its client JSON, and can rebuild the config from `.env` on re-runs.
  - Prompt-injection guard in the bot: tool output is untrusted data, and sending email or invitations is a draft confirmed in a later message (`turn_id` is injected by the framework).
  - `config.settings` is the shared contract; every connected tool registers its keys there.
  - Local runs never use the production database or start a second reminders scheduler.
  - Git identity is set with a GitHub no-reply address, plus `gh auth setup-git`.
  - The new ASCII `bot_slug` is used for repo and service names.
  - Windows-safe instructions: no `&&`, no `%USERPROFILE%`, full helper paths.
  - macOS venvs are created with `python3.12`.
  - `persistence_choice` values are unified across all files.
  - `plugin_version` is stamped only by build and the upgrade audit.
  - `state migrate` moves v2 bots out of a stale `deploy` stage.
  - `render disk` refuses a Free service.
  - `render status` syncs the plan into state.
  - Only secret-looking values are redacted.
  - `env set --from-clipboard` keeps keys out of the conversation.
  - Drift reports are never auto-labelled, so the maintainer's label is the gate.
  - The auto-refresh workflow is limited to one `auto-refresh/<run id>` branch and a PR, and validation runs in a separate job without secrets.

### Added

- `scripts/wa_ops.py` — cross-platform helper with these commands:
  - `doctor`, `state`, `env`, `llm`, `plugin`, `report-drift`, `smoke`, `health`
  - `green` (state, settings, wid, wait-authorized, configure, send, wait-incoming, chats)
  - `render` (owners, create-service, status, env-set/del/keys, deploy, wait, logs, restart, rollback, disk, postgres-create)
  - Secrets are never printed. A fallback handles python.org macOS builds that lack SSL certificates.
- `knowledge/` — `facts.md` (43 volatile facts with verified dates, sources and live checks), `freshness-protocol.md`, `platform.md`, `state-schema.md` (v2 plus a lossless v1→v2 migration), `upgrades.md` (fixes for bots that already exist).
- **Self-updating loop**:
  - Runtime: before third-party screens the skills run a freshness check and follow the live screen if it changed. Drift is recorded in `.wa-state.json`, and a scrubbed drift report goes upstream only with the student's consent.
  - Student side: `/wa` checks for plugin updates once a day and offers an upgrade audit when a bot was built with an older version.
  - Maintainer side: `validate.yml` runs on every push. `freshness.yml` runs weekly (stale facts, dead sources, PyPI drift, Render OpenAPI endpoints). `auto-refresh.yml` runs monthly or when a maintainer labels an issue `drift`: Claude re-verifies the facts and opens a PR, and a human merges it.
- `wa-maintain` → **Upgrade audit** path. `wa-connect/references/outlook.md` (Outlook moved out of the main skill).
- Offline test suite for the helper (`tests/`). A mock server checks request shapes against Render's OpenAPI spec and Green API's docs.

## 2.2.1

UX polish: WID display, KB skeleton, rollback, /wa shortcuts.

## 2.2.0

Memory persistence, chat_id injection, Google Auth Platform UI.

## 2.1.1

QA-driven fixes from first real deploy.

## 2.1.0

Automation pass: Render CLI, Green API webhook, robust Google OAuth.

## 2.0.0

Restructured plugin around orchestrator + state management.
