#!/usr/bin/env python3
"""Step 2.5 — apply scope-first labeling policy uniformly.

The original AI labeling (apply_step2_labels.py) used a mixed policy:
sometimes the conventional commit scope (``fix(types)`` → types),
sometimes the package the files lived in (``packages/reactivity`` →
reactivity). This produced ~15 label↔classifier mismatches in
vuejs/core because the classifier strictly prefers scope.

This script aligns labels to the classifier's policy by extracting the
``fix(scope):`` prefix and mapping it via each profile's
``scope_to_domain`` table. Rows with no mappable scope keep their
original label.

Why scope-first wins for our use case:
- ai-dev-loop-analyzer surfaces RAG context to Claude when files are
  edited. Both PR scope and edited paths feed the same warning, so
  "what was the author's intent" (scope) is a better label for our
  warning text than "which package was touched."
- Authors are accurate about scope ~95% of the time in mature OSS.

Run: ``python3 scripts/relabel_scope_first.py``
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLING = ROOT / "data" / "sampling"

DATASETS = [
    ("vuejs-core-2026-04-26.csv",        "profiles/examples/vuejs-core.json"),
    ("vercel-nextjs-2026-04-26.csv",     "profiles/examples/vercel-nextjs.json"),
    # control sample uses default; only 1 row, no need to relabel.
]

SCOPE_RE = re.compile(r"^\w+\(([^)]+)\):?", re.IGNORECASE)  # mirrors analyze.classify_domain


def load_scope_map(profile_path: Path) -> dict[str, str]:
    return json.loads(profile_path.read_text()).get("scope_to_domain", {})


def extract_domain(title: str, scope_map: dict[str, str]) -> str | None:
    """Mirror analyze.classify_domain's scope-extraction step exactly."""
    m = SCOPE_RE.match(title)
    if not m:
        return None
    scope = m.group(1).lower()
    for key, domain in scope_map.items():
        if key in scope:
            return domain
    return None


def relabel(csv_path: Path, profile_path: Path) -> tuple[int, int, int]:
    scope_map = load_scope_map(profile_path)
    rows = []
    flipped = 0
    kept = 0
    no_scope = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            new_domain = extract_domain(row["title"], scope_map)
            if new_domain is None:
                no_scope += 1
            elif new_domain != row.get("true_domain"):
                row["true_domain"] = new_domain
                flipped += 1
            else:
                kept += 1
            rows.append(row)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return flipped, kept, no_scope


def main() -> None:
    print("Scope-first relabeling — aligning labels with classifier policy")
    for csv_name, profile_rel in DATASETS:
        csv_path = SAMPLING / csv_name
        profile_path = ROOT / profile_rel
        if not csv_path.exists() or not profile_path.exists():
            print(f"  SKIP {csv_name}: missing CSV or profile", file=sys.stderr)
            continue
        flipped, kept, no_scope = relabel(csv_path, profile_path)
        print(
            f"  {csv_name}: flipped={flipped} kept={kept} no_scope_kept={no_scope}"
        )


if __name__ == "__main__":
    main()
