# Green API Webhook Configuration

## What is a Webhook?
When someone sends a WhatsApp message, Green API needs to forward it to your agent. A webhook is the address where Green API sends these messages.

## Setting Up via Dashboard
1. Log in to Green API dashboard
2. Go to your instance
3. Find "Webhook" or "Settings" section
4. Set Webhook URL: `https://YOUR-APP.onrender.com/webhook/green-api`
5. Enable notifications:
   - Incoming messages: ON
   - Other notifications: OFF (for simplicity)
6. Save

## Setting Up via API
```bash
curl -X POST "https://[API_URL]/waInstance[ID]/setSettings/[TOKEN]" \
  -H "Content-Type: application/json" \
  -d '{
    "webhookUrl": "https://YOUR-APP.onrender.com/webhook/green-api",
    "incomingWebhook": "yes",
    "outgoingMessageWebhook": "no",
    "outgoingAPIMessageWebhook": "no",
    "stateWebhook": "no",
    "deviceWebhook": "no"
  }'
```

## Verifying Webhook
1. Check Green API dashboard shows webhook as "active"
2. Send a message to the connected WhatsApp number
3. Check Render logs - you should see the incoming webhook request
4. If no logs appear: webhook URL is wrong or Green API isn't sending

## Common Issues
- **URL must be HTTPS** - Render provides this automatically
- **URL must be publicly accessible** - Render URLs are public
- **Don't include trailing slash** - use `.com/webhook/green-api` not `.com/webhook/green-api/`
- **Render free tier cold start** - First webhook after inactivity may timeout. Green API may retry.
