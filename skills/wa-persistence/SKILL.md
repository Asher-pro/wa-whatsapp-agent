---
name: wa-persistence
description: "Give the deployed WhatsApp bot durable memory that survives Render restarts. Use when the student says 'הבוט שוכח שיחות', 'הבוט לא זוכר אותי', 'wa-persistence', 'תוסיף זיכרון לבוט', 'reminders נמחקים', or any variant of 'memory doesn't persist'. Also called automatically at end of wa-deploy if the student is on Render Free without a disk. Four sub-flows: (A) Render Disk, (B) Supabase Pooler — most common, (C) Render Postgres, (D) Skip with warning."
---

# Give the Bot Durable Memory

The default `wa-build` + `wa-deploy` puts SQLite at `./data/conversations.db`. On Render Free without a disk mount, this file is **ephemeral** — every restart (every ~12 hours, on average) wipes all conversations and pending reminders. Students discover this in production and think the bot is broken.

This skill fixes it. Four sub-flows, from simplest to most scalable.

**Prerequisites**: `wa-deploy` completed (bot is live on Render, `.wa-state.json` has `render_url` and `render_service_id`).

## Interaction Style

Simple Hebrew. Principle: **"I do, you decide"**. The student chooses an option, approves cost, and pastes credentials. Claude Code handles migration and verification.

## The Decision

Always present all four options with their real tradeoffs. Don't default-push one unless the student clearly prioritizes something (free, simple, scale).

| # | Option | Cost | Code changes | Survives Render restart | Complexity | When to choose |
|---|---|---|---|---|---|---|
| A | **Render Disk** | $0.25/mo | **0** | ✅ | Low | Simplest path. Student already on Render. Low volume. |
| B | **Supabase Pooler** | $0 | ~15 lines | ✅ | Medium | Free + persistent. Most popular path. Watch out for IPv6 + pooler config. |
| C | **Render Postgres** | $0 for 90 days, then $7/mo | ~15 lines | ✅ | Medium | Same region as Render service, slightly simpler than Supabase — but not free long-term. |
| D | **Do nothing** | $0 | 0 | ❌ | — | Learning/demo only. Student understands the tradeoff. |

**"איזה אפשרות מתאימה לך? (אני ממליץ A אם זה בוט אישי לטווח קצר, ו-B אם רצינית לטווח ארוך.)"**

## Flow

```dot
digraph wa_persistence {
    rankdir=TB;
    "Student picks option" [shape=diamond];
    "A: Render Disk" [shape=box];
    "B: Supabase Pooler" [shape=box];
    "C: Render Postgres" [shape=box];
    "D: Skip" [shape=box];
    "Verify memory survives restart" [shape=box];
    "Update state + done" [shape=doublecircle];

    "Student picks option" -> "A: Render Disk";
    "Student picks option" -> "B: Supabase Pooler";
    "Student picks option" -> "C: Render Postgres";
    "Student picks option" -> "D: Skip";
    "A: Render Disk" -> "Verify memory survives restart";
    "B: Supabase Pooler" -> "Verify memory survives restart";
    "C: Render Postgres" -> "Verify memory survives restart";
    "D: Skip" -> "Update state + done";
    "Verify memory survives restart" -> "Update state + done";
}
```

---

## Sub-flow A: Render Disk (simplest, paid)

**When the student chooses "A":**

**"הכי פשוט. מוסיפים disk של 1GB ל-Render. עלות: $0.25 לחודש. אין שינויי קוד."**

### A1. Attach the disk via REST API

Reminder — the CLI doesn't support disks. Use REST:

```bash
curl -fsS -X POST "https://api.render.com/v1/disks" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg sid "$RENDER_SERVICE_ID" '{
    serviceId: $sid,
    name: "data",
    mountPath: "/data",
    sizeGB: 1
  }')"
```

### A2. Update env var to use the mount path

```bash
# add_env_var from wa-deploy
add_env_var "$RENDER_SERVICE_ID" "DATABASE_PATH" "/data/conversations.db"
```

### A3. Remove stale `DATABASE_PATH` if it was ephemeral

If `DATABASE_PATH` previously pointed to `./conversations.db`, the `add_env_var` helper replaces it cleanly (it removes entries with the same key before appending).

### A4. Trigger a redeploy (env var changes don't reliably auto-deploy)

```bash
curl -fsS -X POST "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY"
# then poll for "live" like wa-deploy Phase E
```

### A5. Skip to "Verify" below.

**Note on Free tier + Disks**: Render Free does **not** allow disks. If `spec.archetype == personal_assistant` and student is on free, sub-flow A requires upgrade to Starter ($7/mo + $0.25/mo disk = $7.25/mo). If student wants to stay on Free, route to sub-flow B or D.

---

## Sub-flow B: Supabase Pooler (free, most common — and most landmines)

**When the student chooses "B":**

**"Supabase חינמי, מחזיקים שם כ-500MB בחינם וזה מלא-מלא. כמה צעדים, ויש כמה מלכודות שאני עוזר לנווט בהן."**

### B1. Create Supabase project (student action)

Open https://supabase.com in the browser.

**STOP for sign-up**: "תירשם - אפשר עם GitHub."

After login:
- Click "New project"
- **Name**: `[bot_name]-tokens` (or any name)
- **Database Password**: click "Generate" — **STOP**: *"העתק את הסיסמה למקום בטוח לפני שאתה ממשיך. Supabase לא יראו לך אותה שוב."*
- **Region**: **CRITICAL — same region as your Render service**. Israel → `Central EU (Frankfurt)`. Oregon → `West US (N. California)`. Mismatch causes latency pain.

Wait 1-2 minutes for the project to finish provisioning. Don't skip ahead.

### B2. Get the Pooler connection string (not the Direct one!)

**This is the most important step in the entire skill.** Getting this wrong = service crashes on startup with cryptic errors.

In the Supabase dashboard:
- **Project Settings → Database → Connection string**
- You will see **three tabs** or sections:
  1. **Direct connection** → port 5432, `db.xxx.supabase.co` — **DO NOT USE**. This is IPv6-only for projects created after mid-2024. Render Free does not have outbound IPv6. Service will crash with `Network is unreachable`.
  2. **Session pooler** → port 5432, `aws-0-xxx.pooler.supabase.com` — ✅ recommended for our bot (APScheduler jobstore + CRUD)
  3. **Transaction pooler** → port 6543, same host as session — faster for many short requests, but breaks long transactions

**Pick Session pooler.** Copy the full URL. It looks like:
```
postgresql://postgres.xxxxxxxxxx:[YOUR_PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

**Two important parts of this URL**:
- Username is `postgres.xxxxxxxxxx` (with the project-ref after the dot), **not** just `postgres`. If the pooler URL has just `postgres`, the project-ref is missing and you'll hit `FATAL: Tenant or user not found`.
- `[YOUR_PASSWORD]` is a placeholder — replace with the password you saved in B1.

Substitute the password and save as `DATABASE_URL` in `.env`:
```
DATABASE_URL=postgresql://postgres.xxxxxxxxxx:REAL_PASSWORD@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

### B3. Test the connection locally before touching Render

```bash
python -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
print('Connected:', conn.info.server_version)
conn.close()
"
```

If this prints a version number: connection works.

Common failures and fixes:
- `FATAL: Tenant or user not found` → you're using the Direct URL (or pooler URL with missing project-ref). Go back to B2.
- `Connection refused` → wrong port. Session pooler = 5432.
- `password authentication failed` → password mismatch. Go back to B1 and regenerate if you lost the password.

### B4. Update application code

Four files change. Claude Code writes each from scratch to match the new DB; no file templates.

**`config.py`**
- Remove `DATABASE_PATH`
- Add `DATABASE_URL` loaded from env
- Fail fast if missing

**`database.py`** (significant rewrite from SQLite to Postgres)
- `import psycopg2` (or `psycopg` for v3 — student's choice, pin in requirements)
- Connection per-call or via a small pool
- `conversations` table schema in Postgres syntax:
  ```sql
  CREATE TABLE IF NOT EXISTS conversations (
      id BIGSERIAL PRIMARY KEY,
      chat_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_conversations_chat ON conversations (chat_id, created_at);
  ```
- `processed_messages` (for idMessage dedup) same pattern — Postgres `ON CONFLICT (id_message) DO NOTHING`
- SQL parameter placeholders: `?` → `%s` (psycopg uses `%s`)
- `INSERT OR IGNORE` → `INSERT ... ON CONFLICT ... DO NOTHING`
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL PRIMARY KEY`

**`tools/reminders.py`** (APScheduler jobstore swap)
- SQLAlchemy URL **must have prefix**: `postgresql+psycopg2://` (not plain `postgresql://`)
  ```python
  from sqlalchemy.engine.url import make_url
  pg_url = make_url(settings.DATABASE_URL)
  sa_url = pg_url.set(drivername="postgresql+psycopg2")
  scheduler = BackgroundScheduler(jobstores={
      "default": SQLAlchemyJobStore(url=str(sa_url))
  })
  ```
- APScheduler will auto-create `apscheduler_jobs` table on first use.
- **Critical**: the function scheduled via `add_job` **must be module-level**, not a lambda. Postgres-backed jobstores serialize job refs; lambdas can't be serialized across restarts.

**`requirements.txt`**
- Add:
  ```
  psycopg2-binary   # or psycopg[binary] for psycopg v3
  sqlalchemy
  ```

### B5. Local smoke test before push

Claude Code should run, end-to-end:
```bash
cd [project-dir]
python -c "from database import init_db; init_db()"   # creates tables on Supabase
python -c "
from database import append, tail
append('smoke-test@c.us', 'user', 'hi')
print(tail('smoke-test@c.us'))
"
```

If this prints the message back, the migration worked. Also open Supabase dashboard → Table editor → verify `conversations` table has 1 row.

### B6. Update Render env vars

```bash
# Remove the ephemeral DATABASE_PATH, add DATABASE_URL
add_env_var "$RENDER_SERVICE_ID" "DATABASE_URL" "$DATABASE_URL"
remove_env_var "$RENDER_SERVICE_ID" "DATABASE_PATH"
```

### B7. Trigger a redeploy (do NOT trust auto-redeploy)

Render's env-var change auto-trigger is flaky. Explicitly:

```bash
curl -fsS -X POST "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY"
# poll deploy status (see wa-deploy Phase E pattern)
```

### B8. Skip to "Verify" below.

---

## Sub-flow C: Render Postgres (free 90 days, then paid)

**When the student chooses "C":**

**"Render Postgres חינמי 90 יום, אחר כך $7 לחודש. יתרון: באותו datacenter כמו הבוט, אפס latency. חסרון: 90 יום ודי."**

### C1. Provision the database

Same REST call used in `wa-deploy` when Outlook was in spec:

```bash
PG_OUTPUT=$(curl -fsS -X POST "https://api.render.com/v1/postgres" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg name "${BOT_NAME}-db" --arg region "${RENDER_REGION}" '{
    name: $name,
    region: $region,
    plan: "free",
    version: 16
  }')")

PG_ID=$(echo "$PG_OUTPUT" | jq -r .id)
# Poll GET /v1/postgres/{id} until status == "available" (up to 2 min)
```

### C2. Fetch internal connection string

For services within the same Render region/workspace, use the **internal** connection string (faster, no internet hop):

```bash
PG_URL=$(curl -fsS "https://api.render.com/v1/postgres/$PG_ID/connection-info" \
  -H "Authorization: Bearer $RENDER_API_KEY" | jq -r .internalConnectionString)
```

### C3-C7: Same as B4-B7

Code migration is identical to Supabase. The only differences:
- No region mismatch concern (Render Postgres is in the same region by default).
- No IPv6 issue (internal connection is IPv4).
- No pooler vs direct decision — Render Postgres has just one connection string.

---

## Sub-flow D: Do nothing (with warning)

**When the student chooses "D":**

**"הבנתי - בוט ללמידה / דמו. חשוב שתדע:"**

1. **שיחות** ימחקו כל ~12 שעות (Render Free restart cycle).
2. **תזכורות עתידיות** שתזמנת ימחקו באותם restart cycles — אז אם ביקשת "תזכיר לי מחר", סביר שזה לא יקרה.
3. **שום דבר** לא ישתמר בין deploys — כל `git push` מתחיל מאפס.
4. **הבוט עדיין עונה** מיידית - רק אין לו היסטוריה או תיזמון ארוך.

**"אם תגיע לנקודה שאתה רוצה זיכרון, תגיד `wa-persistence` ונטפל."**

Update `.wa-state.json` with `persistence_choice: "ephemeral_accepted"` and exit.

---

## Verify (all paths except D)

### V1. Full round-trip test

Send a real WhatsApp message from the student's personal phone to the bot:
**"תשלח לבוט 'זכור שאני אוהב קפה שחור עם סוכר אחד'."**

Wait for the bot's reply. Confirm it acknowledges.

### V2. Force a restart

Trigger a manual redeploy:
```bash
curl -fsS -X POST "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -d '{"clearCache": "do_not_clear"}'
# poll until "live"
```

### V3. Verify memory survives

**"עכשיו תשלח 'מה אני אוהב?'"**

If the bot answers "קפה שחור עם סוכר אחד" → memory persists ✅.

If it says "לא זוכר" → something wrong. Check:
- For sub-flow A: `DATABASE_PATH=/data/conversations.db` in env? Disk mounted? `ls /data` via `render shell` shows the db file?
- For B/C: `DATABASE_URL` correct? Connection works from Render logs? Tables exist in the DB dashboard?

### V4. Check reminders survive too (if spec has reminders)

**"תשלח 'תזכיר לי בעוד דקה לבדוק'."**

Trigger a manual deploy **within the minute**. Wait. Did the reminder still fire?
- Yes → jobstore persists ✅
- No → for B/C, check SQLAlchemy URL prefix (`postgresql+psycopg2://`). For A, check the mount path.

---

## Update state & hand off

Update `.wa-state.json`:
- `persistence_choice` → final chosen mode (`"disk" | "supabase" | "render_pg" | "ephemeral_accepted"`)
- `persistence_details` → object with connection info (not passwords):
  - For A: `{"mount_path": "/data", "size_gb": 1}`
  - For B: `{"provider": "supabase", "region": "..."}`
  - For C: `{"provider": "render_pg", "pg_id": "..."}`
- `last_touched_iso` → now

Current_stage stays at whatever it was (usually `maintain` — persistence is a mid-life upgrade, not a linear stage).

Then:

**"זיכרון קבוע מופעל. הבוט עכשיו יזכור שיחות ותזכורות גם אחרי restart. אם משהו נראה חשוד, `/wa` ואני אעבור ל-maintenance."**

---

## Error Handling

| Problem | Cause | Fix |
|---|---|---|
| `psycopg2.OperationalError: Network is unreachable` (IPv6 address) | Using Supabase Direct URL on Render Free | Switch to Session pooler URL (B2) |
| `FATAL: Tenant or user not found` | Pooler URL missing project-ref in username | Re-copy from Supabase dashboard — username must be `postgres.<project-ref>` |
| `password authentication failed` | Wrong password or password reset | Supabase → Project Settings → Database → Reset password → update `DATABASE_URL` |
| `Connection refused` on port 5432 to pooler | Wrong port for pooler type | Session pooler = 5432, Transaction pooler = 6543 |
| APScheduler: `Job cannot be serialized since the reference to its callable` | Lambda or nested function used in `add_job(func=...)` | Use module-level function reference |
| APScheduler after B: jobs don't fire on Postgres | SQLAlchemy URL missing `+psycopg2` prefix | `postgresql+psycopg2://...` (not plain `postgresql://`) |
| Service crashes after env var change, logs show `DATABASE_PATH` error | Old ephemeral env var still set | `remove_env_var` for `DATABASE_PATH` |
| Memory test fails even though tables exist | DB query using SQLite syntax (`?` placeholders, `INSERT OR IGNORE`) | Convert to Postgres (`%s`, `ON CONFLICT`) |
| Render Free + sub-flow A fails with "plan does not support disks" | Render Free truly doesn't allow disks | Upgrade to Starter, or switch to sub-flow B (Supabase, free) |
| Supabase region mismatch (latency >200ms) | Supabase created in different region than Render | Only fix: recreate project in matching region. Painful but short. |

---

## Architectural Notes

- **Why no tool-level abstraction over Postgres/SQLite**: different bots have different memory needs. An ORM would add another dependency chain to debug. Raw `psycopg2` queries in `database.py` are 40 lines, readable, no surprises.
- **Why Session pooler over Direct**: Direct is IPv6-only for new Supabase projects; Render Free is IPv4-only. Mismatch = no connection at all. Session pooler resolves to IPv4 deliberately.
- **Why not Transaction pooler by default**: APScheduler's SQLAlchemy jobstore opens long-lived sessions that don't play nice with Transaction pooler's short-transaction constraint. Session pooler is safer.
- **Why APScheduler jobstore + Postgres needs `+psycopg2` explicitly**: SQLAlchemy infers the driver from the URL prefix. Plain `postgresql://` might pick `asyncpg` or another async driver, which APScheduler's sync jobstore can't use.
- **Why we don't recommend Turso/libsql**: SQLite-compatible API, but APScheduler's SQLAlchemy jobstore has sharp edges with libsql. Reminders break silently. Not worth the debugging.
- **Why we warn about region matching**: a Supabase in Seoul and a Render in Frankfurt yields ~300ms per DB query. At 5-10 queries per message, the bot feels sluggish. Matching regions keeps this under 50ms.
- **Why `remove_env_var`**: `add_env_var` replaces entries with the same key, but old-but-still-present `DATABASE_PATH` confuses `config.py` if it checks both vars. Explicit removal keeps state clean.
- **Why trigger redeploy manually after env change**: Render's auto-redeploy-on-env-change is advertised but empirically unreliable. Explicit `POST /deploys` is 3 lines and 100% reliable.
