# LLM API Setup Guide

## OpenAI

### Registration
1. Go to https://platform.openai.com
2. Click "Sign up"
3. Create account (email + password or Google/Microsoft SSO)
4. **Payment required**: Add credit card under Billing → Payment methods
5. Add credit: $5-10 is enough to start

### Create API Key
1. Go to https://platform.openai.com/api-keys
2. Click "Create new secret key"
3. Name it (e.g., "whatsapp-agent")
4. Copy the key immediately (shown only once)
5. Save as OPENAI_API_KEY in .env

### Recommended Models
- `gpt-4.1-mini` - Best balance of cost and quality (recommended)
- `gpt-4.1-nano` - Cheapest, good for simple conversations
- `gpt-4.1` - Most capable, more expensive

### Pricing (approximate)
- gpt-4.1-nano: ~$0.001 per conversation turn
- gpt-4.1-mini: ~$0.005 per conversation turn
- gpt-4.1: ~$0.03 per conversation turn

---

## Anthropic (Claude)

### Registration
1. Go to https://console.anthropic.com
2. Click "Sign up"
3. Create account
4. **Payment required**: Add credit card under Settings → Billing

### Create API Key
1. Go to https://console.anthropic.com/settings/keys
2. Click "Create Key"
3. Name it (e.g., "whatsapp-agent")
4. Copy the key immediately
5. Save as ANTHROPIC_API_KEY in .env

### Recommended Models
- `claude-sonnet-4-6` - Great balance (recommended)
- `claude-haiku-4-5-20251001` - Fastest and cheapest

### Pricing (approximate)
- claude-haiku: ~$0.002 per conversation turn
- claude-sonnet: ~$0.01 per conversation turn

---

## LLM Init Blocks (for agent.py template)

### OpenAI
```python
from openai import OpenAI
client = OpenAI()

# In get_response:
response = client.chat.completions.create(
    model=settings.LLM_MODEL,
    messages=messages,
)
reply = response.choices[0].message.content
```

### Anthropic
```python
from anthropic import Anthropic
client = Anthropic()

# In get_response:
system_msg = messages[0]["content"]
chat_messages = messages[1:]
response = client.messages.create(
    model=settings.LLM_MODEL,
    max_tokens=1024,
    system=system_msg,
    messages=chat_messages,
)
reply = response.content[0].text
```
