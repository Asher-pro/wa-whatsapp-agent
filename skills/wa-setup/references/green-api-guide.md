# Green API Step-by-Step Guide

## What is Green API?
A service that connects your WhatsApp number to the internet via API. Your AI agent uses it to send and receive WhatsApp messages.

## Registration
1. Go to https://green-api.com
2. Click "Sign Up" or "Try Free"
3. Enter email and password
4. Verify email
5. Log in to dashboard

## Pricing
- Free trial: 3 days
- After trial: ~$15/month for one instance
- One instance = one WhatsApp number

## Creating an Instance
1. In dashboard, click "Create Instance" or "Add Instance"
2. Select "WhatsApp" as type
3. Instance will be created with:
   - **Instance ID** (number like 7105222798)
   - **API Token** (long string like a2797d0923494271...)
   - **API URL** (like https://7105.api.greenapi.com)

## Finding Credentials
In the instance dashboard:
- Instance ID: shown in the header or settings
- API Token: shown in settings, may need to click "show"
- API URL: shown in the instance URL or settings

## QR Code Connection
1. In dashboard, go to the instance → QR code section
2. On phone: WhatsApp → Settings → Linked Devices → Link a Device
3. Scan the QR code with phone camera
4. Wait for status to change to "authorized"

## Webhook Settings (configured later in wa-deploy)
- Settings → Webhooks section
- Webhook URL: will be set to Render URL
- Enable: "Receive incoming messages" notification type

## Testing the Connection
Use the Green API REST API:
```
POST https://[API_URL]/waInstance[ID]/sendMessage/[TOKEN]
Content-Type: application/json

{
    "chatId": "972501234567@c.us",
    "message": "Test message"
}
```

Phone number format: country code + number + @c.us
Israeli example: 0501234567 → 972501234567@c.us

## Common Issues
- QR code expires after ~60 seconds → refresh page
- Only one WhatsApp Web session per phone → disconnect old ones first
- Instance takes ~30 seconds to initialize after QR scan
