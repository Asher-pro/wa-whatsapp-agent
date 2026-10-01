#!/usr/bin/env python3
"""validate_plugin.py — structural checks that keep the plugin internally consistent.

Runs in CI on every push/PR and before every release. Standard library only.

Checks
  * plugin.json / marketplace.json parse, names match, versions match
  * CHANGELOG.md has a section for the current version
  * every skills/<dir>/SKILL.md has frontmatter with name == <dir> and a description
  * every command has a description
  * every fact ID (F-…) cited anywhere exists in knowledge/facts.md, and every fact is well-formed
  * every upgrade ID (U…-…) cited anywhere exists in knowledge/upgrades.md
  * every `WA_OPS <group> <command>` mentioned in skills/commands/knowledge exists in wa_ops.py
  * relative markdown links inside the repo resolve
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        err(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"')
    return out


def main() -> int:
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    entry = next((p for p in market.get("plugins", []) if p.get("name") == plugin["name"]), None)
    if not entry:
        err("marketplace.json has no entry named like plugin.json")
    elif entry.get("version") != plugin.get("version"):
        err(f"version mismatch: plugin.json {plugin.get('version')} vs marketplace.json {entry.get('version')}")
    version = plugin.get("version", "")
    changelog = (ROOT / "CHANGELOG.md")
    if not changelog.exists() or f"## {version}" not in changelog.read_text(encoding="utf-8"):
        err(f"CHANGELOG.md has no '## {version}' section")

    skill_dirs = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    for d in skill_dirs:
        f = d / "SKILL.md"
        if not f.exists():
            err(f"{d.name}: missing SKILL.md")
            continue
        fm = frontmatter(f)
        if fm.get("name") != d.name:
            err(f"{d.name}/SKILL.md: name '{fm.get('name')}' != directory name")
        if len(fm.get("description", "")) < 40:
            err(f"{d.name}/SKILL.md: description missing or too short")
    for f in sorted((ROOT / "commands").glob("*.md")):
        if not frontmatter(f).get("description"):
            err(f"commands/{f.name}: missing description")

    docs = [p for p in ROOT.rglob("*.md") if ".git" not in p.parts]
    corpus = {p: p.read_text(encoding="utf-8") for p in docs}

    facts_text = corpus[ROOT / "knowledge/facts.md"]
    facts_body = re.sub(r"(?ms)^```.*?^```", "", facts_text)
    defined_facts = set(re.findall(r"(?m)^### (F-[A-Z0-9-]+)\s*$", facts_body))
    for block in re.split(r"(?m)^### ", facts_body)[1:]:
        fid = block.splitlines()[0].strip()
        if fid.startswith("F-"):
            for key in ("value", "verified", "source", "live-check", "volatile"):
                if not re.search(rf"(?m)^- {key}:\s*\S", block):
                    err(f"facts.md {fid}: missing '{key}'")
    upgrades_text = corpus[ROOT / "knowledge/upgrades.md"]
    defined_upgrades = set(re.findall(r"(?m)^## (U\d+-[A-Z0-9-]+)", upgrades_text))

    for path, text in corpus.items():
        rel = path.relative_to(ROOT)
        for fid in set(re.findall(r"\bF-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", text)):
            if fid not in defined_facts and fid != "F-ID":
                err(f"{rel}: cites unknown fact {fid}")
        for uid in set(re.findall(r"\bU\d{3,}-[A-Z][A-Z0-9-]+\b", text)):
            if uid not in defined_upgrades:
                err(f"{rel}: cites unknown upgrade {uid}")
        for link in re.findall(r"\]\((?!https?://|#|mailto:)([A-Za-z0-9_./-]+(?:\.md|/)(?:#[^)\s]*)?)\)", text):
            target = (path.parent / link.split("#")[0]).resolve()
            if not target.exists():
                err(f"{rel}: broken link {link}")

    # WA_OPS commands referenced in prose must exist in the helper's parser
    import wa_ops  # noqa: E402
    parser = wa_ops.build_parser()
    groups = {}
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        for name, sub in action.choices.items():
            cmds = set()
            for a in getattr(sub, "_subparsers", None)._group_actions if sub._subparsers else []:  # noqa: SLF001
                cmds |= set(a.choices)
            groups[name] = cmds
    for path, text in corpus.items():
        rel = path.relative_to(ROOT)
        for group, cmd in re.findall(r"WA_OPS\s+([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?", text):
            if group not in groups:
                err(f"{rel}: WA_OPS group '{group}' doesn't exist")
            elif groups[group] and cmd and cmd not in groups[group]:
                err(f"{rel}: 'WA_OPS {group} {cmd}' doesn't exist")

    if errors:
        print(f"✗ {len(errors)} problem(s):")
        for e in errors:
            print("  -", e)
        return 1
    print(f"✓ plugin {plugin['name']} {version}: {len(skill_dirs)} skills, "
          f"{len(defined_facts)} facts, {len(defined_upgrades)} upgrades — all consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
