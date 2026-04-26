#!/usr/bin/env python3
"""
PostToolUse 훅 — 방금 작성한 코드가 과거 회귀 패턴과 유사하면 즉시 경고.

Claude Code PostToolUse 이벤트로 stdin에서 JSON을 받아 처리한다:
  {"tool_name": "Edit", "tool_input": {"file_path": "...", "old_string": "...", "new_string": "..."}}

BM25 pickle 캐시(ingest.py 실행 시 자동 생성)를 사용해 ChromaDB 없이도
수십 ms 내로 과거 diff-pattern과의 유사도를 계산한다.

설치:
  .claude/settings.json 의 PostToolUse 훅에 이 스크립트를 등록한다.
"""

import json
import pickle
import re
import signal
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
BM25_CACHE_PATH = DATA_DIR / ".bm25_cache.pkl"

# BM25 절대 점수 기준값: 이 이상일 때만 경고
# 코드 전용 토크나이저 기준으로 기술 토큰 3~5개 이상 겹칠 때 대략 1.5 이상
_SCORE_THRESHOLD = 1.5
# 변경 내용이 너무 짧으면 노이즈가 많아 스킵
_MIN_DIFF_LEN = 30
# PostToolUse 훅 최대 실행 시간 — 초과 시 Claude Code Edit/Write가 블로킹됨
_TIMEOUT_SEC = 5


def _tokenize(text: str) -> list[str]:
    """tokenizer.py와 동일한 로직 — 의존성 없이 인라인으로 유지."""
    parts = re.split(r'[\s\-_./:\\@\[\]{}()\'"=<>|&^%#!?;,~`]+', text)
    result = []
    for part in parts:
        if not part:
            continue
        camel = re.sub(r'([a-z])([A-Z])', r'\1 \2', part)
        for token in camel.split():
            t = token.lower()
            if t:
                result.append(t)
    return result


def _extract_change(tool_name: str, tool_input: dict) -> str:
    """Edit/Write tool_input에서 변경된 내용(새 코드)을 추출한다."""
    if tool_name == "Edit":
        # new_string이 실제로 추가된 내용
        return tool_input.get("new_string", "")
    if tool_name == "Write":
        return tool_input.get("content", "")[:800]
    return ""


def _timeout_handler(signum, frame) -> None:
    sys.exit(0)


def main() -> None:
    # 훅이 hang되면 Claude Code Edit/Write 전체가 블로킹됨 — 타임아웃으로 강제 종료
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(_TIMEOUT_SEC)

    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    change = _extract_change(tool_name, tool_input)
    if len(change.strip()) < _MIN_DIFF_LEN:
        sys.exit(0)

    if not BM25_CACHE_PATH.exists():
        sys.exit(0)

    try:
        cache = pickle.loads(BM25_CACHE_PATH.read_bytes())
        bm25 = cache["bm25"]
        ids: list[str] = cache["ids"]
        docs: list[str] = cache["docs"]
    except Exception:
        sys.exit(0)

    tokens = _tokenize(change)
    if not tokens:
        sys.exit(0)

    scores = bm25.get_scores(tokens)

    # diff_pattern 타입만 대상으로 — 통계 청크는 오탐이 많음
    diff_indices = [i for i, id_ in enumerate(ids) if id_.startswith("diff_")]
    if not diff_indices:
        sys.exit(0)

    best_idx = max(diff_indices, key=lambda i: scores[i])
    best_score = scores[best_idx]

    if best_score < _SCORE_THRESHOLD:
        sys.exit(0)

    best_doc = docs[best_idx]
    # 헤더 첫 줄: "[PR #N] 제목"
    header = best_doc.split("\n")[0].strip()
    file_path = tool_input.get("file_path", "")
    filename = Path(file_path).name if file_path else "?"

    print(f"⚠️  [{filename}] 방금 작성한 코드가 과거 회귀 패턴과 유사합니다 (BM25 {best_score:.1f})")
    print(f"   패턴 참고: {header}")
    print(f"   상세 분석: mcp diff_risk_score 툴로 확인하세요.")

    # 피드백 루프: 경고 로그 기록 — 추후 fix PR과 교차 검증해 정밀도 측정
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from feedback import record_warning
        record_warning(
            file_path=file_path,
            bm25_score=best_score,
            matched_id=ids[best_idx],
            matched_header=header,
        )
    except Exception:
        pass  # 로깅 실패가 경고 출력을 막으면 안 됨


if __name__ == "__main__":
    main()
