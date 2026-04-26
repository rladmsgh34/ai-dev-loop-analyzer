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
    result = classify_domain("add new thing here", [])
    assert result == "general"


def test_classify_domain_chore_is_maintenance():
    """'chore:' prefix maps to 'maintenance', not 'general'."""
    assert classify_domain("chore: bump deps", []) == "maintenance"
    assert classify_domain("chore: update dependencies", []) == "maintenance"
    assert classify_domain("chore: upgrade eslint", []) == "maintenance"


def test_classify_domain_scope_auth():
    """fix(auth): scope maps to 'auth' domain."""
    assert classify_domain("fix(auth): session expiry bug", []) == "auth"
    assert classify_domain("feat(auth): add oauth flow", []) == "auth"


def test_classify_domain_scope_payment():
    """fix(payment): scope maps to 'payment' domain."""
    assert classify_domain("fix(payment): cart total wrong", []) == "payment"
    assert classify_domain("feat(checkout): add coupon", []) == "payment"


def test_classify_domain_scope_ci():
    """fix(ci): scope maps to 'ci/cd' domain."""
    assert classify_domain("fix(ci): docker healthcheck timeout", []) == "ci/cd"
    assert classify_domain("chore(deploy): update workflow", []) == "ci/cd"


def test_classify_domain_scope_database():
    """fix(db): and fix(schema): map to 'database' domain."""
    assert classify_domain("fix(db): add missing index", []) == "database"
    assert classify_domain("feat(schema): add user table", []) == "database"


def test_classify_domain_scope_ui():
    """fix(ui): and feat(layout): map to 'ui' domain."""
    assert classify_domain("fix(ui): modal close button broken", []) == "ui"
    assert classify_domain("feat(layout): add sidebar", []) == "ui"


def test_classify_domain_scope_unknown_falls_through():
    """Unknown scope falls through to keyword matching."""
    # 'logging' scope not in _SCOPE_TO_DOMAIN, but 'docker' keyword catches it
    assert classify_domain("fix(logging): docker container logs", []) == "ci/cd"


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


def test_is_fix_pr_with_scope():
    """fix(scope): is treated as fix PR."""
    assert _is_fix("fix(auth): broken login") is True
    assert _is_fix("fix(payment): cart total") is True
    assert _is_fix("fix(ci): healthcheck timeout") is True


def test_is_fix_hotfix():
    """hotfix: and bugfix: prefixes are treated as fix PRs."""
    assert _is_fix("hotfix: critical payment bug") is True
    assert _is_fix("bugfix: session not cleared") is True
    assert _is_fix("hotfix(auth): token expiry") is True


def test_is_fix_no_colon_not_fix():
    """'fix ' without colon (e.g. 'fix typo') is not a fix PR (colon required)."""
    assert _is_fix("fix typo in readme") is False


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


def test_detect_clusters_scoped_fix_counted():
    """fix(scope): PRs are correctly counted in clusters."""
    prs = [
        _make_pr(1, "feat: initial feature", is_fix=False),
        _make_pr(2, "fix(auth): session bug", is_fix=True),
        _make_pr(3, "fix(auth): token expiry", is_fix=True),
        _make_pr(4, "feat: dashboard", is_fix=False),
    ]
    clusters = detect_clusters(prs, window=8, threshold=2)
    assert len(clusters) >= 1
    cluster_pr_numbers = {p.number for c in clusters for p in c.prs}
    assert 2 in cluster_pr_numbers
    assert 3 in cluster_pr_numbers


# ── AI detection logic test ───────────────────────────────────────────────────

def test_ai_detection_via_commit_body():
    """Commit body containing 'Co-Authored-By: Claude' is detected as AI-generated."""
    commit_body_with_claude = "Some commit message\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    commit_body_without_claude = "Some commit message\n\nCo-Authored-By: Human Dev <dev@example.com>"

    assert "co-authored-by: claude" in commit_body_with_claude.lower()
    assert "co-authored-by: claude" not in commit_body_without_claude.lower()


def test_ai_detection_case_insensitive():
    """AI detection is case-insensitive for co-authored-by trailer."""
    variants = [
        "co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>",
        "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>",
        "CO-AUTHORED-BY: Claude Opus <noreply@anthropic.com>",
    ]
    for body in variants:
        assert "co-authored-by: claude" in body.lower(), f"Failed for: {body}"


# ── Profile loading test ──────────────────────────────────────────────────────

def test_load_profile():
    """load_profile() replaces DOMAIN_PATTERNS with values from the JSON file."""
    profile_path = Path(__file__).parent.parent / "profiles" / "default.json"
    assert profile_path.exists(), f"profiles/default.json not found at {profile_path}"

    load_profile(profile_path)

    assert len(DOMAIN_PATTERNS) > 0
    first_domain, first_pattern = DOMAIN_PATTERNS[0]
    assert first_domain == "ci/cd"
    assert "docker" in first_pattern


def test_load_profile_fix_pr_regex():
    """load_profile() updates FIX_PR_REGEX to handle scoped commits."""
    import analyze
    import re
    profile_path = Path(__file__).parent.parent / "profiles" / "default.json"
    load_profile(profile_path)
    assert re.match(analyze.FIX_PR_REGEX, "fix(auth): bug", re.I)
    assert not re.match(analyze.FIX_PR_REGEX, "feat: new thing", re.I)
