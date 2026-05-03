"""Schema validation for config/repos.json — the single source of truth
that drives the GitHub Actions matrix in evolve-rules.yml.

Catches drift like missing required fields, wrong types, or duplicate
repo entries before the workflow fails on a live cron.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "repos.json"

REQUIRED_FIELDS = {
    "repo": str,
    "profile": (str, type(None)),
    "schedule": str,
    "fetch_limit": int,
    "enabled": bool,
}
VALID_SCHEDULES = {"daily", "weekly"}


@pytest.fixture(scope="module")
def repos() -> list[dict]:
    return json.loads(CONFIG.read_text())


def test_top_level_is_list(repos):
    assert isinstance(repos, list)
    assert len(repos) > 0, "config/repos.json must declare at least one repo"


def test_each_repo_has_required_fields(repos):
    for entry in repos:
        for field, expected_type in REQUIRED_FIELDS.items():
            assert field in entry, f"{entry.get('repo', '?')}: missing '{field}'"
            assert isinstance(entry[field], expected_type), (
                f"{entry['repo']}: '{field}' must be {expected_type}, got {type(entry[field])}"
            )


def test_repo_format(repos):
    for entry in repos:
        assert "/" in entry["repo"], f"{entry['repo']}: must be 'owner/repo' format"


def test_schedule_value(repos):
    for entry in repos:
        assert entry["schedule"] in VALID_SCHEDULES, (
            f"{entry['repo']}: schedule must be one of {VALID_SCHEDULES}"
        )


def test_fetch_limit_sane(repos):
    for entry in repos:
        # Lower bound: at least 10 PRs to cluster-detect.
        # Upper bound: 1500 keeps a single run under the GH_PAT 5000/hr budget
        # given analyze.py's per-PR API calls (no incremental fetch yet).
        assert 10 <= entry["fetch_limit"] <= 1500, (
            f"{entry['repo']}: fetch_limit {entry['fetch_limit']} outside [10, 1500]"
        )


def test_no_duplicate_repos(repos):
    repo_names = [e["repo"] for e in repos]
    assert len(repo_names) == len(set(repo_names)), (
        f"duplicate repo entries: {repo_names}"
    )


def test_profile_paths_exist(repos):
    for entry in repos:
        if entry["profile"] is None:
            continue
        profile_path = ROOT / entry["profile"]
        assert profile_path.exists(), (
            f"{entry['repo']}: profile path '{entry['profile']}' does not exist"
        )
