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
from dataclasses import dataclass, field
from typing import Optional

# ── gh CLI 토큰 자동 감지 ────────────────────────────────────────────────────
def _get_gh_token() -> str:
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


# ── 도메인 분류 규칙 (파일 경로 기반) ───────────────────────────────────────
DOMAIN_PATTERNS = [
    # PR 제목 키워드 + 파일 경로 모두 매칭
    ("ci/cd",       r"deploy|docker|dockerfile|ci\b|workflow|buildx|healthcheck|compose|image.tag|prisma.cli|binary.target|musl|alpine"),
    ("auth",        r"auth|login|signup|session|jwt|credential|credentials|signin|configuration.error"),
    ("payment",     r"payment|portone|checkout|order|cart|purchase|결제|주문|장바구니"),
    ("database",    r"prisma/|migration|schema\.prisma|prisma\b"),
    ("security",    r"csp|xss|csrf|rate.limit|sanitize|escape|frame.src|allowlist|content.security"),
    ("external-api",r"kakao|postcode|우편번호|google.maps|portone|gcs|sentry|daum"),
    ("test/e2e",    r"\.test\.|\.spec\.|e2e|playwright|vitest|coverage|flaky|standalone.server"),
    ("config",      r"next\.config|env\.ts|tsconfig|biome|tailwind|npmrc|pnpm"),
    ("api",         r"src/app/api/|route\.ts|api.route"),
    ("ui",          r"src/components/|page\.tsx|컴포넌트"),
]

def classify_domain(title: str, files: list[str]) -> str:
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
        is_fix = bool(re.match(r'^fix', item["title"], re.I))
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

def fetch_pr_files(pr_number: int) -> list[str]:
    result = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "files"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    return [f["path"] for f in data.get("files", [])]


def fetch_pr_is_ai_generated(pr_number: int) -> bool:
    """PR의 커밋에 'Co-Authored-By: Claude' 태그가 있으면 AI 생성 PR로 판정"""
    result = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "commits"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    data = json.loads(result.stdout)
    for commit in data.get("commits", []):
        body = commit.get("messageBody", "") or ""
        headline = commit.get("messageHeadline", "") or ""
        if "Co-Authored-By: Claude" in body or "Co-Authored-By: Claude" in headline:
            return True
    return False


def fetch_pr_review_comments(pr_number: int) -> list[str]:
    """리뷰어 코멘트 수집 — 사람이 잡아낸 패턴을 LLM 프롬프트에 반영"""
    result = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "reviews,comments"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    comments = []
    for r in data.get("reviews", []):
        body = (r.get("body") or "").strip()
        if body and len(body) > 10:
            comments.append(body[:300])
    for c in data.get("comments", []):
        body = (c.get("body") or "").strip()
        if body and len(body) > 10:
            comments.append(body[:300])
    return comments


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


# ── CLAUDE.md 규칙 생성 ──────────────────────────────────────────────────────
RULE_TEMPLATES = {
    "ci/cd": (
        "CI/CD·Docker·배포 파이프라인 변경 전 `scripts/verify-build.sh` 실행 필수 — "
        "{count}회 회귀 감지 (가장 위험한 도메인)"
    ),
    "auth": (
        "인증 관련 파일 수정 시 로그인/세션/권한 플로우 전체 수동 검증 필수 — "
        "{count}회 회귀 이력"
    ),
    "payment": (
        "결제 플로우 변경 시 Opus 모델로 설계 검토 후 구현 — "
        "{count}회 회귀, 금액 불일치 시 강제 취소 로직 반드시 확인"
    ),
    "database": (
        "Prisma 스키마 변경 PR에는 down SQL 필수 첨부 — {count}회 회귀 이력"
    ),
    "security": (
        "CSP·XSS·rate-limit 수정 후 새 외부 도메인이 allowlist에 누락되지 않았는지 확인 — "
        "{count}회 회귀"
    ),
    "external-api": (
        "외부 API(Kakao·PortOne·GCS) 연동 변경 시 localhost와 스테이징 동작이 다를 수 있음 — "
        "{count}회 회귀, 반드시 스테이징 배포 후 검증"
    ),
    "test/e2e": (
        "E2E 테스트 서버는 `next start`(standalone) 기준으로만 실행 — "
        "dev JIT race로 {count}회 플레이키 발생"
    ),
    "config": (
        "`next.config.ts` · `env.ts` 변경 후 반드시 dev 서버 재시작 및 빌드 확인 — "
        "{count}회 회귀"
    ),
}

def generate_rules(domain_counts: list[tuple[str, int]]) -> list[str]:
    """템플릿 기반 규칙 생성 (Claude API 없을 때 폴백)"""
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
    fix_summary_lines = []
    for p in fix_prs:
        line = f"- #{p.number}: {p.title}"
        if p.files:
            line += f" (파일: {', '.join(p.files[:3])})"
        if p.review_comments:
            line += f"\n  리뷰: {' / '.join(p.review_comments[:2])}"
        fix_summary_lines.append(line)
    fix_summary = "\n".join(fix_summary_lines)
    cluster_summary = "\n".join(
        f"- [{c.domain}] PR #{c.start}~#{c.end} ({c.size}개 연속 fix)"
        for c in clusters
    ) or "없음"
    domain_summary = "\n".join(f"- {d}: {n}회" for d, n in domain_counts if n >= 2) or "없음"
    file_summary = "\n".join(f"- {f}: {n}회" for f, n in risky_files[:8]) or "없음"

    return f"""당신은 소프트웨어 품질 분석 전문가입니다.
아래는 한 GitHub 레포지토리의 PR 히스토리 분석 결과입니다.

## fix PR 목록
{fix_summary}

## 회귀 클러스터 (연속 fix 발생 구간)
{cluster_summary}

## 도메인별 fix 횟수
{domain_summary}

## 고위험 파일 (fix PR에 자주 등장)
{file_summary}

위 데이터를 바탕으로 AI 코딩 어시스턴트(Claude Code)의 CLAUDE.md에 추가할 규칙을 3~5개 작성해주세요.

요구사항:
1. 각 규칙은 "- " 로 시작하는 한 줄
2. 반복된 실수 패턴을 방지하는 구체적인 행동 지침
3. 파일명·도메인·횟수 등 데이터 기반 근거 포함
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
) -> list[str]:
    """
    AI 기반 규칙 생성. 우선순위:
      1. ANTHROPIC_API_KEY → Anthropic API (claude-haiku)
      2. GITHUB_TOKEN      → GitHub Models API (OpenAI-compatible, 무료)
    """
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
        print(json.dumps({
            "summary": {"total_prs": total, "fix_prs": fix_count, "fix_rate": round(fix_rate, 1)},
            "clusters": [{"start": c.start, "end": c.end, "size": c.size, "domain": c.domain} for c in clusters],
            "risky_files": [{"file": f, "fix_count": n} for f, n in risky_files],
            "domain_counts": [{"domain": d, "fix_count": n} for d, n in domain_counts],
            "claude_md_suggestions": rules,
            "ai_vs_human": ai_stats,
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
    parser.add_argument("--fetch-files", action="store_true", help="각 fix PR의 파일 목록 수집 (느림)")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--input", help="미리 받은 PR JSON 파일 (gh 생략)")
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
    args = parser.parse_args()

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
            is_fix = bool(re.match(r'^fix', item["title"], re.I))
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

    if args.fetch_files:
        fix_prs = [p for p in prs if p.is_fix]
        print(f"fix PR {len(fix_prs)}개 파일 + 리뷰 코멘트 + AI 여부 수집 중...", file=sys.stderr)
        for pr in fix_prs:
            pr.files = fetch_pr_files(pr.number)
            pr.review_comments = fetch_pr_review_comments(pr.number)
            pr.is_ai_generated = fetch_pr_is_ai_generated(pr.number)
            domain = classify_domain(pr.title, pr.files)
            pr.domain = domain

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
