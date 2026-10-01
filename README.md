# WhatsApp AI Agent Builder

A Claude Code plugin that guides non-technical users through building, deploying, and maintaining a WhatsApp AI agent — step by step, in Hebrew, with zero coding required. Works on **macOS and Windows** (desktop app, VS Code or terminal).

## Installation

In Claude Code:

```
/plugin marketplace add Asher-pro/wa-whatsapp-agent
/plugin install wa-whatsapp-agent@practice-ai-plugins
```

Then **open a new session** (or run `/reload-plugins`) and type `/wa` to start.

### Installed it but `/wa` doesn't show up?

- A newly installed plugin is active from the **next session**. Open a new session, or run `/reload-plugins` in the current one.
- The plugin is installed per computer and shared between the Claude desktop app, VS Code and the terminal — install once, use anywhere on that machine.
- Plugins don't load in cloud sessions (claude.ai/code in the browser) or in WSL sessions of the desktop app — use a regular local session.

### Staying up to date

The plugin keeps improving after you install it. `/wa` checks once a day and tells you when there's a new version. To update:

```
/plugin marketplace update practice-ai-plugins
```

then `/reload-plugins` (or a new session). To get updates automatically: `/plugin` → **Marketplaces** → `practice-ai-plugins` → enable auto-update.

If you built your bot with an older version, `/wa` will offer an **upgrade audit** that finds and (with your OK) fixes what changed — see [`knowledge/upgrades.md`](knowledge/upgrades.md).

## How It Works

The plugin has one entry command (`/wa`) and seven skills. You run `/wa`, it figures out where you are, and routes you to the right skill.

```
/wa ─┬─▶ wa-setup        (Green API + phone number)
     ├─▶ wa-characterize (define what the bot does)
     ├─▶ wa-build        (generate code)
     ├─▶ wa-deploy       (ship to Render)
     ├─▶ wa-connect      (wire tools: calendar, mail, groups, handoff — one at a time)
     ├─▶ wa-maintain     (debug, update, upgrade after launch)
     └─▶ wa-persistence  (durable memory — any time after deploy)
```

Progress is tracked in a `.wa-state.json` file in your project — if you leave mid-way and come back a week later, `/wa` picks up where you left off.

## The Stack (Generated)

Opinionated, lean, readable:

- **FastAPI** — webhook receiver, authenticated with a token Green API sends on every call
- **Direct LLM SDK** (Anthropic, or OpenAI / Google) with native tool-calling — no framework magic
- **SQLite** locally → **Supabase Postgres** (free) or a Render disk in production — conversation memory and reminders
- **APScheduler** — reminders that survive restarts and free-tier sleep
- **Google APIs** — Gmail + Calendar (one OAuth consent covers both, published so it doesn't expire)
- **Microsoft Graph** (optional, advanced) — Outlook Mail + Calendar via `msal`
- **Render.com** — deployment target, driven through its REST API

Why this and not LangChain/Agno/CrewAI? So you can read every line of your own bot's code and debug it. Framework magic bites non-technical users hardest when it fails.

## What You Need

- Claude Code installed (desktop app, VS Code or terminal)
- A phone number for WhatsApp (eSIM recommended, ~₪15/month)
- Green API: free **Developer** plan for a personal assistant (up to 3 chats a month) or **Business** (~$12/month) for customer service
- An LLM API key — pay-per-use, usually a few dollars a month
- Free accounts on GitHub, Render and Supabase
- The plugin checks your computer and installs what's missing (Python, Git, GitHub CLI) — only with your OK

## For Maintainers

### Layout

```
commands/wa.md          orchestrator (/wa)
skills/wa-*/SKILL.md    the seven skills (+ references/ for long sub-flows)
knowledge/              facts.md · freshness-protocol.md · platform.md · state-schema.md · upgrades.md
scripts/wa_ops.py       cross-platform helper the skills call (stdlib Python, no installs)
scripts/check_freshness.py   stale facts, dead sources, PyPI drift, Render OpenAPI check
scripts/validate_plugin.py   structural consistency (facts, upgrades, helper commands, versions)
tests/                  offline tests for wa_ops.py (mock Render / Green API)
.github/workflows/      validate · freshness (weekly) · auto-refresh (monthly / on `drift` label)
```

### The three layers of orchestration

1. **`/wa` command** — single entry point, reads `.wa-state.json`, routes to the correct skill, checks for plugin updates
2. **Each skill** — does one stage of the work, writes progress back to `.wa-state.json`, offers the next stage on completion
3. **`.wa-state.json`** — single source of truth for "where the student is" ([schema](knowledge/state-schema.md))

No skill assumes state from file existence. No skill calls the next one blindly. `/wa` always has the full picture.

### How the plugin stays current

Everything that can change without our code changing (UI paths, prices, limits, model IDs) lives once, in [`knowledge/facts.md`](knowledge/facts.md), with a `verified` date, a source and a live check. Then:

1. **At runtime** ([freshness protocol](knowledge/freshness-protocol.md)): skills check stale facts before sending a student to a third-party screen, prefer live answers (APIs, the student's screen) over stored ones, follow the real screen when it changed, and record the difference in the student's `drift_log`. With the student's consent, `wa_ops.py report-drift --post` files a scrubbed issue here.
2. **Weekly** (`freshness.yml`): `check_freshness.py` flags stale facts, dead sources, new package versions and missing Render API endpoints in one "Freshness report" issue.
3. **Monthly, or when a maintainer labels an issue `drift`** (`auto-refresh.yml`): Claude re-verifies the flagged facts against official docs, updates `facts.md`/skills/`upgrades.md`, bumps the version, and opens a pull request. **A human reviews and merges.**
4. **Release**: merging the version bump reaches students through `/wa`'s update check; their existing bots get the fixes through the upgrade audit.

**One-time setup** for step 3:
1. Repository secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).
2. Settings → Actions → General → Workflow permissions → enable **"Allow GitHub Actions to create and approve pull requests"**.
3. Recommended: protect `main` (Settings → Branches → add a rule requiring a pull request), so automation can never push to it directly.

Without these, steps 1, 2 and 4 still work.

Students' drift reports arrive as plain issues — the plugin never labels them. Read the report, and if it's real, add the **`drift`** label: that's what starts the auto-refresh run.

### Releasing

1. Change skills/knowledge/helper.
2. If a fix also matters for bots that already exist, add an entry to `knowledge/upgrades.md`.
3. Bump `version` in **both** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (students only receive updates when the version changes), add a `## <version>` section to `CHANGELOG.md`.
4. `python3 scripts/validate_plugin.py && python3 -m unittest discover -s tests && claude plugin validate .`
5. Merge to `main`.

## License

MIT
