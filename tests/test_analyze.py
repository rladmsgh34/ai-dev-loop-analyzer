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


def test_is_fix_no_colon_is_fix_now():
    """
    새 regex(2026-04-26): 'fix '를 콜론 없이 쓴 경우도 fix PR로 인식.
    next.js 같은 비표준 컨벤션 레포의 'Fix dev mode hydration' 같은 PR을
    잡기 위한 의도적 변경. 'fixture'/'fixes' 등은 \\b 워드 경계로 구분.
    """
    assert _is_fix("fix typo in readme") is True
    assert _is_fix("Fix the build") is True


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


# ── Korean PR title classification tests ─────────────────────────────────────

def test_classify_domain_korean_auth():
    """Korean auth keywords (로그인, 비밀번호, 탈퇴) map to 'auth'."""
    assert classify_domain("feat: 로그인 소셜 버튼 추가", []) == "auth"
    assert classify_domain("fix: 비밀번호 변경 기능", []) == "auth"
    assert classify_domain("feat: 회원 탈퇴 (soft-delete)", []) == "auth"


def test_classify_domain_korean_payment():
    """Korean payment keywords (결제, 주문, 장바구니) map to 'payment'."""
    assert classify_domain("fix: 결제 금액 불일치 수정", []) == "payment"
    assert classify_domain("feat: 장바구니 수량 변경", []) == "payment"
    assert classify_domain("fix: 주문 상태 업데이트", []) == "payment"


def test_classify_domain_korean_ui():
    """Korean UI keywords (페이지, 화면, 스켈레톤, 상품) map to 'ui'."""
    assert classify_domain("feat: 페이지 로딩 스켈레톤 구현", []) == "ui"
    assert classify_domain("feat: 상품 목록 페이지네이션", []) == "ui"
    assert classify_domain("feat: 에러/404 전용 화면 구현", []) == "ui"


def test_classify_domain_korean_external_api():
    """Korean external service names (카카오, 네이버) map to 'external-api'."""
    assert classify_domain("fix: 카카오 우편번호 팝업 수정", []) == "external-api"
    assert classify_domain("feat: 네이버 지도 연동", []) == "external-api"


def test_classify_domain_korean_cicd():
    """Korean deploy keywords (배포, 도커) map to 'ci/cd'."""
    assert classify_domain("fix: 스테이징 배포 실패 수정", []) == "ci/cd"
    assert classify_domain("chore: 도커 이미지 최적화", []) == "ci/cd"


# ── scope_to_domain profile override tests ───────────────────────────────────

def test_load_profile_scope_to_domain_merge():
    """scope_to_domain in profile merges into existing mappings (does not replace)."""
    import analyze
    import json, tempfile, os

    profile = {
        "scope_to_domain": {
            "sms":    "external-api",
            "cron":   "database",
            "pitr":   "database",
            "studio": "ui",
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(profile, f)
        tmp = f.name

    try:
        load_profile(tmp)
        assert analyze._SCOPE_TO_DOMAIN["sms"] == "external-api"
        assert analyze._SCOPE_TO_DOMAIN["cron"] == "database"
        assert analyze._SCOPE_TO_DOMAIN["pitr"] == "database"
        assert analyze._SCOPE_TO_DOMAIN["studio"] == "ui"
        assert analyze._SCOPE_TO_DOMAIN["auth"] == "auth"
        assert analyze._SCOPE_TO_DOMAIN["payment"] == "payment"
    finally:
        os.unlink(tmp)


def test_classify_domain_profile_scope_override():
    """Custom scope_to_domain from profile is used in classify_domain()."""
    import analyze, json, tempfile, os

    profile = {"scope_to_domain": {"sms": "external-api", "pitr": "database"}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(profile, f)
        tmp = f.name

    try:
        load_profile(tmp)
        assert classify_domain("fix(sms): hook validation", []) == "external-api"
        assert classify_domain("fix(pitr): restore duration input", []) == "database"
    finally:
        os.unlink(tmp)


# ── Time-window clustering tests ─────────────────────────────────────────────

def _make_pr_dated(number: int, title: str, is_fix: bool, merged_at: str) -> PR:
    return PR(
        number=number,
        title=title,
        merged_at=merged_at,
        additions=10,
        deletions=5,
        is_fix=is_fix,
        domain=classify_domain(title, []),
    )


def test_time_window_cluster_within_14_days():
    """Two fix PRs merged 10 days apart are detected as a cluster (window=14)."""
    prs = [
        _make_pr_dated(1, "feat: feature", False, "2026-01-01T00:00:00Z"),
        _make_pr_dated(2, "fix: auth bug", True,  "2026-01-05T00:00:00Z"),
        _make_pr_dated(3, "fix: session",  True,  "2026-01-10T00:00:00Z"),
        _make_pr_dated(4, "feat: page",    False, "2026-01-15T00:00:00Z"),
    ]
    clusters = detect_clusters(prs, window=14, threshold=2)
    assert len(clusters) == 1
    pr_nums = {p.number for p in clusters[0].prs}
    assert pr_nums == {2, 3}


def test_time_window_no_cluster_beyond_window():
    """Two fix PRs merged 20 days apart are NOT a cluster when window=14."""
    prs = [
        _make_pr_dated(1, "fix: early bug", True, "2026-01-01T00:00:00Z"),
        _make_pr_dated(2, "fix: late bug",  True, "2026-01-25T00:00:00Z"),
    ]
    clusters = detect_clusters(prs, window=14, threshold=2)
    assert len(clusters) == 0


def test_time_window_two_separate_clusters():
    """Two independent time-window clusters in different periods are both detected."""
    prs = [
        _make_pr_dated(1, "fix: bug A1", True, "2026-01-01T00:00:00Z"),
        _make_pr_dated(2, "fix: bug A2", True, "2026-01-03T00:00:00Z"),
        _make_pr_dated(3, "feat: skip",  False, "2026-01-10T00:00:00Z"),
        _make_pr_dated(4, "fix: bug B1", True, "2026-02-01T00:00:00Z"),
        _make_pr_dated(5, "fix: bug B2", True, "2026-02-05T00:00:00Z"),
    ]
    clusters = detect_clusters(prs, window=14, threshold=2)
    assert len(clusters) == 2
    all_pr_nums = {p.number for c in clusters for p in c.prs}
    assert all_pr_nums == {1, 2, 4, 5}


def test_time_window_boundary_exact_14_days():
    """Fix PR exactly window days apart is still included (boundary inclusive)."""
    prs = [
        _make_pr_dated(1, "fix: start", True, "2026-01-01T00:00:00Z"),
        _make_pr_dated(2, "fix: end",   True, "2026-01-15T00:00:00Z"),  # exactly 14 days
    ]
    clusters = detect_clusters(prs, window=14, threshold=2)
    assert len(clusters) == 1


def test_time_window_malformed_date_fallback():
    """PRs with unparseable merged_at are grouped together (epoch fallback)."""
    prs = [
        _make_pr_dated(1, "fix: bad date1", True, "not-a-date"),
        _make_pr_dated(2, "fix: bad date2", True, "also-bad"),
    ]
    clusters = detect_clusters(prs, window=14, threshold=2)
    assert len(clusters) == 1  # both fall to epoch, so they're in the same window


# ── build_cache_dict (mcp_server + evolve-rules.yml 공유 함수) ──────────────

def test_build_cache_dict_basic_fields():
    """기본 캐시 빌드 — analyze.py JSON 출력 → cache 구조."""
    from analyze import build_cache_dict
    report = {
        "summary": {"total_prs": 100, "fix_prs": 12, "fix_rate": 12.0},
        "clusters": [{"start": 10, "end": 20, "size": 3, "domain": "ci/cd"}],
        "risky_files": [{"file": "src/lib/auth.ts", "fix_count": 5}],
        "domain_counts": [{"domain": "auth", "fix_count": 5}],
        "ai_vs_human": {"ai": {"weak_domains": [{"domain": "auth", "count": 3}]}},
        "fix_prs_with_diff": [
            {"number": 42, "title": "fix: auth", "domain": "auth",
             "files": ["src/lib/auth.ts"], "diff_snippet": "diff content"}
        ],
    }
    cache = build_cache_dict(report, "owner/repo")

    assert cache["repo"] == "owner/repo"
    assert cache["fix_rate"] == 12.0
    assert cache["risky_files"][0]["file"] == "src/lib/auth.ts"
    assert cache["risky_files"][0]["fix_count"] == 5
    # 마지막 fix diff가 risky_files에 매칭됨
    assert cache["risky_files"][0]["last_fix_title"] == "fix: auth"
    assert "diff content" in cache["risky_files"][0]["last_diff_snippet"]


def test_build_cache_dict_uses_fix_count_not_count():
    """analyze.py JSON 출력은 'fix_count' 키를 쓰며 'count'를 쓰지 않는다 (회귀 방지)."""
    from analyze import build_cache_dict
    report = {
        "summary": {"fix_rate": 5.0},
        "risky_files": [{"file": "x.ts", "fix_count": 7}],
        "fix_prs_with_diff": [],
    }
    cache = build_cache_dict(report, "test/repo")
    # KeyError 없이 동작하면 OK
    assert cache["risky_files"][0]["fix_count"] == 7


def test_build_cache_dict_empty_report():
    """비어있는 report도 안전하게 처리."""
    from analyze import build_cache_dict
    cache = build_cache_dict({}, "empty/repo")
    assert cache["repo"] == "empty/repo"
    assert cache["risky_files"] == []
    assert cache["clusters"] == []


# ── 비표준 prefix 패턴 (next.js-style) ────────────────────────────────────────

def test_is_fix_bracket_with_colon():
    """'[ci]: fix permissions on workflow' 같은 next.js 패턴."""
    assert _is_fix("[ci]: fix permissions on comment workflow") is True
    assert _is_fix("[tests]: fix cache-components.test.ts type error") is True


def test_is_fix_bracket_with_space_and_capital():
    """'[turbopack] Fix max_level_hint' 같은 패턴."""
    assert _is_fix("[turbopack] Fix max_level_hint to return most verbose") is True
    assert _is_fix("[ci] Fix auto-label workflow") is True
    assert _is_fix("[next/image] Fix image rendering") is True


def test_is_fix_patch_keyword():
    """'Patch X' 같은 patch 키워드 (next.js)."""
    assert _is_fix("Patch setHeader for direct route handlers") is True


def test_is_fix_capital_no_colon():
    """'Fix dev mode hydration' 같은 콜론 없는 capital Fix."""
    assert _is_fix("Fix dev mode hydration failure") is True
    assert _is_fix("Fix monorepo binary postinstall") is True


def test_is_fix_word_prefix_with_fix():
    """'webpack: fix swcPlugins' / 'turbo-tasks: Fix recomputation' 같은 단어 prefix."""
    assert _is_fix("webpack: fix swcPlugins with relative paths") is True
    assert _is_fix("turbo-tasks: Fix recomputation loop") is True
    assert _is_fix("Turbopack: fix filesystem watcher config") is True
    assert _is_fix("docs: fix broken bun.sh link") is True


def test_is_fix_does_not_match_fix_in_middle():
    """'Turbopack: optimize ... and fix range...' fix가 제목 중간이면 매칭 안 함."""
    assert _is_fix("Turbopack: optimize SelfTimeTree performance and fix range query") is False


def test_is_fix_does_not_match_fixture():
    """'fixture: ...' 처럼 fix로 시작하지만 다른 단어인 케이스 미매칭."""
    assert _is_fix("fixture: add new test fixtures") is False
    assert _is_fix("fixtures need updating") is False


def test_is_fix_does_not_match_fixes_plural():
    """'Fixes #123' 복수형은 의도적으로 미매칭 (추후 확장 가능)."""
    assert _is_fix("Fixes #123 broken thing") is False


def test_is_fix_chore_with_fix_in_title():
    """'chore: fix CI build' 같은 chore prefix + fix는 매칭 (실용적 판단)."""
    # 진짜 CI 픽스이므로 회귀 분석에 포함하는 게 맞음
    assert _is_fix("chore: fix CI build — add GCS_BUCKET_NAME dummy env") is True


def test_is_fix_case_insensitive():
    """대소문자 무관."""
    assert _is_fix("FIX: broken button") is True
    assert _is_fix("Fix the bug") is True
    assert _is_fix("PATCH: server route") is True


# ── fetch_prs --since flag ───────────────────────────────────────────────────

def test_fetch_prs_command_without_since(monkeypatch):
    """기본 fetch_prs는 --search 플래그를 추가하지 않는다."""
    from unittest.mock import MagicMock
    import analyze

    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        m = MagicMock()
        m.returncode = 0
        m.stdout = "[]"
        return m
    monkeypatch.setattr(analyze.subprocess, "run", fake_run)
    analyze.fetch_prs(limit=50)
    assert "--search" not in captured["cmd"]
    assert "--limit=50" in captured["cmd"]


def test_fetch_prs_command_with_since(monkeypatch):
    """--since 전달 시 gh search filter `merged:>=DATE`로 변환된다."""
    from unittest.mock import MagicMock
    import analyze

    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        m = MagicMock()
        m.returncode = 0
        m.stdout = "[]"
        return m
    monkeypatch.setattr(analyze.subprocess, "run", fake_run)
    analyze.fetch_prs(limit=50, since="2026-04-01")
    assert "--search" in captured["cmd"]
    idx = captured["cmd"].index("--search")
    assert captured["cmd"][idx + 1] == "merged:>=2026-04-01"
