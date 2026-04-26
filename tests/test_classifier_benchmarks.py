"""Step 4 — classifier accuracy benchmarks against step 1 labels.

Loads each repo's profile, classifies the labeled sample, and asserts
minimum accuracy + maximum general-rate thresholds. Drift in the
classifier shows up here as a hard failure rather than an analyst-only
metric.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

import src.analyze as analyze

ROOT = Path(__file__).resolve().parent.parent
SAMPLING = ROOT / "data" / "sampling"
PROFILES = ROOT / "profiles" / "examples"


def _classify_sample(profile_path: Path, csv_path: Path) -> tuple[int, int, Counter]:
    """Return (correct, total, predicted_distribution)."""
    # Reset module state between profile loads — load_profile mutates globals.
    analyze.DOMAIN_PATTERNS.clear()
    analyze.DOMAIN_PATTERNS.extend(
        [
            ("ci/cd", "deploy|docker|workflow"),
            ("test/e2e", "\\.test\\.|playwright"),
            ("docs", "readme|changelog"),
            ("config", "\\.config\\."),
        ]
    )
    analyze._SCOPE_TO_DOMAIN.clear()
    analyze.load_profile(profile_path)

    correct = 0
    total = 0
    predicted = Counter()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            true_domain = row["true_domain"]
            if not true_domain:
                continue
            files = [p.strip() for p in row["files_top3"].split(";") if p.strip()]
            pred = analyze.classify_domain(row["title"], files)
            predicted[pred] += 1
            if pred == true_domain:
                correct += 1
            total += 1
    return correct, total, predicted


@pytest.mark.parametrize(
    "profile_name,csv_name,min_accuracy,max_general_rate",
    [
        # vuejs-core: 100 labels, 12 domains. Aim for ≥70% accuracy.
        ("vuejs-core.json", "vuejs-core-2026-04-26.csv", 0.70, 0.10),
        # vercel-nextjs: 41 labels, 14 domains. Aim for ≥65%.
        ("vercel-nextjs.json", "vercel-nextjs-2026-04-26.csv", 0.65, 0.15),
    ],
)
def test_profile_classifier_accuracy(
    profile_name: str,
    csv_name: str,
    min_accuracy: float,
    max_general_rate: float,
) -> None:
    profile_path = PROFILES / profile_name
    csv_path = SAMPLING / csv_name
    correct, total, predicted = _classify_sample(profile_path, csv_path)
    accuracy = correct / total
    general_rate = predicted.get("general", 0) / total
    assert accuracy >= min_accuracy, (
        f"{profile_name}: accuracy {accuracy:.1%} < target {min_accuracy:.0%}\n"
        f"  predicted: {predicted.most_common()}"
    )
    assert general_rate <= max_general_rate, (
        f"{profile_name}: general rate {general_rate:.1%} > limit {max_general_rate:.0%}"
    )
