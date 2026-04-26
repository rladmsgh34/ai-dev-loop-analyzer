#!/usr/bin/env python3
"""
레포별 데이터 경로 관리 — 멀티 레포 지원 핵심 모듈.

공유 데이터 (전 레포 공통):
  data/diff-patterns.json      — BM25/벡터 학습용 diff 패턴
  data/language-patterns.json  — 언어별 크로스 레포 통계
  data/.bm25_cache.pkl         — BM25 인덱스 (전 레포 합산)

레포별 데이터 (레포마다 독립):
  data/repos/{slug}/analysis-cache.json  — 회귀 파일·클러스터·도메인 분석
  data/repos/{slug}/warning-log.jsonl    — PostToolUse 경고 로그
  data/repos/{slug}/feedback-stats.json  — 경고 정밀도 통계

하위 호환:
  data/analysis-cache.json 이 있으면 fallback으로 사용 (v0.x 마이그레이션).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
REPOS_DIR = DATA_DIR / "repos"

# 하위 호환: 구버전 단일 레포 캐시 경로
_LEGACY_CACHE = DATA_DIR / "analysis-cache.json"


def repo_slug(repo: str) -> str:
    """'owner/repo' → 'owner_repo' (디렉토리명으로 사용 가능한 형태)."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", repo)


def repo_data_dir(repo: str) -> Path:
    """레포별 데이터 디렉토리. 없으면 자동 생성."""
    path = REPOS_DIR / repo_slug(repo)
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(repo: str) -> Path:
    return repo_data_dir(repo) / "analysis-cache.json"


def warning_log_path(repo: str) -> Path:
    return repo_data_dir(repo) / "warning-log.jsonl"


def feedback_stats_path(repo: str) -> Path:
    return repo_data_dir(repo) / "feedback-stats.json"


def load_cache(repo: str | None = None) -> dict:
    """
    레포 지정 시 레포별 캐시 로드.
    미지정 시 등록된 첫 번째 레포 또는 legacy 캐시 fallback.
    """
    import json

    if repo:
        p = cache_path(repo)
        if p.exists():
            return json.loads(p.read_text())
        # 레포가 지정됐지만 캐시가 없으면 빈 dict (analyze_pr_history 먼저 실행 필요)
        return {}

    # repo 미지정: 등록된 레포 중 첫 번째 사용
    registered = list_registered_repos()
    for r in registered:
        p = cache_path(r)
        if p.exists():
            return json.loads(p.read_text())

    # legacy fallback (v0.x 호환)
    if _LEGACY_CACHE.exists():
        import json
        return json.loads(_LEGACY_CACHE.read_text())

    return {}


def list_registered_repos() -> list[str]:
    """data/repos/ 하위 디렉토리 존재 여부로 등록 레포 목록 반환."""
    if not REPOS_DIR.exists():
        return []
    return [
        d.name.replace("_", "/", 1)  # slug → owner/repo (첫 번째 _ 만 치환)
        for d in sorted(REPOS_DIR.iterdir())
        if d.is_dir() and (d / "analysis-cache.json").exists()
    ]


def detect_current_repo() -> str | None:
    """
    현재 디렉토리의 git remote origin에서 레포 이름을 자동 감지.
    GitHub URL 형식: https://github.com/owner/repo.git
                     git@github.com:owner/repo.git
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        )
        url = result.stdout.strip()
        # SSH: git@github.com:owner/repo.git
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None
