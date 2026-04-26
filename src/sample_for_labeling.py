#!/usr/bin/env python3
"""
1단계 샘플링 — fix PR 중 'general' 도메인으로 분류된 케이스를 CSV로 출력.

목적: 도메인 분류기의 False Negative(놓친 도메인)를 사람이 직접 라벨링해
      ground truth를 만들고 4단계 회귀 테스트 베이스라인을 확보한다.

사용:
  python3 src/sample_for_labeling.py \
    --repo vuejs/core --target 100 --scan 600 \
    --output data/sampling/vuejs-core-2026-04-26.csv

  # 프로파일 적용 (gwangcheon-shop control)
  python3 src/sample_for_labeling.py \
    --repo rladmsgh34/gwangcheon-shop --target 50 --scan 200 \
    --profile profiles/examples/korean-nextjs-shop.json \
    --output data/sampling/gwangcheon-shop-control-2026-04-26.csv

CSV 컬럼:
  repo, pr_number, pr_url, merged_at, title, files_top3, files_count,
  current_domain (= 'general'), true_domain (라벨러 입력),
  suggested_pattern (라벨러 입력), notes (라벨러 입력)
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import analyze as ana  # noqa: E402


def fetch_merged_prs(repo: str, scan: int) -> list[dict]:
    """gh CLI로 머지된 PR 목록을 가져온다 (내부 페이징은 gh CLI가 처리)."""
    cmd = [
        "gh", "pr", "list",
        "--repo", repo,
        "--state", "merged",
        "--limit", str(scan),
        "--json", "number,title,url,mergedAt",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fetch_pr_files(repo: str, pr_num: int) -> list[str]:
    """gh CLI로 PR의 변경 파일 경로 목록을 가져온다."""
    try:
        result = subprocess.run([
            "gh", "pr", "view", str(pr_num),
            "--repo", repo,
            "--json", "files",
        ], capture_output=True, text=True, check=True, timeout=15)
        data = json.loads(result.stdout)
        return [f["path"] for f in data.get("files", [])]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="대상 레포 (owner/repo)")
    parser.add_argument("--target", type=int, default=100, help="수집 목표 general fix PR 개수")
    parser.add_argument("--scan", type=int, default=400, help="이 한도까지 PR 스캔")
    parser.add_argument("--profile", default=None, help="프로파일 JSON 경로 (선택)")
    parser.add_argument("--output", required=True, help="출력 CSV 경로")
    parser.add_argument("--workers", type=int, default=8, help="파일 fetch 동시 worker")
    args = parser.parse_args()

    if args.profile:
        ana.load_profile(args.profile)
        print(f"📋 프로파일 로드: {args.profile}")
    else:
        print("📋 프로파일 없음 — default DOMAIN_PATTERNS 사용")

    print(f"📥 {args.repo} 머지 PR 가져오는 중 (최대 {args.scan}개)...")
    prs = fetch_merged_prs(args.repo, scan=args.scan)
    print(f"   수집: {len(prs)}개")

    fix_regex = re.compile(ana.FIX_PR_REGEX, re.I)
    fix_prs = [p for p in prs if fix_regex.match(p["title"])]
    print(f"   fix PR: {len(fix_prs)}개 ({len(fix_prs)/max(len(prs),1)*100:.1f}%)")

    if not fix_prs:
        print("⚠️  fix PR 0개 — 종료")
        return

    print(f"📂 fix PR 파일 정보 fetch (병렬 worker={args.workers})...")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        files_list = list(ex.map(
            lambda p: fetch_pr_files(args.repo, p["number"]),
            fix_prs,
        ))

    files_map = {p["number"]: f for p, f in zip(fix_prs, files_list)}

    # 분류 → general 사례만 수집
    general_fix: list[dict] = []
    for pr in fix_prs:
        files = files_map.get(pr["number"], [])
        domain = ana.classify_domain(pr["title"], files)
        if domain == "general":
            general_fix.append({
                "repo": args.repo,
                "pr_number": pr["number"],
                "pr_url": pr["url"],
                "merged_at": pr["mergedAt"],
                "title": pr["title"],
                "files_top3": "; ".join(files[:3]),
                "files_count": len(files),
                "current_domain": "general",
                "true_domain": "",
                "suggested_pattern": "",
                "notes": "",
            })
        if len(general_fix) >= args.target:
            break

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not general_fix:
        out.write_text("# 'general' 도메인으로 분류된 fix PR 없음 — 분류기가 모두 잡아냄\n")
        print(f"✅ general fix PR 0개 (분류기가 잘 동작하거나 fix PR 자체가 적음)")
        print(f"   빈 CSV 저장: {out}")
        return

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(general_fix[0].keys()))
        writer.writeheader()
        writer.writerows(general_fix)

    print(f"✅ CSV 저장: {out}")
    print(f"   general fix PR {len(general_fix)}건 / fix 전체 {len(fix_prs)}건 = "
          f"{len(general_fix)/len(fix_prs)*100:.1f}%")


if __name__ == "__main__":
    main()
