# WhatsApp AI Agent Builder

A Claude Code plugin that guides non-technical users through building, deploying, and maintaining a WhatsApp AI agent.

## Installation

```
/plugin marketplace add Asher-pro/wa-whatsapp-agent
/plugin install wa-whatsapp-agent@practice-ai-plugins
```

Then type `/wa` to start.

To test locally without marketplace:
```
claude --plugin-dir /path/to/wa-whatsapp-agent
```

## What This Plugin Does

Guides you step-by-step through:

1. **`/wa`** - Entry point, detects where you are and routes to the right step
2. **wa-setup** - Connect your WhatsApp number via Green API
3. **wa-agent** - Define your agent's personality and generate all the code
4. **wa-deploy** - Deploy to Render.com for 24/7 operation
5. **wa-maintain** - Change behavior, fix issues, update settings

## Tech Stack (Generated)

The plugin generates a complete Python project:
- **FastAPI** - Webhook server
- **OpenAI / Anthropic SDK** - AI conversation
- **SQLite** - Conversation memory
- **Render.com** - Cloud hosting

## Requirements

- Claude Code
- A phone number for WhatsApp
- Credit card for Green API (~$15/month) and LLM API (pay-per-use)

## License

MIT
