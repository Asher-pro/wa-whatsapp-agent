# Sub-flow E: Outlook (Microsoft 365) — Advanced

Loaded by `wa-connect` only when the student explicitly chose Outlook over Google. The
Step 0 warning in `SKILL.md` should already have set expectations.

Facts: F-MS-REFRESH-LIFETIME, F-MS-ENTRA-REGISTRATION, F-MSAL (in `knowledge/facts.md`).
The Entra admin center changes its labels often — follow the freshness protocol before E3.

## E1. Re-confirm and explain the cost
**"בוא נוודא שאנחנו רוצים להמשיך: החיבור הזה מוסיף שני דברים שלא היו בגוגל:"**
1. **רישום אפליקציה ב-Azure** - דומה לגוגל אבל עם קצת יותר קליקים
2. **זיכרון קבוע לבוט** - כי הטוקן של מיקרוסופט מתחלף בכל שימוש, צריך לשמור אותו במסד נתונים אמיתי. `.env` לא מספיק.

**"אתה סומך על זה או שעדיף לעצור ולחשוב?"** Give the student a real out.

## E2. Durable storage first (no separate database)

Microsoft refresh tokens **rotate on every use** (F-MS-REFRESH-LIFETIME), so the bot must
store the newest one where it survives restarts: the bot's own database.

- `persistence_choice` is `supabase` or `render_pg` → good, continue.
- `disk` or anything else → the one-time consent script (E4) runs on the student's laptop and must write into the **same** database the deployed bot reads. A Render disk can't be reached from the laptop, so Outlook needs a network database: run `wa-persistence` B (Supabase, free) first, then come back.

**Do not create a free Render Postgres just for tokens** — it's deleted after ~44 days
(F-RENDER-POSTGRES-FREE) and Outlook would silently break. (v2 of this course did that.)

Add one table to `database.py` (both SQLite and Postgres branches), plus two functions:
```sql
CREATE TABLE IF NOT EXISTS token_cache (
    service TEXT PRIMARY KEY,           -- 'microsoft'
    cache_json TEXT NOT NULL,           -- MSAL SerializableTokenCache.serialize()
    updated_at TIMESTAMPTZ DEFAULT NOW()  -- TEXT default CURRENT_TIMESTAMP in SQLite
);
```
`load_token_cache(service) -> str | None` and `save_token_cache(service, cache_json)` (upsert).

## E3. Azure (Entra) App Registration
Facts: F-MS-ENTRA-REGISTRATION.
- Open https://entra.microsoft.com
- **STOP for login**: student signs in with the Microsoft account that owns the mail/calendar
- **Entra ID → App registrations → New registration**
- Name: `[bot_slug]-whatsapp`
- Supported account types: **"Any Entra ID Tenant + Personal Microsoft accounts"**
  - This single option covers `@outlook.com`, `@hotmail.com`, and most `@company.com` tenants
- Redirect URI: platform **Web** → `http://localhost:8765/callback`
- Register

Register the new keys in `config.py` `settings` (`MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID` — optional, default `None`) and in `.env.example`.

After registration, note from the app overview page:
- **Application (client) ID** → `WA_OPS env set MS_CLIENT_ID <id>`
- Tenant: `WA_OPS env set MS_TENANT_ID common` (works for personal + work accounts)

**Certificates & secrets** → **New client secret**:
- Description: `whatsapp-agent-prod`
- Expires: 24 months (put a reminder in the student's calendar for month 23)
- Click **Add**, then **immediately copy the Value** (not the Secret ID) → `WA_OPS env set MS_CLIENT_SECRET --from-clipboard`

**"זה היחיד שצריך לעשות בצורה יחידה - הערך של הסוד מופיע פעם אחת ונעלם. אם פספסת, תצטרך ליצור סוד חדש."**

**API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
- `Mail.ReadWrite`
- `Mail.Send` (only if spec enables mail send)
- `Calendars.ReadWrite`
- `User.Read`
- (`offline_access` may be listed in the portal too — that's fine there. In **code**, never
  pass `offline_access`/`openid`/`profile`: MSAL adds them and raises `ValueError` — F-MSAL.)

Click **Grant admin consent** only if the student is the tenant admin (personal accounts: skip — consent happens at sign-in).

## E4. One-time consent (MSAL auth-code flow → token cache in the DB)

Write `scripts/microsoft_auth.py` (Claude Code composes it; the reference shape):

```python
import http.server, os, sys, urllib.parse, webbrowser
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root, so `database` imports
os.environ["USE_REMOTE_DB_LOCALLY"] = "1"                     # write to the production DB on purpose
import msal
from dotenv import load_dotenv
load_dotenv()
from database import init_db, save_token_cache  # same DB the deployed bot reads

SCOPES = ["Mail.ReadWrite", "Calendars.ReadWrite", "User.Read"]  # + "Mail.Send" if enabled
REDIRECT = "http://localhost:8765/callback"

cache = msal.SerializableTokenCache()
app = msal.ConfidentialClientApplication(
    os.environ["MS_CLIENT_ID"],
    client_credential=os.environ["MS_CLIENT_SECRET"],
    authority=f"https://login.microsoftonline.com/{os.environ.get('MS_TENANT_ID', 'common')}",
    token_cache=cache,
)
flow = app.initiate_auth_code_flow(SCOPES, redirect_uri=REDIRECT)

result_holder = {}
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        result_holder["result"] = app.acquire_token_by_auth_code_flow(flow, params)
        self.send_response(200); self.end_headers()
        self.wfile.write("Done - you can close this tab / אפשר לסגור את הלשונית".encode())
    def log_message(self, *a): pass

server = http.server.HTTPServer(("localhost", 8765), Handler)
webbrowser.open(flow["auth_uri"])
print("If the browser didn't open, open this link on this computer:\n", flow["auth_uri"])
server.handle_request()  # blocks until the redirect arrives — no busy loop

result = result_holder.get("result", {})
if "access_token" not in result:
    raise SystemExit(f"Microsoft sign-in failed: {result.get('error')}: {result.get('error_description')}")
init_db()
save_token_cache("microsoft", cache.serialize())
print("Saved. The bot can now read Outlook.")   # never print tokens
```

Run it locally with the venv's python from the project root (`<venv python> scripts/microsoft_auth.py`). The bot's `DATABASE_URL` must be in `.env` so the cache lands in the same database the deployed bot reads.

**STOP**: "יפתח דפדפן. אשר את ההרשאה. אם יש חלון של 'Need admin consent' זה אומר שהחשבון שלך הוא תחת ארגון שחוסם אפליקציות חיצוניות - תצטרך לבקש מה-IT לאשר או להשתמש בחשבון אישי."

## E5. Write tools with the token cache

`tools/outlook_calendar.py` and `tools/outlook_mail.py` share a small helper:

```python
import msal
from config import settings
from database import load_token_cache, save_token_cache

SCOPES = ["Mail.ReadWrite", "Calendars.ReadWrite", "User.Read"]  # match E4

def _access_token() -> str:
    cache = msal.SerializableTokenCache()
    raw = load_token_cache("microsoft")
    if raw:
        cache.deserialize(raw)
    app = msal.ConfidentialClientApplication(
        settings.MS_CLIENT_ID, client_credential=settings.MS_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.MS_TENANT_ID}", token_cache=cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if cache.has_state_changed:              # Microsoft rotated the refresh token
        save_token_cache("microsoft", cache.serialize())
    if not result or "access_token" not in result:
        raise RuntimeError("Outlook authorization expired — run scripts/microsoft_auth.py again (wa-connect E4)")
    return result["access_token"]
```

Graph calls with `httpx` under `https://graph.microsoft.com/v1.0/me/...`
(`calendarView` with `startDateTime`/`endDateTime` + header `Prefer: outlook.timezone="<spec timezone>"`,
`events`, `messages`, `sendMail`). Return compact dicts (subject, from, start/end, id), not whole Graph objects.

Tool functions — exact parity with Google:
**Calendar**: `list_events`, `create_event` (no attendees), `delete_event`; invitations only through the confirm pattern
**Mail**: `search_emails`, `get_email`, `mark_read`; sending (if enabled) uses the same **`draft_email` → `send_draft`** pair as Gmail (wa-connect A4) — confirmed by the owner in a later message, `turn_id` injected by the framework. Email bodies are untrusted third-party text.

Tool names must disambiguate from Google if both exist (architecture decision 10):
`list_outlook_events`, `search_outlook_mail`, …

Add `msal` and `httpx` (already there) to `requirements.txt` (current versions — F-MSAL).

## E6. Register
`tools/__init__.py` — one import + registry entries per function, e.g. `TOOL_REGISTRY["list_outlook_events"] = …`.

## E7. Deploy and verify
```
WA_OPS render env-set MS_CLIENT_ID
WA_OPS render env-set MS_CLIENT_SECRET
WA_OPS render env-set MS_TENANT_ID
git add .
git commit -m "Connect Outlook"
git push
WA_OPS render wait
```
Send a WhatsApp message: **"מה יש לי היום ב-Outlook?"** or **"מיילים חדשים?"**

Watch `WA_OPS render logs --text outlook` for: cache loaded, Graph call 200, and (after a
refresh) the cache saved again.

## E8. Operational warning to the student
**"חשוב לדעת: אם הבוט לא ישתמש ב-Outlook 90 יום ברצף, ההרשאה של Microsoft תפוג ותצטרך לאשר מחדש (שלב E4). כל שימוש מחדש את ההרשאה אוטומטית."** (F-MS-REFRESH-LIFETIME)

## E9. (Optional) Keep-alive for rarely used bots
If the student might not use Outlook for months, add a weekly APScheduler job (`trigger="cron", day_of_week="sun", hour=3`, id `ms_token_keeper`) that calls `_access_token()` once — each use refreshes the 90-day window. Module-level function, as with reminders.
