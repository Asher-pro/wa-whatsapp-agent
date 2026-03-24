# GitHub Setup for Non-Technical Users

## What is GitHub?
A website that stores code online. Think of it like Google Drive but for code. Render needs the code to be on GitHub to deploy it.

## Creating an Account
1. Go to https://github.com
2. Click "Sign up"
3. Enter email, password, username
4. Verify email
5. Free account is enough

## Creating a Repository (via browser)
1. Click "+" icon (top right) → "New repository"
2. Name: your-agent-name (e.g., "my-whatsapp-agent")
3. Leave as Public
4. DON'T add README (we already have code)
5. Click "Create repository"
6. Follow the "push existing repository" instructions shown

## Creating a Repository (via gh CLI)
```bash
# Login first
gh auth login

# Create and push
cd /path/to/your/project
git init
git add .
git commit -m "Initial commit"
gh repo create my-whatsapp-agent --public --source=. --push
```

## Pushing Updates
After making changes to the code:
```bash
git add .
git commit -m "Updated agent"
git push
```
Render will automatically redeploy.
