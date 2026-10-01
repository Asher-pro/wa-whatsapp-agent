#!/usr/bin/env python3
"""wa_ops.py — the WhatsApp-agent plugin's cross-platform operations helper.

One command surface for everything the wa-* skills do outside the bot's own code:
Green API, Render, LLM key checks, the .wa-state.json file, plugin update checks and
drift reports.

Design rules
  * Standard library only — runs on a fresh Python 3.9+ on macOS, Windows or Linux,
    under bash, zsh, Git Bash or PowerShell. No jq, no brew, no Render CLI.
  * Secrets are never printed. Values are read from the project's .env by key name,
    every printed payload is redacted, and `env set KEY --from-clipboard` lets a student
    save a key without it ever appearing in the conversation.
  * Machine-readable output: JSON on stdout. Human hints go to stderr.
  * Exit code 0 = success, 1 = the remote side said no / check failed, 2 = usage or
    local problem (missing .env key, bad arguments).

Run from the bot's project directory (or pass --project DIR):

    python3 wa_ops.py doctor
    python3 wa_ops.py green state
    python3 wa_ops.py render env-set GOOGLE_REFRESH_TOKEN      # value read from .env

`python3 wa_ops.py --help` and `python3 wa_ops.py <group> --help` list everything.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
UPSTREAM_REPO = "Asher-pro/wa-whatsapp-agent"
UPSTREAM_PLUGIN_JSON = (
    f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/main/.claude-plugin/plugin.json"
)
RENDER_API = "https://api.render.com/v1"
STATE_FILE = ".wa-state.json"
ENV_FILE = ".env"
USER_AGENT = "wa-whatsapp-agent-ops/3"

# --------------------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------------------

SECRET_KEY_HINTS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "APIKEY", "PRIVATE", "REFRESH")
SECRET_VALUE_PATTERNS = [
    re.compile(r"rnd_[A-Za-z0-9]{8,}"),            # Render API keys
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),      # Anthropic keys
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),  # OpenAI keys
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),        # Google API keys
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),     # GitHub tokens
    re.compile(r"1//[0-9A-Za-z_\-]{20,}"),         # Google refresh tokens
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),     # Google client secrets
    re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:[^@\s]+@"),  # DB URLs with passwords
]


class OpsError(Exception):
    """A failure we can explain. exit_code 1 = remote said no, 2 = local/usage problem."""

    def __init__(self, message: str, hint: str | None = None, exit_code: int = 1,
                 details: Any = None):
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code
        self.details = details


def _looks_secret_key(key: str) -> bool:
    k = key.upper()
    return any(h in k for h in SECRET_KEY_HINTS)


def redact(obj: Any, extra_secrets: list[str] | None = None) -> Any:
    """Return a deep copy of obj with secret-looking values masked."""
    extra = [s for s in (extra_secrets or []) if s and len(s) >= 6]

    def mask_str(s: str) -> str:
        for secret in extra:
            s = s.replace(secret, secret[:3] + "…" + "[redacted]")
        for pat in SECRET_VALUE_PATTERNS:
            s = pat.sub(lambda m: m.group(0)[:6] + "…[redacted]", s)
        return s

    def walk(o: Any, parent_key: str = "") -> Any:
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if isinstance(v, str) and v and _looks_secret_key(str(k)) and str(k).lower() not in ("key",):
                    out[k] = (v[:3] + "…[redacted]") if len(v) > 6 else "[redacted]"
                else:
                    out[k] = walk(v, str(k))
            return out
        if isinstance(o, list):
            return [walk(x, parent_key) for x in o]
        if isinstance(o, str):
            return mask_str(o)
        return o

    return walk(obj)


_KNOWN_SECRETS: list[str] = []


def emit(data: Any) -> None:
    print(json.dumps(redact(data, _KNOWN_SECRETS), ensure_ascii=False, indent=2))


def hint(msg: str) -> None:
    print(msg, file=sys.stderr)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------------------
# Project files: .env and .wa-state.json
# --------------------------------------------------------------------------------------

class Project:
    def __init__(self, root: Path):
        self.root = root

    @property
    def env_path(self) -> Path:
        return self.root / ENV_FILE

    @property
    def state_path(self) -> Path:
        return self.root / STATE_FILE

    # ---- .env ----
    def read_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if not self.env_path.exists():
            return env
        for raw in self.env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            # strip an inline comment only when the value is unquoted
            if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            env[key] = value
        for k, v in env.items():
            if len(v) >= 8 and (_looks_secret_key(k) or k in ("DATABASE_URL", "DATABASE_URL_PG")):
                _KNOWN_SECRETS.append(v)
        return env

    def env_value(self, key: str, required: bool = True) -> str | None:
        value = os.environ.get(key) or self.read_env().get(key)
        if required and not value:
            raise OpsError(f"{key} is missing from {self.env_path}",
                           hint=f"Add `{key}=...` to .env (the skill tells you where to get it).",
                           exit_code=2)
        return value

    def write_env(self, key: str, value: str) -> bool:
        """Set KEY=value in .env, preserving every other line. Returns True if changed."""
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise OpsError(f"Bad env var name: {key!r}", exit_code=2)
        if "\n" in value:
            raise OpsError("Env values must be a single line", exit_code=2)
        lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        needs_quotes = value != value.strip() or "#" in value or " " in value
        rendered = f'{key}="{value}"' if needs_quotes else f"{key}={value}"
        changed, found = False, False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
                found = True
                if stripped != rendered:
                    lines[i] = rendered
                    changed = True
        if not found:
            lines.append(rendered)
            changed = True
        if changed:
            self.root.mkdir(parents=True, exist_ok=True)
            self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                os.chmod(self.env_path, 0o600)
            except OSError:
                pass
        self.ensure_gitignored(ENV_FILE)
        return changed

    def ensure_gitignored(self, *patterns: str) -> None:
        gi = self.root / ".gitignore"
        existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        missing = [p for p in patterns if p not in existing]
        if missing:
            gi.write_text("\n".join(existing + missing).strip() + "\n", encoding="utf-8")

    # ---- state ----
    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise OpsError(f"{self.state_path} is not valid JSON ({e})",
                           hint="Open the file and fix the syntax, or restore .wa-state.backup.json.",
                           exit_code=2)

    def write_state(self, state: dict[str, Any]) -> None:
        state["last_touched_iso"] = now_iso()
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.state_path)
        self.ensure_gitignored(STATE_FILE, ".wa-state.backup.json")


def plugin_version() -> str:
    try:
        return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return "unknown"


def detect_os() -> str:
    s = platform.system().lower()
    return {"darwin": "macos", "windows": "windows"}.get(s, "linux" if s == "linux" else s)


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """A verifying SSL context that also works on python.org macOS builds without
    'Install Certificates.command' (a very common student setup): if Python has no CA
    bundle of its own, fall back to certifi, then to the OS bundle."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    paths = ssl.get_default_verify_paths()
    has_own = any(p and os.path.exists(p) for p in (paths.cafile, paths.openssl_cafile,
                                                     os.environ.get(paths.openssl_cafile_env or "", "")))
    if has_own or sys.platform.startswith("win"):
        _SSL_CONTEXT = ssl.create_default_context()  # Windows uses the system store
        return _SSL_CONTEXT
    candidates = []
    try:
        import certifi  # type: ignore
        candidates.append(certifi.where())
    except ImportError:
        pass
    candidates += ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"]
    for cafile in candidates:
        if os.path.exists(cafile):
            _SSL_CONTEXT = ssl.create_default_context(cafile=cafile)
            return _SSL_CONTEXT
    _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def http(method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None,
         timeout: float = 30, retries: int = 2, expect_json: bool = True) -> tuple[int, Any]:
    """Make an HTTP request. Retries 429/5xx and connection errors with backoff.

    Returns (status, parsed_body). Raises OpsError on network failure; HTTP error
    statuses are returned, not raised, so callers can explain them.
    """
    data = None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read() or b""
            status = e.code
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
                raise OpsError(
                    f"SSL certificate check failed calling {urllib.parse.urlsplit(url).netloc}",
                    hint=("On macOS with the python.org installer, double-click "
                          "'Install Certificates.command' in /Applications/Python 3.x/ once, then retry."),
                    exit_code=2)
            if attempt < retries:
                attempt += 1
                time.sleep(2 * attempt)
                continue
            raise OpsError(f"Network error calling {urllib.parse.urlsplit(url).netloc}: {reason}",
                           hint="Check the internet connection and that the URL is right.")
        if status in (429, 500, 502, 503, 504) and attempt < retries:
            attempt += 1
            time.sleep(3 * attempt)
            continue
        if not raw:
            return status, None
        text = raw.decode("utf-8", errors="replace")
        if expect_json:
            try:
                return status, json.loads(text)
            except json.JSONDecodeError:
                return status, text
        return status, text


def _fail(service: str, status: int, payload: Any, hint_text: str | None = None) -> OpsError:
    return OpsError(f"{service} returned HTTP {status}", hint=hint_text, details=payload)


# --------------------------------------------------------------------------------------
# doctor — what machine are we on, what's installed
# --------------------------------------------------------------------------------------

def _which_version(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        out = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, timeout=15)
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0] if text else "installed"
    except Exception:
        return "installed"


def cmd_doctor(args, project: Project) -> int:
    os_name = detect_os()
    shell = os.environ.get("SHELL") or ("powershell" if os.environ.get("PSModulePath") and os_name == "windows"
                                       else os.environ.get("ComSpec", "unknown"))
    tools = {
        "git": _which_version(["git", "--version"]),
        "gh": _which_version(["gh", "--version"]),
        "brew": _which_version(["brew", "--version"]) if os_name == "macos" else None,
        "winget": _which_version(["winget", "--version"]) if os_name == "windows" else None,
    }
    gh_logged_in = None
    if tools["gh"]:
        try:
            r = subprocess.run([shutil.which("gh"), "auth", "status"], capture_output=True, text=True, timeout=15)
            gh_logged_in = r.returncode == 0
        except Exception:
            gh_logged_in = None
    venv_python = project.root / (".venv/Scripts/python.exe" if os_name == "windows" else ".venv/bin/python")
    py_ok = sys.version_info >= (3, 10)
    # The bot runs on 3.12 (Render pin). On macOS, `brew install python@3.12` provides
    # `python3.12`, not `python3`, so look for it explicitly.
    py312_cmd = ["py", "-3.12"] if os_name == "windows" else ["python3.12"]
    py312 = _which_version(py312_cmd + ["--version"])
    if py312 and "3.12" not in py312:
        py312 = None
    venv_cmd = (" ".join(py312_cmd) if py312 else ("py -3" if os_name == "windows" else "python3")) + " -m venv .venv"
    report = {
        "os": os_name,
        "os_release": platform.release(),
        "shell": shell,
        "python": {"version": platform.python_version(), "executable": sys.executable,
                   "ok_for_bot": py_ok or bool(py312),
                   "launcher": "py -3" if os_name == "windows" else "python3",
                   "python312": " ".join(py312_cmd) if py312 else None,
                   "venv_create": venv_cmd},
        "tools": tools,
        "gh_logged_in": gh_logged_in,
        "project": {
            "dir": str(project.root),
            "has_env": project.env_path.exists(),
            "env_keys": sorted(project.read_env().keys()),
            "has_state": project.state_path.exists(),
            "has_spec": (project.root / "spec.json").exists(),
            "has_venv": venv_python.exists(),
            "venv_python": str(venv_python),
            "is_git_repo": (project.root / ".git").exists(),
        },
        "plugin": {"version": plugin_version(), "root": str(PLUGIN_ROOT),
                   "wa_ops": str(Path(__file__).resolve())},
    }
    missing = []
    if not (py_ok or py312):
        missing.append("python>=3.10 (bot needs 3.12)")
    if not tools["git"]:
        missing.append("git")
    if not tools["gh"]:
        missing.append("gh")
    report["missing"] = missing
    emit(report)
    return 0


# --------------------------------------------------------------------------------------
# state — .wa-state.json
# --------------------------------------------------------------------------------------

V1_TO_V2 = {
    "render_url": ("render", "url"),
    "render_service_id": ("render", "service_id"),
    "render_dashboard_url": ("render", "dashboard_url"),
    "render_postgres_id": ("render", "postgres_id"),
    "render_region": ("render", "region"),
}


def migrate_state(state: dict[str, Any], project: Project) -> tuple[dict[str, Any], bool]:
    if not state:
        return state, False
    changed = False
    if state.get("version", 1) < 2:
        render = dict(state.get("render") or {})
        for old, (_, new) in V1_TO_V2.items():
            if old in state:
                if state[old] is not None and render.get(new) is None:
                    render[new] = state[old]
                del state[old]
        state["render"] = render
        state["version"] = 2
        changed = True
    for key, default in (("drift_log", []), ("maintenance_log", []), ("upgrades_applied", []),
                         ("connected_tools", []), ("completed_stages", []),
                         ("timezone", "Asia/Jerusalem")):
        if key not in state:
            state[key] = default
            changed = True
    if not state.get("os"):
        state["os"] = detect_os()
        changed = True
    if not state.get("project_dir"):
        state["project_dir"] = str(project.root)
        changed = True
    # v2 wa-connect set current_stage="deploy" after the last tool, sending finished bots
    # back into wa-deploy. A deployed bot is never "at deploy" again.
    render_sid = _get_path(state, "render.service_id")
    if state.get("current_stage") == "deploy" and "deploy" in (state.get("completed_stages") or []) and render_sid:
        state["current_stage"] = "connect" if _remaining_external_tools(state, project) else "maintain"
        changed = True
    return state, changed


def _remaining_external_tools(state: dict[str, Any], project: Project) -> list[str]:
    try:
        spec = json.loads((project.root / "spec.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    connected = set(state.get("connected_tools") or []) | {"reminders"}
    return [t for t in (spec.get("tools") or []) if t not in connected]


def _get_path(d: dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(d: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _parse_value(raw: str) -> Any:
    """JSON for objects/lists/quoted strings/true/false/null; everything else stays a string
    (so IDs like 7105222798 or phone numbers never turn into numbers)."""
    text = raw.strip()
    if text in ("true", "false", "null") or text[:1] in ("{", "[", '"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return raw
    return raw


def cmd_state(args, project: Project) -> int:
    state = project.read_state()
    if args.state_cmd == "get":
        if not state:
            emit({"exists": False, "path": str(project.state_path)})
            return 0
        emit(_get_path(state, args.key) if args.key else state)
        return 0
    if args.state_cmd == "init":
        if state and not args.force:
            raise OpsError(".wa-state.json already exists", hint="Use `state migrate`, or --force to back it up and start fresh.", exit_code=2)
        if state:
            (project.root / ".wa-state.backup.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        state = {"version": 2, "project_dir": str(project.root), "os": detect_os(), "bot_name": None,
                 "archetype": None, "timezone": "Asia/Jerusalem", "current_stage": "setup",
                 "completed_stages": [], "connected_tools": [], "render": {}, "drift_log": [],
                 "maintenance_log": [], "upgrades_applied": [], "plugin_version": plugin_version()}
        project.write_state(state)
        emit(state)
        return 0
    if not state:
        raise OpsError("No .wa-state.json in this directory", hint="Run from the bot's project directory, or `state init`.", exit_code=2)
    if args.state_cmd == "migrate":
        state, changed = migrate_state(state, project)
        if changed:
            project.write_state(state)
        emit({"migrated": changed, "state": state})
        return 0
    state, _ = migrate_state(state, project)
    if args.state_cmd == "set":
        for pair in args.pairs:
            if "=" not in pair:
                raise OpsError(f"Expected key=value, got {pair!r}", exit_code=2)
            k, _, v = pair.partition("=")
            _set_path(state, k.strip(), _parse_value(v))
    elif args.state_cmd == "append":
        cur = _get_path(state, args.key)
        cur = list(cur) if isinstance(cur, list) else []
        value = _parse_value(args.value)
        if value not in cur:
            cur.append(value)
        _set_path(state, args.key, cur)
    elif args.state_cmd == "stage-done":
        done = list(state.get("completed_stages") or [])
        if args.stage not in done:
            done.append(args.stage)
        state["completed_stages"] = done
        state["current_stage"] = args.next_stage
        if args.stage == "build":
            # plugin_version = the version the bot's CODE was built/upgraded with. Only a
            # build or an upgrade audit may set it — otherwise older bots would silently
            # skip the fixes in knowledge/upgrades.md.
            state["plugin_version"] = plugin_version()
    elif args.state_cmd == "log":
        entry = {"ts": now_iso(), "change": args.text, "plugin_version": plugin_version()}
        log = list(state.get("maintenance_log") or [])
        log.append(entry)
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=180)
        state["maintenance_log"] = [e for e in log if _parse_iso(e.get("ts")) >= cutoff][-50:]
    elif args.state_cmd == "drift":
        entry = {"ts": now_iso(), "plugin_version": plugin_version(), "skill": args.skill,
                 "fact_id": args.fact_id, "expected": args.expected, "observed": args.observed,
                 "fix_that_worked": args.fix, "reported": False}
        state.setdefault("drift_log", []).append(scrub_text_fields(entry))
    project.write_state(state)
    emit(state if args.state_cmd != "drift" else {"logged": True, "unreported": sum(1 for e in state["drift_log"] if not e.get("reported"))})
    return 0


def _parse_iso(value: Any) -> _dt.datetime:
    try:
        return _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)


PHONE_RE = re.compile(r"(?<!\d)(?:\+?972|0)5\d[\s\-]?\d{3}[\s\-]?\d{4}(?!\d)|(?<!\d)\d{11,15}(?:@[a-z.]+)?")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def scrub_text_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Remove phone numbers, emails and secrets from free-text drift fields."""
    out = {}
    for k, v in entry.items():
        if isinstance(v, str):
            v = redact(v)
            v = PHONE_RE.sub("[phone]", v)
            v = EMAIL_RE.sub("[email]", v)
        out[k] = v
    return out


# --------------------------------------------------------------------------------------
# env — .env management (values never echoed)
# --------------------------------------------------------------------------------------

EXPECTED_SHAPES = {
    "ANTHROPIC_API_KEY": (r"^sk-ant-", "an Anthropic key starting with sk-ant-"),
    "RENDER_API_KEY": (r"^rnd_", "a Render key starting with rnd_"),
    "OPENAI_API_KEY": (r"^sk-", "an OpenAI key starting with sk-"),
    "GOOGLE_API_KEY": (r"^AIza", "a Google AI Studio key starting with AIza"),
    "DATABASE_URL": (r"^postgres(ql)?://", "a postgresql:// connection string"),
    "GREEN_API_URL": (r"^https?://", "a URL like https://7105.api.greenapi.com"),
    "GREEN_API_INSTANCE": (r"^\d+$", "digits only"),
}


def _sanity_check_value(key: str, value: str) -> str | None:
    shape = EXPECTED_SHAPES.get(key)
    if shape and not re.search(shape[0], value):
        return f"This doesn't look like {shape[1]} — saved anyway; double-check what was copied."
    if key == "DATABASE_URL" and "[YOUR-PASSWORD]" in value:
        return "The URL still contains [YOUR-PASSWORD] — replace it with the real password."
    return None


def read_clipboard() -> str:
    """Read the system clipboard (macOS pbpaste, Windows Get-Clipboard, Linux wl-paste/xclip)."""
    os_name = detect_os()
    if os_name == "macos":
        cmds = [["pbpaste"]]
    elif os_name == "windows":
        cmds = [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                ["pwsh", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]
    else:
        cmds = [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]]
    for cmd in cmds:
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        try:
            r = subprocess.run([exe] + cmd[1:], capture_output=True, timeout=10)
        except Exception:
            continue
        if r.returncode == 0:
            return r.stdout.decode("utf-8", errors="replace")
    raise OpsError("Couldn't read the clipboard on this computer",
                   hint="Pass the value as an argument instead (it will appear in the conversation).", exit_code=2)

def cmd_env(args, project: Project) -> int:
    if args.env_cmd == "set":
        value = args.value
        if args.generate:
            value = secrets.token_urlsafe(32)
        elif args.from_clipboard:
            value = read_clipboard()
        if value is None:
            if sys.stdin.isatty():
                import getpass
                value = getpass.getpass(f"Value for {args.key} (hidden): ")
            else:
                raise OpsError(f"No value given for {args.key}",
                               hint="Ask the student to copy the value and run again with --from-clipboard "
                                    "(keeps it out of the conversation), or pass it as an argument.",
                               exit_code=2)
        value = value.strip()
        if not value:
            raise OpsError(f"Empty value for {args.key}",
                           hint="The clipboard was empty — ask the student to copy the value again." if args.from_clipboard else None,
                           exit_code=2)
        warning = _sanity_check_value(args.key, value)
        changed = project.write_env(args.key, value)
        out = {"key": args.key, "saved": True, "changed": changed, "length": len(value)}
        if warning:
            out["warning"] = warning
        emit(out)
        return 0
    if args.env_cmd == "check":
        env = project.read_env()
        result = {k: bool(env.get(k) or os.environ.get(k)) for k in args.keys}
        emit({"present": result, "all_present": all(result.values())})
        return 0 if all(result.values()) else 1
    if args.env_cmd == "keys":
        emit(sorted(project.read_env().keys()))
        return 0
    raise OpsError("unknown env command", exit_code=2)


# --------------------------------------------------------------------------------------
# llm — key and model checks (Anthropic / OpenAI / Google)
# --------------------------------------------------------------------------------------

ANTHROPIC_VERSION = "2023-06-01"


def _anthropic_headers(key: str) -> dict[str, str]:
    return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}


def _explain_anthropic(status: int, payload: Any) -> OpsError:
    err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
    msg = str(err.get("message", ""))
    if status == 401:
        return _fail("Anthropic", status, payload,
                     "The key is wrong, revoked, or EXPIRED (keys created with an expiration stop working "
                     "and cannot be revived). Create a new key with Expiration = Never — see F-ANTHROPIC-KEY-DIALOG.")
    if status == 400 and "workspace" in msg.lower():
        return _fail("Anthropic", status, payload,
                     "This key works on several workspaces, so every request would need an "
                     "anthropic-workspace-id header. Simpler: create a new key scoped to the Default workspace.")
    if status == 402 or err.get("type") == "billing_error":
        return _fail("Anthropic", status, payload, "No credit. Add credit at https://platform.claude.com/settings/billing")
    if status == 404:
        return _fail("Anthropic", status, payload, "That model ID doesn't exist for this key. Run `llm models`.")
    if status == 429:
        return _fail("Anthropic", status, payload, "Rate limited — wait a minute and retry.")
    return _fail("Anthropic", status, payload)


def cmd_llm(args, project: Project) -> int:
    env = project.read_env()
    provider = (args.provider or env.get("LLM_PROVIDER") or "anthropic").lower()
    if provider == "anthropic":
        key = project.env_value("ANTHROPIC_API_KEY")
        if args.llm_cmd == "models":
            status, payload = http("GET", "https://api.anthropic.com/v1/models?limit=1000",
                                   headers=_anthropic_headers(key))
            if status != 200:
                raise _explain_anthropic(status, payload)
            models = [{"id": m.get("id"), "display_name": m.get("display_name"),
                       "created_at": m.get("created_at")} for m in payload.get("data", [])]
            if args.family:
                models = [m for m in models if args.family.lower() in (m["id"] or "").lower()]
            emit({"provider": "anthropic", "models": models})
            return 0
        model = args.model or env.get("LLM_MODEL") or "claude-haiku-4-5"
        status, payload = http("GET", f"https://api.anthropic.com/v1/models/{urllib.parse.quote(model)}",
                               headers=_anthropic_headers(key))
        if status != 200:
            raise _explain_anthropic(status, payload)
        result = {"provider": "anthropic", "key_ok": True, "model": model,
                  "model_resolved": payload.get("id"), "display_name": payload.get("display_name")}
        if args.ping:
            status, msg = http("POST", "https://api.anthropic.com/v1/messages",
                               headers=_anthropic_headers(key),
                               body={"model": model, "max_tokens": 16,
                                     "messages": [{"role": "user", "content": "Reply with: ok"}]},
                               timeout=60)
            if status != 200:
                raise _explain_anthropic(status, msg)
            text = "".join(b.get("text", "") for b in (msg or {}).get("content", []) if b.get("type") == "text")
            result.update({"ping": "ok", "reply": text.strip()[:40], "usage": (msg or {}).get("usage")})
        emit(result)
        return 0
    if provider == "openai":
        key = project.env_value("OPENAI_API_KEY")
        status, payload = http("GET", "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
        if status != 200:
            raise _fail("OpenAI", status, payload, "Check the key at https://platform.openai.com/api-keys and billing.")
        ids = sorted(m.get("id") for m in payload.get("data", []))
        if args.family:
            ids = [i for i in ids if args.family.lower() in i.lower()]
        model = args.model or env.get("LLM_MODEL")
        emit({"provider": "openai", "key_ok": True, "model": model,
              "model_available": (model in ids) if model else None,
              "models": ids if args.llm_cmd == "models" else None})
        return 0
    if provider == "google":
        key = project.env_value("GOOGLE_API_KEY")
        status, payload = http("GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
                               headers={"x-goog-api-key": key})
        if status != 200:
            raise _fail("Google Gemini", status, payload, "Check the key at https://aistudio.google.com/apikey")
        ids = sorted(m.get("name", "").removeprefix("models/") for m in payload.get("models", []))
        if args.family:
            ids = [i for i in ids if args.family.lower() in i.lower()]
        model = args.model or env.get("LLM_MODEL")
        emit({"provider": "google", "key_ok": True, "model": model,
              "model_available": (model in ids) if model else None,
              "models": ids if args.llm_cmd == "models" else None})
        return 0
    raise OpsError(f"Unknown provider {provider!r}", exit_code=2)


# --------------------------------------------------------------------------------------
# plugin — version and update check
# --------------------------------------------------------------------------------------

def _vtuple(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def cmd_plugin(args, project: Project) -> int:
    local = plugin_version()
    if args.plugin_cmd == "version":
        emit({"version": local, "root": str(PLUGIN_ROOT)})
        return 0
    # check-update
    status, payload = http("GET", UPSTREAM_PLUGIN_JSON, timeout=10, retries=1)
    latest = payload.get("version") if status == 200 and isinstance(payload, dict) else None
    update = bool(latest) and _vtuple(latest) > _vtuple(local)
    out = {
        "installed": local,
        "latest": latest,
        "update_available": update,
        "how_to_update": [
            "/plugin marketplace update practice-ai-plugins",
            "/plugin update wa-whatsapp-agent@practice-ai-plugins  (or reinstall from the /plugin menu)",
            "/reload-plugins  (or start a new session)",
        ] if update else [],
        "changelog": f"https://github.com/{UPSTREAM_REPO}/blob/main/CHANGELOG.md" if update else None,
    }
    if latest is None:
        out["note"] = "Could not reach GitHub to check for updates — not a problem, continue."
    state = project.read_state()
    if state:
        state["last_update_check_iso"] = now_iso()
        project.write_state(state)
    emit(out)
    return 0


# --------------------------------------------------------------------------------------
# report-drift — turn drift_log into an upstream GitHub issue (with consent)
# --------------------------------------------------------------------------------------

def build_drift_issue(state: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    entries = [scrub_text_fields(e) for e in state.get("drift_log", []) if not e.get("reported")]
    title = f"[drift] {len(entries)} change(s) seen by a student — plugin {plugin_version()}"
    lines = [
        "Automated drift report from the `wa-whatsapp-agent` plugin (sent with the student's consent).",
        "No secrets, phone numbers or emails are included.",
        "",
        f"- plugin version: `{plugin_version()}`",
        f"- OS: `{state.get('os') or detect_os()}`",
        f"- stage: `{state.get('current_stage')}`",
        "",
        "| skill | fact | expected | observed | fix that worked |",
        "|---|---|---|---|---|",
    ]
    for e in entries:
        cells = [str(e.get(k) or "").replace("|", "\\|").replace("\n", " ")[:300]
                 for k in ("skill", "fact_id", "expected", "observed", "fix_that_worked")]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "_Maintainers: review, then add the `drift` label to trigger `.github/workflows/auto-refresh.yml`._"]
    return title, "\n".join(lines), entries


def cmd_report_drift(args, project: Project) -> int:
    state = project.read_state()
    title, body, entries = build_drift_issue(state)
    if not entries:
        emit({"unreported": 0, "message": "Nothing to report."})
        return 0
    if not args.post:
        emit({"unreported": len(entries), "title": title, "body": body,
              "manual_url": f"https://github.com/{UPSTREAM_REPO}/issues/new?template=drift-report.md",
              "next": "Show this text to the student. Only with their OK: re-run with --post."})
        return 0
    gh = shutil.which("gh")
    if not gh:
        raise OpsError("gh is not installed", hint=f"Paste the text manually at https://github.com/{UPSTREAM_REPO}/issues/new?template=drift-report.md", exit_code=2)
    # No label on purpose: a maintainer reviews the report and adds the "drift" label,
    # which is what triggers the auto-refresh workflow (the human gate).
    cmd = [gh, "issue", "create", "--repo", UPSTREAM_REPO, "--title", title, "--body-file", "-"]
    r = subprocess.run(cmd, input=body, capture_output=True, text=True)
    if r.returncode != 0:
        raise OpsError("gh issue create failed", hint=(r.stderr or "").strip()[:300])
    for e in state.get("drift_log", []):
        e["reported"] = True
    project.write_state(state)
    emit({"posted": True, "url": r.stdout.strip()})
    return 0


# --------------------------------------------------------------------------------------
# green — Green API instance operations
# --------------------------------------------------------------------------------------

def _green(project: Project) -> tuple[str, str, str]:
    url = project.env_value("GREEN_API_URL").rstrip("/")
    instance = project.env_value("GREEN_API_INSTANCE")
    token = project.env_value("GREEN_API_TOKEN")
    if not url.startswith("http"):
        url = "https://" + url
    return url, instance, token


def green_call(project: Project, method: str, verb: str = "GET", body: Any = None,
               suffix: str = "", timeout: float = 30) -> Any:
    url, instance, token = _green(project)
    full = f"{url}/waInstance{instance}/{method}/{token}{suffix}"
    status, payload = http(verb, full, body=body, timeout=timeout)
    if status == 200:
        return payload
    hints = {
        401: "GREEN_API_INSTANCE or GREEN_API_TOKEN is wrong — copy them again from the console.",
        403: "The instance is not paid/active, or the token is wrong.",
        404: "GREEN_API_URL or the instance ID is wrong (the URL must match the instance, e.g. https://7105.api.greenapi.com).",
        466: "Plan limit reached (the free Developer plan only talks to a few chats). See F-GREENAPI-PLANS.",
        429: "Too many requests — wait a few seconds.",
    }
    raise _fail(f"Green API {method}", status, payload, hints.get(status))


STANDARD_GREEN_SETTINGS = {
    "incomingWebhook": "yes",
    "outgoingMessageWebhook": "no",
    "outgoingAPIMessageWebhook": "no",
    "outgoingWebhook": "no",
    "stateWebhook": "no",
    "incomingCallWebhook": "no",
    "pollMessageWebhook": "no",
    # Keep senders as phone numbers (972…@c.us). LID mode is beta and turns senders into
    # opaque …@lid ids, which breaks phone-number whitelists (F-GREENAPI-LID).
    "enableLidMode": "no",
}


def _bot_phone_from_settings(settings: dict[str, Any]) -> str | None:
    wid = (settings or {}).get("wid") or ""
    return wid.split("@", 1)[0] if wid and "@c.us" in wid else None


def cmd_green(args, project: Project) -> int:
    c = args.green_cmd
    if c == "state":
        emit(green_call(project, "getStateInstance"))
        return 0
    if c == "settings":
        s = green_call(project, "getSettings")
        if isinstance(s, dict) and s.get("webhookUrlToken"):
            s["webhookUrlToken"] = "[set]"
        emit(s)
        return 0
    if c == "wid":
        s = green_call(project, "getSettings")
        phone = _bot_phone_from_settings(s)
        state = project.read_state()
        if state and phone:
            state.setdefault("green_api", {})["bot_phone"] = phone
            project.write_state(state)
        emit({"wid": s.get("wid"), "bot_phone": phone})
        return 0
    if c == "wait-authorized":
        deadline = time.time() + args.timeout
        last = None
        while time.time() < deadline:
            last = (green_call(project, "getStateInstance") or {}).get("stateInstance")
            if last == "authorized":
                emit({"stateInstance": last, "authorized": True})
                return 0
            hint(f"  stateInstance={last} — waiting for the QR scan…")
            time.sleep(5)
        emit({"stateInstance": last, "authorized": False})
        return 1
    if c == "configure":
        body = dict(STANDARD_GREEN_SETTINGS)
        if args.webhook_url is not None:
            body["webhookUrl"] = args.webhook_url
        if args.webhook_token_from_env:
            tok = project.env_value(args.webhook_token_from_env)
            body["webhookUrlToken"] = f"Bearer {tok}"
        elif args.clear_webhook_token:
            body["webhookUrlToken"] = ""
        resp = green_call(project, "setSettings", "POST", body)
        if not (isinstance(resp, dict) and resp.get("saveSettings")):
            raise OpsError("setSettings did not confirm saveSettings=true", details=resp)
        # setSettings reboots the instance; changes can take up to ~5 minutes to show
        # (F-GREENAPI-SETTINGS-DELAY). Poll gently — the API allows ~1 request/second.
        expected_url = args.webhook_url
        for attempt in range(args.verify_tries):
            time.sleep(10)
            s = green_call(project, "getSettings")
            url_ok = expected_url is None or (s.get("webhookUrl") or "") == expected_url
            if s.get("incomingWebhook") == "yes" and url_ok:
                emit({"saved": True, "verified": True, "webhookUrl": s.get("webhookUrl"),
                      "incomingWebhook": s.get("incomingWebhook"),
                      "webhookUrlToken": "[set]" if s.get("webhookUrlToken") else "[empty]"})
                return 0
            hint(f"  [{attempt + 1}/{args.verify_tries}] settings not visible yet (the instance restarts after setSettings)…")
        emit({"saved": True, "verified": False,
              "note": "Saved, not visible yet. Green API can take up to 5 minutes — run `green settings` again shortly."})
        return 1
    if c == "send":
        chat_id = to_chat_id(args.to)
        resp = green_call(project, "sendMessage", "POST", {"chatId": chat_id, "message": args.text})
        emit({"sent": True, "chatId": chat_id, "idMessage": (resp or {}).get("idMessage")})
        return 0
    if c == "wait-incoming":
        s = green_call(project, "getSettings")
        if (s or {}).get("webhookUrl"):
            raise OpsError("A webhook URL is set, so incoming messages go to the server, not the HTTP queue.",
                           hint="This check only works before deploy. After deploy, watch `render logs` instead.",
                           exit_code=2)
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            n = green_call(project, "receiveNotification", suffix="?receiveTimeout=20", timeout=40)
            if not n:
                hint("  no message yet…")
                continue
            receipt = n.get("receiptId")
            body = n.get("body") or {}
            if receipt is not None:
                green_call(project, "deleteNotification", "DELETE", suffix=f"/{receipt}")
            if body.get("typeWebhook") == "incomingMessageReceived":
                sd = body.get("senderData") or {}
                emit({"received": True, "typeMessage": (body.get("messageData") or {}).get("typeMessage"),
                      "from_chatId": sd.get("chatId"), "sender": sd.get("sender"),
                      "senderName": sd.get("senderName")})
                return 0
        emit({"received": False})
        return 1
    if c == "chats":
        chats = green_call(project, "getChats") or []
        if args.groups:
            chats = [ch for ch in chats if str(ch.get("id", "")).endswith("@g.us")]
        emit([{"id": ch.get("newChatId") or ch.get("id"), "name": ch.get("name"), "type": ch.get("type")}
              for ch in chats])
        return 0
    raise OpsError("unknown green command", exit_code=2)


def to_chat_id(value: str) -> str:
    """'050-123 4567' / '+972501234567' / '972501234567@c.us' → '972501234567@c.us'."""
    v = value.strip()
    if "@" in v:
        return v
    digits = re.sub(r"\D", "", v)
    if digits.startswith("0") and len(digits) == 10:  # Israeli local format
        digits = "972" + digits[1:]
    if not (8 <= len(digits) <= 15):
        raise OpsError(f"{value!r} doesn't look like a phone number", hint="Use country code + number, e.g. 972501234567", exit_code=2)
    return f"{digits}@c.us"


# --------------------------------------------------------------------------------------
# render — Render REST API (no CLI needed)
# --------------------------------------------------------------------------------------

TERMINAL_DEPLOY_STATUSES = {"live", "deactivated", "build_failed", "update_failed", "canceled", "pre_deploy_failed"}


def render_call(project: Project, verb: str, path: str, body: Any = None,
                ok: tuple[int, ...] = (200, 201, 202, 204)) -> Any:
    key = project.env_value("RENDER_API_KEY")
    status, payload = http(verb, f"{RENDER_API}{path}", headers={"Authorization": f"Bearer {key}"}, body=body)
    if status in ok:
        return payload
    msg = payload.get("message") if isinstance(payload, dict) else str(payload)[:300]
    hints = {
        401: "RENDER_API_KEY is wrong or was deleted. Create a new one: Account Settings → API Keys (F-RENDER-API-KEY).",
        402: "Render needs a payment method for this plan. The student adds a card in the dashboard (Billing), then retry.",
        404: "Not found — wrong service/owner ID, or the resource was deleted.",
        409: "Conflict — something with that name already exists, or another operation is running.",
        429: "Render rate limit — wait a minute and retry.",
    }
    h = hints.get(status)
    if status == 400 and msg and re.search(r"repo|git|credential|access", msg, re.I):
        h = ("Render can't read the GitHub repo. Connect GitHub once: Account Settings → Account Security → "
             "Git Deployment Credentials → Add credential (F-RENDER-GIT-CONNECT), and give the Render GitHub app "
             "access to this repo: https://github.com/apps/render/installations/new — then retry.")
    raise OpsError(f"Render API {verb} {path} → HTTP {status}: {msg}", hint=h, details=payload)


def _render_service_id(project: Project, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    state = project.read_state()
    sid = _get_path(state, "render.service_id") or state.get("render_service_id")
    if not sid:
        raise OpsError("No Render service ID in .wa-state.json", hint="Pass --service srv-…, or run `render create-service` first.", exit_code=2)
    return sid


def _render_owner_id(project: Project, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    state = project.read_state()
    if _get_path(state, "render.owner_id"):
        return _get_path(state, "render.owner_id")
    owners = render_call(project, "GET", "/owners?limit=100") or []
    owners = [o.get("owner", o) for o in owners]
    if len(owners) == 1:
        return owners[0]["id"]
    raise OpsError("This Render account has several workspaces — choose one.",
                   hint="Run `render owners`, ask the student which workspace, then pass --owner tea-…",
                   details=[{"id": o.get("id"), "name": o.get("name"), "type": o.get("type")} for o in owners],
                   exit_code=2)


def _save_render_state(project: Project, **values: Any) -> None:
    state = project.read_state()
    if not state:
        return
    state, _ = migrate_state(state, project)
    render = dict(state.get("render") or {})
    render.update({k: v for k, v in values.items() if v is not None})
    state["render"] = render
    project.write_state(state)


def _latest_deploy(project: Project, sid: str, since: _dt.datetime | None = None) -> dict[str, Any] | None:
    """Newest deploy, optionally only one created at/after `since` (so a queued deploy
    that hasn't appeared yet is never confused with the previous, already-live one)."""
    items = render_call(project, "GET", f"/services/{sid}/deploys?limit=5") or []
    deploys = [i.get("deploy", i) for i in items]
    deploys.sort(key=lambda d: d.get("createdAt") or "", reverse=True)
    if since is not None:
        deploys = [d for d in deploys if _parse_iso(d.get("createdAt")) >= since]
    return deploys[0] if deploys else None


def _git_head(project: Project) -> str | None:
    git = shutil.which("git")
    if not git or not (project.root / ".git").exists():
        return None
    try:
        r = subprocess.run([git, "rev-parse", "HEAD"], cwd=project.root, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        return r.stdout.strip() or None
    except Exception:
        return None


def _deploy_for_commit(project: Project, sid: str, commit: str) -> dict[str, Any] | None:
    items = render_call(project, "GET", f"/services/{sid}/deploys?limit=10") or []
    deploys = sorted((i.get("deploy", i) for i in items), key=lambda d: d.get("createdAt") or "", reverse=True)
    for d in deploys:
        cid = ((d.get("commit") or {}).get("id") or "")
        if cid and (cid.startswith(commit) or commit.startswith(cid)):
            return d
    return None


def _wait_deploy(project: Project, sid: str, deploy_id: str | None, timeout: int,
                 since: _dt.datetime | None = None, commit: str | None = None) -> dict[str, Any]:
    """Wait for a deploy to finish. Identify it by id, else by commit (the pushed HEAD),
    else as the newest deploy created after `since`. Never report an older deploy."""
    deadline = time.time() + timeout
    dep: dict[str, Any] | None = None
    while time.time() < deadline:
        if deploy_id:
            dep = render_call(project, "GET", f"/services/{sid}/deploys/{deploy_id}")
        elif commit:
            dep = _deploy_for_commit(project, sid, commit)
            deploy_id = (dep or {}).get("id")
            if not dep:
                hint(f"  waiting for Render to start deploying commit {commit[:8]}…")
        else:
            dep = _latest_deploy(project, sid, since)
            deploy_id = (dep or {}).get("id")
        status = (dep or {}).get("status")
        hint(f"  deploy {deploy_id}: {status}")
        if status in TERMINAL_DEPLOY_STATUSES:
            break
        time.sleep(15)
    result = {"deploy_id": deploy_id, "status": (dep or {}).get("status"),
              "commit": ((dep or {}).get("commit") or {}).get("id"), "live": (dep or {}).get("status") == "live"}
    if not result["live"]:
        try:
            result["recent_logs"] = _fetch_logs(project, sid, limit=60,
                                                log_type="build" if (dep or {}).get("status") == "build_failed" else None)
        except OpsError:
            pass
        if (dep or {}).get("status") is None or time.time() >= deadline:
            result["timed_out"] = True
        if dep is None and commit:
            result["hint"] = (f"No deploy for commit {commit[:8]} appeared. Was it pushed (`git status`)? "
                              "Is auto-deploy on? Otherwise run `render deploy --wait`.")
    return result


def _fetch_logs(project: Project, sid: str, limit: int = 100, text: str | None = None,
                log_type: str | None = None, minutes: int = 60) -> list[str]:
    owner = _render_owner_id(project)
    start = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=minutes)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    params = [("ownerId", owner), ("resource", sid), ("direction", "backward"),
              ("limit", str(min(limit, 100))), ("startTime", start)]
    if text:
        params.append(("text", text))
    if log_type:
        params.append(("type", log_type))
    payload = render_call(project, "GET", "/logs?" + urllib.parse.urlencode(params)) or {}
    lines = [f"{l.get('timestamp', '')} {l.get('message', '')}" for l in payload.get("logs", [])]
    return list(reversed(lines))


def cmd_render(args, project: Project) -> int:
    c = args.render_cmd
    if c == "owners":
        owners = render_call(project, "GET", "/owners?limit=100") or []
        emit([{"id": o.get("owner", o).get("id"), "name": o.get("owner", o).get("name"),
               "type": o.get("owner", o).get("type")} for o in owners])
        return 0

    if c == "create-service":
        owner = _render_owner_id(project, args.owner)
        env = project.read_env()
        env_vars = []
        for k in [k.strip() for k in (args.env_keys or "").split(",") if k.strip()]:
            if env.get(k):
                env_vars.append({"key": k, "value": env[k]})
            else:
                hint(f"  skipping {k}: empty or missing in .env")
        for pair in args.env or []:
            k, _, v = pair.partition("=")
            env_vars.append({"key": k.strip(), "value": v})
        if args.disk_gb and args.plan == "free":
            raise OpsError("Free instances can't have a disk (F-RENDER-FREE-LIMITS).",
                           hint="Use --plan starter, or skip the disk and use wa-persistence (Supabase).", exit_code=2)
        details: dict[str, Any] = {
            "runtime": "python",
            "plan": args.plan,
            "region": args.region,
            "healthCheckPath": args.health_path,
            "envSpecificDetails": {
                "buildCommand": args.build_command,
                "startCommand": args.start_command,
            },
        }
        if args.disk_gb:
            details["disk"] = {"name": "data", "mountPath": args.disk_mount, "sizeGB": args.disk_gb}
        body = {"type": "web_service", "name": args.name, "ownerId": owner, "repo": args.repo,
                "branch": args.branch, "autoDeployTrigger": "commit", "envVars": env_vars,
                "serviceDetails": details}
        resp = render_call(project, "POST", "/services", body) or {}
        svc = resp.get("service", resp)
        out = {"service_id": svc.get("id"), "url": (svc.get("serviceDetails") or {}).get("url"),
               "dashboard_url": svc.get("dashboardUrl"), "deploy_id": resp.get("deployId"),
               "plan": args.plan, "region": args.region, "env_vars_set": [e["key"] for e in env_vars]}
        _save_render_state(project, service_id=out["service_id"], url=out["url"],
                           dashboard_url=out["dashboard_url"], owner_id=owner, plan=args.plan, region=args.region)
        emit(out)
        return 0

    sid = _render_service_id(project, getattr(args, "service", None))

    if c == "status":
        svc = render_call(project, "GET", f"/services/{sid}")
        dep = _latest_deploy(project, sid)
        plan = (svc.get("serviceDetails") or {}).get("plan")
        if plan:
            _save_render_state(project, plan=plan, url=(svc.get("serviceDetails") or {}).get("url"))
        emit({"service_id": sid, "name": svc.get("name"), "suspended": svc.get("suspended"),
              "url": (svc.get("serviceDetails") or {}).get("url"), "plan": (svc.get("serviceDetails") or {}).get("plan"),
              "region": (svc.get("serviceDetails") or {}).get("region"), "dashboard_url": svc.get("dashboardUrl"),
              "latest_deploy": {"id": (dep or {}).get("id"), "status": (dep or {}).get("status"),
                                "commit": ((dep or {}).get("commit") or {}).get("id"),
                                "createdAt": (dep or {}).get("createdAt")}})
        return 0
    if c == "env-set":
        if args.generate:
            body = {"generateValue": True}
        else:
            value = args.value if args.value is not None else project.env_value(args.key)
            body = {"value": value}
        render_call(project, "PUT", f"/services/{sid}/env-vars/{urllib.parse.quote(args.key)}", body)
        emit({"key": args.key, "set": True, "note": "Env changes apply on the next deploy — run `render deploy --wait`."})
        return 0
    if c == "env-del":
        render_call(project, "DELETE", f"/services/{sid}/env-vars/{urllib.parse.quote(args.key)}", ok=(200, 204, 404))
        emit({"key": args.key, "deleted": True})
        return 0
    if c == "env-keys":
        keys, cursor = [], None
        while True:
            q = "?limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
            page = render_call(project, "GET", f"/services/{sid}/env-vars{q}") or []
            for item in page:
                keys.append(item.get("envVar", item).get("key"))
            if len(page) < 100:
                break
            cursor = page[-1].get("cursor")
            if not cursor:
                break
        emit(sorted(keys))
        return 0
    if c == "deploy":
        body: dict[str, Any] = {"clearCache": "clear" if args.clear_cache else "do_not_clear"}
        if args.commit:
            body["commitId"] = args.commit
        triggered_at = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=30)  # clock-skew margin
        resp = render_call(project, "POST", f"/services/{sid}/deploys", body)
        deploy_id = (resp or {}).get("id")  # 202 Queued returns no body
        if not args.wait:
            emit({"triggered": True, "deploy_id": deploy_id, "queued": deploy_id is None})
            return 0
        time.sleep(3)
        result = _wait_deploy(project, sid, deploy_id, args.timeout, since=triggered_at)
        emit(result)
        return 0 if result.get("live") else 1
    if c == "wait":
        commit = None
        if not args.deploy and not args.any_latest:
            commit = args.commit or _git_head(project)
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=10)) if (not args.deploy and not commit) else None
        result = _wait_deploy(project, sid, args.deploy, args.timeout, since=since, commit=commit)
        emit(result)
        return 0 if result.get("live") else 1
    if c == "logs":
        emit(_fetch_logs(project, sid, limit=args.limit, text=args.text, log_type=args.type, minutes=args.minutes))
        return 0
    if c == "restart":
        render_call(project, "POST", f"/services/{sid}/restart")
        emit({"restarted": True})
        return 0
    if c == "rollback":
        deploy_id = args.deploy
        if not deploy_id:
            items = render_call(project, "GET", f"/services/{sid}/deploys?limit=20") or []
            deploys = sorted((i.get("deploy", i) for i in items), key=lambda d: d.get("createdAt") or "", reverse=True)
            candidates = [d for d in deploys[1:] if d.get("status") in ("live", "deactivated")]
            if not candidates:
                raise OpsError("No earlier successful deploy to roll back to.", exit_code=1)
            deploy_id = candidates[0]["id"]
        dep = render_call(project, "POST", f"/services/{sid}/rollback", {"deployId": deploy_id})
        emit({"rolled_back_to": deploy_id, "new_deploy": (dep or {}).get("id"),
              "note": "Auto-deploy stays on: the next git push deploys again. Fix the bug before pushing."})
        return 0
    if c == "disk":
        svc = render_call(project, "GET", f"/services/{sid}") or {}
        if (svc.get("serviceDetails") or {}).get("plan") == "free":
            raise OpsError("This service is on the Free plan, which can't have a disk (F-RENDER-FREE-LIMITS).",
                           hint="Upgrade the instance type to Starter first (student approves the cost), or use wa-persistence B (Supabase).",
                           exit_code=2)
        disk = render_call(project, "POST", "/disks", {"serviceId": sid, "name": args.name,
                                                       "mountPath": args.mount, "sizeGB": args.size_gb})
        emit({"disk_id": (disk or {}).get("id"), "mountPath": args.mount, "sizeGB": args.size_gb,
              "note": "A disk attaches on the next deploy — run `render deploy --wait`."})
        return 0
    if c == "postgres-create":
        owner = _render_owner_id(project)
        state = project.read_state()
        region = args.region or _get_path(state, "render.region") or "frankfurt"
        pg = render_call(project, "POST", "/postgres", {"name": args.name, "plan": args.plan, "ownerId": owner,
                                                        "version": args.version, "region": region}) or {}
        pg_id = pg.get("id")
        deadline = time.time() + 300
        while pg_id and time.time() < deadline and pg.get("status") != "available":
            time.sleep(10)
            pg = render_call(project, "GET", f"/postgres/{pg_id}") or {}
            hint(f"  postgres {pg_id}: {pg.get('status')}")
        _save_render_state(project, postgres_id=pg_id)
        out = {"postgres_id": pg_id, "status": pg.get("status"), "expiresAt": pg.get("expiresAt")}
        if args.save_as and pg.get("status") == "available":
            info = render_call(project, "GET", f"/postgres/{pg_id}/connection-info") or {}
            conn = info.get("internalConnectionString" if args.internal else "externalConnectionString")
            if conn:
                project.write_env(args.save_as, conn)
                out["saved_to_env"] = args.save_as
        emit(out)
        return 0
    raise OpsError("unknown render command", exit_code=2)


# --------------------------------------------------------------------------------------
# smoke — send the bot a fake Green API webhook (local or deployed)
# --------------------------------------------------------------------------------------

def cmd_smoke(args, project: Project) -> int:
    env = project.read_env()
    phone = re.sub(r"\D", "", args.sender)
    if phone.startswith("0") and len(phone) == 10:
        phone = "972" + phone[1:]
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "idMessage": "smoke-" + secrets.token_hex(6),
        "timestamp": int(time.time()),
        "instanceData": {"idInstance": int(env.get("GREEN_API_INSTANCE") or 0) if (env.get("GREEN_API_INSTANCE") or "").isdigit() else 0,
                         "wid": "", "typeInstance": "whatsapp"},
        "senderData": {"chatId": f"{phone}@c.us", "sender": f"{phone}@c.us", "senderName": "בדיקה", "chatName": "בדיקה"},
        "messageData": {"typeMessage": "textMessage", "textMessageData": {"textMessage": args.text}},
    }
    if args.type == "quoted":
        payload["messageData"] = {"typeMessage": "quotedMessage",
                                  "extendedTextMessageData": {"text": args.text, "stanzaId": "X", "participant": f"{phone}@c.us"},
                                  "quotedMessage": {"stanzaId": "X", "participant": f"{phone}@c.us",
                                                    "typeMessage": "textMessage", "textMessage": "הודעה קודמת"}}
    elif args.type == "extended":
        payload["messageData"] = {"typeMessage": "extendedTextMessage",
                                  "extendedTextMessageData": {"text": args.text, "description": "", "title": ""}}
    headers = {}
    if not args.no_auth:
        token = env.get("WEBHOOK_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if not args.async_mode:
        headers["X-Debug-Sync"] = "1"
    url = args.url.rstrip("/")
    if not url.endswith("/webhook/green-api"):
        url += "/webhook/green-api"
    status, body = http("POST", url, headers=headers, body=payload, timeout=120, retries=0)
    emit({"status": status, "response": body, "sent_from": f"{phone}@c.us", "auth_header": not args.no_auth and bool(env.get("WEBHOOK_TOKEN"))})
    return 0 if 200 <= status < 300 else 1


# --------------------------------------------------------------------------------------
# health — wake a sleeping service and check /health
# --------------------------------------------------------------------------------------

def cmd_health(args, project: Project) -> int:
    url = args.url
    if not url:
        state = project.read_state()
        base = _get_path(state, "render.url") or state.get("render_url")
        if not base:
            raise OpsError("No URL given and no render.url in state", exit_code=2)
        url = base.rstrip("/") + "/health"
    deadline = time.time() + args.timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            status, payload = http("GET", url, timeout=30, retries=0)
        except OpsError as e:
            status, payload = 0, str(e)
        if status == 200:
            emit({"ok": True, "status": status, "body": payload, "attempts": attempt})
            return 0
        if time.time() >= deadline:
            emit({"ok": False, "status": status, "body": payload, "attempts": attempt,
                  "hint": "A free Render service takes about a minute to wake (F-RENDER-COLD-START). If it never answers, check `render logs`."})
            return 1
        hint(f"  [{attempt}] {url} → {status or 'no answer'} (waking up?)")
        time.sleep(10)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wa_ops.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default=None, help="Bot project directory (default: current directory)")
    sub = p.add_subparsers(dest="group", required=True)

    sub.add_parser("doctor", help="Report OS, Python, git/gh, and project files (JSON)")

    st = sub.add_parser("state", help="Read/update .wa-state.json")
    sts = st.add_subparsers(dest="state_cmd", required=True)
    g = sts.add_parser("get"); g.add_argument("key", nargs="?", help="dot path, e.g. render.url")
    i = sts.add_parser("init"); i.add_argument("--force", action="store_true")
    sts.add_parser("migrate", help="Upgrade a v1 state file to v2 (lossless)")
    s = sts.add_parser("set", help="key=value pairs; values parsed as JSON when possible")
    s.add_argument("pairs", nargs="+")
    a = sts.add_parser("append", help="Append to a list (deduped)"); a.add_argument("key"); a.add_argument("value")
    d = sts.add_parser("stage-done", help="Mark a stage complete and set the next one")
    d.add_argument("stage"); d.add_argument("next_stage")
    lg = sts.add_parser("log", help="Add a maintenance_log entry"); lg.add_argument("text")
    dr = sts.add_parser("drift", help="Record drift (reality ≠ skill) — no secrets")
    dr.add_argument("--skill", required=True); dr.add_argument("--fact-id", default=None)
    dr.add_argument("--expected", required=True); dr.add_argument("--observed", required=True)
    dr.add_argument("--fix", default=None)

    en = sub.add_parser("env", help="Manage .env without echoing values")
    ens = en.add_subparsers(dest="env_cmd", required=True)
    es = ens.add_parser("set", help="Set KEY (value from arg, hidden prompt, stdin, or --generate)")
    es.add_argument("key"); es.add_argument("value", nargs="?")
    es.add_argument("--generate", action="store_true", help="Generate a random secret (e.g. WEBHOOK_TOKEN)")
    es.add_argument("--from-clipboard", action="store_true",
                    help="Read the value from the clipboard — the secret never appears in the conversation")
    ec = ens.add_parser("check", help="Which keys are present"); ec.add_argument("keys", nargs="+")
    ens.add_parser("keys", help="List key names only")

    ll = sub.add_parser("llm", help="Validate the LLM key and model")
    lls = ll.add_subparsers(dest="llm_cmd", required=True)
    for name in ("check", "models"):
        x = lls.add_parser(name)
        x.add_argument("--provider", choices=["anthropic", "openai", "google"])
        x.add_argument("--model"); x.add_argument("--family", help="filter, e.g. haiku / sonnet / mini / flash")
        x.add_argument("--ping", action="store_true", help="Send a 16-token test message (costs a fraction of a cent)")

    pl = sub.add_parser("plugin", help="Plugin version / update check")
    pls = pl.add_subparsers(dest="plugin_cmd", required=True)
    pls.add_parser("version"); pls.add_parser("check-update")

    rd = sub.add_parser("report-drift", help="Prepare (or, with --post, file) an upstream drift issue")
    rd.add_argument("--post", action="store_true", help="Actually post with gh — only after the student agreed")

    gr = sub.add_parser("green", help="Green API instance operations")
    grs = gr.add_subparsers(dest="green_cmd", required=True)
    grs.add_parser("state"); grs.add_parser("settings"); grs.add_parser("wid")
    wa = grs.add_parser("wait-authorized"); wa.add_argument("--timeout", type=int, default=180)
    cf = grs.add_parser("configure", help="Apply the standard webhook settings (+ optional URL and token)")
    cf.add_argument("--webhook-url", default=None, help="Full URL, e.g. https://x.onrender.com/webhook/green-api ('' to clear)")
    cf.add_argument("--webhook-token-from-env", default=None, metavar="KEY", help="Send 'Bearer <.env KEY>' as Authorization")
    cf.add_argument("--clear-webhook-token", action="store_true")
    cf.add_argument("--verify-tries", type=int, default=12, help="10s polls while the instance restarts (default 12 = 2 min)")
    sd = grs.add_parser("send"); sd.add_argument("to", help="phone (any format) or chatId"); sd.add_argument("text")
    wi = grs.add_parser("wait-incoming", help="Pre-deploy only: wait for a message in the HTTP queue")
    wi.add_argument("--timeout", type=int, default=120)
    ch = grs.add_parser("chats"); ch.add_argument("--groups", action="store_true")

    rn = sub.add_parser("render", help="Render REST API operations (needs RENDER_API_KEY in .env)")
    rns = rn.add_subparsers(dest="render_cmd", required=True)
    rns.add_parser("owners")
    cs = rns.add_parser("create-service")
    cs.add_argument("--name", required=True); cs.add_argument("--repo", required=True)
    cs.add_argument("--branch", default="main"); cs.add_argument("--owner")
    cs.add_argument("--plan", default="free", help="free | starter (alias of 0.5c-512mb) | …")
    cs.add_argument("--region", default="frankfurt", choices=["frankfurt", "oregon", "ohio", "virginia", "singapore"])
    cs.add_argument("--env-keys", help="Comma-separated .env keys to copy to Render (values never printed)")
    cs.add_argument("--env", action="append", help="Non-secret KEY=VALUE (repeatable)")
    cs.add_argument("--health-path", default="/health")
    cs.add_argument("--build-command", default="pip install -r requirements.txt")
    cs.add_argument("--start-command", default="uvicorn main:app --host 0.0.0.0 --port $PORT")
    cs.add_argument("--disk-gb", type=int, default=0); cs.add_argument("--disk-mount", default="/data")
    for name in ("status", "env-keys", "restart"):
        x = rns.add_parser(name); x.add_argument("--service")
    x = rns.add_parser("env-set", help="Set ONE env var (per-key API — never wipes the others)")
    x.add_argument("key"); x.add_argument("--value", default=None, help="Non-secret value; default: read KEY from .env")
    x.add_argument("--generate", action="store_true"); x.add_argument("--service")
    x = rns.add_parser("env-del"); x.add_argument("key"); x.add_argument("--service")
    x = rns.add_parser("deploy"); x.add_argument("--service"); x.add_argument("--commit")
    x.add_argument("--clear-cache", action="store_true"); x.add_argument("--wait", action="store_true")
    x.add_argument("--timeout", type=int, default=900)
    x = rns.add_parser("wait", help="Wait for the deploy of the pushed commit (default: local git HEAD)")
    x.add_argument("--service"); x.add_argument("--deploy", help="wait for this deploy id")
    x.add_argument("--commit", help="wait for the deploy of this commit (default: git HEAD)")
    x.add_argument("--any-latest", action="store_true", help="newest deploy from the last 10 minutes, any commit")
    x.add_argument("--timeout", type=int, default=900)
    x = rns.add_parser("logs"); x.add_argument("--service"); x.add_argument("--limit", type=int, default=100)
    x.add_argument("--text"); x.add_argument("--type", choices=["app", "build", "request"]); x.add_argument("--minutes", type=int, default=60)
    x = rns.add_parser("rollback"); x.add_argument("--service"); x.add_argument("--deploy", help="default: previous successful deploy")
    x = rns.add_parser("disk"); x.add_argument("--service"); x.add_argument("--size-gb", type=int, default=1)
    x.add_argument("--mount", default="/data"); x.add_argument("--name", default="data")
    x = rns.add_parser("postgres-create"); x.add_argument("--name", required=True); x.add_argument("--plan", default="free")
    x.add_argument("--version", default="17"); x.add_argument("--region")
    x.add_argument("--save-as", default=None, metavar="ENV_KEY", help="Write the connection string to .env under this key")
    x.add_argument("--internal", action="store_true", help="Save the internal (same-region) URL instead of the external one")

    sm = sub.add_parser("smoke", help="POST a fake incoming-message webhook to the bot")
    sm.add_argument("--url", default="http://localhost:8000", help="bot base URL (default local)")
    sm.add_argument("--from", dest="sender", required=True, help="sender phone (any format)")
    sm.add_argument("--text", default="היי")
    sm.add_argument("--type", choices=["text", "quoted", "extended"], default="text")
    sm.add_argument("--no-auth", action="store_true", help="omit the Authorization header (expect 401)")
    sm.add_argument("--async", dest="async_mode", action="store_true", help="don't ask for a synchronous debug reply")

    h = sub.add_parser("health", help="GET /health, waiting for a sleeping service to wake")
    h.add_argument("url", nargs="?"); h.add_argument("--timeout", type=int, default=150)
    return p


HANDLERS = {
    "doctor": cmd_doctor, "state": cmd_state, "env": cmd_env, "llm": cmd_llm, "plugin": cmd_plugin,
    "report-drift": cmd_report_drift, "green": cmd_green, "render": cmd_render, "health": cmd_health,
    "smoke": cmd_smoke,
}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    project = Project(Path(args.project).expanduser().resolve() if args.project else Path.cwd())
    project.read_env()  # registers secret values for redaction
    try:
        return HANDLERS[args.group](args, project)
    except OpsError as e:
        out: dict[str, Any] = {"ok": False, "error": str(e)}
        if e.hint:
            out["hint"] = e.hint
        if e.details is not None:
            out["details"] = e.details
        emit(out)
        return e.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
