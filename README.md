# WhatsApp AI Agent Builder

A Claude Code plugin that guides non-technical users through building, deploying, and maintaining a WhatsApp AI agent — step by step, in Hebrew, with zero coding required.

## Installation

```
/plugin marketplace add Asher-pro/wa-whatsapp-agent
/plugin install wa-whatsapp-agent@practice-ai-plugins
```

Then run `/wa` to start.

## How It Works

The plugin has one entry command (`/wa`) and six skills. You run `/wa`, it figures out where you are, and routes you to the right skill.

```
/wa ─┬─▶ wa-setup        (Green API + phone number)
     ├─▶ wa-characterize (define what the bot does)
     ├─▶ wa-build        (generate code)
     ├─▶ wa-connect      (wire tools: calendar, mail, groups, reminders)
     ├─▶ wa-deploy       (ship to Render)
     └─▶ wa-maintain     (debug & update after launch)
```

Progress is tracked in a `.wa-state.json` file in your project — if you leave mid-way and come back a week later, `/wa` picks up where you left off.

## The Stack (Generated)

Opinionated, lean, readable:

- **FastAPI** — webhook receiver
- **Direct LLM SDK** (Anthropic or OpenAI) with native tool-calling — no framework magic
- **SQLite** — conversation memory
- **APScheduler** — reminders
- **Google APIs** — Gmail + Calendar (one OAuth consent covers both)
- **Microsoft Graph** (optional, advanced) — Outlook Mail + Calendar via `msal`
- **Render.com** — deployment target

Why this and not LangChain/Agno/CrewAI? So you can read every line of your own bot's code and debug it. Framework magic bites non-technical users hardest when it fails.

## What You Need

- Claude Code installed
- A phone number for WhatsApp (eSIM recommended, ~₪15/month)
- Credit card for Green API (~$15/month for customer service; free tier works for personal assistant) and LLM API (pay-per-use, usually a few dollars/month)
- If using Outlook: also Render Postgres (free tier)

## The Three Layers of Orchestration

For contributors:

1. **`/wa` command** — single entry point, reads `.wa-state.json`, routes to the correct skill
2. **Each skill** — does one stage of the work, writes progress back to `.wa-state.json`, offers the next skill on completion
3. **`.wa-state.json`** — single source of truth for "where the student is"

This means: no skill assumes state from file existence. No skill calls the next one blindly. `/wa` always has the full picture.

## License

MIT
