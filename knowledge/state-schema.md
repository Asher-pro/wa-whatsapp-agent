# `.wa-state.json` — schema v2

The single source of truth for *where the student is*. Lives in the bot's project
directory, is git-ignored (it may hold service IDs, never secrets), and is read by `/wa`
and every skill before doing anything.

`wa_ops.py state get|set|append|migrate` reads and writes it safely (atomic write,
pretty-printed, keys sorted). Skills may also edit it directly — but always
read → merge → write; never overwrite the whole file from memory.

## Shape

```json
{
  "version": 2,
  "plugin_version": "3.0.0",
  "project_dir": "/Users/dana/whatsapp-agent",
  "os": "macos | windows | linux",
  "bot_name": "רוני",
  "bot_slug": "roni-bot",
  "archetype": "personal_assistant | customer_service",
  "timezone": "Asia/Jerusalem",

  "current_stage": "setup | characterize | build | deploy | connect | maintain",
  "completed_stages": ["setup", "characterize", "build", "deploy"],
  "connected_tools": ["reminders", "google_calendar"],

  "green_api": {
    "instance_id": "7105222798",
    "api_url": "https://7105.api.greenapi.com",
    "plan": "developer | business",
    "bot_phone": "972501234567"
  },

  "llm": { "provider": "anthropic", "model": "claude-haiku-4-5" },

  "render": {
    "service_id": "srv-…",
    "url": "https://roni-whatsapp.onrender.com",
    "dashboard_url": "https://dashboard.render.com/web/srv-…",
    "owner_id": "tea-…",
    "plan": "free | starter",
    "region": "frankfurt",
    "postgres_id": null,
    "keep_awake": "none | external_ping | paid_plan"
  },

  "persistence_choice": "ephemeral | disk_planned | external_db_planned | disk | supabase | render_pg | ephemeral_accepted",
  "persistence_details": { "provider": "supabase", "region": "eu-central-1" },

  "google": { "publishing_status": "in_production | testing", "authorized_at": "2026-10-01T10:00:00Z" },

  "drift_log": [],
  "maintenance_log": [],
  "upgrades_applied": ["3.0.0"],
  "last_update_check_iso": "2026-10-01T10:00:00Z",
  "last_touched_iso": "2026-10-01T10:00:00Z"
}
```

Unknown keys must be preserved when writing — a newer plugin version may have added them.

Field notes:
- `bot_slug` — ASCII (`a-z`, `0-9`, `-`), set in wa-characterize; used for the GitHub repo and Render service names (GitHub names can't contain Hebrew).
- `persistence_choice` — `*_planned` and `ephemeral` are intentions from wa-build; `disk`, `supabase`, `render_pg` mean durable memory **is in place**; `ephemeral_accepted` means the student chose to live without it. "Durable" checks anywhere = `disk | supabase | render_pg`.
- `llm` — written by wa-build step 2 (provider + model; never the key).
- `plugin_version` — the version the bot's **code** was built or upgraded with. Set only by wa-build (`stage-done build …`) and the Upgrade audit.

## Migrating v1 → v2 (`wa_ops.py state migrate`)

v1 files (plugin ≤ 2.2.1) are flat. The migration is lossless and idempotent:

| v1 key | v2 location |
|---|---|
| `render_url` | `render.url` |
| `render_service_id` | `render.service_id` |
| `render_dashboard_url` | `render.dashboard_url` |
| `render_postgres_id` | `render.postgres_id` |
| `render_region` | `render.region` |
| everything else | unchanged |

It also sets `version: 2`, adds `drift_log: []`, `upgrades_applied: []`, `timezone`
(default `Asia/Jerusalem`) and detects `os`. It does **not** set `plugin_version` — that
field records the version the bot was last built/upgraded with, and its absence is how
`/wa` knows an older bot needs the upgrade audit in [`upgrades.md`](upgrades.md).

## Stage rules

```
setup → characterize → build → deploy → connect (once per external tool) → maintain
                                   └──── wa-persistence: any time after deploy
```

- `deploy` comes **before** `connect`: the bot goes live with only reminders, then each
  external tool is wired and redeployed one at a time.
- After `deploy`: `current_stage = "connect"` if `spec.tools` has external tools not yet in
  `connected_tools`, else `"maintain"`.
- After each `connect`: stay on `"connect"` while external tools remain, else `"maintain"`.
- `maintain` and `persistence` never move `current_stage` backwards.
