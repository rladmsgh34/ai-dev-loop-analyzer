#!/usr/bin/env python3
"""
ai-dev-loop-analyzer — core analysis engine

PR 히스토리에서 회귀 클러스터·고위험 파일·도메인을 감지하고
CLAUDE.md 규칙 후보를 생성합니다.
"""

import json
import os
import re
import sys
import subprocess
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── gh CLI 토큰 자동 감지 ────────────────────────────────────────────────────
def _get_gh_token() -> str:
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


# ── 도메인 분류 규칙 (프로파일로 오버라이드 가능) ────────────────────────────
DOMAIN_PATTERNS: list[tuple[str, str]] = [
    # PR 제목 키워드 + 파일 경로 모두 매칭 — 기본값은 범용. load_profile()로 교체 가능.
    ("ci/cd",        r"deploy|docker|dockerfile|ci\b|workflow|buildx|healthcheck|compose|github.action|pipeline"),
    ("auth",         r"auth|login|signup|session|jwt|credential|credentials|signin|oauth|permission|role\b"),
    ("payment",      r"payment|checkout|order|cart|purchase|invoice|billing|subscription"),
    ("database",     r"migration|schema\.|migrate\b|prisma|seed\.ts|seed\.js"),
    ("security",     r"csp|xss|csrf|rate.limit|sanitize|escape|content.security|vulnerabilit|injection"),
    ("external-api", r"stripe|twilio|sendgrid|s3\b|cloudfront|firebase|slack|webhook|kakao|portone|toss|naver|daum|coolsms|sentry|gcs\b|gcp\b|aws\b|azure|openai|anthropic"),
    ("test/e2e",     r"\.test\.|\.spec\.|/tests?/|e2e|playwright|vitest|jest|coverage|flaky|mock|fixture"),
    ("maintenance",  r"refactor|cleanup|rename|deprecat|reorganize|remov\b|rewrite|chore\b|bump\b|upgrade|downgrade|update.dep|dependen|package\.json"),
    ("docs",         r"readme|changelog|docs?\b|document|comment|jsdoc"),
    ("config",       r"\.config\.|env\.ts|tsconfig|biome|tailwind|eslint|prettier|lint\b|next\.config|vite\.config|webpack|babel|postcss"),
    ("api",          r"api/|route\.ts|route\.js|endpoint|middleware"),
    ("ui",           r"components?/|pages?/|page\.tsx|page\.jsx|layout|modal|dialog|sidebar|navbar|header|footer|/styles?/|/theme/|/hooks?/|/context/|/store/"),
]

# fix PR 판별 정규식 — conventional commit scope 포함. load_profile()로 오버라이드 가능.
# 예: fix: ... / fix(auth): ... / hotfix: ... / bugfix(payment): ...
FIX_PR_REGEX: str = r"^(fix|hotfix|bugfix)(\([^)]*\))?:"

# conventional commit scope → 도메인 직접 매핑
# classify_domain()에서 keyword 매칭보다 먼저 시도
_SCOPE_TO_DOMAIN: dict[str, str] = {
    "auth": "auth", "login": "auth", "session": "auth", "oauth": "auth",
    "payment": "payment", "checkout": "payment", "order": "payment",
    "cart": "payment", "billing": "payment",
    "ci": "ci/cd", "cd": "ci/cd", "deploy": "ci/cd", "docker": "ci/cd",
    "workflow": "ci/cd", "pipeline": "ci/cd",
    "db": "database", "schema": "database", "migration": "database",
    "prisma": "database", "seed": "database",
    "security": "security", "csp": "security", "xss": "security",
    "api": "api", "route": "api", "endpoint": "api",
    "ui": "ui", "component": "ui", "layout": "ui", "page": "ui",
    "modal": "ui", "style": "ui", "theme": "ui",
    "test": "test/e2e", "e2e": "test/e2e", "spec": "test/e2e",
    "config": "config", "env": "config", "setup": "config",
    "docs": "docs", "doc": "docs", "readme": "docs",
    "external": "external-api", "webhook": "external-api",
}

# MCP rule_hints / LLM 프롬프트 힌트 — load_profile()로 채워짐
RULE_HINTS: dict[str, str] = {}
PROMPT_HINTS: dict[str, str] = {}


def load_profile(path: str | Path) -> None:
    """JSON 프로파일을 로드해 도메인 패턴·규칙·힌트를 교체한다.

    프로파일 경로는 --profile CLI 인수 또는 AI_DEV_LOOP_PROFILE 환경변수로 지정.
    """
    global FIX_PR_REGEX
    data = json.loads(Path(path).read_text())
    if "domain_patterns" in data:
        DOMAIN_PATTERNS[:] = [(d, r) for d, r in data["domain_patterns"]]
    if "rule_templates" in data:
        RULE_TEMPLATES.clear()
        RULE_TEMPLATES.update(data["rule_templates"])
    if "rule_hints" in data:
        RULE_HINTS.clear()
        RULE_HINTS.update(data["rule_hints"])
    if "fix_pr_regex" in data:
        FIX_PR_REGEX = data["fix_pr_regex"]
    if "prompt_hints" in data:
        PROMPT_HINTS.clear()
        PROMPT_HINTS.update(data["prompt_hints"])

def classify_domain(title: str, files: list[str]) -> str:
    # 1단계: conventional commit scope 추출 → 직접 매핑 (가장 정밀)
    scope_match = re.match(r"^\w+\(([^)]+)\):", title, re.I)
    if scope_match:
        scope = scope_match.group(1).lower()
        for key, domain in _SCOPE_TO_DOMAIN.items():
            if key in scope:
                return domain

    # 2단계: 제목 + 파일 경로 키워드 매칭
    combined = " ".join([title] + files).lower()
    for domain, pattern in DOMAIN_PATTERNS:
        if re.search(pattern, combined, re.I):
            return domain
    return "general"


# ── 데이터 구조 ──────────────────────────────────────────────────────────────
@dataclass
class PR:
    number: int
    title: str
    merged_at: str
    additions: int
    deletions: int
    is_fix: bool
    domain: str
    files: list[str] = field(default_factory=list)
    review_comments: list[str] = field(default_factory=list)
    is_ai_generated: bool = False  # Co-Authored-By: Claude 커밋 포함 여부
    diff_snippet: str = ""  # gh pr diff 앞 100줄 (smart-fetch / --fetch-files 모드)

@dataclass
class Cluster:
    prs: list[PR]
    domain: str

    @property
    def start(self): return self.prs[0].number
    @property
    def end(self): return self.prs[-1].number
    @property
    def size(self): return len(self.prs)


# ── GitHub 데이터 수집 ───────────────────────────────────────────────────────
def fetch_prs(limit: int = 300) -> list[PR]:
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "merged", f"--limit={limit}",
         "--json", "number,title,mergedAt,additions,deletions"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[error] gh pr list 실패: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(result.stdout)
    prs = []
    for item in raw:
        is_fix = bool(re.match(FIX_PR_REGEX, item["title"], re.I))
        domain = classify_domain(item["title"], [])
        prs.append(PR(
            number=item["number"],
            title=item["title"],
            merged_at=item["mergedAt"],
            additions=item["additions"],
            deletions=item["deletions"],
            is_fix=is_fix,
            domain=domain,
        ))
    return sorted(prs, key=lambda p: p.number)

def fetch_pr_details(pr_number: int) -> tuple[list[str], list[str], bool, str]:
    """메타(파일·리뷰·커밋) + diff snippet을 단일 worker에서 수집.
    gh pr view 1회 + gh pr diff 1회. 호출 자체는 ThreadPoolExecutor로 병렬화된다.
    """
    meta = subprocess.run(
        ["gh", "pr", "view", str(pr_number),
         "--json", "files,reviews,comments,commits"],
        capture_output=True, text=True
    )
    files: list[str] = []
    comments: list[str] = []
    is_ai = False
    if meta.returncode == 0:
        data = json.loads(meta.stdout)
        files = [f["path"] for f in data.get("files", [])]
        for r in data.get("reviews", []):
            body = (r.get("body") or "").strip()
            if body and len(body) > 10:
                comments.append(body[:300])
        for c in data.get("comments", []):
            body = (c.get("body") or "").strip()
            if body and len(body) > 10:
                comments.append(body[:300])
        is_ai = any(
            "co-authored-by: claude" in (commit.get("messageBody", "") or "").lower()
            or "co-authored-by: claude" in (commit.get("messageHeadline", "") or "").lower()
            for commit in data.get("commits", [])
        )

    # diff snippet: 앞 100줄만 사용해 프롬프트 토큰 절약
    diff_result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number)],
        capture_output=True, text=True
    )
    diff_snippet = ""
    if diff_result.returncode == 0 and diff_result.stdout:
        lines = diff_result.stdout.splitlines()
        diff_snippet = "\n".join(lines[:100])
        if len(lines) > 100:
            diff_snippet += f"\n... ({len(lines) - 100}줄 생략)"

    return files, comments, is_ai, diff_snippet


def _parallel_fetch(pr_numbers: list[int], label: str) -> dict[int, tuple]:
    """pr_numbers 목록을 ThreadPoolExecutor(workers=8)로 병렬 fetch."""
    pr_map: dict[int, tuple] = {}
    print(f"{label} {len(pr_numbers)}개 병렬 수집 중 (workers=8)...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_pr_details, num): num for num in pr_numbers}
        for future in as_completed(futures):
            pr_map[futures[future]] = future.result()
    return pr_map


def _fetch_ai_flag(pr_number: int) -> tuple[int, bool]:
    """커밋 메시지에서 'Co-Authored-By: Claude' 포함 여부만 확인 (파일/diff 없이 커밋만)."""
    result = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "commits"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return (pr_number, False)
    try:
        data = json.loads(result.stdout)
        is_ai = any(
            "co-authored-by: claude" in (commit.get("messageBody", "") or "").lower()
            or "co-authored-by: claude" in (commit.get("messageHeadline", "") or "").lower()
            for commit in data.get("commits", [])
        )
        return (pr_number, is_ai)
    except Exception:
        return (pr_number, False)


def fetch_ai_flags(pr_numbers: list[int]) -> dict[int, bool]:
    """PR 번호 목록을 받아 AI 생성 여부를 병렬로 확인한다."""
    print(f"AI 생성 PR 감지 중 ({len(pr_numbers)}개)...", file=sys.stderr)
    results: dict[int, bool] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_ai_flag, num): num for num in pr_numbers}
        for future in as_completed(futures):
            num, is_ai = future.result()
            results[num] = is_ai
    return results


# ── 분석 엔진 ────────────────────────────────────────────────────────────────
def detect_clusters(prs: list[PR], window: int = 8, threshold: int = 2) -> list[Cluster]:
    """
    PR 번호 순서로 window 안에 fix가 threshold개 이상이면 클러스터.
    겹치는 클러스터는 병합해 중복 제거.
    """
    n = len(prs)
    in_cluster: set[int] = set()  # 이미 클러스터에 포함된 PR index
    clusters = []

    i = 0
    while i < n:
        if not prs[i].is_fix or i in in_cluster:
            i += 1
            continue
        # i에서 시작하는 window 수집
        group_idx = [i]
        j = i + 1
        while j < n and prs[j].number - prs[i].number < window * 3:
            if prs[j].is_fix:
                group_idx.append(j)
            j += 1
            if len(group_idx) >= 8:  # 최대 클러스터 크기
                break

        if len(group_idx) >= threshold:
            group = [prs[k] for k in group_idx]
            domain = Counter(p.domain for p in group).most_common(1)[0][0]
            clusters.append(Cluster(prs=group, domain=domain))
            for k in group_idx:
                in_cluster.add(k)
            i = group_idx[-1] + 1
        else:
            i += 1
    return clusters

def rank_risky_files(prs: list[PR]) -> list[tuple[str, int]]:
    """fix PR에 자주 등장한 파일 순위"""
    counter = Counter()
    for pr in prs:
        if pr.is_fix:
            for f in pr.files:
                counter[f] += 1
    return counter.most_common(15)

def rank_risky_domains(prs: list[PR]) -> list[tuple[str, int]]:
    counter = Counter(p.domain for p in prs if p.is_fix)
    return counter.most_common()


def analyze_ai_vs_human(prs: list[PR]) -> dict:
    """AI 생성 PR vs 사람 PR의 fix 패턴 비교"""
    ai_prs = [p for p in prs if p.is_ai_generated]
    human_prs = [p for p in prs if not p.is_ai_generated]

    def fix_rate(lst: list[PR]) -> float:
        if not lst:
            return 0.0
        return round(sum(1 for p in lst if p.is_fix) / len(lst) * 100, 1)

    def domain_breakdown(lst: list[PR]) -> list[dict]:
        counter = Counter(p.domain for p in lst if p.is_fix)
        return [{"domain": d, "count": n} for d, n in counter.most_common()]

    return {
        "ai": {
            "total": len(ai_prs),
            "fix_count": sum(1 for p in ai_prs if p.is_fix),
            "fix_rate": fix_rate(ai_prs),
            "weak_domains": domain_breakdown(ai_prs),
        },
        "human": {
            "total": len(human_prs),
            "fix_count": sum(1 for p in human_prs if p.is_fix),
            "fix_rate": fix_rate(human_prs),
            "weak_domains": domain_breakdown(human_prs),
        },
    }


# ── Rule generation (template fallback, overridable via profile) ─────────────
RULE_TEMPLATES: dict[str, str] = {
    "ci/cd":        "CI/CD pipeline changes require running a build verification script — {count} regressions detected",
    "auth":         "Auth-related changes require full manual verification of login/session/permission flows — {count} regressions",
    "payment":      "Review payment flow changes carefully before implementing — {count} regressions",
    "database":     "Schema change PRs must include a down SQL — {count} regressions",
    "security":     "After security changes, verify no external domains are missing from the allowlist — {count} regressions",
    "external-api": "External API integration changes may behave differently locally vs. deployed — {count} regressions, verify on staging",
    "test/e2e":     "Run E2E tests against a production build server, not dev — {count} flaky incidents",
    "maintenance":  "After refactoring/cleanup, run all related tests to catch regressions — {count} regressions",
    "docs":         "After documentation changes, verify content matches actual code and config — {count} mismatches",
    "config":       "After config file changes, restart the dev server and verify the build — {count} regressions",
}

def generate_rules(domain_counts: list[tuple[str, int]]) -> list[str]:
    """Template-based rule generation (fallback when no AI key is available)."""
    rules = []
    for domain, count in domain_counts:
        if count < 2:
            continue
        template = RULE_TEMPLATES.get(domain)
        if template:
            rules.append(f"- {template.format(count=count)}")
        else:
            rules.append(
                f"- `{domain}` 도메인: fix PR {count}회 — 변경 전 관련 테스트 전체 실행 필수"
            )
    return rules


def _build_prompt(
    clusters: list[Cluster],
    domain_counts: list[tuple[str, int]],
    risky_files: list[tuple[str, int]],
    fix_prs: list[PR],
) -> str:
    # 클러스터 소속 PR 우선, 없으면 fix PR 상위 10개로 diff 포함
    cluster_pr_numbers = {p.number for c in clusters for p in c.prs}
    diff_candidates = [p for p in fix_prs if p.number in cluster_pr_numbers and p.diff_snippet]
    if not diff_candidates:
        diff_candidates = [p for p in fix_prs if p.diff_snippet][:10]

    fix_summary_lines = []
    for p in fix_prs:
        line = f"- #{p.number}: {p.title}"
        if p.files:
            line += f" (파일: {', '.join(p.files[:3])})"
        if p.review_comments:
            line += f"\n  리뷰: {' / '.join(p.review_comments[:2])}"
        fix_summary_lines.append(line)
    fix_summary = "\n".join(fix_summary_lines)

    diff_section = ""
    if diff_candidates:
        diff_blocks = [
            f"### PR #{p.number}: {p.title}\n```diff\n{p.diff_snippet}\n```"
            for p in diff_candidates[:5]
        ]
        diff_section = "\n\n## 주요 fix PR diff (실제 코드 변경)\n" + "\n\n".join(diff_blocks)

    cluster_summary = "\n".join(
        f"- [{c.domain}] PR #{c.start}~#{c.end} ({c.size}개 연속 fix)"
        for c in clusters
    ) or "없음"
    domain_summary = "\n".join(f"- {d}: {n}회" for d, n in domain_counts if n >= 2) or "없음"
    file_summary = "\n".join(f"- {f}: {n}회" for f, n in risky_files[:8]) or "없음"

    ai_assistant = PROMPT_HINTS.get("ai_assistant", "AI coding assistant")
    config_file  = PROMPT_HINTS.get("config_file", "CLAUDE.md")
    lang         = PROMPT_HINTS.get("language", "ko")
    lang_note    = "한국어로 작성" if lang == "ko" else "Write in English"

    return f"""당신은 소프트웨어 품질 분석 전문가입니다.
아래는 한 GitHub 레포지토리의 PR 히스토리 분석 결과입니다.

## fix PR 목록
{fix_summary}{diff_section}

## 회귀 클러스터 (연속 fix 발생 구간)
{cluster_summary}

## 도메인별 fix 횟수
{domain_summary}

## 고위험 파일 (fix PR에 자주 등장)
{file_summary}

위 데이터를 바탕으로 {ai_assistant}의 {config_file}에 추가할 규칙을 3~5개 작성해주세요.

요구사항:
1. 각 규칙은 "- " 로 시작하는 한 줄
2. 반복된 실수 패턴을 방지하는 구체적인 행동 지침
3. diff에 드러난 구체적인 패턴(함수명·파일명·설정값 등)을 규칙에 반영
4. 한국어로 작성
5. 과도하게 일반적인 규칙("테스트를 잘 하세요") 금지

규칙 목록만 출력하세요 (설명 없이):"""


def _parse_rules(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith("-")]


def generate_rules_with_ai(
    clusters: list[Cluster],
    domain_counts: list[tuple[str, int]],
    risky_files: list[tuple[str, int]],
    fix_prs: list[PR],
    *,
    anthropic_key: Optional[str] = None,
    github_token: Optional[str] = None,
    model: str = "",
    language: str = "",
) -> list[str]:
    """
    AI 기반 규칙 생성. 우선순위:
      1. RAG (ChromaDB) + Claude Code CLI  — 가장 정밀
      2. ANTHROPIC_API_KEY → Anthropic API
      3. GITHUB_TOKEN      → GitHub Models API (무료)
      4. 템플릿 폴백
    """
    # RAG 시도
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from rag.query import RagEngine
        from rag.ingest import CHROMA_DIR
        if CHROMA_DIR.exists():
            engine = RagEngine()
            total_prs = len(fix_prs) + sum(c.size for c in clusters)
            fix_rate = round(len(fix_prs) / total_prs * 100, 1) if total_prs else 0
            top_domain = domain_counts[0][0] if domain_counts else "general"
            rules = engine.generate_rules(
                domain=top_domain,
                fix_rate=fix_rate,
                language=language,
                extra_context=f"회귀 클러스터 {len(clusters)}개, 위험 파일 {len(risky_files)}개",
            )
            if rules:
                print(f"[RAG] {len(rules)}개 규칙 생성 완료", file=sys.stderr)
                return rules
    except Exception as e:
        print(f"[RAG] 폴백: {e}", file=sys.stderr)

    prompt = _build_prompt(clusters, domain_counts, risky_files, fix_prs)

    if anthropic_key:
        return _call_anthropic(prompt, anthropic_key, model or "claude-haiku-4-5-20251001")
    if github_token:
        return _call_github_models(prompt, github_token, model or "gpt-4o-mini")

    print("[AI 규칙 생성] API 키 없음 — 템플릿 폴백", file=sys.stderr)
    return []


def _call_anthropic(prompt: str, api_key: str, model: str) -> list[str]:
    payload = json.dumps({
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return _parse_rules(result["content"][0]["text"])
    except Exception as e:
        print(f"[Anthropic API 오류] {e}", file=sys.stderr)
        return []


def _call_github_models(prompt: str, token: str, model: str) -> list[str]:
    """GitHub Models API — GITHUB_TOKEN만으로 GPT-4o·Claude 등 호출 가능"""
    payload = json.dumps({
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return _parse_rules(result["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"[GitHub Models API 오류] {e}", file=sys.stderr)
        return []


# ── 리포트 출력 ──────────────────────────────────────────────────────────────
def print_report(
    prs: list[PR],
    clusters: list[Cluster],
    risky_files: list[tuple[str, int]],
    domain_counts: list[tuple[str, int]],
    rules: list[str],
    output_format: str = "text",
):
    total = len(prs)
    fix_count = sum(1 for p in prs if p.is_fix)
    fix_rate = fix_count / total * 100 if total else 0

    ai_stats = analyze_ai_vs_human(prs)

    if output_format == "json":
        fix_prs_with_diff = [
            {
                "number": p.number,
                "title": p.title,
                "domain": p.domain,
                "files": p.files,
                "diff_snippet": p.diff_snippet,
            }
            for p in prs
            if p.is_fix and p.diff_snippet
        ]
        print(json.dumps({
            "summary": {"total_prs": total, "fix_prs": fix_count, "fix_rate": round(fix_rate, 1)},
            "clusters": [{"start": c.start, "end": c.end, "size": c.size, "domain": c.domain} for c in clusters],
            "risky_files": [{"file": f, "fix_count": n} for f, n in risky_files],
            "domain_counts": [{"domain": d, "fix_count": n} for d, n in domain_counts],
            "claude_md_suggestions": rules,
            "ai_vs_human": ai_stats,
            "fix_prs_with_diff": fix_prs_with_diff,
        }, ensure_ascii=False, indent=2))
        return

    # ── text 포맷 ────────────────────────────────────────────────────────────
    bar = lambda n, total: "█" * round(n / total * 30) if total else ""

    print("\n" + "═" * 60)
    print("  🔍 AI Dev Loop Analyzer — PR 품질 리포트")
    print("═" * 60)
    print(f"\n  총 PR: {total}개  |  fix PR: {fix_count}개 ({fix_rate:.1f}%)\n")

    print("─" * 60)
    print("  📍 회귀 클러스터 (같은 영역에서 fix 연속 발생)")
    print("─" * 60)
    if clusters:
        for c in clusters:
            pr_nums = " → ".join(f"#{p.number}" for p in c.prs)
            print(f"  [{c.domain:12}]  {pr_nums}")
    else:
        print("  감지된 클러스터 없음 ✅")

    print("\n" + "─" * 60)
    print("  🏴 도메인별 fix 집계")
    print("─" * 60)
    for domain, count in domain_counts:
        print(f"  {domain:15} {count:3}회  {bar(count, fix_count)}")

    if risky_files:
        print("\n" + "─" * 60)
        print("  📁 고위험 파일 (fix PR에 자주 등장)")
        print("─" * 60)
        for f, count in risky_files:
            print(f"  {count:2}회  {f}")

    # AI vs 사람 분리 (fetch-files 모드에서만 의미 있음)
    if ai_stats["ai"]["total"] > 0 or ai_stats["human"]["total"] > 0:
        print("\n" + "─" * 60)
        print("  🤖 AI 생성 PR vs 사람 PR 비교")
        print("─" * 60)
        ai = ai_stats["ai"]
        hu = ai_stats["human"]
        print(f"  AI 생성   {ai['total']:3}개  fix {ai['fix_count']}개 ({ai['fix_rate']}%)")
        print(f"  사람 작성 {hu['total']:3}개  fix {hu['fix_count']}개 ({hu['fix_rate']}%)")
        if ai["weak_domains"]:
            print(f"\n  AI가 특히 약한 도메인:")
            for d in ai["weak_domains"][:3]:
                print(f"    {d['domain']:15} {d['count']}회")

    print("\n" + "─" * 60)
    print("  💡 CLAUDE.md 추가 규칙 제안")
    print("─" * 60)
    if rules:
        for rule in rules:
            print(f"  {rule}")
    else:
        print("  제안 없음 (패턴 충분하지 않음)")

    # 규칙 효과 측정
    try:
        from rule_tracker import effectiveness_summary
        eff = effectiveness_summary()
        if "아직" not in eff:
            print("\n" + "─" * 60)
            print(eff)
    except Exception:
        pass

    print("\n" + "═" * 60 + "\n")


# ── 진입점 ───────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Dev Loop Analyzer")
    parser.add_argument("--limit", type=int, default=300, help="분석할 PR 수 (기본 300)")
    parser.add_argument("--fetch-files", action="store_true",
                        help="모든 fix PR의 파일·리뷰·diff 수집 (정밀 분석, 느림)")
    parser.add_argument("--no-smart-fetch", action="store_true",
                        help="클러스터 PR 자동 fetch 비활성화 (기본: 활성)")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--input", help="미리 받은 PR JSON 파일 (gh 생략)")
    parser.add_argument(
        "--profile",
        default=os.environ.get("AI_DEV_LOOP_PROFILE"),
        help="도메인·규칙 프로파일 JSON 경로 (AI_DEV_LOOP_PROFILE 환경변수로도 지정 가능)",
    )
    parser.add_argument(
        "--anthropic-key",
        default=os.environ.get("ANTHROPIC_API_KEY"),
        help="Anthropic API 키 (ANTHROPIC_API_KEY 환경변수 사용 가능)",
    )
    parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN") or _get_gh_token(),
        help="GitHub token (GitHub Models API 사용, 기본값: gh CLI 토큰)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="모델 오버라이드 (기본: anthropic=claude-haiku / github=gpt-4o-mini)",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="AI 규칙 생성 비활성화, 템플릿만 사용",
    )
    parser.add_argument(
        "--no-fetch-ai",
        action="store_true",
        help="AI 생성 PR 감지 패스 비활성화 (기본: 활성)",
    )
    args = parser.parse_args()

    if args.profile:
        load_profile(args.profile)

    if args.input:
        with open(args.input) as f:
            raw = json.load(f)
        # 분석 결과 JSON(report format)이면 바로 출력
        if isinstance(raw, dict) and "summary" in raw:
            if args.format == "json":
                print(json.dumps(raw, ensure_ascii=False, indent=2))
            else:
                d = raw
                s = d["summary"]
                clusters_data = d.get("clusters", [])
                domain_counts = [(c["domain"], c["fix_count"]) for c in d.get("domain_counts", [])]
                risky_files = [(f["file"], f["fix_count"]) for f in d.get("risky_files", [])]
                rules = d.get("claude_md_suggestions", [])
                # 간이 출력
                print(f"\n총 PR: {s['total_prs']}개 | fix PR: {s['fix_prs']}개 ({s['fix_rate']}%)\n")
                if clusters_data:
                    print("회귀 클러스터:")
                    for c in clusters_data:
                        print(f"  [{c['domain']:12}] #{c['start']} → #{c['end']} ({c['size']}개)")
                print("\n도메인별 fix:")
                for domain, cnt in domain_counts:
                    print(f"  {domain:15} {cnt}회")
                if risky_files:
                    print("\n고위험 파일:")
                    for f, cnt in risky_files:
                        print(f"  {cnt:2}회  {f}")
                if rules:
                    print("\nCLAUDE.md 추가 규칙 제안:")
                    for r in rules:
                        print(f"  {r}")
            return
        # 원시 PR 목록 JSON
        prs = []
        for item in raw:
            is_fix = bool(re.match(FIX_PR_REGEX, item["title"], re.I))
            prs.append(PR(
                number=item["number"], title=item["title"],
                merged_at=item["mergedAt"], additions=item["additions"],
                deletions=item["deletions"], is_fix=is_fix,
                domain=classify_domain(item["title"], []),
            ))
        prs = sorted(prs, key=lambda p: p.number)
    else:
        print("PR 데이터 수집 중...", file=sys.stderr)
        prs = fetch_prs(args.limit)

    pr_map_by_num = {p.number: p for p in prs}

    if args.fetch_files:
        # 전체 fix PR 대상 정밀 수집
        fix_nums = [p.number for p in prs if p.is_fix]
        details = _parallel_fetch(fix_nums, "fix PR (전체)")
        for num, (files, comments, is_ai, diff) in details.items():
            pr = pr_map_by_num[num]
            pr.files, pr.review_comments, pr.is_ai_generated, pr.diff_snippet = files, comments, is_ai, diff
            pr.domain = classify_domain(pr.title, pr.files)
    elif not args.no_smart_fetch:
        # smart-fetch: 클러스터 감지 후 해당 PR만 fetch (기본 동작)
        pre_clusters = detect_clusters(prs)
        cluster_nums = list({p.number for c in pre_clusters for p in c.prs})
        if cluster_nums:
            details = _parallel_fetch(cluster_nums, "클러스터 PR (smart-fetch)")
            for num, (files, comments, is_ai, diff) in details.items():
                pr = pr_map_by_num[num]
                pr.files, pr.review_comments, pr.is_ai_generated, pr.diff_snippet = files, comments, is_ai, diff
                pr.domain = classify_domain(pr.title, pr.files)

    # AI 감지 패스: smart-fetch/fetch-files로 커버되지 않은 PR에 적용
    if not args.no_fetch_ai:
        already_checked = {p.number for p in prs if p.is_ai_generated}
        remaining = [p.number for p in prs if p.number not in already_checked]
        if remaining:
            ai_flags = fetch_ai_flags(remaining)
            for num, is_ai in ai_flags.items():
                pr_map_by_num[num].is_ai_generated = is_ai

    clusters = detect_clusters(prs)
    risky_files = rank_risky_files(prs)
    domain_counts = rank_risky_domains(prs)

    if not args.no_ai:
        fix_prs = [p for p in prs if p.is_fix]
        print("AI로 규칙 생성 중...", file=sys.stderr)
        rules = generate_rules_with_ai(
            clusters, domain_counts, risky_files, fix_prs,
            anthropic_key=args.anthropic_key,
            github_token=args.github_token,
            model=args.model,
        )
        if not rules:
            rules = generate_rules(domain_counts)
    else:
        rules = generate_rules(domain_counts)

    print_report(prs, clusters, risky_files, domain_counts, rules, args.format)


if __name__ == "__main__":
    main()
