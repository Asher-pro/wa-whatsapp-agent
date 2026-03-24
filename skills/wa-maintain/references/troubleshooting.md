# Troubleshooting Guide

## Service Crashed on Render
**Symptoms:** Health endpoint returns error, no responses to messages
**Fix:**
1. Go to Render dashboard → service → Logs
2. Find the error (usually a Python traceback)
3. Common causes:
   - Missing env var → add it in Environment tab
   - Bad dependency → check requirements.txt
   - Code bug → fix locally, push to GitHub
4. Manual restart: Dashboard → "Manual Deploy" → "Clear build cache & deploy"

## Green API Instance Expired
**Symptoms:** Webhook not receiving messages, dashboard shows "inactive"
**Fix:**
1. Log in to Green API dashboard
2. Check subscription status
3. Renew payment
4. May need to re-scan QR code after renewal

## API Key Invalid
**Symptoms:** Render logs show "AuthenticationError" or "Invalid API key"
**Fix:**
1. Go to OpenAI platform (or Anthropic console)
2. Create a new API key
3. Update the env var on Render dashboard
4. Service auto-restarts

## Out of LLM Credits
**Symptoms:** Render logs show "InsufficientQuotaError" or "Rate limit exceeded"
**Fix:**
1. Go to OpenAI billing (or Anthropic billing)
2. Add funds / update payment method
3. No code change needed - will start working once funded

## Messages Not Arriving
**Symptoms:** Agent is running but doesn't respond to WhatsApp messages
**Check:**
1. Green API dashboard → webhook URL correct?
2. URL should be `https://YOUR-APP.onrender.com/webhook/green-api`
3. `incomingWebhook` enabled?
4. Try: send test message, check Render logs for any incoming request
5. If no logs at all → webhook not configured correctly

## Agent Responding Slowly
**Causes:**
- Render free tier: sleeps after 15 min, takes ~30s to wake
- Heavy LLM model: switch to gpt-4.1-nano or gpt-4.1-mini
- Long conversation history: reduce MAX_HISTORY
**Fix:** Upgrade Render plan ($7/mo) for always-on, or use lighter model

## Agent Responds in Wrong Language
**Fix:** Update SYSTEM_PROMPT to explicitly include language instruction:
"Always respond in Hebrew (עברית). Never switch to English unless the user writes in English."

## Database Lost / Conversations Reset
**Causes:**
- No disk attached on Render (conversations stored in ephemeral filesystem)
- Disk full
**Fix:**
- Add disk on Render (Settings → Disks → Add Disk, mount: /data)
- Ensure DATABASE_PATH env var is `/data/conversations.db`

## Agent Responds to Group Messages (shouldn't)
**Check:** main.py should have `@g.us` filter:
```python
if "@g.us" in chat_id:
    return {"ok": True, "skipped": "group_message"}
```
If missing, add it and redeploy.
