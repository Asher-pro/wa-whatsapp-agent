---
name: wa-build
description: "Build the WhatsApp agent code from a characterization spec. Use after wa-characterize when the student has an approved spec.json, or says 'wa-build', 'בנה את הסוכן', 'תבנה את הקוד', 'יאללה בוא נבנה'. This skill enforces the opinionated architecture (FastAPI + direct LLM SDK + SQLite + explicit tool registry) and guides Claude Code to generate a clean, deploy-ready codebase. No framework magic - the student can read every line."
---

# Build the WhatsApp Agent

Generate a complete, runnable bot from `spec.json`. Enforce a clear architecture so every later skill (`wa-connect`, `wa-deploy`, `wa-maintain`) has predictable files to modify.

**This skill is architecture-first.** Before writing code, it commits to a specific stack and layout, explains the choice to the student in one sentence, and then lets Claude Code generate against that spec.

**Prerequisites:** `wa-characterize` completed (`spec.json` exists in the project directory).

## Interaction Style

Simple Hebrew with the student. Claude Code does the heavy lifting - reads `spec.json`, writes files, runs `pip install`. The student watches and approves at clear checkpoints.

## The Opinionated Stack (Non-Negotiable)

This decision is made once, here. All downstream skills assume it.

| Layer | Choice | Why this and not alternatives |
|---|---|---|
| Web framework | **FastAPI** | Async, native webhook pattern, runs on Render cleanly, students meet it later in the course |
| LLM access | **Direct SDK** (`openai` or `anthropic`) with native tool calling | Agno was considered - Gmail send blocked, memory leak open, docs split. Not worth the risk for non-technical students. MCP was considered - wrong abstraction (MCP is for LLM clients, not webhook servers). Direct SDK wins on simplicity and debuggability. |
| Conversation memory | **SQLite** via a small `database.py` | One file, no server, survives Render disk mount. If load grows → swap to Postgres, same interface. |
| Tool registry | **Explicit Python dict** of tool name → schema + Python function | Zero magic. The student (and future Claude Code sessions) can grep for a tool's name and find it. |
| Scheduling / reminders | **APScheduler** in-process, backed by SQLite jobstore | No separate cron service. Survives restart because jobstore is on disk. |
| Deployment | **Render.com web service** | Defined by `wa-deploy`. |
| Google auth (Gmail/Calendar) | **OAuth refresh token in env var**, single credential covers both | Defined by `wa-connect`. |

**Tell the student this in one sentence:** **"אני בונה את הבוט כך: FastAPI מקבל הודעות מ-Green API, שולח ל-Claude/GPT שמחליט מה לעשות (עונה או קורא לכלי), ומחזיר תשובה. כל שיחה נשמרת ב-SQLite. זה מבנה פשוט ושקוף - אתה יכול לקרוא כל שורה."**

## File Layout (Enforced)

```
project-dir/
├── .env                    # secrets (from wa-setup, wa-connect will append)
├── .env.example            # committed, shows which vars are needed
├── .gitignore              # excludes .env, __pycache__, *.db
├── .python-version         # pins Python to 3.12.x (Render reads this)
├── spec.json               # from wa-characterize, source of truth
├── requirements.txt        # pinned versions
├── render.yaml             # Render service config (wa-deploy uses this)
├── main.py                 # FastAPI app: /webhook/green-api endpoint, health
├── agent.py                # LLM call + tool-calling loop
├── database.py             # SQLite: conversations table, get/append/tail
├── config.py               # loads .env and spec.json, exposes settings
├── prompt.py               # system prompt generator from spec.json
├── tools/
│   ├── __init__.py         # TOOL_REGISTRY dict
│   ├── whatsapp.py         # send_message helper (always needed)
│   ├── reminders.py        # APScheduler wrapper (if selected)
│   ├── google_calendar.py  # (added by wa-connect if selected)
│   ├── gmail.py            # (added by wa-connect if selected)
│   ├── whatsapp_groups.py  # (added by wa-connect if selected)
│   └── human_handoff.py    # (added by wa-connect if selected)
└── data/                   # conversations.db lives here (mounted on Render)
```

**Why this matters:** `wa-connect` and `wa-maintain` both look for `tools/` and `TOOL_REGISTRY`. If the layout drifts, those skills break.

**Why `.python-version` is mandatory**: Render defaults new Python services to the latest Python (currently 3.14), where many pinned dependencies (notably `pydantic-core`) have no prebuilt wheels. Pip falls back to compiling from Rust, Render's sandbox blocks the Cargo cache, build fails. `.python-version` with `3.12.7` avoids the whole class. Do **not** use `runtime.txt` (Heroku convention, Render ignores it).

## Critical Ordering Principle

**The bot gets deployed after `wa-build`, before any external tools are connected.**

This is intentional. Reasons:
1. **Fast win**: student sees their bot alive and talking within an hour. Motivation matters.
2. **Debugging isolation**: if something is broken, is it the code? the deploy? the OAuth? Staging the work means each failure is localized.
3. **External tools require redeploy anyway**: every tool added in `wa-connect` triggers a push + redeploy cycle. No value in batching.
4. **Local smoke test is not real validation**: the bot isn't "working" until the student can message it on WhatsApp. That requires Green API webhook → public URL → Render. Deploy is the real test.

So `wa-build` scope is **minimal**:
- Prompt is built
- Conversation memory (SQLite)
- Whitelist / audience filtering
- **Reminders tool wired up** (native APScheduler — no external auth needed, comes "free")
- External tools (Gmail, Calendar, WhatsApp groups) are **not** wired here. They're mentioned in the spec but not added to `TOOL_REGISTRY` yet.

## Flow

```dot
digraph wa_build {
    rankdir=TB;
    "Read spec.json + .env" [shape=box];
    "Ask: LLM choice" [shape=diamond];
    "Set up LLM API key\n(STOP for payment)" [shape=box];
    "Write core files\n(config, database, prompt, agent, main)" [shape=box];
    "Wire reminders tool\n(if in spec)" [shape=box];
    "pip install -r requirements.txt" [shape=box];
    "Run local smoke test\n(fake webhook → agent → reply)" [shape=box];
    "Show student sample conversation" [shape=box];
    "Student happy with tone?" [shape=diamond];
    "Fine-tune prompt" [shape=box];
    "Done - suggest wa-deploy" [shape=doublecircle];

    "Read spec.json + .env" -> "Ask: LLM choice";
    "Ask: LLM choice" -> "Set up LLM API key\n(STOP for payment)";
    "Set up LLM API key\n(STOP for payment)" -> "Write core files\n(config, database, prompt, agent, main)";
    "Write core files\n(config, database, prompt, agent, main)" -> "Wire reminders tool\n(if in spec)";
    "Wire reminders tool\n(if in spec)" -> "pip install -r requirements.txt";
    "pip install -r requirements.txt" -> "Run local smoke test\n(fake webhook → agent → reply)";
    "Run local smoke test\n(fake webhook → agent → reply)" -> "Show student sample conversation";
    "Show student sample conversation" -> "Student happy with tone?";
    "Student happy with tone?" -> "Fine-tune prompt" [label="no"];
    "Fine-tune prompt" -> "Run local smoke test\n(fake webhook → agent → reply)";
    "Student happy with tone?" -> "Done - suggest wa-deploy" [label="yes"];
}
```

## Steps

### 1. Load spec and environment
Read `spec.json` and `.env`. If either is missing, send the student back.

Identify from spec:
- `archetype` → affects audience filter in `main.py`
- `tools` → which files go in `tools/`
- `handoff` → whether `tools/human_handoff.py` is created

### 2. Choose LLM (only if not already set)
If `.env` already has an LLM key from a previous run, skip. Otherwise present the student with a decision matched to their use case.

First explain the concept:
**"הסוכן צריך 'מוח' - מודל AI שיחליט מה לענות ומתי לקרוא לכלי. המחיר נמדד בטוקנים (חלקי מילים) - בוט טיפוסי זה כמה דולרים בחודש, לא יותר."**

Then pick the recommendation based on `spec.archetype`:

#### For **personal_assistant** (low volume, quality matters):

| מודל | חוזקות | חולשות | עלות ל-1000 הודעות |
|---|---|---|---|
| **Claude Haiku 4.5** 🟢 מומלץ | עברית טובה, קריאות כלים מצוינות, מהיר (~3שנ) | - | ~$2-4 |
| Claude Sonnet 4.6 | עברית הכי טובה בשוק, הכי חכם | פי 3 יקר, איטי יותר | ~$6-12 |
| GPT-5.4-mini | זול יותר, תחרותי | עברית טיפה פחות טבעית | ~$2-3 |
| Gemini 2.5 Flash | הכי זול בקטגוריה | עברית סבירה, לא מצוינת | ~$1-2 |

**ברירת מחדל: Claude Haiku 4.5** - `claude-haiku-4-5` - איזון הכי טוב.

#### For **customer_service** (higher volume, brand matters):

| מודל | חוזקות | חולשות | עלות ל-1000 הודעות |
|---|---|---|---|
| **Claude Haiku 4.5** 🟢 מומלץ | איזון מצוין, מהיר, עברית טובה | - | ~$2-4 |
| Claude Sonnet 4.6 | איכות פרימיום | יקר פי 3 | ~$6-12 |
| GPT-5.4 | תחרותי ל-Sonnet | ecosystem preference | ~$5-10 |

**ברירת מחדל: Claude Haiku 4.5** - המודל ששווה את המאמץ להתחיל ממנו. אם תגלה שחסר איכות, קל לשדרג ל-Sonnet 4.6.

#### For **budget-first** (student on a tight budget, low-volume hobby bot):

- **GPT-5.4-nano** - `gpt-5.4-nano` - ~$0.3-1 ל-1000 הודעות. אבל עברית סבירה בלבד.
- **Gemini 2.5 Flash** - גם זול. ראה טבלה.

Present the table via AskUserQuestion with 3-4 options. Default to Claude Haiku 4.5 unless the student explicitly signals budget sensitivity.

**Do NOT recommend these** (explain if student asks):
- **Claude Opus 4.6** - overkill. 4-6 שניות לתשובה = חוויה רעה ב-WhatsApp. משלמים פי 5 מ-Haiku על איכות שהסוכן לא מנצל.
- **Grok / DeepSeek** - עברית חלשה. לא מיועדים לשוק שלנו.
- **GPT-4o / Claude 3.5** - מודלים ישנים (2024/2025), הוחלפו.

Save to `.env`:
```
LLM_PROVIDER=anthropic          # or openai, google
LLM_MODEL=claude-haiku-4-5      # full model ID
ANTHROPIC_API_KEY=...           # or OPENAI_API_KEY, GOOGLE_API_KEY
```

Then guide API key creation via browser (STOP at password/payment).

**Note on prices**: the numbers above are April 2026 snapshots. Prices change. If the student asks for current pricing, check the provider's pricing page directly - don't quote from memory.

### 3. Write core files

Write each file from scratch based on `spec.json` and the acceptance criteria below. Do not use file templates — see the "Writing the Code" section below for why. The key properties each file must have:

**`.python-version`** (must be first, single line)
```
3.12.7
```
Render reads this file during build and pins the interpreter. Without it, build fails on default Render Python (3.14). **This is not optional.** Also do NOT create `runtime.txt` — Render ignores it (Heroku convention).

**`config.py`**
- Loads `.env` via `python-dotenv`
- Loads `spec.json` into a `SPEC` dict
- Exposes: `GREEN_API_URL/INSTANCE/TOKEN`, `LLM_PROVIDER/MODEL`, `API_KEY`, `DATABASE_PATH`, `MAX_HISTORY`
- Fails fast with a clear error if any required env var is missing

**`database.py`**
- SQLite with one table: `conversations(chat_id, role, content, created_at)`
- Functions: `append(chat_id, role, content)`, `tail(chat_id, n=MAX_HISTORY)`, `init_db()`
- Opens connection per-call (no pooling headaches, fine for Render scale)

**`prompt.py`**
- `build_system_prompt(spec, tool_registry) -> str`
- Composes: identity + tone + audience rules + scope rules + knowledge base + **dynamic** tool availability section
- **Dynamic tool section**: iterates `tool_registry.values()` and lists each tool's name + description. **Never hardcode the tool list.** When `wa-connect` adds a tool, the prompt updates automatically on next build without a student forgetting to announce it to the LLM.
  ```python
  def _tools_section(tool_registry):
      if not tool_registry:
          return "אין לך כלים חיצוניים כרגע. ענה מהידע שלך בלבד."
      lines = ["יש לך הכלים הבאים:"]
      for name, td in tool_registry.items():
          desc = td["schema"].get("description", "")
          lines.append(f"- `{name}`: {desc}")
      return "\n".join(lines)
  ```
- **Crucial**: embeds the handoff rule ("If the user asks for a human, call `request_human_handoff` tool") when that tool is in the registry — detect via `"request_human_handoff" in tool_registry` rather than hardcoding.

**`agent.py`**
- Single function: `handle_message(chat_id, sender_phone, message_text) -> reply_text`
- Load history via `database.tail()`, build messages list, include system prompt
- Call LLM with tools from `TOOL_REGISTRY`
- Tool-calling loop: if LLM asks for a tool, execute it, feed result back, repeat (max 5 iterations, then force a reply)
- Append user message and final reply to DB
- Return reply text
- **CRITICAL: framework-controlled parameter injection** (see below)

### Framework-controlled parameters (security + correctness)

Some tool parameters must never be chosen by the LLM — the framework owns them. Most common: `chat_id`. If the LLM picks the chat_id, it can (accidentally or via jailbreak) send a reminder to a different user, or guess the wrong format ("user's name" instead of `972XXXXXXXXX@c.us`), causing Green API 400 and silent tool failure.

Implement this pattern in `agent.py`:

```python
# Tools whose chat_id must be overridden from the webhook context,
# never from LLM-chosen arguments. Every tool that sends a message
# or schedules an action for "the current user" belongs here.
FRAMEWORK_INJECTED_CHAT_ID = {
    "schedule_reminder",
    "list_reminders",
    "cancel_reminder",
    # extended by wa-connect when human_handoff is added:
    # "request_human_handoff",
}

def _run_tool(tool_use, chat_id: str):
    tool_def = TOOL_REGISTRY[tool_use.name]
    tool_input = dict(tool_use.input or {})

    # Framework owns these, not the LLM
    if tool_use.name in FRAMEWORK_INJECTED_CHAT_ID:
        tool_input["chat_id"] = chat_id  # override

    return tool_def["fn"](**tool_input)
```

The tool schemas for these tools should **still** declare `chat_id` as required (so the LLM's tool-calling loop doesn't break), but the framework overwrites whatever value the LLM chose. Document this in the schema description: `"chat_id will be filled by the framework; leave empty"`.

**Adding a new framework-injected tool later** (e.g., during `wa-connect`): append to `FRAMEWORK_INJECTED_CHAT_ID`. This is the one exception to the "tools live in `tools/`" rule — the *set* of framework-injected names lives in `agent.py` because only the framework sees the webhook context.

**`main.py`**
- FastAPI app
- `POST /webhook/green-api` - dedupes by `idMessage` (check DB), filters by `senderData.chatId` suffix (`@g.us` for groups - skip if `answer_groups=false`), enforces whitelist if `archetype=personal_assistant`, calls `agent.handle_message`, sends reply via Green API
- `GET /health` - returns `{status: "ok", version: 1}`
- Ignores own messages (senderId == instance's own JID)

**`tools/__init__.py`**
- `TOOL_REGISTRY: dict[str, ToolDef]` where each entry has `{"schema": <LLM tool schema>, "fn": <python callable>}`
- Starts **empty** (the framework populates on import; external tools added later by `wa-connect`)

**`tools/whatsapp.py`** (framework-only, not an LLM tool)
- `send_reply(chat_id, text)` - POSTs to Green API
- `send_to_phone(phone_e164, text)` - same, but formats `chatId` correctly
- Used internally by `main.py` and by future tools (e.g. reminders calling `send_to_phone`)

### 4. Wire the reminders tool (only if `"reminders"` in spec.tools)

Reminders are the **only tool wired in `wa-build`**. Why: they use APScheduler in-process, no external auth, no extra credentials. They work the moment the server starts.

External tools (Gmail, Calendar, WhatsApp groups, human handoff, Outlook) are **not** wired here. They go through `wa-connect` after deploy. If spec lists them:
- Do **not** create `tools/google_calendar.py` yet
- Do **not** mention them in the system prompt yet
- Do **not** add them to `TOOL_REGISTRY`

If `"reminders"` is in `spec.tools`, write `tools/reminders.py` with:
- `create_reminder(chat_id, remind_at_iso, message)` — schedules an APScheduler job
- `list_reminders(chat_id)` — returns pending reminders for a chat
- `cancel_reminder(reminder_id)` — removes a job
- SQLAlchemy jobstore pointed at the same SQLite file as `DATABASE_PATH` (survives restart)
- Register in `TOOL_REGISTRY` on import
- The system prompt mentions reminders are available

**Why this minimalism matters**: the student will see a reply to their "היי" within minutes of deploy. If external tools were half-wired, the LLM would try to call them and fail with cryptic errors. Better to expose the LLM to only what's real.

### 5. Dependencies
`requirements.txt` pinned (update pins to current stable versions — check PyPI, don't paste stale versions):
```
fastapi
uvicorn[standard]
python-dotenv
httpx
apscheduler
pydantic

# Exactly one of these, based on LLM_PROVIDER:
anthropic          # if using Claude (Haiku 4.5 / Sonnet 4.6)
# openai           # if using GPT
# google-genai     # if using Gemini
```

Claude Code should pin to current stable versions at generation time. Don't ship unpinned to production, but also don't freeze to a 6-month-old version.

Run `pip install -r requirements.txt`. If Python/pip missing, guide install via computer-use.

### 6. Local smoke test
Start the server:
```
cd [project-dir]
uvicorn main:app --reload --port 8000
```

Send a fake inbound webhook:
```
curl -X POST http://localhost:8000/webhook/green-api \
  -H "Content-Type: application/json" \
  -d '{
    "typeWebhook": "incomingMessageReceived",
    "idMessage": "smoke-test-1",
    "timestamp": 1712000000,
    "senderData": {"chatId": "972501234567@c.us", "senderName": "סטודנט"},
    "messageData": {"typeMessage": "textMessage", "textMessageData": {"textMessage": "היי"}}
  }'
```

Check the server logs for the reply and that it was sent to Green API (or mocked if the bot's outbound isn't critical yet).

### 7. Show the student

**"זה מה שהבוט ענה לשלום 'היי':"**

Print the reply. Ask: **"זה הסגנון שרצית? יש משהו לדייק?"**

### 8. Iterate (fine-tune loop)
If the student isn't happy:
- Small tweaks (tone, length) → edit `spec.json` directly, regenerate `prompt.py`, rerun smoke test
- Large changes (scope, audience) → send back to `wa-characterize`

Keep the iteration loop tight - don't rewrite files the student hasn't asked about.

### 9. Memory persistence warning

**Before** handing off to deploy, warn the student about what will happen to conversations and reminders:

**"משהו שחשוב לדעת לפני שמעלים לאוויר:"**

Explain based on what's likely:
- **Render Free tier without disk**: "השיחות והתזכורות יחיו במזה שהבוט לא מתאתחל. Render עושה restart אוטומטית בערך כל 12 שעות, ואז הכל נמחק. זה לא באג - זה איך Render Free עובד."
- **Render Free + Disk ($0.25/mo)**: "עם disk קטן, הכל נשמר. מומלץ."
- **Supabase/Postgres חיצוני**: "הכי עמיד, גם חינמי. מתאים לבוט שיהיה בפרודקשן לטווח ארוך."

**"אחרי שנעלה לאוויר, אם תרצה זיכרון קבוע - נעשה את זה דרך הסקיל `wa-persistence`. עכשיו, קדימה לעלות."**

Record the memory-persistence decision (or the lack of one) in `.wa-state.json` as `persistence_choice`:
- `"ephemeral"` — student chose not to worry about it yet (bot will forget on restart)
- `"disk_planned"` — will add Render Disk in deploy
- `"external_db_planned"` — will use `wa-persistence` after deploy

This flag lets `wa-deploy` and `wa-maintain` know what the student intended.

### 10. Update state & hand off

Update `.wa-state.json`:
- Append `"build"` to `completed_stages`
- Set `current_stage: "deploy"` (always — external tools come after deploy)
- Set `persistence_choice` from step 9
- Update `last_touched_iso`

Then, regardless of what's in `spec.tools`:

**"הקוד מוכן. הבוט מדבר איתך מקומית ומכיר את עצמו. השלב הבא: להעלות אותו לאוויר כדי שתוכל לדבר איתו בוואטסאפ אמיתי. אחרי זה נחבר את הכלים (יומן/מייל/וכו') אחד-אחד. רוצה להמשיך?"**

- If yes → invoke `wa-deploy` via Skill tool
- If "תן לי רגע" → **"סגור. `/wa` כשתחזור."**

**Important**: even if `spec.tools` includes Gmail/Calendar/groups, the student **first deploys**, then comes back through `/wa` to `wa-connect` to add each tool. Don't offer to skip ahead — it's bad for debugging.

## Writing the Code

Do not use file templates. Claude Code writes each file from scratch, informed by `spec.json` and the file-layout contract above. Reasons:

- Templates drift out of date; libraries update, best practices evolve
- Claude Code is capable of producing clean FastAPI + SDK code directly when the *contract* (what each file must do) is clear
- Every student's bot is slightly different - hard-coded placeholders obscure this

The contract for each file is documented in the **"Write core files"** section above. Follow those bullet points as acceptance criteria. If a file doesn't satisfy its bullets, it's incomplete.

Generate the final `SYSTEM_PROMPT` by composing naturally-readable Hebrew/English paragraphs from spec sections (identity, tone, audience rules, scope, knowledge, tool availability). The prompt should read like something a human wrote for this specific bot, not like string-interpolated spec fields.

## Error Handling

| Problem | Solution |
|---------|----------|
| No `spec.json` | Run `wa-characterize` first |
| No `.env` | Run `wa-setup` first |
| `pip install` fails | Check Python version (needs 3.11+), try `pip3`, suggest venv |
| `uvicorn` not starting | Check port conflict, print error |
| LLM auth error | Wrong API key or no funds - guide to billing |
| Smoke test: no reply | Check server logs for traceback, usually wrong env var |
| Smoke test: reply in wrong language | Prompt issue - add explicit language instruction to spec and regenerate |
| Student wants to use Agno/Langchain/CrewAI | Politely decline with one sentence: "לקורס הזה אנחנו רוצים קוד שאתה יכול לקרוא כל שורה שלו - פריימוורקים מוסיפים שכבות קסם שקשות לדיבוג. אם תרצה בעתיד, קל להחליף - הארכיטקטורה מודולרית." |

## Architectural Notes (for Claude Code's reference)

- **Why `prompt.py` as a separate file**: the prompt changes every time the spec does. Keeping it isolated means `wa-maintain` can regenerate it without touching logic. Also, students can read it and *understand* their bot - literally print it at `/health?debug=prompt`.
- **Why tool stubs that `raise NotImplementedError`**: early visibility. The LLM will call tools that aren't wired up, the student gets a clear error pointing at `wa-connect`, and we avoid silent fallback misbehavior.
- **Why 5-iteration tool loop cap**: LLMs occasionally loop on tool calls. Cap prevents runaway cost on Render. Log and force a text reply on cap.
- **Why APScheduler in-process and not a Render Cron**: Render Crons are billed separately and awkward for per-user reminders ("remind me in 10 minutes"). In-process with SQLite jobstore survives restarts and costs nothing.
- **Why `idMessage` dedup in DB, not in memory**: Render restarts lose memory. We'd replay the last message on every restart. One extra SQL lookup per webhook is cheap.
- **Why whitelist enforcement in `main.py` not prompt**: non-bypassable. A prompt can be jailbroken - a Python `if sender not in whitelist: return` cannot.
- **Why not emit MCP server from this bot**: maybe later. Not in MVP. `fastapi-mcp` could auto-generate one from existing routes if ever needed.
