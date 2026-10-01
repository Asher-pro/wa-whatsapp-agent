# Platform guide — Mac, Windows, Linux

Students arrive on macOS or Windows, in the Claude desktop app, VS Code or the terminal.
Every skill must work on all of them. This page is the single reference for how.

## The rule: one command surface — `wa_ops.py`

All infrastructure work (Green API, Render, LLM key checks, state file, drift reports) goes
through the plugin's helper, a single **standard-library-only** Python script:

```
<PLUGIN_ROOT>/scripts/wa_ops.py
```

`PLUGIN_ROOT` is two directories above any skill's base directory
(`${CLAUDE_SKILL_DIR}/../..`). It runs identically under Bash, Git Bash, zsh and PowerShell,
needs no `jq`, no `brew`, no Render CLI, and never prints secrets. Run it from the bot's
project directory (it reads `.env` and `.wa-state.json` from the current directory, or
from `--project <dir>`).

| OS | Python launcher | Example |
|---|---|---|
| macOS / Linux | `python3` | `python3 "/Users/dana/.claude/plugins/cache/practice-ai-plugins/wa-whatsapp-agent/3.0.0/scripts/wa_ops.py" green state` |
| Windows (PowerShell or Git Bash) | `py -3` (falls back to `python`) | `py -3 "C:\Users\Dana\.claude\plugins\cache\practice-ai-plugins\wa-whatsapp-agent\3.0.0\scripts\wa_ops.py" green state` |

In the skills, `WA_OPS` is shorthand for that full quoted path — always write the path out. Shell variables don't persist between Claude Code commands, and `$VAR` / `$env:VAR` syntax differs between Bash and PowerShell.

Raw `curl` examples in the skills are reference material (what the helper does under the
hood). Prefer the helper; fall back to raw calls only if the helper itself errors, and
then say so in `drift_log`.

## Detecting the platform (wa-setup step 0, and `/wa` on every run)

`wa_ops.py doctor` prints a JSON report: OS, shell, Python version, `git`, `gh`,
package manager (`brew` / `winget`), and whether the current directory has `.env` and
`.wa-state.json`. Use it instead of guessing. Store `os` in `.wa-state.json`.

If Python itself is missing, `wa_ops.py` cannot run yet — detect with `python3 --version`
(macOS/Linux) or `py -3 --version` / `python --version` (Windows) and install first.

## Required tools and how to install them

| Tool | Needed from | macOS | Windows |
|---|---|---|---|
| Python 3.12 | wa-setup (helper) + wa-build (bot) | `brew install python@3.12` → the command is **`python3.12`** (plain `python3` may still be Apple's 3.9); or the python.org installer | `winget install -e --id Python.Python.3.12` → `py -3.12` |
| Git | wa-deploy (push code) | `xcode-select --install` or `brew install git` | `winget install -e --id Git.Git` |
| GitHub CLI `gh` | wa-deploy (create repo, login) | `brew install gh` | `winget install -e --id GitHub.cli` |

That's all. `jq`, the Render CLI and `curl` are **no longer required** — the helper calls
the Render and Green API REST APIs directly.

**Install only with the student's OK** — say what will be installed and why, in one line,
then run it. winget/brew may ask for the computer password or a UAC prompt; that is the
student's action (*"יקפוץ חלון אישור של Windows — תאשר אותו"*).

### Windows specifics that bite

- **Restart after installing.** The desktop app and terminals don't see a tool installed
  by winget until they restart (PATH is read at launch). After installing Python/Git/gh:
  *"סגור את האפליקציה ופתח מחדש, ואז תכתוב `/wa` — נמשיך בדיוק מאיפה שעצרנו."*
  `.wa-state.json` makes this painless. In the meantime the full path works:
  `"$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"`.
- **Shell.** Without Git for Windows, Claude Code runs commands in **PowerShell**. Once Git
  is installed (and the app restarted) it uses Git Bash. Both are fine for `wa_ops.py`.
  Don't write bash-only constructs (`set -a; source .env`, `$(...)` pipelines, heredocs)
  in instructions meant for Windows — use the helper.
- **`curl` in Windows PowerShell 5.1** is an alias for `Invoke-WebRequest` and does not
  accept curl flags. If a raw call is unavoidable, use `curl.exe` explicitly.
- **Paths with spaces** (`C:\Users\Dana Cohen\...`) — always quote paths.
- **`%USERPROFILE%` is cmd syntax** — in PowerShell it's taken literally. Use `~` (PowerShell and Git Bash both understand it in paths; `wa_ops.py --project ~/whatsapp-agent` expands it itself).
- **`&&` doesn't exist in Windows PowerShell 5.1.** Give commands one per line.
- **Python "App execution alias".** Typing `python` may open the Microsoft Store instead of
  running Python. Use `py -3`, which the python.org/winget installer always provides.
- **Plugins in WSL.** Plugins are not available in WSL sessions of the desktop app — use a
  regular local session.

### macOS specifics

- First `git` call may trigger the Xcode Command Line Tools installer — a system dialog the
  student approves; it takes a few minutes.
- If `brew` is missing, don't install Homebrew just for this: use the python.org installer
  for Python and `xcode-select --install` for git; `gh` has a `.pkg` on
  https://cli.github.com.

## Virtual environment for the bot

wa-build creates `.venv` in the project:

| | macOS / Linux | Windows |
|---|---|---|
| create | `python3.12 -m venv .venv` (`WA_OPS doctor` → `python.venv_create` gives the exact command) | `py -3.12 -m venv .venv` |
| python in venv | `.venv/bin/python` | `.venv\Scripts\python.exe` |

Always call the venv's python explicitly instead of "activating" (activation differs per
shell and doesn't persist between Claude Code commands).

## Where Claude Code is running

- **Desktop app / VS Code / terminal on the same machine** share `~/.claude` — a plugin
  installed in one is available in the others.
- **New plugin or plugin update** is active from the next session, or after `/reload-plugins`.
- **Cloud sessions** (claude.ai/code in the browser) don't load local plugins — the course
  runs locally.
