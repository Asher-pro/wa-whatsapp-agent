#!/usr/bin/env python3
"""check_freshness.py — is the plugin's knowledge still true?

Deterministic checks a machine can do without credentials:
  1. Every fact in knowledge/facts.md has value/verified/source/live-check lines.
  2. Facts whose `verified:` date is older than --max-age days (default 60).
  3. Source URLs that no longer answer (HTTP >= 400 or network failure).
  4. Python packages pinned in facts (`pkg` X.Y.Z) vs. the latest on PyPI.
  5. Render API endpoints the helper uses still exist in Render's public OpenAPI spec.

Semantic re-verification (did a screen move? did a price change?) is the job of the
Claude refresh workflow, which reads this report. Standard library only.

    python3 scripts/check_freshness.py                       # human summary
    python3 scripts/check_freshness.py --markdown out.md --json out.json --offline
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "knowledge" / "facts.md"
RENDER_OPENAPI = "https://api-docs.render.com/openapi/render-public-api-1.json"
RENDER_ENDPOINTS = [
    ("/owners", "get"), ("/services", "post"), ("/services/{serviceId}", "get"),
    ("/services/{serviceId}/env-vars", "get"), ("/services/{serviceId}/env-vars/{envVarKey}", "put"),
    ("/services/{serviceId}/env-vars/{envVarKey}", "delete"), ("/services/{serviceId}/deploys", "post"),
    ("/services/{serviceId}/deploys", "get"), ("/services/{serviceId}/deploys/{deployId}", "get"),
    ("/services/{serviceId}/rollback", "post"), ("/services/{serviceId}/restart", "post"),
    ("/disks", "post"), ("/postgres", "post"), ("/postgres/{postgresId}", "get"),
    ("/postgres/{postgresId}/connection-info", "get"), ("/logs", "get"),
]
PACKAGE_RE = re.compile(r"`([a-z0-9][a-z0-9_.\-]*)`\s+(\d+\.\d+\.\d+)")
UA = {"User-Agent": "wa-whatsapp-agent-freshness/1"}


def parse_facts(text: str) -> list[dict]:
    text = re.sub(r"(?ms)^```.*?^```", "", text)  # ignore the format example in code fences
    facts = []
    for block in re.split(r"(?m)^### ", text)[1:]:
        lines = block.splitlines()
        fid = lines[0].strip()
        if not fid.startswith("F-"):
            continue
        fact = {"id": fid}
        for line in lines[1:]:
            m = re.match(r"-\s+(value|verified|source|live-check|volatile):\s*(.*)", line.strip())
            if m:
                fact[m.group(1)] = m.group(2).strip()
        facts.append(fact)
    return facts


def _ssl_context() -> ssl.SSLContext:
    paths = ssl.get_default_verify_paths()
    if any(p and os.path.exists(p) for p in (paths.cafile, paths.openssl_cafile)):
        return ssl.create_default_context()
    for cafile in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(cafile):  # python.org macOS builds without bundled certs
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


SSL_CTX = _ssl_context()


def fetch(url: str, timeout: float = 20) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=int, default=60)
    ap.add_argument("--offline", action="store_true", help="skip network checks")
    ap.add_argument("--markdown")
    ap.add_argument("--json")
    ap.add_argument("--today", help="YYYY-MM-DD (tests)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    text = FACTS.read_text(encoding="utf-8")
    facts = parse_facts(text)
    report: dict = {"date": today.isoformat(), "facts": len(facts), "malformed": [], "stale": [],
                    "dead_sources": [], "package_drift": [], "render_api_missing": [], "errors": []}

    for f in facts:
        missing = [k for k in ("value", "verified", "source", "live-check") if not f.get(k)]
        if missing:
            report["malformed"].append({"id": f["id"], "missing": missing})
            continue
        try:
            age = (today - dt.date.fromisoformat(f["verified"])).days
        except ValueError:
            report["malformed"].append({"id": f["id"], "missing": ["verified (bad date)"]})
            continue
        limit = args.max_age // 2 if f.get("volatile") == "high" else args.max_age
        if age > limit:
            report["stale"].append({"id": f["id"], "verified": f["verified"], "age_days": age,
                                    "volatile": f.get("volatile", "?"), "source": f["source"]})

    if not args.offline:
        urls = sorted({u for f in facts for u in re.findall(r"https?://\S+", f.get("source", ""))})
        for url in urls:
            status, _ = fetch(url)
            # 401/403/429 usually mean "bot blocked" or "login wall", not a dead page
            if status == 0 or (status >= 400 and status not in (401, 403, 429)):
                report["dead_sources"].append({"url": url, "status": status})

        seen = {}
        for pkg, version in PACKAGE_RE.findall(text):
            seen.setdefault(pkg, version)
        for pkg, version in seen.items():
            status, body = fetch(f"https://pypi.org/pypi/{pkg}/json")
            if status != 200:
                continue
            latest = json.loads(body)["info"]["version"]
            if latest != version:
                report["package_drift"].append({"package": pkg, "facts_say": version, "pypi_latest": latest})

        status, body = fetch(RENDER_OPENAPI, timeout=40)
        if status == 200:
            paths = json.loads(body).get("paths", {})
            base = ""
            for path, verb in RENDER_ENDPOINTS:
                if verb not in paths.get(base + path, {}):
                    report["render_api_missing"].append(f"{verb.upper()} {path}")
        else:
            report["errors"].append(f"Render OpenAPI spec unreachable (HTTP {status})")

    problems = sum(len(report[k]) for k in ("malformed", "stale", "dead_sources", "package_drift", "render_api_missing"))
    report["problems"] = problems

    md = [f"# Freshness report — {today.isoformat()}", "",
          f"{len(facts)} facts checked · {problems} finding(s).", ""]
    sections = [
        ("Stale facts (re-verify against the source)", "stale",
         lambda x: f"- **{x['id']}** — verified {x['verified']} ({x['age_days']} days, volatile: {x['volatile']}) — {x['source']}"),
        ("Malformed facts", "malformed", lambda x: f"- **{x['id']}** missing: {', '.join(x['missing'])}"),
        ("Dead or moved sources", "dead_sources", lambda x: f"- {x['url']} → HTTP {x['status']}"),
        ("Package versions changed on PyPI", "package_drift",
         lambda x: f"- `{x['package']}`: facts say {x['facts_say']}, PyPI has {x['pypi_latest']}"),
        ("Render API endpoints no longer in the OpenAPI spec", "render_api_missing", lambda x: f"- {x}"),
        ("Check errors", "errors", lambda x: f"- {x}"),
    ]
    for title, key, fmt in sections:
        if report[key]:
            md += [f"## {title}", *[fmt(x) for x in report[key]], ""]
    if not problems:
        md.append("Everything checked is current. ✅")
    md += ["", "_Generated by `scripts/check_freshness.py`. The `auto-refresh` workflow uses this as its to-do list._"]
    md_text = "\n".join(md)

    if args.markdown:
        Path(args.markdown).write_text(md_text + "\n", encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(md_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
