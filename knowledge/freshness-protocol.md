# Freshness Protocol — how every wa-* skill stays correct after it ships

The outside world this plugin depends on (Green API, Render, Supabase, Google Cloud,
Anthropic, Microsoft Entra, Claude Code itself) changes its screens, prices, limits and
APIs every few months. A skill that hardcodes "click X in the top-left" goes stale
silently, and a non-technical student cannot tell a stale instruction from their own
mistake. This protocol is how the skills defend against that **at runtime**, and how the
plugin learns from every student who hits a change.

Every skill MUST follow it. It is short on purpose.

## 1. Facts live in one place

Anything that can change without our code changing — a UI path, a price, a free-tier
limit, a model ID, a timeout, an API field name — lives in
[`facts.md`](facts.md) as a fact with an ID (`F-…`), a `verified:` date, a `source:` URL
and a `live-check:` line. Skills reference the ID (for example *"see F-RENDER-COLD-START"*)
instead of restating the value, so one edit fixes every skill.

## 2. Live beats stored

Before relying on a fact, prefer asking the live system over trusting the stored value:

| Instead of trusting… | Ask the live system |
|---|---|
| a Claude model ID or price | `wa_ops.py llm models` (lists models the student's key can use) |
| Green API setting names | `wa_ops.py green settings` (the JSON the instance actually returns) |
| a Render field or status | the API response itself (`wa_ops.py render …` prints it) |
| a Python package version | `python -m pip index versions <pkg>` |
| a dashboard screen layout | a browser screenshot of the screen the student is looking at |

The student's own screen is the final authority. If the student says the button is not
where we said, believe the student and look.

## 3. Stale-check before UI instructions

When a step is about to send the student to a third-party screen (Google Auth Platform,
Render dashboard, Supabase Connect, Anthropic key page, Entra, Green API console):

1. Look up the fact in `facts.md`.
2. If its `verified:` date is **older than 60 days**, or the fact is marked `volatile: high`,
   spend one quick check first: open the `source:` URL (WebFetch) or the page itself in the
   browser and confirm the path/label still matches. Keep it to one or two fetches — this
   is a sanity check, not research.
3. If the live page matches, continue with the stored instruction.
4. If it does **not** match, follow the live page, tell the student plainly
   (*"המסך השתנה מאז שכתבנו את המדריך — הנה איפה זה עכשיו"*), and record drift (§4).

Never block the student on a freshness check. If the check itself fails (no network, page
behind login), proceed with the stored instruction and say what to look for in case it moved.

## 4. Record drift — in the student's project

When reality disagrees with the skill (a moved button, a renamed field, a new error code,
a price change, a fix that worked for an error our tables don't list), append an entry to
`drift_log` in the project's `.wa-state.json`:

```json
{
  "ts": "2026-10-01T10:00:00Z",
  "plugin_version": "3.0.0",
  "skill": "wa-persistence",
  "fact_id": "F-SUPABASE-CONNECT-UI",
  "expected": "Connect button → Direct tab → Method: Session pooler",
  "observed": "Connect button → 'Connection string' tab → Type: Session",
  "fix_that_worked": "Used the new tab; URL shape unchanged",
  "reported": false
}
```

No secrets, no phone numbers, no tokens, no email addresses — ever.

## 5. Report drift upstream — only with consent

At the end of the stage (not mid-flow), if `drift_log` has entries with `reported: false`,
offer once:

> *"נתקלנו ב-[N] דברים שהשתנו אצל הספקים מאז שהמדריך נכתב. רוצה שאשלח דיווח קצר (בלי שום
> מידע אישי או מפתחות) כדי שהמדריך יתעדכן לכל שאר התלמידים?"*

- **Yes, and `gh` is logged in** → `wa_ops.py report-drift` first (it builds the issue text
  from `drift_log` and strips anything that looks like a secret, phone or email) — show the
  student that exact text — then `wa_ops.py report-drift --post` opens the issue on
  `Asher-pro/wa-whatsapp-agent` and marks the entries `reported: true`.
- **Yes, but no `gh`** → print the issue text and the URL
  `https://github.com/Asher-pro/wa-whatsapp-agent/issues/new?template=drift-report.md` for the
  student to paste themselves.
- **No** → mark nothing, never ask again in this session.

Reports arrive unlabelled. When the course owner confirms one and adds the `drift` label,
the refresh workflow (`.github/workflows/auto-refresh.yml`) re-verifies the fact against
official docs and opens a pull request. The course owner merges it; the version bump then
reaches every student through `/wa`'s update check.

## 6. The update loop, end to end

```
student hits a changed screen ──▶ skill follows the live page ──▶ drift_log entry
        ▲                                                              │
        │                                  (consent) issue ──▶ owner adds the "drift" label
/wa update check ◀── version bump ◀── maintainer merges PR ◀── auto-refresh workflow
        │
        └──▶ wa-maintain "upgrade audit" applies fixes to bots that were built earlier
             (see upgrades.md)
```

Plus a weekly scheduled check (`freshness.yml`) that flags facts older than 60 days and
dead source links, so the plugin is re-verified even when no student complains.
