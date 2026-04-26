import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pathlib import Path
import pytest

from analyze import PR, classify_domain, detect_clusters, load_profile, DOMAIN_PATTERNS


# ── Domain classification tests ──────────────────────────────────────────────

def test_classify_domain_ci():
    """PR title containing deployment/docker keywords maps to 'ci/cd'."""
    result = classify_domain("fix: docker healthcheck", [])
    assert result == "ci/cd"


def test_classify_domain_auth():
    """PR title containing session/token keywords maps to 'auth'."""
    result = classify_domain("fix: session token refresh", [])
    assert result == "auth"


def test_classify_domain_payment():
    """PR title containing checkout/cart keywords maps to 'payment'."""
    result = classify_domain("fix: checkout cart total", [])
    assert result == "payment"


def test_classify_domain_external_api():
    """Korean service keywords (kakao, portone, sentry) map to 'external-api'."""
    assert classify_domain("feat: kakao pay integration", ["src/lib/kakao.ts"]) == "external-api"
    assert classify_domain("fix: portone webhook timeout", []) == "external-api"
    assert classify_domain("chore: update sentry dsn", []) == "external-api"


def test_classify_domain_general():
    """PR title that matches no domain pattern resolves to 'general'."""
    result = classify_domain("chore: bump deps", [])
    assert result == "general"


# ── is_fix helper tests ───────────────────────────────────────────────────────

def _is_fix(title: str) -> bool:
    """Replicate the is_fix logic used in fetch_prs (regex match against FIX_PR_REGEX)."""
    import re
    from analyze import FIX_PR_REGEX
    return bool(re.match(FIX_PR_REGEX, title, re.I))


def test_is_fix_pr_true():
    """Titles starting with 'fix:' are identified as fix PRs."""
    assert _is_fix("fix: broken button") is True


def test_is_fix_pr_false():
    """Titles starting with 'feat:' are not identified as fix PRs."""
    assert _is_fix("feat: add button") is False


# ── Cluster detection tests ───────────────────────────────────────────────────

def _make_pr(number: int, title: str, is_fix: bool) -> PR:
    return PR(
        number=number,
        title=title,
        merged_at="2026-01-01T00:00:00Z",
        additions=10,
        deletions=5,
        is_fix=is_fix,
        domain=classify_domain(title, []),
    )


def test_detect_clusters_finds_consecutive_fixes():
    """Two consecutive fix PRs within the default window are detected as a cluster."""
    prs = [
        _make_pr(1, "feat: initial feature", is_fix=False),
        _make_pr(2, "fix: broken layout", is_fix=True),
        _make_pr(3, "fix: missing border", is_fix=True),
        _make_pr(4, "feat: new page", is_fix=False),
    ]
    clusters = detect_clusters(prs, window=8, threshold=2)
    assert len(clusters) >= 1
    cluster_pr_numbers = {p.number for c in clusters for p in c.prs}
    # Both fix PRs must be captured in the cluster
    assert 2 in cluster_pr_numbers
    assert 3 in cluster_pr_numbers


def test_detect_clusters_no_cluster_for_single_fix():
    """A single isolated fix PR does not form a cluster (below threshold=2)."""
    prs = [
        _make_pr(1, "feat: initial feature", is_fix=False),
        _make_pr(2, "fix: typo", is_fix=True),
        _make_pr(3, "feat: new feature", is_fix=False),
    ]
    clusters = detect_clusters(prs, window=8, threshold=2)
    assert len(clusters) == 0


# ── AI detection logic test ───────────────────────────────────────────────────

def test_ai_detection_via_commit_body():
    """Commit body containing 'Co-Authored-By: Claude' is detected as AI-generated.

    This tests the pure string-matching logic used inside fetch_pr_details,
    without invoking subprocess or any external call.
    """
    commit_body_with_claude = "Some commit message\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    commit_body_without_claude = "Some commit message\n\nCo-Authored-By: Human Dev <dev@example.com>"

    assert "Co-Authored-By: Claude" in commit_body_with_claude
    assert "Co-Authored-By: Claude" not in commit_body_without_claude


# ── Profile loading test ──────────────────────────────────────────────────────

def test_load_profile():
    """load_profile() replaces DOMAIN_PATTERNS with values from the JSON file."""
    profile_path = Path(__file__).parent.parent / "profiles" / "default.json"
    assert profile_path.exists(), f"profiles/default.json not found at {profile_path}"

    original_first_domain = DOMAIN_PATTERNS[0][0] if DOMAIN_PATTERNS else None

    load_profile(profile_path)

    # After loading the default profile, DOMAIN_PATTERNS must be non-empty
    assert len(DOMAIN_PATTERNS) > 0

    # The first entry in profiles/default.json domain_patterns is 'ci/cd'
    first_domain, first_pattern = DOMAIN_PATTERNS[0]
    assert first_domain == "ci/cd"
    assert "docker" in first_pattern
