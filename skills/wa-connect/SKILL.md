---
name: wa-connect
description: "Wire a tool (Google Calendar, Gmail, WhatsApp groups, Human handoff, Outlook) into a deployed WhatsApp agent. Use after wa-deploy when the student is ready to give the bot capabilities, or says 'wa-connect', 'חבר כלי', 'חבר יומן', 'חבר מייל', 'חבר קבוצות', 'תוסיף כלי לסוכן'. Each invocation wires exactly ONE tool and redeploys. Run multiple times to add multiple tools. Handles auth, credential storage, tool implementation, redeploy, and live verification."
---

# Connect a Tool to the Agent

Give the live agent a new capability. Handles auth, writes the tool implementation into `tools/<tool>.py`, registers it in `TOOL_REGISTRY`, pushes to GitHub, waits for Render to redeploy, and verifies end-to-end with a real WhatsApp message.

**This skill is a router.** It asks which tool, runs the matching sub-flow, then pushes + redeploys. Each sub-flow shares the same pattern: *auth → credentials → implementation → register → push → redeploy → verify*.

**Prerequisites:**
- `wa-deploy` completed (bot is live on Render, `.wa-state.json` has `render_url`)
- Student can talk to the bot in real WhatsApp already

**This skill runs ONCE per tool.** If the spec lists three external tools, the student runs `wa-connect` three times. This is by design — each tool has its own OAuth/credentials/verification cycle, and batching them makes debugging impossible.

## Interaction Style

Simple Hebrew with the student. Claude Code drives the integration - browser for OAuth, terminal for code. The student clicks "approve" in Google, pastes a token when asked, and watches the verification succeed.

## The Connections

| Tool | Auth type | External service | Difficulty for student |
|---|---|---|---|
| **google_calendar** | Google OAuth 2.0 (refresh token) | Google Cloud project | Medium - one-time OAuth consent |
| **gmail** | Google OAuth 2.0 (same refresh token as calendar!) | Same Google Cloud project | Easy if calendar already done |
| **whatsapp_groups** | Green API credentials (already in `.env`) | Green API | Trivial - no new auth |
| **human_handoff** | Green API (already in `.env`) | Green API | Trivial |
| **outlook_calendar** 🔶 | Microsoft OAuth + **rotating refresh tokens** | Azure App Registration + Postgres/Redis for token storage | **Advanced** - extra infra required |
| **outlook_mail** 🔶 | Same Microsoft OAuth as outlook_calendar | Same Azure App | **Advanced** - extra infra required |

🔶 = advanced. Requires persistent DB beyond SQLite file. Default to Google if the student is new.

**Note on reminders**: the reminders tool is wired in `wa-build`, not here. It's native to the bot (APScheduler in-process, no external auth). It already works when the student hits `wa-connect`. If the student asks about reminders here, redirect: "התזכורות כבר עובדות מאז שהבוט עלה - נסה 'תזכיר לי בעוד דקה לבדוק'."

## Architecture Decisions (fixed for all sub-flows)

These match `wa-build`'s opinionated stack. Deviations break other skills.

1. **Google integrations use `google-api-python-client`** - official, stable, low-surface.
2. **Microsoft integrations use `msal` + `httpx`** (not `msgraph-sdk`) - lower abstraction, students can read it, fits the course's "no framework magic" principle.
3. **One Google OAuth client for Gmail + Calendar + any future Google service** - minimizes the student's OAuth consent screen exposure. Same pattern for Microsoft: one Azure app covers Mail + Calendar.
4. **Google refresh token stored in `.env` as `GOOGLE_REFRESH_TOKEN`** - long-lived, simple.
5. **Microsoft refresh tokens stored in Postgres `user_tokens` table** - they rotate every use, so `.env` doesn't work. Triggers the Postgres dependency only if the student picks Outlook.
6. **Tool schemas follow Anthropic/OpenAI native tool-calling format** - no framework wrapper.
7. **Every tool registers itself on import in `tools/__init__.py`** - one import line per connection.
8. **WhatsApp groups tool reads Green API `getChatHistory`** - no message-by-message polling, just fetch on demand.
9. **Reminders tool uses APScheduler with SQLAlchemy jobstore pointing at the same SQLite file** - survives restart.
10. **Never mix Google and Microsoft for the same user** in production - two tools both named "calendar" confuses the LLM. If a student needs both (rare), the tool names must disambiguate: `list_google_events` and `list_outlook_events`.

## Flow

```dot
digraph wa_connect {
    rankdir=TB;
    "Which tool?" [shape=diamond];
    "Google Calendar" [shape=box];
    "Gmail" [shape=box];
    "WhatsApp groups" [shape=box];
    "Reminders" [shape=box];
    "Human handoff" [shape=box];
    "Google auth\n(once)" [shape=box];
    "Write tool file" [shape=box];
    "Register in TOOL_REGISTRY" [shape=box];
    "Restart server\n+ verify with real message" [shape=box];
    "Done - offer another connection\nor suggest wa-deploy" [shape=doublecircle];

    "Which tool?" -> "Google Calendar";
    "Which tool?" -> "Gmail";
    "Which tool?" -> "WhatsApp groups";
    "Which tool?" -> "Reminders";
    "Which tool?" -> "Human handoff";
    "Google Calendar" -> "Google auth\n(once)";
    "Gmail" -> "Google auth\n(once)";
    "Google auth\n(once)" -> "Write tool file";
    "WhatsApp groups" -> "Write tool file";
    "Reminders" -> "Write tool file";
    "Human handoff" -> "Write tool file";
    "Write tool file" -> "Register in TOOL_REGISTRY";
    "Register in TOOL_REGISTRY" -> "Restart server\n+ verify with real message";
    "Restart server\n+ verify with real message" -> "Done - offer another connection\nor suggest wa-deploy";
}
```

## Step 0: Route

Ask the student:

**"איזה כלי לחבר עכשיו? (נעשה אחד בכל פעם)"**

Present the menu from the spec's `tools` list, skipping already-connected ones (check if `tools/<name>.py` exists and imports cleanly).

**If the student picks Outlook/Microsoft** - before routing, say this explicitly:

**"שים לב - חיבור ל-Outlook יותר מורכב מגוגל. למה? הטוקן של מיקרוסופט פג כל 14 יום ומתעדכן בכל שימוש, אז אי אפשר לשמור אותו ב-`.env` כמו בגוגל - צריך מסד נתונים אמיתי. אם יש לך גם חשבון גוגל, ההמלצה שלי היא להתחבר אליו במקום. אם אתה חייב Outlook (כי ככה מתנהלת העבודה שלך) - יאללה, נעבור יחד שלב אחר שלב, יהיה בסדר."**

Wait for confirmation before proceeding to Sub-flow E.

Jump to the matching sub-flow below.

---

## Sub-flow A: Google Calendar or Gmail

(These share the same Google auth. If the other one was already set up, skip to step A4.)

### A1. Explain once
**"יומן/Gmail של Google דורשים הרשאה חד-פעמית - בעצם אתה אומר לגוגל 'אני מאשר לבוט הזה לקרוא את היומן שלי'. זה מתבצע בדפדפן, ואחרי שאישרת פעם אחת, הבוט מקבל מפתח ארוך-טווח ושומר אותו אצלו. אתה יכול לבטל את ההרשאה כל רגע דרך הגדרות Google."**

### A2. Google Cloud project
Check if `GOOGLE_CLIENT_ID` already exists in `.env`. If yes, skip to A3.

Otherwise:
- Open https://console.cloud.google.com in the browser
- **STOP for login**: student signs in with the Google account that owns the calendar/mail the bot will access
- Create a new project called `whatsapp-agent-[bot_name]`
- Enable APIs: Gmail API, Google Calendar API (both, even if only one is needed now - makes future connection free)
- Go to "APIs & Services → OAuth consent screen"
  - User type: **External**
  - App name: `[bot_name] WhatsApp Agent`
  - User support email: student's email
  - Scopes: `.../auth/calendar.events`, `.../auth/gmail.readonly`, `.../auth/gmail.send` (if Gmail send enabled in spec)
  - Test users: add the student's own email (until published, OAuth flow only works for test users)
- Go to "APIs & Services → Credentials"
  - Create OAuth client ID
  - Application type: **Desktop app**
  - Download the JSON credentials file

**"תוריד את קובץ ה-JSON שקיבלת מ-Google. אני שומר אותו אצלך בפרויקט ואז עושה את תהליך ההרשאה."**

Save the JSON as `google_client_secret.json` in the project dir. Add it to `.gitignore` immediately.

### A3. OAuth flow (get refresh token)
Write `scripts/google_auth.py` with the pattern below. **Two critical flags** prevent the two most common failure modes:

- `access_type="offline"` — required or Google returns no refresh token
- `prompt="consent"` — forces re-consent even if the student previously authorized this app (without this, returning users often get `creds.refresh_token = None`)

```python
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    # add "https://www.googleapis.com/auth/gmail.send" if Gmail send in spec
]

flow = InstalledAppFlow.from_client_secrets_file("google_client_secret.json", SCOPES)

# Try local server first (browser auto-opens, token captured automatically).
# If port 8765 is blocked by firewall/AV/corporate network → fall back to console
# mode where the student pastes the auth code manually.
try:
    creds = flow.run_local_server(
        port=8765,
        access_type="offline",
        prompt="consent",
    )
except OSError as e:
    print(f"Local server failed ({e}); falling back to console mode.")
    print("Open the URL printed below in your browser, approve, then paste the code here.")
    creds = flow.run_console()

if not creds.refresh_token:
    raise SystemExit(
        "No refresh_token returned. This usually means you previously authorized "
        "this app. Go to https://myaccount.google.com/permissions, remove the app, "
        "and run this script again."
    )

print("REFRESH TOKEN:", creds.refresh_token)
print("CLIENT ID:", flow.client_config["client_id"])
print("CLIENT SECRET:", flow.client_config["client_secret"])
```

**STOP** when the browser opens: **"עכשיו גוגל שואלת אותך אם לאשר. יופיע מסך אדום 'Google hasn't verified this app' - זה נורמלי, זו האפליקציה שלך. לחץ 'Advanced' (בפינה שמאל תחתית) → 'Go to [app] (unsafe)'. אחר כך תאשר את ההרשאות."**

**If the local server fallback triggers** (port blocked): explain to the student: **"חומת האש חוסמת את גוגל מלחזור אלינו אוטומטית. זה בסדר - אני אתן לך קישור, אתה תאשר, ותעתיק קוד בחזרה אליי. עובד תמיד."**

After approval, script prints three values. Append to `.env`:
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
```

Delete `google_client_secret.json` - it's no longer needed (refresh token is in `.env`).

### A4. Write tool implementation

Write `tools/google_calendar.py` (or `tools/gmail.py`) from scratch. Claude Code composes the file directly — no file templates. The expected shape (same for both):
```python
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from config import settings

def _service():
    creds = Credentials(
        token=None,
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("calendar", "v3", credentials=creds)  # or "gmail", "v1"

def list_events(time_min_iso: str, time_max_iso: str) -> list[dict]:
    ...

SCHEMA = {
    "name": "list_calendar_events",
    "description": "List events on the user's calendar between two ISO-8601 timestamps.",
    "input_schema": {...}
}

TOOL = {"schema": SCHEMA, "fn": list_events}
```

Tool functions to implement per service:

**Calendar**:
- `list_events(time_min, time_max)` → upcoming events
- `create_event(summary, start_iso, end_iso, attendees=None)` → new event
- `delete_event(event_id)` → cancel

**Gmail (read_only)**:
- `search_emails(query, max_results=10)` → subject/from/snippet list
- `get_email(message_id)` → full body
- `mark_read(message_id)` → remove unread label

**Gmail (with send, if spec enables)**:
- All of above
- `send_email(to, subject, body, html=False)`

### A5. Register
Edit `tools/__init__.py` - add one line:
```python
from .google_calendar import TOOL as CALENDAR_TOOL
TOOL_REGISTRY["list_calendar_events"] = CALENDAR_TOOL
TOOL_REGISTRY["create_calendar_event"] = {...}  # if exposing multiple functions, one per tool
```

### A6. Restart and verify
Restart the server. Send a real WhatsApp message from the student's phone to the bot:
**"מה יש לי היום ביומן?"** (for calendar) or **"יש לי מיילים חדשים?"** (for gmail).

Watch server logs to confirm the tool was called. Confirm the bot replied with actual data.

If the LLM doesn't call the tool: the prompt needs a nudge. Add to `prompt.py`:
`"You have access to the user's Google Calendar via list_calendar_events, create_calendar_event. Use them when the user asks about schedule, meetings, availability."`

Restart, retry.

---

## Sub-flow B: WhatsApp Groups

### B1. Identify target groups
**"לאילו קבוצות הבוט צריך גישה? תן לי שמות. צריך להבין שהבוט צריך להיות חבר בקבוצה - הוא לא יכול לקרוא קבוצות שהוא לא בהן."**

Get a list of group names from the student.

### B2. Get chat IDs
Green API exposes group chat IDs via `getChats`:
```
GET https://[API_URL]/waInstance[ID]/getChats/[TOKEN]
```

Filter results where `id` ends with `@g.us` and `name` contains the student's target names.

Add the bot to each group first if it isn't already:
**"תוסיף את המספר של הבוט לקבוצה '[name]' כחבר רגיל. ברגע שהוא חבר, הוא יוכל לקרוא."**

Record `group_ids` in the project - add to `spec.json`:
```json
"tools_config": {
  "whatsapp_groups": {
    "allowed_groups": [
      {"name": "משפחה", "chat_id": "123456789@g.us"}
    ]
  }
}
```

### B3. Write tool
`tools/whatsapp_groups.py`:
```python
import httpx
from config import settings

def list_group_history(group_name: str, last_n: int = 50) -> list[dict]:
    chat_id = _resolve_group_name(group_name)
    url = f"{settings.GREEN_API_URL}/waInstance{settings.GREEN_API_INSTANCE}/getChatHistory/{settings.GREEN_API_TOKEN}"
    r = httpx.post(url, json={"chatId": chat_id, "count": last_n})
    return [{"from": m.get("senderName"), "text": m.get("textMessage"), "ts": m.get("timestamp")} for m in r.json()]
```

`_resolve_group_name` reads `spec.json` → `allowed_groups` for the mapping.

**Why name resolution**: the LLM talks in names ("קבוצת משפחה"), the API wants IDs. One place to translate.

### B4. Register and verify
Register in `TOOL_REGISTRY`. Test: **"מה היה בקבוצת המשפחה?"**

---

## Sub-flow C: Reminders

### C1. No auth needed
**"תזכורות לא דורשות שום חיבור חיצוני - הבוט מנהל אותן אצלו."**

### C2. Write tool
`tools/reminders.py`:
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from config import settings
from tools.whatsapp import send_to_phone

scheduler = BackgroundScheduler(jobstores={
    "default": SQLAlchemyJobStore(url=f"sqlite:///{settings.DATABASE_PATH}")
})

def create_reminder(chat_id: str, remind_at_iso: str, message: str) -> str:
    job = scheduler.add_job(
        send_to_phone,
        trigger="date",
        run_date=remind_at_iso,
        args=[chat_id, f"🔔 תזכורת: {message}"],
    )
    return job.id

def list_reminders(chat_id: str) -> list[dict]:
    return [
        {"id": j.id, "at": j.next_run_time.isoformat(), "message": j.args[1]}
        for j in scheduler.get_jobs() if j.args[0] == chat_id
    ]

def cancel_reminder(reminder_id: str) -> bool:
    scheduler.remove_job(reminder_id)
    return True
```

### C3. Start the scheduler
Edit `main.py` startup to call `scheduler.start()` on app startup, `scheduler.shutdown()` on shutdown.

### C4. Register and verify
**"תזכיר לי בעוד דקה לצאת לשתות קפה."**

Wait a minute. Reminder should arrive. Works → done. Doesn't → check scheduler logs, often timezone issue (APScheduler defaults to UTC; ensure `run_date` is timezone-aware).

---

## Sub-flow D: Human Handoff

### D1. Confirm mode from spec
Read `spec.handoff.mode`: one of `phone_number_relay`, `notification`, or `both`. If not set, ask now.

### D2. Write tool
`tools/human_handoff.py`:
```python
from tools.whatsapp import send_to_phone
from config import settings

def request_human(customer_chat_id: str, customer_phone: str, customer_name: str, reason: str) -> str:
    manager = settings.HANDOFF_MANAGER_PHONE
    msg = f"🆘 לקוח רוצה נציג אנושי\nשם: {customer_name}\nטלפון: {customer_phone}\nסיבה: {reason}\n\nצור איתו קשר מהמספר שלך (לא מהבוט)."
    send_to_phone(manager, msg)
    return f"מעביר אותך לנציג אנושי. הוא יחזור אליך בהקדם מהמספר {manager[-4:]}****"
```

The returned string is what the LLM surfaces to the customer.

### D3. Register and verify
Test: **"אני רוצה לדבר עם נציג אנושי."**

Confirm manager got the notification with customer's details. The customer's reply should be the message returned from the tool.

---

## Sub-flow E: Outlook (Microsoft 365) — Advanced

**Only run this if the student explicitly chose Outlook over Google.** The skill-level warning in Step 0 should have already set expectations.

### E1. Re-confirm and explain the cost
**"בוא נוודא שאנחנו רוצים להמשיך: החיבור הזה מוסיף שני דברים שלא היו בגוגל:"**
1. **רישום אפליקציה ב-Azure** - דומה לגוגל אבל עם קצת יותר קליקים
2. **מסד נתונים חיצוני (Postgres)** - כי הטוקן מתעדכן כל פעם. `.env` לא מספיק.

**"אתה סומך על זה או שעדיף לעצור ולחשוב?"** Give the student a real out.

### E2. Provision Postgres (Render has a free tier option)
Before Azure, make sure the infrastructure is ready:
- Open https://render.com/dashboard
- Create → Postgres → Free tier (1GB, sufficient)
- Copy the External Database URL (starts with `postgresql://`)

Add to `.env`:
```
DATABASE_URL_PG=postgresql://user:pass@host:port/dbname
```

Create a `user_tokens` table (one row per external service per user). Simple schema:
```sql
CREATE TABLE user_tokens (
    service TEXT NOT NULL,          -- 'microsoft'
    user_key TEXT NOT NULL,         -- phone number or stable user id
    refresh_token TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (service, user_key)
);
```

Claude Code writes a migration helper `scripts/init_pg.py` and runs it once.

### E3. Azure App Registration
- Open https://entra.microsoft.com (Microsoft Entra admin center)
- **STOP for login**: student signs in with the Microsoft account that owns the mail/calendar
- App registrations → **New registration**
- Name: `[bot_name]-whatsapp`
- Supported account types: **"Accounts in any organizational directory and personal Microsoft accounts"**
  - This single option covers `@outlook.com`, `@hotmail.com`, and most `@company.com` tenants
- Redirect URI: **Web** → `http://localhost:8765/callback`
- Register

After registration, note three values from the app overview page:
- **Application (client) ID** → `MS_CLIENT_ID`
- **Directory (tenant) ID** → set `MS_TENANT_ID=common` for multi-account support (simpler than the specific tenant ID)

Go to **Certificates & secrets** → **New client secret**:
- Description: `whatsapp-agent-prod`
- Expires: 24 months
- Click **Add**, then **immediately copy the Value** (not the ID) → `MS_CLIENT_SECRET`

**"זה היחיד שצריך לעשות בצורה יחידה - הערך של הסוד מופיע פעם אחת ונעלם. אם פספסת, תצטרך ליצור סוד חדש."**

Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
- `offline_access` (critical - without this, no refresh token at all)
- `Mail.ReadWrite`
- `Mail.Send` (only if spec enables Gmail/mail send)
- `Calendars.ReadWrite`
- `User.Read`

Click **Grant admin consent** if the student is the tenant admin (for personal accounts, skip — individual consent works at sign-in).

### E4. OAuth flow (MSAL)
Write `scripts/microsoft_auth.py` (Claude Code composes it; the example below is the reference shape):

```python
from msal import ConfidentialClientApplication
import webbrowser, urllib.parse, http.server, threading, os

app = ConfidentialClientApplication(
    client_id=os.environ["MS_CLIENT_ID"],
    client_credential=os.environ["MS_CLIENT_SECRET"],
    authority=f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}",
)

SCOPES = ["offline_access", "Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "User.Read"]
auth_url = app.get_authorization_request_url(SCOPES, redirect_uri="http://localhost:8765/callback")
webbrowser.open(auth_url)

# tiny local server to catch the ?code=... redirect
code_holder = {}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        code_holder["code"] = urllib.parse.parse_qs(q).get("code", [None])[0]
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Done - you can close this tab")
threading.Thread(target=lambda: http.server.HTTPServer(("", 8765), H).handle_request(), daemon=True).start()

while "code" not in code_holder:
    pass

result = app.acquire_token_by_authorization_code(
    code_holder["code"], scopes=SCOPES, redirect_uri="http://localhost:8765/callback"
)
print("REFRESH TOKEN:", result["refresh_token"])
```

**STOP**: "יפתח דפדפן. אשר את ההרשאה. אם יש חלון של 'Need admin consent' זה אומר שהחשבון שלך הוא תחת ארגון שחוסם אפליקציות חיצוניות - תצטרך לבקש מה-IT לאשר או להשתמש בחשבון אישי."

After success, save the initial refresh token to Postgres (NOT `.env` — it will rotate):
```python
# in scripts/microsoft_auth.py after receiving result:
save_token("microsoft", student_phone_e164, result["refresh_token"])
```

### E5. Write tools with rotation handling
`tools/outlook_calendar.py` and `tools/outlook_mail.py`.

Critical pattern: **every API call fetches-and-rotates** the token:

```python
from msal import ConfidentialClientApplication
import httpx
from tools.token_store import get_token, save_token  # new helper module
from config import settings

_msal = ConfidentialClientApplication(
    client_id=settings.MS_CLIENT_ID,
    client_credential=settings.MS_CLIENT_SECRET,
    authority=f"https://login.microsoftonline.com/{settings.MS_TENANT_ID}",
)

def _access_token(user_key: str) -> str:
    refresh = get_token("microsoft", user_key)
    result = _msal.acquire_token_by_refresh_token(
        refresh, scopes=["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite"]
    )
    if "refresh_token" in result:  # Microsoft rotates it
        save_token("microsoft", user_key, result["refresh_token"])
    return result["access_token"]

def list_events(user_key: str, start_iso: str, end_iso: str) -> list[dict]:
    token = _access_token(user_key)
    r = httpx.get(
        "https://graph.microsoft.com/v1.0/me/calendar/calendarView",
        params={"startDateTime": start_iso, "endDateTime": end_iso},
        headers={"Authorization": f"Bearer {token}"},
    )
    return r.json().get("value", [])
```

`tools/token_store.py` wraps Postgres access:
```python
import psycopg
from config import settings

def get_token(service: str, user_key: str) -> str:
    with psycopg.connect(settings.DATABASE_URL_PG) as conn:
        row = conn.execute(
            "SELECT refresh_token FROM user_tokens WHERE service=%s AND user_key=%s",
            (service, user_key),
        ).fetchone()
    if not row:
        raise RuntimeError(f"No token for {service}:{user_key} - run OAuth setup first")
    return row[0]

def save_token(service: str, user_key: str, refresh_token: str) -> None:
    with psycopg.connect(settings.DATABASE_URL_PG) as conn:
        conn.execute(
            """INSERT INTO user_tokens (service, user_key, refresh_token, updated_at)
               VALUES (%s, %s, %s, NOW())
               ON CONFLICT (service, user_key) DO UPDATE
               SET refresh_token=EXCLUDED.refresh_token, updated_at=NOW()""",
            (service, user_key, refresh_token),
        )
        conn.commit()
```

Tool functions to implement — exact parity with Google:

**Calendar**: `list_events`, `create_event`, `delete_event`
**Mail**: `search_emails`, `get_email`, `mark_read`, `send_email` (if enabled)

All Graph endpoints are under `https://graph.microsoft.com/v1.0/me/...`.

### E6. Register
`tools/__init__.py`:
```python
from .outlook_calendar import TOOL as OUTLOOK_CAL
from .outlook_mail import TOOL as OUTLOOK_MAIL
TOOL_REGISTRY["list_outlook_events"] = OUTLOOK_CAL
TOOL_REGISTRY["search_outlook_mail"] = OUTLOOK_MAIL
# ...
```

### E7. Verify
Same pattern as Google - send a WhatsApp message:
**"מה יש לי היום ב-Outlook?"** or **"מיילים חדשים?"**

Watch logs for:
- Token fetched from Postgres
- Graph API call succeeded
- (after 14+ days) Token rotation actually saved a new refresh token

### E8. Operational warning to the student
**"חשוב לדעת: אם הבוט לא יפעל 30 יום ברצף, הטוקן של Microsoft ימות ותצטרך לעשות את תהליך ה-OAuth מחדש (שלב E4). זה שונה מגוגל שבו הטוקן עובד לנצח עד שתבטל אותו ידנית."**

### E9. (Optional) Auto-refresh keeper
If concerned about inactivity expiring tokens, add a daily APScheduler job that calls `_access_token` for every user in `user_tokens` - touches each token daily, keeps it alive indefinitely:

```python
scheduler.add_job(
    refresh_all_microsoft_tokens,
    trigger="cron", hour=3, minute=0,  # 3am daily
    id="ms_token_keeper"
)
```

Recommend this if the bot has <10 users; skip if larger (Graph API rate limits).

---

## After Any Sub-flow - Update state & hand off

Update `.wa-state.json`:
- Append the connected tool name to `connected_tools` (dedupe)
- Keep `current_stage: "connect"` if there are more tools in `spec.tools` not yet in `connected_tools`
- Otherwise set `current_stage: "deploy"`
- Update `last_touched_iso`

Then:

**"הכלי [X] מחובר ועובד."**

Check remaining tools = `spec.tools - connected_tools`:

**If remaining tools exist:**
**"נשארו [list]. רוצה לחבר עוד אחד עכשיו?"**
- If yes → re-enter this skill (route via Step 0 to the next sub-flow)
- If "מספיק לי כרגע" → offer to deploy now: **"אפשר לעלות לאוויר ולחבר את השאר אחר כך - רוצה?"**

**If all tools connected:**
**"כל הכלים מחוברים. השלב הבא: להעלות את הסוכן לאוויר. רוצה להמשיך?"**
- If yes → invoke `wa-deploy` via Skill tool
- If "תן לי רגע" → **"סגור. `/wa` כשתחזור."**

## Error Handling

| Problem | Solution |
|---------|----------|
| Google OAuth "unverified app" warning scares student | Explain: this is their own app, not someone else's. Click Advanced → Proceed. Won't appear again after first approval. |
| Refresh token comes back as `None` | The A3 script already uses `access_type="offline"` + `prompt="consent"`. If still empty, student has a stale authorization - tell them to go to https://myaccount.google.com/permissions, remove the app, and re-run the script. |
| `OSError: [Errno 48] Address already in use` on port 8765 | Another process has the port. The script's try/except already falls back to `run_console`. If both fail: kill whatever's on 8765 (`lsof -i :8765 \| grep LISTEN`) or change the port number. |
| Browser doesn't auto-open (headless/SSH/corporate) | The `run_console` fallback handles this. Student gets a URL to open manually and pastes the code back. |
| Firewall/antivirus blocks localhost redirect | `run_console` fallback. Explain to student: "חומת האש חוסמת, נעבור למצב ידני". |
| `refresh token not valid` at runtime | Student revoked access, or token >6mo old without use. Rerun step A3. |
| Gmail 403 on send | Check spec includes `gmail.send` scope. If added late, re-run OAuth with new scope. |
| Group `getChatHistory` returns empty | Bot isn't a member yet, or never saw messages while online. Wait for new messages, or accept empty history until activity. |
| APScheduler fires at wrong time | Timezone - ensure `run_date` is `datetime.now(tz=...)` aware |
| Manager never receives handoff notification | `HANDOFF_MANAGER_PHONE` env var missing or wrong format (country code, no +) |
| LLM never invokes the tool | Prompt doesn't mention tool availability - edit `prompt.py`, restart, retry |

## Architectural Notes (for Claude Code's reference)

- **Why Google Calendar + Gmail share auth**: one OAuth app, one consent screen, one refresh token covering multiple scopes. Reduces student friction from N flows to 1.
- **Why we don't use a Google service account**: service accounts can't access a personal Gmail or Calendar. Domain-wide delegation exists but requires a Google Workspace admin - out of scope for a personal assistant.
- **Why `_resolve_group_name` lives in the tool file, not in the LLM**: LLMs are bad at consistent string → ID mapping. Hardcoding the translation in Python makes it deterministic.
- **Why APScheduler instead of `time.sleep` in background thread**: survives restarts (Render redeploys every few hours on free tier). `time.sleep` loses all pending reminders on every restart.
- **Why the handoff tool returns a string to the LLM**: the LLM's reply to the customer should reflect that a human is coming. A synchronous tool return lets the LLM compose a natural message instead of the customer getting a canned "handed off" reply.
- **Why `outgoingAPIMessageWebhook=no` matters for handoff**: when the bot sends the notification *to the manager*, Green API would otherwise webhook back to the bot - and the bot would try to process it. `wa-setup` step 7 already disabled this. Sanity-check it's still off if handoff misbehaves.
- **MCP is not used in any sub-flow.** We considered it. MCP is for Claude Code / Claude Desktop clients, not for a FastAPI webhook. Direct SDK is simpler and faster here.
- **Each sub-flow is idempotent.** Running `wa-connect` again for an already-connected tool should detect it and offer to reconfigure instead of duplicating entries.
