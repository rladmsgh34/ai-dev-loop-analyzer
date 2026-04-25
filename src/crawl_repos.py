#!/usr/bin/env python3
"""
언어별 상위 오픈소스 레포를 크롤링하여 회귀 패턴을 집계합니다.

사용법:
  python3 src/crawl_repos.py                    # 기본 (언어당 30개)
  python3 src/crawl_repos.py --limit 50         # 언어당 50개
  python3 src/crawl_repos.py --lang typescript  # 특정 언어만
  python3 src/crawl_repos.py --dry-run          # 레포 목록만 출력
"""

import json
import os
import re
import sys
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from analyze import (
    classify_domain, PR,
    detect_clusters, rank_risky_domains,
    DOMAIN_PATTERNS,
)

GH_API = "https://api.github.com"
DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = DATA_DIR / "language-patterns.json"

LANGUAGES = ["typescript", "python", "go", "rust", "java", "javascript", "kotlin", "swift"]

# 분석에서 제외할 레포 (포크 많은 튜토리얼 등)
EXCLUDE_REPOS = {
    "EbookFoundation/free-programming-books",
    "jwasham/coding-interview-university",
    "sindresorhus/awesome",
}


def _token() -> str:
    if t := os.environ.get("GITHUB_TOKEN"):
        return t
    try:
        import subprocess
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, token: str) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers=_headers(token))
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("  ⚠️  API 요청 한도 초과, 60초 대기...", file=sys.stderr)
            time.sleep(60)
        elif e.code == 422:
            pass  # search result window exceeded
        else:
            print(f"  HTTP {e.code}: {url}", file=sys.stderr)
    except Exception as e:
        print(f"  error: {e}", file=sys.stderr)
    return None


def search_top_repos(language: str, limit: int, token: str) -> list[dict]:
    repos = []
    page = 1
    while len(repos) < limit:
        url = (
            f"{GH_API}/search/repositories"
            f"?q=language:{language}+stars:>500+is:public"
            f"&sort=stars&order=desc&per_page=30&page={page}"
        )
        data = _get(url, token)
        if not data:
            break
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            full_name = item["full_name"]
            if full_name not in EXCLUDE_REPOS and not item.get("fork"):
                repos.append(item)
        if len(items) < 30:
            break
        page += 1
        time.sleep(1.5)  # search API 요청 간격
    return repos[:limit]


def fetch_merged_prs(owner: str, repo: str, limit: int, token: str) -> list[PR]:
    prs = []
    page = 1
    while len(prs) < limit:
        url = (
            f"{GH_API}/repos/{owner}/{repo}/pulls"
            f"?state=closed&per_page=100&page={page}&sort=updated&direction=desc"
        )
        data = _get(url, token)
        if not data or not isinstance(data, list):
            break
        merged = [p for p in data if p.get("merged_at")]
        for p in merged:
            title = p["title"]
            is_fix = bool(re.match(r"^(fix|hotfix|bugfix|revert|regression|bug)\b", title, re.I))
            domain = classify_domain(title, [])
            prs.append(PR(
                number=p["number"],
                title=title,
                merged_at=p["merged_at"],
                additions=p.get("additions", 0),
                deletions=p.get("deletions", 0),
                is_fix=is_fix,
                domain=domain,
            ))
        if len(data) < 100 or len(prs) >= limit:
            break
        page += 1
        time.sleep(0.5)
    return prs[:limit]


def analyze_repo(owner: str, repo: str, token: str) -> dict | None:
    prs = fetch_merged_prs(owner, repo, 200, token)
    if len(prs) < 10:
        return None

    total = len(prs)
    fix_prs = [p for p in prs if p.is_fix]
    fix_rate = round(len(fix_prs) / total * 100, 1)

    domain_counts = rank_risky_domains(prs)  # list of (domain, count)
    clusters = detect_clusters(prs)

    domain_fix_rates = {}
    for domain, count in domain_counts:
        domain_fix_rates[domain] = {
            "fix_count": count,
            "fix_rate": round(count / total * 100, 1),
        }

    return {
        "owner": owner,
        "repo": repo,
        "total_prs": total,
        "fix_rate": fix_rate,
        "domain_fix_rates": domain_fix_rates,
        "cluster_count": len(clusters),
        "top_domain": domain_counts[0][0] if domain_counts else None,
    }


def aggregate_language(results: list[dict]) -> dict:
    if not results:
        return {}

    domain_stats: dict[str, list[float]] = {}
    fix_rates = []
    cluster_counts = []

    for r in results:
        fix_rates.append(r["fix_rate"])
        cluster_counts.append(r["cluster_count"])
        for domain, stats in r["domain_fix_rates"].items():
            domain_stats.setdefault(domain, []).append(stats["fix_rate"])

    # 도메인별 평균 fix율 계산
    domain_avg = {
        domain: round(sum(rates) / len(rates), 1)
        for domain, rates in domain_stats.items()
        if len(rates) >= max(2, len(results) // 5)  # 5% 이상 레포에서 등장한 도메인만
    }
    top_domains = sorted(domain_avg, key=lambda d: -domain_avg[d])[:5]

    return {
        "repos_analyzed": len(results),
        "avg_fix_rate": round(sum(fix_rates) / len(fix_rates), 1),
        "avg_clusters": round(sum(cluster_counts) / len(cluster_counts), 1),
        "domain_avg_fix_rates": domain_avg,
        "top_domains": top_domains,
        "sample_repos": [f"{r['owner']}/{r['repo']}" for r in results[:5]],
    }


def load_existing() -> dict:
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text())
        except Exception:
            pass
    return {"updated_at": "", "total_repos_analyzed": 0, "languages": {}, "repo_results": []}


def save(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="언어별 오픈소스 회귀 패턴 크롤러")
    parser.add_argument("--limit", type=int, default=30, help="언어당 분석할 레포 수 (기본 30)")
    parser.add_argument("--lang", help="특정 언어만 분석 (예: typescript)")
    parser.add_argument("--dry-run", action="store_true", help="레포 목록만 출력, 분석 안 함")
    parser.add_argument("--append", action="store_true", help="기존 데이터에 추가 (기본: 덮어씀)")
    args = parser.parse_args()

    token = _token()
    if not token:
        print("⚠️  GITHUB_TOKEN 또는 gh CLI 인증이 필요합니다.", file=sys.stderr)
        sys.exit(1)

    target_langs = [args.lang] if args.lang else LANGUAGES
    existing = load_existing() if args.append else {"updated_at": "", "total_repos_analyzed": 0, "languages": {}, "repo_results": []}

    all_repo_results: list[dict] = existing.get("repo_results", [])
    analyzed_keys = {f"{r['owner']}/{r['repo']}" for r in all_repo_results}

    for lang in target_langs:
        print(f"\n🔍 {lang} — 상위 {args.limit}개 레포 검색 중...")
        repos = search_top_repos(lang, args.limit, token)
        print(f"   {len(repos)}개 발견")

        if args.dry_run:
            for r in repos:
                print(f"   {r['full_name']} ⭐{r['stargazers_count']:,}")
            continue

        lang_results = []
        for i, repo_meta in enumerate(repos, 1):
            full_name = repo_meta["full_name"]
            owner, repo_name = full_name.split("/", 1)

            if full_name in analyzed_keys:
                print(f"   [{i}/{len(repos)}] {full_name} — 스킵 (이미 분석됨)")
                # 기존 결과 재사용
                existing_result = next((r for r in all_repo_results if f"{r['owner']}/{r['repo']}" == full_name), None)
                if existing_result:
                    lang_results.append(existing_result)
                continue

            print(f"   [{i}/{len(repos)}] {full_name} ⭐{repo_meta['stargazers_count']:,} 분석 중...", end=" ", flush=True)
            result = analyze_repo(owner, repo_name, token)
            if result:
                result["language"] = lang
                result["stars"] = repo_meta["stargazers_count"]
                lang_results.append(result)
                all_repo_results.append(result)
                analyzed_keys.add(full_name)
                print(f"fix율 {result['fix_rate']}% ({result['total_prs']} PR)")
            else:
                print("스킵 (PR 부족)")
            time.sleep(1)

        if not args.dry_run and lang_results:
            existing["languages"][lang] = aggregate_language(lang_results)
            print(f"   ✅ {lang}: 평균 fix율 {existing['languages'][lang]['avg_fix_rate']}%, 상위 도메인: {', '.join(existing['languages'][lang]['top_domains'][:3])}")

    if not args.dry_run:
        existing["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing["total_repos_analyzed"] = len(all_repo_results)
        existing["repo_results"] = all_repo_results
        save(existing)
        print(f"\n✅ {OUTPUT_FILE} 저장 완료 (총 {len(all_repo_results)}개 레포)")


if __name__ == "__main__":
    main()
