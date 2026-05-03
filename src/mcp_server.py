#!/usr/bin/env python3
"""
ai-dev-loop-analyzer MCP 서버

Claude Code, Cursor, Cline 등 MCP 지원 AI 에디터에서
코드 작성 시점에 회귀 위험을 사전 경고합니다.

도구:
  check_risk_zones(file_paths)        — 편집할 파일의 회귀 위험도 사전 체크 (RAG 유사 패턴 포함)
  suggest_review_checklist(...)       — PR 제목 + 파일 기반 리뷰 체크리스트 생성
  diff_risk_score(diff)               — 스테이지된 diff를 과거 fix 패턴과 비교해 위험도 점수화
  analyze_pr_history(repo)            — 레포 PR 히스토리 전체 분석
  list_repos()                        — 분석 캐시가 존재하는 등록 레포 목록 조회

설치 (Claude Code):
  claude mcp add ai-dev-loop-analyzer -- python3 /path/to/src/mcp_server.py
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SRC_DIR = Path(__file__).parent

sys.path.insert(0, str(SRC_DIR))

import analyze as _ana  # noqa: E402
from repo_store import load_cache, list_registered_repos, cache_path  # noqa: E402

_profile_path = os.environ.get("AI_DEV_LOOP_PROFILE")
if _profile_path and Path(_profile_path).exists():
    _ana.load_profile(_profile_path)


# ── 도구 구현 ─────────────────────────────────────────────────────────────────
def _check_risk_zones(file_paths: list[str], repo: str | None = None) -> str:
    """
    편집하려는 파일들이 과거 회귀 핫존인지 확인.
    repo 지정 시 해당 레포 캐시만 조회. 미지정 시 등록 레포가 1개면 자동 선택,
    2개 이상이면 ValueError → 사용자에게 명시 요청.
    """
    try:
        cache = load_cache(repo)
    except ValueError as e:
        return f"⚠️ {e}"
    if not cache:
        return (
            "⚠️ 캐시 없음 — `analyze_pr_history`를 먼저 실행하거나 "
            "evolve-rules 워크플로우 결과를 기다려주세요."
        )

    risky = {item["file"]: item for item in cache.get("risky_files", [])}
    domain_counts = {d["domain"]: d["fix_count"] for d in cache.get("domain_counts", [])}
    ai_weak = {d["domain"] for d in cache.get("ai_weak_domains", [])}

    results = []
    safe_files = []

    for path in file_paths:
        match = risky.get(path) or next(
            (v for k, v in risky.items() if path.endswith(k) or k.endswith(path)), None
        )

        if match:
            domain = match.get("domain", "general")
            count = match.get("fix_count", 0)
            ai_flag = " 🤖 AI 생성 코드에서 특히 취약" if domain in ai_weak else ""
            rule_hint = _get_rule_hint(domain, domain_counts)

            block = (
                f"🔴 **{path}**\n"
                f"   회귀 이력: {count}회 | 도메인: `{domain}`{ai_flag}\n"
                f"   {rule_hint}"
            )

            # diff 스니펫이 캐시에 있으면 추가
            last_title = match.get("last_fix_title", "")
            last_diff = match.get("last_diff_snippet", "")
            if last_diff:
                block += (
                    f"\n\n   📌 마지막 수정 (`{last_title}`):\n"
                    f"   ```diff\n"
                    + "\n".join(f"   {l}" for l in last_diff.splitlines()[:15])
                    + "\n   ```"
                )

            # RAG: 유사한 과거 fix 패턴 검색
            rag_docs = _try_rag_context(domain, f"{domain} {path} fix 패턴", n=2)
            if rag_docs:
                block += "\n\n   🔎 유사 과거 패턴:"
                for doc in rag_docs:
                    first_line = doc.splitlines()[0] if doc else ""
                    block += f"\n   - {first_line[:120]}"

            results.append(block)
        else:
            safe_files.append(path)

    if not results:
        return f"✅ 모든 파일 안전 — 알려진 회귀 핫존 없음\n파일: {', '.join(file_paths)}"

    output = ["## 🔍 회귀 위험 경고\n"]
    output.extend(results)

    if safe_files:
        output.append(f"\n✅ 안전: {', '.join(safe_files)}")

    output.append(
        f"\n_분석 기준: {cache.get('generated_at', '날짜 불명')} | "
        f"fix율 {cache.get('fix_rate', '?')}%_"
    )
    return "\n".join(output)


def _get_rule_hint(domain: str, domain_counts: dict[str, int]) -> str:
    """도메인에 맞는 사전 경고 메시지 — 프로파일의 rule_hints에서 로드."""
    return _ana.RULE_HINTS.get(domain, f"→ {domain} 도메인: 변경 전 관련 테스트 전체 실행 권장")


def _try_rag_context(domain: str, query: str, n: int = 3) -> list[str]:
    """ChromaDB가 있으면 유사 패턴을 반환, 없으면 빈 리스트."""
    try:
        sys.path.insert(0, str(SRC_DIR / "rag"))
        from rag.query import RagEngine
        engine = RagEngine()
        return engine.retrieve(query, n_results=n, where={"type": "diff_pattern"}) or \
               engine.retrieve(query, n_results=n)
    except Exception:
        return []


def _analyze_pr_history(repo: str, limit: int = 200) -> str:
    """레포 PR 히스토리 분석 후 캐시 저장"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        try:
            result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
            token = result.stdout.strip()
        except Exception:
            pass

    # PR 수집
    cmd = ["gh", "pr", "list", "--repo", repo, "--state", "merged",
           f"--limit={limit}", "--json", "number,title,mergedAt,additions,deletions"]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            env={**os.environ, "GH_TOKEN": token})

    if result.returncode != 0:
        return f"❌ PR 수집 실패: {result.stderr}\n레포 이름 확인 (예: owner/repo-name)"

    raw = json.loads(result.stdout)

    import re
    import analyze as ana
    from concurrent.futures import ThreadPoolExecutor, as_completed

    _FIX_RE = re.compile(r'^fix|^hotfix|수정|버그|bug\b|regression|revert', re.I)
    prs = []
    for item in raw:
        is_fix = bool(_FIX_RE.search(item["title"]))
        pr = ana.PR(
            number=item["number"], title=item["title"],
            merged_at=item["mergedAt"], additions=item["additions"],
            deletions=item["deletions"], is_fix=is_fix,
            domain=ana.classify_domain(item["title"], []),
        )
        prs.append(pr)
    prs = sorted(prs, key=lambda p: p.number)

    # fix PR 전체 파일 fetch → domain 분류 정확도 향상
    # (클러스터 여부 관계없이 fix PR이면 모두 파일+diff 수집)
    pr_map = {p.number: p for p in prs}
    fix_nums = [p.number for p in prs if p.is_fix]

    if fix_nums:
        def _fetch(num):
            return num, ana.fetch_pr_details(num)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch, num): num for num in fix_nums}
            for future in as_completed(futures):
                num, (files, comments, is_ai, diff) = future.result()
                pr = pr_map[num]
                pr.files, pr.review_comments = files, comments
                pr.is_ai_generated, pr.diff_snippet = is_ai, diff
                pr.domain = ana.classify_domain(pr.title, pr.files)

    # AI 감지 패스: fix PR 외 나머지 PR 대상으로 Co-Authored-By 확인
    already_checked = set(fix_nums)
    remaining = [p.number for p in prs if p.number not in already_checked]
    if remaining:
        ai_flags = ana.fetch_ai_flags(remaining)
        for num, is_ai in ai_flags.items():
            if not pr_map[num].is_ai_generated:
                pr_map[num].is_ai_generated = is_ai

    clusters = ana.detect_clusters(prs)
    risky_files = ana.rank_risky_files(prs)
    domain_counts = ana.rank_risky_domains(prs)
    ai_stats = ana.analyze_ai_vs_human(prs)

    total = len(prs)
    fix_count = sum(1 for p in prs if p.is_fix)
    fix_rate = round(fix_count / total * 100, 1) if total else 0

    # report dict로 정규화 후 ana.build_cache_dict 호출
    # → evolve-rules.yml Step 1.5와 100% 동일한 스키마 보장 (드리프트 차단)
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
    report = {
        "summary": {"total_prs": total, "fix_prs": fix_count, "fix_rate": fix_rate},
        "clusters": [{"start": c.start, "end": c.end, "size": c.size, "domain": c.domain} for c in clusters],
        "risky_files": [{"file": f, "fix_count": n} for f, n in risky_files],
        "domain_counts": [{"domain": d, "fix_count": n} for d, n in domain_counts],
        "ai_vs_human": ai_stats,
        "fix_prs_with_diff": fix_prs_with_diff,
    }
    cache = ana.build_cache_dict(report, repo)
    cache_path(repo).write_text(json.dumps(cache, ensure_ascii=False, indent=2))

    # 응답 구성
    lines = [
        f"## 📊 {repo} 분석 완료",
        f"총 PR {total}개 | fix PR {fix_count}개 ({fix_rate}%)",
        "",
        "### 회귀 클러스터",
    ]
    for c in clusters:
        lines.append(f"- [{c.domain}] #{c.start} → #{c.end}")

    lines += ["", "### 고위험 파일 Top 5"]
    for f, n in risky_files[:5]:
        lines.append(f"- `{f}` ({n}회)")

    ai = ai_stats["ai"]
    if ai["total"] > 0:
        lines += [
            "", f"### 🤖 AI 생성 PR fix율: {ai['fix_rate']}%",
            "AI가 특히 약한 도메인:",
        ]
        for d in ai["weak_domains"][:3]:
            lines.append(f"- {d['domain']} ({d['count']}회)")

    lines.append("\n✅ 캐시 저장 완료 — `check_risk_zones`로 파일별 위험도 조회 가능")
    return "\n".join(lines)


def _suggest_review_checklist(pr_title: str, file_paths: list[str]) -> str:
    """
    PR 제목 + 변경 파일을 기반으로 이 레포 특화 리뷰 체크리스트를 생성.
    1) 도메인 분류 → 2) 고위험 파일 매칭 → 3) 활성 규칙 인용 → 4) RAG 패턴 추가.
    """
    domain = _ana.classify_domain(pr_title, file_paths)
    cache = load_cache()
    history = load_history()

    lines = [f"## 📋 리뷰 체크리스트 — `{pr_title}`", f"도메인: `{domain}`\n"]

    # ① 고위험 파일 경고
    risky = {item["file"]: item for item in cache.get("risky_files", [])}
    hit_files = []
    for path in file_paths:
        match = risky.get(path) or next(
            (v for k, v in risky.items() if path.endswith(k) or k.endswith(path)), None
        )
        if match:
            hit_files.append((path, match.get("fix_count", 0), match.get("last_fix_title", "")))

    if hit_files:
        lines.append("### ⚠️ 고위험 파일 (과거 회귀 이력)")
        for path, count, last in hit_files:
            last_note = f" — 마지막: _{last}_" if last else ""
            lines.append(f"- [ ] `{path}` ({count}회 회귀{last_note}): 변경 전후 동작 직접 확인")
        lines.append("")

    # ② 도메인 규칙 기반 체크리스트
    domain_rules = [
        r["rule"] for r in history.get("rules", [])
        if domain.lower() in r["rule"].lower() or domain in r.get("domain", "")
    ][:5]

    rule_hint = _get_rule_hint(domain, {})
    lines.append("### ✅ 도메인 체크리스트")
    if domain_rules:
        for rule in domain_rules:
            lines.append(f"- [ ] {rule}")
    else:
        lines.append(f"- [ ] {rule_hint.lstrip('→ ')}")

    # ③ RAG 유사 패턴 — 과거 fix에서 뽑은 구체적 주의사항
    rag_docs = _try_rag_context(domain, f"{domain} {pr_title} fix 주의사항", n=3)
    if rag_docs:
        lines.append("\n### 🔎 유사 과거 fix에서 배운 것")
        for doc in rag_docs:
            first = doc.splitlines()[0][:140] if doc else ""
            if first:
                lines.append(f"- [ ] 확인: {first}")

    # ④ 항상 포함되는 기본 항목
    lines += [
        "\n### 🔧 기본 확인",
        "- [ ] `pnpm test` 통과",
        "- [ ] 타입 에러 없음 (`pnpm type-check`)",
        f"- [ ] {domain} 관련 기존 테스트 갱신",
    ]

    return "\n".join(lines)


def _diff_risk_score(diff: str, context: str = "") -> str:
    """
    Scores a staged diff (0-10) by comparing it against past fix-PR patterns in ChromaDB.
    Returns a markdown block with score badge, top-3 similar patterns, and a recommendation.
    """
    # 1. Use first 120 lines of the diff (token limit)
    diff_lines = diff.splitlines()[:120]
    diff_excerpt = "\n".join(diff_lines)

    # 2. Extract changed file names from `+++ b/` lines in the diff
    extracted_files: list[str] = []
    for line in diff_lines:
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            if file_path and file_path != "/dev/null":
                extracted_files.append(file_path)

    # 3. Classify domain via _ana.classify_domain(context, extracted_files)
    domain = _ana.classify_domain(context, extracted_files)

    # 4. Query RAG context
    query = f"{domain} fix {context} {diff_excerpt[:400]}"
    rag_docs = _try_rag_context(domain, query, n=5)

    # 5. Compute risk score 0-10: each matched similar pattern = +2, capped at 10
    score = min(len(rag_docs) * 2, 10)

    # Score badge
    if score >= 7:
        badge = f"🔴 **위험 점수: {score}/10**"
        recommendation = "커밋 전 관련 테스트를 전부 실행하고, 과거 fix 패턴과 동일한 실수가 없는지 직접 확인하세요."
    elif score >= 4:
        badge = f"🟡 **위험 점수: {score}/10**"
        recommendation = f"{domain} 도메인 관련 테스트를 실행하고 체크리스트를 확인하세요."
    else:
        badge = f"🟢 **위험 점수: {score}/10**"
        recommendation = "유사한 과거 회귀 패턴이 적습니다. 기본 테스트 통과 후 커밋하세요."

    # Build output
    lines = [
        f"## 🔍 Diff 위험 점수 분석",
        f"{badge}",
        f"도메인: `{domain}` | 변경 파일: {len(extracted_files)}개",
        "",
    ]

    if extracted_files:
        lines.append(f"**변경 파일:** {', '.join(f'`{f}`' for f in extracted_files[:5])}")
        lines.append("")

    # Top-3 similar patterns (first line only, max 120 chars each)
    if rag_docs:
        lines.append("### 🔎 유사 과거 fix 패턴 (상위 3개)")
        for doc in rag_docs[:3]:
            first_line = doc.splitlines()[0] if doc else ""
            if first_line:
                lines.append(f"- {first_line[:120]}")
        lines.append("")

    lines.append(f"**권장 조치:** {recommendation}")

    return "\n".join(lines)


# ── MCP 서버 ──────────────────────────────────────────────────────────────────
server = Server("ai-dev-loop-analyzer")

TOOLS = [
    Tool(
        name="check_risk_zones",
        description=(
            "Check whether the files you are about to edit are known regression hotspots. "
            "Call this before modifying a file to receive warnings such as "
            "'this file has regressed 4 times in the payment domain'. "
            "Supports multiple repos — specify repo to query a specific project's history."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "확인할 파일 경로 목록 (예: ['src/lib/auth.ts', 'next.config.ts'])",
                },
                "repo": {
                    "type": "string",
                    "description": "조회할 레포 (예: 'owner/repo'). 미지정 시 첫 번째 등록 레포 사용.",
                    "default": "",
                },
            },
            "required": ["file_paths"],
        },
    ),
    Tool(
        name="analyze_pr_history",
        description=(
            "GitHub 레포의 PR 히스토리를 분석해 회귀 패턴, 고위험 파일, "
            "AI가 약한 도메인을 추출합니다. 결과는 캐시에 저장되어 "
            "check_risk_zones에서 즉시 사용됩니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "분석할 레포 (예: 'owner/repo-name')",
                },
                "limit": {
                    "type": "integer",
                    "description": "분석할 최근 PR 수 (기본 200)",
                    "default": 200,
                },
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="suggest_review_checklist",
        description=(
            "Given a PR title and list of changed files, generate a review checklist "
            "tailored to this repo's past regression patterns. "
            "Combines risky-file history, domain-specific rules, and RAG-retrieved "
            "similar fix diffs to produce concrete, actionable items. "
            "Call this when opening a PR or starting a code review."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pr_title": {
                    "type": "string",
                    "description": "PR 제목 (예: 'feat: 결제 흐름 리팩터')",
                },
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "변경된 파일 경로 목록",
                    "default": [],
                },
            },
            "required": ["pr_title"],
        },
    ),
    Tool(
        name="diff_risk_score",
        description=(
            "Score the risk of a staged diff (0–10) by comparing it against past fix-PR patterns in ChromaDB. "
            "Call this before committing (e.g., pipe `git diff --staged` output) to catch patterns "
            "that have caused regressions before. Returns score, similar past fixes, and a recommendation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "diff": {
                    "type": "string",
                    "description": "Raw diff string (e.g., output of `git diff --staged`)",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context such as PR title or commit message to improve domain classification",
                    "default": "",
                },
            },
            "required": ["diff"],
        },
    ),
    Tool(
        name="list_repos",
        description=(
            "분석 캐시가 존재하는 등록 레포 목록을 반환합니다. "
            "멀티 레포 환경에서 어떤 레포가 추적되고 있는지 확인할 때 사용합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]


@server.list_tools()
async def list_tools():
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "check_risk_zones":
            text = _check_risk_zones(
                arguments.get("file_paths", []),
                arguments.get("repo") or None,
            )
        elif name == "suggest_review_checklist":
            text = _suggest_review_checklist(
                arguments["pr_title"],
                arguments.get("file_paths", []),
            )
        elif name == "diff_risk_score":
            text = _diff_risk_score(
                arguments["diff"],
                arguments.get("context", ""),
            )
        elif name == "analyze_pr_history":
            text = _analyze_pr_history(
                arguments["repo"],
                arguments.get("limit", 200),
            )
        elif name == "list_repos":
            repos = list_registered_repos()
            if not repos:
                text = "등록된 레포 없음 — `analyze_pr_history`를 먼저 실행하세요."
            else:
                lines = [f"## 등록된 레포 ({len(repos)}개)\n"]
                for r in repos:
                    p = cache_path(r)
                    import json as _json
                    cache = _json.loads(p.read_text()) if p.exists() else {}
                    fix_rate = cache.get("fix_rate", "?")
                    analyzed_at = cache.get("generated_at", "?")
                    lines.append(f"- **{r}** | fix율 {fix_rate}% | 분석: {analyzed_at}")
                text = "\n".join(lines)
        else:
            text = f"알 수 없는 도구: {name}"
    except Exception as e:
        text = f"오류: {e}"

    return [TextContent(type="text", text=text)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
