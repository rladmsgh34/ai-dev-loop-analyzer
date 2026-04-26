"""rule_tracker — origin tagging + cross-repo pollution guard.

Critical safety nets for the loop-efficacy measurement:
- new rules carry the analyzed repo as explicit fact
- snapshots only attach to rules from the matching repo (no
  vue snapshots polluting gwangcheon rule history)
- self-referential analyzer rules are excluded from default efficacy
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import rule_tracker as rt


@pytest.fixture
def tmp_history(tmp_path, monkeypatch):
    """Redirect HISTORY_FILE to a tmp path so tests don't touch real data."""
    p = tmp_path / "rules-history.json"
    monkeypatch.setattr(rt, "HISTORY_FILE", p)
    return p


def test_new_rule_records_explicit_origin(tmp_history):
    rt.record_new_rules(
        rules=["fix something in payment"],
        domain_fix_rates={"payment": 5.0},
        total_fix_rate=10.0,
        date="2026-04-26",
        repo="rladmsgh34/gwangcheon-shop",
    )
    history = json.loads(tmp_history.read_text())
    assert len(history["rules"]) == 1
    r = history["rules"][0]
    assert r["origin_repo"] == "rladmsgh34/gwangcheon-shop"
    assert r["origin_confidence"] == "explicit"


def test_new_rule_without_repo_marked_unknown(tmp_history):
    """Backward-compat path: legacy callers omitting repo get unknown."""
    rt.record_new_rules(
        rules=["legacy rule"],
        domain_fix_rates={},
        total_fix_rate=0.0,
        date="2026-04-26",
    )
    r = json.loads(tmp_history.read_text())["rules"][0]
    assert r["origin_repo"] == "unknown"
    assert r["origin_confidence"] == "unknown"


def test_snapshot_only_attaches_to_matching_repo(tmp_history):
    """Vue snapshot must NOT pollute a gwangcheon-induced rule's timeline."""
    rt.record_new_rules(
        rules=["shop rule"], domain_fix_rates={"payment": 3.0},
        total_fix_rate=8.0, date="2026-04-20",
        repo="rladmsgh34/gwangcheon-shop",
    )
    rt.record_new_rules(
        rules=["vue rule"], domain_fix_rates={"reactivity": 4.0},
        total_fix_rate=12.0, date="2026-04-20",
        repo="vuejs/core",
    )
    # Snapshot from vue analysis run.
    rt.record_snapshot(
        domain_fix_rates={"reactivity": 5.0},
        total_fix_rate=15.0,
        date="2026-04-26",
        repo="vuejs/core",
    )
    history = json.loads(tmp_history.read_text())
    by_id = {r["origin_repo"]: r for r in history["rules"]}
    # vue rule received the vue snapshot
    assert len(by_id["vuejs/core"]["snapshots"]) == 1
    # gwangcheon rule did NOT
    assert len(by_id["rladmsgh34/gwangcheon-shop"]["snapshots"]) == 0


def test_snapshot_attaches_to_unknown_origin_rules(tmp_history):
    """Legacy unknown-origin rules accept all snapshots (best-effort)."""
    rt.record_new_rules(
        rules=["legacy"], domain_fix_rates={},
        total_fix_rate=0.0, date="2026-04-20",
    )
    rt.record_snapshot(
        domain_fix_rates={"x": 1.0}, total_fix_rate=2.0,
        date="2026-04-26", repo="vuejs/core",
    )
    rt.record_snapshot(
        domain_fix_rates={"y": 3.0}, total_fix_rate=4.0,
        date="2026-04-27", repo="rladmsgh34/gwangcheon-shop",
    )
    r = json.loads(tmp_history.read_text())["rules"][0]
    assert len(r["snapshots"]) == 2


def test_compute_effectiveness_filters_by_repo(tmp_history):
    rt.record_new_rules(
        rules=["vue rule"], domain_fix_rates={},
        total_fix_rate=10.0, date="2026-01-01",
        repo="vuejs/core",
    )
    rt.record_new_rules(
        rules=["shop rule"], domain_fix_rates={},
        total_fix_rate=10.0, date="2026-01-01",
        repo="rladmsgh34/gwangcheon-shop",
    )
    # Push enough snapshots so min_days=7 is satisfied.
    for i in range(8):
        rt.record_snapshot(
            domain_fix_rates={}, total_fix_rate=5.0,
            date=f"2026-01-{i + 2:02d}", repo="vuejs/core",
        )
    vue_only = rt.compute_effectiveness(repo="vuejs/core")
    assert len(vue_only) == 1
    shop_only = rt.compute_effectiveness(repo="rladmsgh34/gwangcheon-shop")
    assert len(shop_only) == 0  # no snapshots for shop yet


def test_compute_effectiveness_excludes_self_by_default(tmp_history):
    rt.record_new_rules(
        rules=["analyzer rule"], domain_fix_rates={},
        total_fix_rate=10.0, date="2026-01-01", repo="self",
    )
    for i in range(8):
        rt.record_snapshot(
            domain_fix_rates={}, total_fix_rate=5.0,
            date=f"2026-01-{i + 2:02d}", repo="self",
        )
    assert rt.compute_effectiveness() == []  # self excluded
    assert len(rt.compute_effectiveness(include_self=True)) == 1


def test_compute_effectiveness_strict_excludes_inferred(tmp_history):
    rt.record_new_rules(
        rules=["explicit rule"], domain_fix_rates={},
        total_fix_rate=10.0, date="2026-01-01",
        repo="vuejs/core", origin_confidence="explicit",
    )
    rt.record_new_rules(
        rules=["inferred rule"], domain_fix_rates={},
        total_fix_rate=10.0, date="2026-01-01",
        repo="vuejs/core", origin_confidence="inferred",
    )
    for i in range(8):
        rt.record_snapshot(
            domain_fix_rates={}, total_fix_rate=5.0,
            date=f"2026-01-{i + 2:02d}", repo="vuejs/core",
        )
    assert len(rt.compute_effectiveness()) == 2
    assert len(rt.compute_effectiveness(include_inferred=False)) == 1
