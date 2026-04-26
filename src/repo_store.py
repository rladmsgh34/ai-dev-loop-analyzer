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

슬러그 정책:
  '/' → '__' (이중 언더스코어). 'owner_with_underscore/repo' 같은 케이스에서도
  안전하게 round-trip 가능. 추가로 list_registered_repos()는 슬러그 역변환에
  의존하지 않고 analysis-cache.json 안의 'repo' 필드를 정답 소스로 사용한다.

하위 호환:
  data/analysis-cache.json (구버전 단일 레포) 존재 시 fallback으로 사용.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
REPOS_DIR = DATA_DIR / "repos"

# 하위 호환: 구버전 단일 레포 캐시 경로
_LEGACY_CACHE = DATA_DIR / "analysis-cache.json"

# detect_current_repo() 결과 캐시 — subprocess 비용 제거
_REPO_CACHE: dict[str, str | None] = {}


def repo_slug(repo: str) -> str:
    """
    'owner/repo' → 'owner__repo'. 단일 underscore가 아닌 더블 underscore를 써서
    owner나 repo 이름에 underscore가 있어도 round-trip 안전.
    """
    if "/" not in repo:
        # 잘못된 형식이면 안전한 문자만 남김
        return re.sub(r"[^a-zA-Z0-9._-]", "_", repo)
    return repo.replace("/", "__")


def repo_data_dir(repo: str, create: bool = True) -> Path:
    """
    레포별 데이터 디렉토리. create=False 면 존재 여부 확인용으로 사용 (mkdir 안 함).
    """
    path = REPOS_DIR / repo_slug(repo)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(repo: str, create: bool = True) -> Path:
    return repo_data_dir(repo, create=create) / "analysis-cache.json"


def warning_log_path(repo: str, create: bool = True) -> Path:
    return repo_data_dir(repo, create=create) / "warning-log.jsonl"


def feedback_stats_path(repo: str, create: bool = True) -> Path:
    return repo_data_dir(repo, create=create) / "feedback-stats.json"


def list_registered_repos() -> list[str]:
    """
    data/repos/{slug}/analysis-cache.json 안의 'repo' 필드를 정답 소스로 읽는다.
    슬러그 역변환에 의존하지 않으므로 owner/repo에 underscore가 있어도 안전.
    """
    if not REPOS_DIR.exists():
        return []
    repos: list[str] = []
    for d in sorted(REPOS_DIR.iterdir()):
        if not d.is_dir():
            continue
        cache_file = d / "analysis-cache.json"
        if not cache_file.exists():
            continue
        try:
            data = json.loads(cache_file.read_text())
            repo_name = data.get("repo")
            if repo_name:
                repos.append(repo_name)
        except Exception:
            continue
    return repos


def load_cache(repo: str | None = None) -> dict:
    """
    repo 명시 → 해당 레포 캐시 (없으면 빈 dict).
    repo 미지정:
      - 등록 레포 0개 + legacy 캐시 존재 → legacy 사용
      - 등록 레포 1개 → 그것 사용 (모호하지 않음)
      - 등록 레포 ≥2개 → ValueError (무음 오답 방지)
    """
    if repo:
        p = cache_path(repo, create=False)
        if p.exists():
            return json.loads(p.read_text())
        return {}

    registered = list_registered_repos()

    if len(registered) >= 2:
        raise ValueError(
            f"여러 레포가 등록되어 있습니다 ({', '.join(registered)}). "
            f"repo 파라미터를 명시하세요."
        )

    if len(registered) == 1:
        p = cache_path(registered[0], create=False)
        if p.exists():
            return json.loads(p.read_text())

    # legacy fallback (v0.x 호환)
    if _LEGACY_CACHE.exists():
        return json.loads(_LEGACY_CACHE.read_text())

    return {}


def detect_current_repo() -> str | None:
    """
    현재 디렉토리의 git remote origin에서 레포 이름을 자동 감지.
    결과는 cwd 단위로 캐싱하여 PostToolUse 훅 latency를 줄인다.
    """
    cwd = str(Path.cwd())
    if cwd in _REPO_CACHE:
        return _REPO_CACHE[cwd]

    repo: str | None = None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        )
        url = result.stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            repo = m.group(1)
    except Exception:
        pass

    _REPO_CACHE[cwd] = repo
    return repo
