#!/usr/bin/env python3
"""
v0.x → v1.0 마이그레이션 — 단일 레포 캐시를 멀티 레포 구조로 이전.

이전: data/analysis-cache.json (한 파일에 한 레포)
이후: data/repos/{slug}/analysis-cache.json (레포별 디렉토리)

`repo` 필드를 cache 안에서 읽어 정확한 슬러그 디렉토리에 이동한다.
이미 마이그레이션 됐거나 legacy 파일이 없으면 no-op.

실행:
  python3 scripts/migrate_to_multi_repo.py [--dry-run]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from repo_store import cache_path, _LEGACY_CACHE  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not _LEGACY_CACHE.exists():
        print("legacy data/analysis-cache.json 없음 — 마이그레이션 불필요")
        return

    try:
        data = json.loads(_LEGACY_CACHE.read_text())
    except Exception as e:
        print(f"legacy 파일 파싱 실패: {e}")
        sys.exit(1)

    repo = data.get("repo")
    if not repo:
        print("legacy 파일에 'repo' 필드 없음 — 수동 처리 필요")
        sys.exit(1)

    target = cache_path(repo, create=False)
    if target.exists():
        print(f"⚠️  대상 이미 존재: {target} — legacy 삭제만 진행 ({'dry-run' if args.dry_run else 'execute'})")
        if not args.dry_run:
            _LEGACY_CACHE.unlink()
        return

    print(f"이동: {_LEGACY_CACHE} → {target}")
    if args.dry_run:
        print("(dry-run — 실제 이동 안 함)")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(_LEGACY_CACHE), str(target))
    print(f"✅ 마이그레이션 완료 (repo: {repo})")


if __name__ == "__main__":
    main()
