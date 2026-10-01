---
name: wa-persistence
description: "Give the deployed WhatsApp bot durable memory that survives Render restarts and free-tier sleep. Use when the student says 'הבוט שוכח שיחות', 'הבוט לא זוכר אותי', 'wa-persistence', 'תוסיף זיכרון לבוט', 'reminders נמחקים', or any variant of 'memory doesn't persist'. Also called right after wa-deploy when the student is on Render Free without a disk. Four sub-flows: (A) Render Disk (paid plan), (B) Supabase Session pooler — free, most common, (C) Render Postgres, (D) Skip with warning."
---

# Give the Bot Durable Memory

The default `wa-build` + `wa-deploy` puts SQLite at `./data/conversations.db`. On Render Free (which can't have a disk) this file is **ephemeral**: Render wipes the service's files every time it spins down after **15 minutes without messages**, and on every restart and redeploy (F-RENDER-FREE-LIMITS). In practice the bot forgets conversations and pending reminders several times a day. Students discover this in production and think the bot is broken.

This skill fixes it. Four sub-flows, from simplest to most scalable.

**Prerequisites**: `wa-deploy` completed (bot is live on Render, `.wa-state.json` has `render.url` and `render.service_id`).

## Plugin files (read once per session)

- `PLUGIN_ROOT` = `${CLAUDE_SKILL_DIR}/../..` · helper `WA_OPS` = `PLUGIN_ROOT/scripts/wa_ops.py` (`python3` on macOS/Linux, `py -3` on Windows; run from the bot's project directory).
- Facts: `PLUGIN_ROOT/knowledge/facts.md` — the `F-SUPABASE-…` facts (Connect screen, pooler host, IPv4, password characters, free-plan pausing), **F-RENDER-FREE-LIMITS, F-RENDER-PLANS, F-RENDER-POSTGRES-FREE**. Supabase's dashboard changes often: follow `knowledge/freshness-protocol.md` §3 before B2 and record drift if the Connect screen moved.

## Interaction Style

Simple Hebrew. Principle: **"I do, you decide"**. The student chooses an option, approves cost, and pastes credentials. Claude Code handles migration and verification.

## The Decision

Always present all four options with their real tradeoffs. Don't default-push one unless the student clearly prioritizes something (free, simple, scale).

| # | Option | Cost | Code changes | Survives restart / sleep | Complexity | When to choose |
|---|---|---|---|---|---|---|
| A | **Render Disk** | Starter $7/mo + $0.25/mo disk (Free can't have disks) | **0** | ✅ | Low | Student is already on (or wants) a paid Render plan. Also fixes reminder timing (no sleep). |
| B | **Supabase Session pooler** | $0 | ~60 lines | ✅ | Medium | Free + persistent. Most popular path — the course path. Pauses after 7 quiet days (F-SUPABASE-FREE-PAUSE); daily use or a keep-awake ping prevents that. |
| C | **Render Postgres** | Free expires after 30 days (+14 grace, then **deleted**); paid from $6/mo | ~60 lines | ✅ | Medium | Same provider/region as the bot — but only worth it on the paid database plan (F-RENDER-POSTGRES-FREE). |
| D | **Do nothing** | $0 | 0 | ❌ | — | Learning/demo only. Student understands the tradeoff. |

**"איזה אפשרות מתאימה לך? (אני ממליץ B — Supabase, חינמי — וזה גם מה שעושים בקורס. A מתאים אם השרת שלך כבר בתשלום.)"**

## Flow

```dot
digraph wa_persistence {
    rankdir=TB;
    "Student picks option" [shape=diamond];
    "A: Render Disk" [shape=box];
    "B: Supabase Session pooler" [shape=box];
    "C: Render Postgres" [shape=box];
    "D: Skip" [shape=box];
    "Verify memory survives restart" [shape=box];
    "Update state + done" [shape=doublecircle];

    "Student picks option" -> "A: Render Disk";
    "Student picks option" -> "B: Supabase Session pooler";
    "Student picks option" -> "C: Render Postgres";
    "Student picks option" -> "D: Skip";
    "A: Render Disk" -> "Verify memory survives restart";
    "B: Supabase Session pooler" -> "Verify memory survives restart";
    "C: Render Postgres" -> "Verify memory survives restart";
    "D: Skip" -> "Update state + done";
    "Verify memory survives restart" -> "Update state + done";
}
```

---

## Sub-flow A: Render Disk (simplest, paid)

**When the student chooses "A":**

**"הכי פשוט. מוסיפים disk של 1GB ל-Render. אין שינויי קוד. דיסק אפשר רק בשרת בתשלום (Starter, $7 לחודש) - והדיסק עצמו בערך 25 סנט לחודש."**

### A1. Make sure the service is on a paid plan

`WA_OPS render status` → `plan`. If it's `free`, **STOP** for the cost decision; the upgrade is Render dashboard → the service → **Settings → Instance Type → Starter** (student approves the payment). Afterwards run `WA_OPS render status` again (it syncs `render.plan` into `.wa-state.json`) and `WA_OPS state set render.keep_awake=paid_plan`. Free services cannot have disks (F-RENDER-FREE-LIMITS) — `render disk` refuses rather than letting Render fail.

### A2. Attach the disk

```
WA_OPS render disk --size-gb 1 --mount /data
WA_OPS render env-set DATABASE_PATH --value /data/conversations.db
WA_OPS render deploy --wait
```

The disk attaches on the next deploy, which the last command triggers and waits for. A disk turns off zero-downtime deploys — each deploy now has a few seconds of downtime (F-RENDER-PLANS). Green API retries, so no message is lost.

### A3. Skip to "Verify" below.

---

## Sub-flow B: Supabase Session pooler (free, most common — and most landmines)

**When the student chooses "B":**

**"Supabase חינמי, מחזיקים שם כ-500MB בחינם וזה מלא-מלא. כמה צעדים, ויש כמה מלכודות שאני עוזר לנווט בהן."**

### B1. Create Supabase project (student action)

Open https://supabase.com in the browser.

**STOP for sign-up**: "תירשם - אפשר עם GitHub."

After login:
- Click "New project"
- **Name**: `[bot_slug]-memory` (or any name)
- **Database Password**: a password of **letters and digits only** — Supabase's "Generate" is fine if what it produced has no symbols; otherwise type one. Symbols like `@ # ? & /` break the connection URL unless encoded (F-SUPABASE-PASSWORD-CHARS). **STOP**: *"העתק את הסיסמה למקום בטוח לפני שאתה ממשיך. Supabase לא יראו לך אותה שוב."*
- **Region**: **CRITICAL — same region as your Render service**. Israel / Frankfurt → `Central EU (Frankfurt)`. Oregon → `West US`. Mismatch causes latency pain.

Wait 1-2 minutes for the project to finish provisioning. Don't skip ahead.

Free accounts have 2 active projects (F-SUPABASE-FREE-PAUSE). If the student already has two, they pause or delete one first.

### B2. Get the Session pooler connection string (not the Direct one!)

**This is the most important step in the entire skill.** Getting this wrong = service crashes on startup with cryptic errors.

Where it lives today (F-SUPABASE-CONNECT-UI — check freshness, this screen moves):
- The **Connect** button at the **top of the project dashboard** (not under Project Settings)
- Direct link that opens it on the right tab: https://supabase.com/dashboard/project/_?showConnect=true&connectTab=direct&method=session
- In the dialog: tab **Direct** → **Connection Method: Session pooler**

The three methods you'll see:
1. **Direct connection** → `db.xxx.supabase.co` — **DO NOT USE**. IPv6-only unless you pay for an add-on; Render has no outbound IPv6 → `Network is unreachable` (F-SUPABASE-IPV4).
2. **Session pooler** → port **5432**, host `aws-0-…` or `aws-1-….pooler.supabase.com` — ✅ the one for our bot (APScheduler jobstore + CRUD)
3. **Transaction pooler** → port 6543 — breaks long-lived sessions; not for us

**Copy the full string exactly as shown — never type or "fix" the host.** The `aws-0`/`aws-1` part differs between projects and can't be guessed from the region; a guessed host gives `FATAL: Tenant or user not found` (F-SUPABASE-POOLER-HOST). It looks like:
```
postgresql://postgres.xxxxxxxxxx:[YOUR-PASSWORD]@aws-1-eu-central-1.pooler.supabase.com:5432/postgres
```

**Two important parts of this URL**:
- Username is `postgres.xxxxxxxxxx` (with the project-ref after the dot), **not** just `postgres`.
- `[YOUR-PASSWORD]` is a placeholder — replace it (brackets included) with the password from B1.

**"בחלון של Supabase יש כפתור Connect למעלה. תבחר Direct, ואז ב-Connection Method תבחר Session pooler, ותעתיק לי את השורה כמו שהיא. אל תשנה בה כלום חוץ מהסיסמה."**

Save it without it ever entering the chat — the student pastes the URL into a text editor, replaces `[YOUR-PASSWORD]`, copies the whole line, and says "העתקתי":
```
WA_OPS env set DATABASE_URL --from-clipboard
```
The helper warns if what was copied isn't a `postgresql://` URL or still contains `[YOUR-PASSWORD]`. (If the student pasted it into the chat instead: `WA_OPS env set DATABASE_URL "<url>"`.)

### B3. Install the driver and test the connection locally before touching Render

Add to `requirements.txt` (pin current versions — `pip index versions psycopg`):
```
psycopg[binary]   # psycopg 3
sqlalchemy        # already there for the APScheduler jobstore
```
Install with the venv's python, then:
```
<venv python> -c "import os,psycopg;from dotenv import load_dotenv;load_dotenv();c=psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=10);print('Connected:',c.info.server_version);c.close()"
```

If this prints a version number: connection works.

Common failures and fixes:
- `FATAL: Tenant or user not found` → host typed/guessed, or username without `.<project-ref>` → copy again from Connect (F-SUPABASE-POOLER-HOST).
- `Network is unreachable` / IPv6 address → that's the Direct URL; go back to B2.
- `password authentication failed` → wrong password, or a symbol in it that needs encoding → reset the password in Supabase (Project Settings → Database) to letters+digits and update the URL.
- Timeout → wrong port (Session pooler = 5432), or the project is paused (dashboard shows **Resume project**).

### B4. Update application code

Claude Code writes each change from scratch to match the new DB; no file templates. **The public function names in `database.py` stay exactly the same** (`init_db`, `append`, `tail`, `mark_processed`, `ping`) — nothing else in the bot changes.

**`config.py`**
- Add `DATABASE_URL` loaded from env
- If `DATABASE_URL` is set → Postgres; otherwise fall back to `DATABASE_PATH` (SQLite). This keeps local experiments possible and makes the switch one env var

**`database.py`**
- Postgres branch with `psycopg` (v3): connection per call (`psycopg.connect(DATABASE_URL, connect_timeout=10)`) — fine at this scale
- Same tables in Postgres syntax:
  ```sql
  CREATE TABLE IF NOT EXISTS conversations (
      id BIGSERIAL PRIMARY KEY,
      chat_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_conversations_chat ON conversations (chat_id, created_at);
  CREATE TABLE IF NOT EXISTS processed_messages (
      id_message TEXT PRIMARY KEY,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- `mark_processed`: `INSERT … ON CONFLICT (id_message) DO NOTHING` and return `cursor.rowcount == 1`
- SQL parameter placeholders: `?` → `%s`; `INSERT OR IGNORE` → `INSERT … ON CONFLICT … DO NOTHING`; `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL PRIMARY KEY`
- `ping()` → `SELECT 1` — `/health` calls it, which also counts as database activity for Supabase's 7-day pause rule
- Any extra tables later skills added (`pending_actions` for email confirmations, `token_cache` for Outlook) get their Postgres version too, behind the same function names
- `USE_POSTGRES` comes from `config.py` (wa-build): on Render it's on whenever `DATABASE_URL` is set; on the laptop only with `USE_REMOTE_DB_LOCALLY=1` — so local experiments never write to the production database

**`tools/reminders.py`** (APScheduler jobstore swap)
- SQLAlchemy URL **must name the driver**: `postgresql+psycopg://` (not plain `postgresql://`)
  ```python
  from sqlalchemy.engine.url import make_url
  sa_url = make_url(settings.DATABASE_URL).set(drivername="postgresql+psycopg")
  jobstore = SQLAlchemyJobStore(url=sa_url.render_as_string(hide_password=False))
  ```
- Keep `job_defaults={"misfire_grace_time": None, "coalesce": True}` and the module-level `deliver_reminder` from wa-build (lambdas can't be stored)
- APScheduler auto-creates the `apscheduler_jobs` table on first use

### B5. Local smoke test before push

Claude Code runs, end-to-end, with the venv's python (the one-time `USE_REMOTE_DB_LOCALLY` opt-in makes this run talk to Supabase on purpose):
```
<venv python> -c "import os; os.environ['USE_REMOTE_DB_LOCALLY']='1'; from database import init_db; init_db()"
<venv python> -c "import os; os.environ['USE_REMOTE_DB_LOCALLY']='1'; from database import append, tail; append('smoke-test@c.us','user','hi'); print(tail('smoke-test@c.us'))"
```

If this prints the message back, the migration worked. Also open Supabase dashboard → Table editor → verify `conversations` has the row. A normal local server run (`WA_OPS smoke`) keeps using local SQLite — that's intended.

### B6. Update Render env vars and redeploy

```
WA_OPS render env-set DATABASE_URL          # value read from .env
WA_OPS render env-del DATABASE_PATH         # remove the old ephemeral path
git add .
git commit -m "Durable memory on Supabase"
git push
WA_OPS render wait                          # waits for the deploy of the pushed commit; env changes ride along
```
If no push was needed, `WA_OPS render deploy --wait` instead.

### B7. Keep Supabase awake

A free project pauses after a week with little database activity (F-SUPABASE-FREE-PAUSE). A bot that's used daily is fine; one used rarely isn't. If the student chose the external keep-awake ping in wa-deploy, `/health` already touches the database every 10 minutes. Otherwise tell them once: **"אם הבוט לא יקבל הודעות שבוע, Supabase ישהה את מסד הנתונים. תקבל מייל אזהרה, ומחזירים אותו בלחיצה על Resume project."**

### B8. Skip to "Verify" below.

---

## Sub-flow C: Render Postgres

**When the student chooses "C":**

**"Render Postgres נמצא אצל אותו ספק ובאותו אזור כמו הבוט. אבל שים לב: מסד הנתונים החינמי של Render נמחק אחרי 30 יום (ועוד שבועיים חסד). לזיכרון קבוע צריך את המסלול בתשלום - בערך $6 לחודש."** (F-RENDER-POSTGRES-FREE)

If the student still wants free → recommend B instead (it doesn't expire). Use C on a paid database plan.

### C1. Provision the database

```
WA_OPS render postgres-create --name <bot_slug>-db --plan basic_256mb --save-as DATABASE_URL
```

The helper creates it in the bot's region, waits until it's `available`, and writes the **external** connection string to `.env` as `DATABASE_URL` (works both locally and from Render). Payment approval may be needed (402 → card in the dashboard).

### C2-C6: Same as B3-B6

Code migration is identical to Supabase. The only differences:
- No region mismatch concern (created in the bot's region).
- No IPv6 or pooler decision — one connection string.

---

## Sub-flow D: Do nothing (with warning)

**When the student chooses "D":**

**"הבנתי - בוט ללמידה / דמו. חשוב שתדע:"**

1. **שיחות** ימחקו בכל פעם שהשרת החינמי נרדם — אחרי 15 דקות בלי הודעות, כלומר כמה פעמים ביום.
2. **תזכורות עתידיות** שתזמנת ימחקו באותם רגעים — אז אם ביקשת "תזכיר לי מחר", סביר שזה לא יקרה.
3. **שום דבר** לא ישתמר בין deploys — כל `git push` מתחיל מאפס.
4. **הבוט עדיין עונה** מיידית - רק אין לו היסטוריה או תיזמון ארוך.

**"אם תגיע לנקודה שאתה רוצה זיכרון, תגיד `wa-persistence` ונטפל."**

`WA_OPS state set persistence_choice=ephemeral_accepted` and exit.

---

## Verify (all paths except D)

### V1. Full round-trip test

Send a real WhatsApp message from the student's personal phone to the bot:
**"תשלח לבוט 'זכור שאני אוהב קפה שחור עם סוכר אחד'."**

Wait for the bot's reply. Confirm it acknowledges.

### V2. Force a restart

```
WA_OPS render restart
WA_OPS health
```

### V3. Verify memory survives

**"עכשיו תשלח 'מה אני אוהב?'"**

If the bot answers "קפה שחור עם סוכר אחד" → memory persists ✅.

If it says "לא זוכר" → something wrong. Check:
- For sub-flow A: `WA_OPS render env-keys` shows `DATABASE_PATH`; its value is under `/data`; the latest deploy happened after the disk was created.
- For B/C: `DATABASE_URL` set on Render (`env-keys`), no `DATABASE_PATH` left over, logs show no connection errors (`WA_OPS render logs --text psycopg`), tables exist in the DB dashboard.

### V4. Check reminders survive too (if spec has reminders)

**"תשלח 'תזכיר לי בעוד דקה לבדוק'."**

Then immediately `WA_OPS render restart` (it takes well under a minute; with `misfire_grace_time=None` the reminder is delivered even if the restart overlaps the due time). Wait. Did the reminder still arrive (possibly with the "באיחור" note)?
- Yes → jobstore persists ✅
- No → for B/C, check the SQLAlchemy URL driver (`postgresql+psycopg://`) and `misfire_grace_time=None`. For A, check the mount path.

---

## Update state & hand off

Use dotted keys (no JSON on the command line — PowerShell mangles embedded quotes); connection info only, **never** passwords:
- A: `WA_OPS state set persistence_choice=disk persistence_details.mount_path=/data persistence_details.size_gb=1`
- B: `WA_OPS state set persistence_choice=supabase persistence_details.provider=supabase persistence_details.region=eu-central-1`
- C: `WA_OPS state set persistence_choice=render_pg persistence_details.provider=render_pg persistence_details.plan=basic_256mb`
- D: `WA_OPS state set persistence_choice=ephemeral_accepted`

(All values of `persistence_choice` are listed in `knowledge/state-schema.md`.)

`current_stage` stays whatever it was (usually `connect` or `maintain` — persistence is a mid-life upgrade, not a linear stage). `WA_OPS state log "Durable memory: <choice>"`.

If a Supabase/Render screen didn't match these instructions, it's in `drift_log` — offer the upstream report once (freshness protocol §5).

Then:

**"זיכרון קבוע מופעל. הבוט עכשיו יזכור שיחות ותזכורות גם אחרי restart. אם משהו נראה חשוד, `/wa` ואני אעבור ל-maintenance."**

If `wa-deploy` sent the student here before connecting tools → return to `/wa`, which continues to `wa-connect`.

---

## Error Handling

| Problem | Cause | Fix |
|---|---|---|
| `OperationalError: … Network is unreachable` (IPv6 address) | Supabase Direct URL on Render | Session pooler URL (B2, F-SUPABASE-IPV4) |
| `FATAL: Tenant or user not found` | Host typed/guessed (`aws-0` vs `aws-1`) or username without project-ref | Copy the string from Connect again (F-SUPABASE-POOLER-HOST) |
| `password authentication failed` | Wrong password or unencoded symbol in it | Reset to letters+digits (F-SUPABASE-PASSWORD-CHARS), update `DATABASE_URL` in `.env` and on Render |
| `Connection refused` / timeout on 5432 | Wrong port or project paused | Session pooler = 5432; **Resume project** in Supabase |
| Supabase email "project will be paused" | 7 days of low activity | Use the bot, or keep-awake ping on `/health` (wa-deploy) |
| APScheduler: `Job cannot be serialized since the reference to its callable` | Lambda or nested function in `add_job` | Module-level `deliver_reminder` |
| APScheduler: "unknown driver" / jobs don't persist | SQLAlchemy URL missing `+psycopg` | `postgresql+psycopg://…` |
| Service crashes after env var change, logs mention `DATABASE_PATH` | Old ephemeral env var still set | `WA_OPS render env-del DATABASE_PATH` + deploy |
| Memory test fails even though tables exist | SQLite syntax in the Postgres branch (`?`, `INSERT OR IGNORE`) | Convert to `%s`, `ON CONFLICT` |
| "plan does not support disks" | Service is on Free | Starter, or sub-flow B |
| Render Postgres "expired" / deleted | Free Render Postgres lifetime (F-RENDER-POSTGRES-FREE) | Paid DB plan, or move to Supabase |
| Supabase region mismatch (slow replies) | Project in a different region than Render | Only fix: recreate the project in the matching region |

---

## Architectural Notes

- **Why no ORM over Postgres/SQLite**: different bots have different memory needs. An ORM would add another dependency chain to debug. Raw `psycopg` queries in `database.py` are short, readable, no surprises.
- **Why keep the same function names**: `agent.py`, `main.py`, `/health` and every tool talk to `database.py` only through `init_db/append/tail/mark_processed/ping`. Swapping storage is a one-file change plus one env var.
- **Why Session pooler over Direct**: Direct is IPv6-only without a paid add-on; Render's outbound traffic is IPv4. Session pooler is IPv4 on every plan.
- **Why not Transaction pooler**: APScheduler's SQLAlchemy jobstore keeps sessions that don't fit transaction pooling.
- **Why `postgresql+psycopg` explicitly**: SQLAlchemy infers the driver from the URL prefix; plain `postgresql://` defaults to psycopg2, which isn't installed.
- **Why we don't recommend Turso/libsql**: SQLite-compatible API, but APScheduler's SQLAlchemy jobstore has sharp edges with libsql. Reminders break silently.
- **Why region matching**: a Supabase in Seoul and a Render in Frankfurt yields ~300ms per DB query. At several queries per message, the bot feels sluggish.
- **Why `env-del DATABASE_PATH`**: an old path left on Render confuses `config.py` and future debugging. One explicit removal keeps state clean.
- **Why `/health` pings the database**: it proves the bot can reach its memory, and it's the activity that keeps a free Supabase project from pausing.
