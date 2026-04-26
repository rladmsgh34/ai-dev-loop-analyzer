#!/usr/bin/env python3
"""
ai-dev-loop-analyzer CLI 래퍼 — Claude Code PreToolUse 훅용

사용법:
  # Claude Code 훅에서 stdin으로 tool 정보를 수신
  echo '{"tool_name":"Edit","tool_input":{"file_path":"/path/to/file"}}' | python3 cli.py

  # 단독 테스트
  python3 cli.py /path/to/file

동작:
  1. stdin JSON에서 tool_input.file_path 또는 tool_input.path를 추출
  2. 현재 git remote에서 레포를 자동 감지 (AI_DEV_LOOP_REPO 환경변수로 override 가능)
  3. 레포별 analysis-cache.json을 읽어 회귀 위험 파일 여부를 확인
  4. 위험 있으면 stdout에 경고 출력 (Claude가 경고로 읽음)
  5. 위험 없으면 조용히 종료 (exit 0, 출력 없음)
"""

import json
import os
import sys
from pathlib import Path

SRC_DIR = Path(__file__).parent
sys.path.insert(0, str(SRC_DIR))

from repo_store import detect_current_repo, load_cache


def get_file_path_from_stdin() -> str | None:
    """stdin JSON에서 파일 경로 추출. 실패 시 None 반환."""
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return None
        data = json.loads(raw)
        tool_input = data.get("tool_input", {})
        return tool_input.get("file_path") or tool_input.get("path")
    except (json.JSONDecodeError, AttributeError):
        return None


def check_risk(file_path: str, repo: str | None) -> str | None:
    """
    레포별 캐시에서 해당 파일의 위험도를 확인.
    위험하면 경고 문자열 반환, 안전하면 None 반환.
    """
    cache = load_cache(repo)
    if not cache:
        return None

    risky: dict[str, dict] = {
        item["file"]: item for item in cache.get("risky_files", [])
    }

    match = risky.get(file_path) or next(
        (v for k, v in risky.items() if file_path.endswith(k) or k.endswith(file_path)),
        None,
    )

    if not match:
        return None

    domain = match.get("domain", "general")
    count = match.get("fix_count", 0)
    last_title = match.get("last_fix_title", "")
    file_name = Path(file_path).name
    repo_label = f" [{repo}]" if repo else ""

    lines = [f"[ai-dev-loop]{repo_label} {file_name} — {domain} 도메인에서 {count}회 수정 이력"]
    if last_title:
        lines.append(f"    마지막 fix: {last_title}")

    return "\n".join(lines)


def main():
    # CLI 인수가 있으면 직접 파일 경로로 받음 (테스트용)
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = get_file_path_from_stdin()

    if not file_path:
        sys.exit(0)

    # 레포 감지: 환경변수 → git remote 자동 감지 → None(fallback)
    repo = os.environ.get("AI_DEV_LOOP_REPO") or detect_current_repo()

    warning = check_risk(file_path, repo)
    if warning:
        print(warning)
    sys.exit(0)


if __name__ == "__main__":
    main()
