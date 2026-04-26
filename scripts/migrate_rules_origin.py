#!/usr/bin/env python3
"""Best-effort origin tagging for legacy rules in data/rules-history.json.

Adds ``origin_repo`` and ``origin_confidence`` to every rule that doesn't
have them. Idempotent — re-running won't overwrite already-tagged rules.

Heuristic order (first match wins):
  1. explicit — rule text mentions a path/symbol uniquely tied to one repo
  2. inferred — rule text mentions a domain keyword that maps to one repo
                (lower confidence: same word could appear in future repos)
  3. unknown  — neither matches; keep but exclude from default efficacy

The ``self`` repo tag is reserved for rules induced from analyzing
ai-dev-loop-analyzer's own PRs. Self-rules are excluded from default
efficacy calculation because measuring them requires the analyzer to
analyze itself, which is recursively unstable.

Run: ``python3 scripts/migrate_rules_origin.py``
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "rules-history.json"

# explicit: file paths and symbols that appear in only one repo
SELF_EXPLICIT = [
    "src/analyze.py", "src/cli.py", "src/rag", "src/mcp_server",
    "src/repo_store", "src/feedback", "rag_hook.py", "patch_claude_md",
    "tests/test_analyze", "tests/test_rag", "tests/test_repo",
    "detect_clusters", "classify_domain", "analysis-cache",
    "build_cache_dict",
]
SHOP_EXPLICIT = [
    "src/app/", "src/components/", "src/lib/auth", "prisma/",
    "src/lib/portone", "src/lib/kakao", "src/lib/gcs",
    "광천", "광성",
]
VUE_EXPLICIT = [
    "compiler-sfc", "compiler-core", "compiler-dom", "runtime-vapor",
    "runtime-core", "runtime-dom", "defineProps", "defineEmits",
    "sfc-playground",
]
NEXTJS_EXPLICIT = [
    "turbopack", "use-cache", "next/font", "server-actions",
    "next/src/cli", "next/src/server", "pnpm-workspace",
]

# inferred: domain keywords that strongly suggest a repo but aren't unique
# (e.g. `compiler` appears in vue rule text but could conceivably appear elsewhere)
VUE_INFERRED = [
    "vapor", "compiler", "hydration", "reactivity", "vfor", "transition",
    "type-only ExportNamed",
]
NEXTJS_INFERRED = ["next.js", "nextjs"]


def _classify(rule_text: str) -> tuple[str, str]:
    """Return (origin_repo, origin_confidence)."""
    text = rule_text.lower()

    def has_any(needles: list[str]) -> bool:
        return any(n.lower() in text for n in needles)

    # Explicit pass — file paths / unique symbols
    explicit_hits = []
    if has_any(SELF_EXPLICIT):
        explicit_hits.append("self")
    if has_any(SHOP_EXPLICIT):
        explicit_hits.append("rladmsgh34/gwangcheon-shop")
    if has_any(VUE_EXPLICIT):
        explicit_hits.append("vuejs/core")
    if has_any(NEXTJS_EXPLICIT):
        explicit_hits.append("vercel/next.js")

    if len(explicit_hits) == 1:
        return explicit_hits[0], "explicit"
    if len(explicit_hits) > 1:
        # Multiple repos mentioned — likely a cross-repo abstract rule.
        # Keep as 'unknown' rather than picking one arbitrarily.
        return "unknown", "unknown"

    # Inferred pass — domain keywords
    inferred_hits = []
    if has_any(VUE_INFERRED):
        inferred_hits.append("vuejs/core")
    if has_any(NEXTJS_INFERRED):
        inferred_hits.append("vercel/next.js")

    if len(inferred_hits) == 1:
        return inferred_hits[0], "inferred"

    return "unknown", "unknown"


def _purge_dirty_snapshots(history: dict) -> tuple[int, int]:
    """Remove snapshots that lack a 'repo' field (created before per-repo
    tracking landed). Without a repo tag we can't tell which repo's analysis
    produced them, so they're unsafe for cross-repo-aware efficacy
    calculation. Idempotent — already-clean histories are no-ops.
    """
    global_purged = 0
    rule_purged = 0

    if "snapshots" in history:
        before = len(history["snapshots"])
        history["snapshots"] = [s for s in history["snapshots"] if s.get("repo")]
        global_purged = before - len(history["snapshots"])

    for rule in history.get("rules", []):
        snaps = rule.get("snapshots", [])
        before = len(snaps)
        rule["snapshots"] = [s for s in snaps if s.get("repo")]
        rule_purged += before - len(rule["snapshots"])

    return global_purged, rule_purged


def main() -> None:
    if not HISTORY.exists():
        print("rules-history.json 없음 — 스킵", file=sys.stderr)
        return

    history = json.loads(HISTORY.read_text())
    rules = history.get("rules", [])

    tagged = {"explicit": 0, "inferred": 0, "unknown": 0, "skipped": 0}
    by_repo = {}

    for rule in rules:
        # idempotent: 이미 태그된 rule은 건너뜀
        if "origin_repo" in rule and "origin_confidence" in rule:
            tagged["skipped"] += 1
            continue
        origin, conf = _classify(rule.get("rule", ""))
        rule["origin_repo"] = origin
        rule["origin_confidence"] = conf
        tagged[conf] += 1
        by_repo[origin] = by_repo.get(origin, 0) + 1

    g_purged, r_purged = _purge_dirty_snapshots(history)

    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2))

    print(f"Tagged {len(rules)} rules:")
    for k, v in tagged.items():
        print(f"  {k}: {v}")
    print(f"\nBy origin_repo:")
    for k, v in sorted(by_repo.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nPurged snapshots without repo tag:")
    print(f"  global: {g_purged}")
    print(f"  rule-attached: {r_purged}")


if __name__ == "__main__":
    main()
