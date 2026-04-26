#!/usr/bin/env python3
"""
ai-dev-loop-analyzer MCP 서버

Claude Code, Cursor, Cline 등 MCP 지원 AI 에디터에서
코드 작성 시점에 회귀 위험을 사전 경고합니다.

도구:
  check_risk_zones(file_paths)   — 편집할 파일의 회귀 위험도 사전 체크
  analyze_pr_history(repo)       — 레포 PR 히스토리 전체 분석
  get_active_rules(domain)       — 도메인별 현재 활성 규칙 조회

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
CACHE_FILE = DATA_DIR / "analysis-cache.json"
HISTORY_FILE = DATA_DIR / "rules-history.json"
SRC_DIR = Path(__file__).parent

sys.path.insert(0, str(SRC_DIR))

import analyze as _ana  # noqa: E402

_profile_path = os.environ.get("AI_DEV_LOOP_PROFILE")
if _profile_path and Path(_profile_path).exists():
    _ana.load_profile(_profile_path)

# ── 캐시 로드 ─────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"rules": [], "snapshots": []}


# ── 도구 구현 ─────────────────────────────────────────────────────────────────
def _check_risk_zones(file_paths: list[str]) -> str:
    """
    편집하려는 파일들이 과거 회귀 핫존인지 확인.
    캐시된 분석 데이터를 사용하므로 빠르게 응답.
    diff 스니펫이 있으면 "마지막으로 이 파일이 고쳐졌을 때 변경 내용"도 함께 표시.
    """
    cache = load_cache()
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

    # smart-fetch: 클러스터 PR만 diff + 파일 수집
    pre_clusters = ana.detect_clusters(prs)
    cluster_nums = list({p.number for c in pre_clusters for p in c.prs})
    pr_map = {p.number: p for p in prs}

    if cluster_nums:
        def _fetch(num):
            return num, ana.fetch_pr_details(num)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch, num): num for num in cluster_nums}
            for future in as_completed(futures):
                num, (files, comments, is_ai, diff) = future.result()
                pr = pr_map[num]
                pr.files, pr.review_comments = files, comments
                pr.is_ai_generated, pr.diff_snippet = is_ai, diff
                pr.domain = ana.classify_domain(pr.title, pr.files)

    clusters = ana.detect_clusters(prs)
    risky_files = ana.rank_risky_files(prs)
    domain_counts = ana.rank_risky_domains(prs)
    ai_stats = ana.analyze_ai_vs_human(prs)

    total = len(prs)
    fix_count = sum(1 for p in prs if p.is_fix)
    fix_rate = round(fix_count / total * 100, 1) if total else 0

    # 파일별 마지막 fix diff 인덱스 구성
    file_last_diff: dict[str, dict] = {}
    for pr in sorted(prs, key=lambda p: p.number):
        if pr.is_fix and pr.diff_snippet:
            for f in pr.files:
                file_last_diff[f] = {"title": pr.title, "diff": pr.diff_snippet}

    # 캐시 저장
    DATA_DIR.mkdir(exist_ok=True)
    cache = {
        "generated_at": __import__("datetime").date.today().isoformat(),
        "repo": repo,
        "fix_rate": fix_rate,
        "risky_files": [
            {
                "file": f,
                "fix_count": n,
                "domain": ana.classify_domain("", [f]),
                "last_fix_title": file_last_diff.get(f, {}).get("title", ""),
                "last_diff_snippet": file_last_diff.get(f, {}).get("diff", "")[:400],
            }
            for f, n in risky_files
        ],
        "domain_counts": [{"domain": d, "fix_count": n} for d, n in domain_counts],
        "ai_weak_domains": ai_stats["ai"]["weak_domains"],
        "clusters": [{"start": c.start, "end": c.end, "domain": c.domain} for c in clusters],
    }
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

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


def _get_active_rules(domain: str = "") -> str:
    """현재 활성 규칙 조회. domain 미지정 시 전체 반환."""
    history = load_history()
    rules = history.get("rules", [])

    if not rules:
        return "등록된 규칙 없음 — CLAUDE.md에 규칙이 추가되면 자동 등록됩니다."

    if domain:
        rules = [r for r in rules if domain.lower() in r["rule"].lower()]

    if not rules:
        return f"'{domain}' 도메인 관련 규칙 없음"

    from rule_tracker import compute_effectiveness
    effectiveness = {e["date_added"] + e["rule"][:20]: e for e in compute_effectiveness()}

    lines = [f"## 활성 규칙 ({len(rules)}개)\n"]
    for r in rules:
        key = r["date_added"] + r["rule"][:20]
        eff = effectiveness.get(key)
        status = ""
        if eff:
            status = f" | {'✅ 효과 있음' if eff['effective'] else '⏳ 측정 중'} ({eff['delta']:+.1f}%p)"
        lines.append(f"- **{r['date_added']}**{status}\n  {r['rule']}")

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
            "Turns retrospective analysis into prospective warnings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "확인할 파일 경로 목록 (예: ['src/lib/auth.ts', 'next.config.ts'])",
                }
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
        name="get_active_rules",
        description=(
            "현재 CLAUDE.md에 등록된 AI Dev Loop 자동 규칙을 조회합니다. "
            "규칙 추가 전후 fix-rate 변화(효과 측정)도 함께 반환합니다."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "필터할 도메인 (예: 'auth', 'payment'). 미입력 시 전체 반환.",
                    "default": "",
                }
            },
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
            text = _check_risk_zones(arguments.get("file_paths", []))
        elif name == "analyze_pr_history":
            text = _analyze_pr_history(
                arguments["repo"],
                arguments.get("limit", 200),
            )
        elif name == "get_active_rules":
            text = _get_active_rules(arguments.get("domain", ""))
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
