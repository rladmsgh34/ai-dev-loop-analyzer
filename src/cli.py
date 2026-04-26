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
  2. analysis-cache.json을 읽어 회귀 위험 파일 여부를 확인
  3. 위험 있으면 stdout에 경고 출력 (Claude가 경고로 읽음)
  4. 위험 없으면 조용히 종료 (exit 0, 출력 없음)
"""

import json
import sys
from pathlib import Path

# 경로 설정
SRC_DIR = Path(__file__).parent
ROOT = SRC_DIR.parent
CACHE_FILE = ROOT / "data" / "analysis-cache.json"

sys.path.insert(0, str(SRC_DIR))


def load_cache() -> dict:
    """분석 캐시 로드. 캐시 없으면 빈 dict 반환."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def get_file_path_from_stdin() -> str | None:
    """stdin JSON에서 파일 경로 추출. 실패 시 None 반환."""
    if sys.stdin.isatty():
        # 대화형 모드: stdin 없음
        return None
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return None
        data = json.loads(raw)
        tool_input = data.get("tool_input", {})
        # Edit/Write 모두 file_path 필드를 사용하지만 혹시 path도 체크
        return tool_input.get("file_path") or tool_input.get("path")
    except (json.JSONDecodeError, AttributeError):
        return None


def check_risk(file_path: str) -> str | None:
    """
    캐시에서 해당 파일의 위험도를 확인.
    위험하면 경고 문자열 반환, 안전하면 None 반환.
    """
    cache = load_cache()
    if not cache:
        return None  # 캐시 없으면 조용히 통과

    risky: dict[str, dict] = {
        item["file"]: item for item in cache.get("risky_files", [])
    }

    # 정확히 일치하거나 접미사/접두사로 부분 매칭
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

    lines = [f"[ai-dev-loop] {file_name} — {domain} 도메인에서 {count}회 수정 이력"]
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
        # 파일 경로를 특정할 수 없으면 조용히 통과
        sys.exit(0)

    warning = check_risk(file_path)
    if warning:
        print(warning)
        # exit 0: Claude Code는 exit code가 아닌 stdout 내용으로 경고를 판단
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
