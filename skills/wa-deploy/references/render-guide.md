# Render.com Setup Guide

## What is Render?
A cloud service that runs your code 24/7. Your agent code lives on Render's servers and responds to WhatsApp messages even when your computer is off.

## Pricing
- **Free tier**: Works but sleeps after 15 min idle. First request takes ~30s to wake.
- **Starter ($7/month)**: Always on, faster.
- **Disk ($0.25/month per GB)**: Persistent storage for conversation memory.

## Creating a Web Service
1. Sign up at https://render.com (use GitHub account for easy connection)
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: your-agent-name
   - **Region**: closest to you (e.g., Frankfurt for Israel)
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Environment Variables
Add each variable from your .env file:
- Click "Environment" tab
- Add key-value pairs one by one
- These are secrets - Render keeps them encrypted

## Adding a Disk (for conversation memory)
1. Go to service settings → Disks
2. Click "Add Disk"
3. Name: `data`
4. Mount Path: `/data`
5. Size: 1 GB ($0.25/month)

## Checking Logs
- Service dashboard → "Logs" tab
- Shows real-time output including errors
- Use "Events" tab to see deploy history

## Redeploying
- Automatic: push to GitHub → Render auto-deploys
- Manual: Dashboard → "Manual Deploy" → "Deploy latest commit"

## Updating Environment Variables
1. Dashboard → Environment
2. Edit the value
3. Click Save
4. Service auto-restarts with new values
