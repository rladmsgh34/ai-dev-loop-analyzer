import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import pickle
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import rag_hook


# ── _tokenize ────────────────────────────────────────────────────────────────

def test_tokenize_splits_on_symbols():
    tokens = rag_hook._tokenize("linux-musl-openssl-3.0.x")
    assert "linux" in tokens
    assert "musl" in tokens
    assert "openssl" in tokens


def test_tokenize_camelcase():
    tokens = rag_hook._tokenize("BinaryTargets")
    assert "binary" in tokens
    assert "targets" in tokens


def test_tokenize_empty():
    assert rag_hook._tokenize("") == []


# ── _extract_change ───────────────────────────────────────────────────────────

def test_extract_change_edit():
    result = rag_hook._extract_change(
        "Edit",
        {"file_path": "a.ts", "old_string": "old", "new_string": "new content here"},
    )
    assert result == "new content here"


def test_extract_change_write():
    result = rag_hook._extract_change(
        "Write",
        {"file_path": "a.ts", "content": "x" * 1000},
    )
    assert len(result) == 800  # truncated to 800


def test_extract_change_unknown_tool():
    result = rag_hook._extract_change("Bash", {"command": "ls"})
    assert result == ""


# ── main() integration ────────────────────────────────────────────────────────

def _make_bm25_cache(docs: list[str], ids: list[str], tmp_path: Path) -> Path:
    """실제 BM25Okapi 캐시를 임시 파일에 만들어 반환한다."""
    from rank_bm25 import BM25Okapi
    tokenized = [rag_hook._tokenize(d) for d in docs]
    bm25 = BM25Okapi(tokenized)
    cache = {"bm25": bm25, "ids": ids, "docs": docs}
    cache_path = tmp_path / ".bm25_cache.pkl"
    cache_path.write_bytes(pickle.dumps(cache))
    return cache_path


def test_main_warns_on_high_score(tmp_path, capsys, monkeypatch):
    """BM25 점수가 임계값 이상이면 stdout에 경고를 출력한다."""
    # BM25 IDF = log((N - df + 0.5) / (df + 0.5))
    # df=1, N=2 → log(1) = 0 이므로 최소 3개 문서 필요
    docs = [
        "[PR #42] fix: prisma binaryTargets linux-musl-openssl missing\n[Domain: ci/cd]\n---\n- linux-musl-openssl-3.0.x binaryTargets",
        "[PR #99] feat: add button component\n[Domain: ui]\n---\n+ <button>click</button>",
        "[PR #55] chore: bump eslint version\n[Domain: maintenance]\n---\n eslint 9.0.0",
    ]
    ids = ["diff_repo_42", "diff_repo_99", "diff_repo_55"]
    cache_path = _make_bm25_cache(docs, ids, tmp_path)

    monkeypatch.setattr(rag_hook, "BM25_CACHE_PATH", cache_path)
    monkeypatch.setattr(rag_hook, "_SCORE_THRESHOLD", 0.1)  # 낮게 설정

    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "prisma/schema.prisma",
            "old_string": "old",
            "new_string": "binaryTargets linux musl openssl fix missing",
        },
    })
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload))

    try:
        rag_hook.main()
    except SystemExit:
        pass

    out = capsys.readouterr().out
    assert "⚠️" in out
    assert "schema.prisma" in out


def test_main_silent_on_low_score(tmp_path, capsys, monkeypatch):
    """점수가 임계값 미만이면 아무 출력도 없다."""
    docs = ["[PR #1] fix: unrelated thing\n---\nsome random content"]
    ids = ["diff_repo_1"]
    cache_path = _make_bm25_cache(docs, ids, tmp_path)

    monkeypatch.setattr(rag_hook, "BM25_CACHE_PATH", cache_path)
    monkeypatch.setattr(rag_hook, "_SCORE_THRESHOLD", 999.0)  # 절대 안 넘음

    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "src/foo.ts",
            "old_string": "a",
            "new_string": "completely different keywords xyz",
        },
    })
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload))

    try:
        rag_hook.main()
    except SystemExit:
        pass

    assert capsys.readouterr().out == ""


def test_main_skips_non_diff_pattern_ids(tmp_path, capsys, monkeypatch):
    """diff_ 접두사가 없는 청크는 경고 대상에서 제외된다."""
    docs = ["lang_typescript 통계 요약: fix율 20%"]
    ids = ["lang_typescript_summary"]  # diff_ 아님
    cache_path = _make_bm25_cache(docs, ids, tmp_path)

    monkeypatch.setattr(rag_hook, "BM25_CACHE_PATH", cache_path)
    monkeypatch.setattr(rag_hook, "_SCORE_THRESHOLD", 0.001)

    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "src/foo.ts",
            "old_string": "a",
            "new_string": "typescript fix율 통계 요약 lang",
        },
    })
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload))

    try:
        rag_hook.main()
    except SystemExit:
        pass

    assert capsys.readouterr().out == ""


def test_main_skips_short_change(tmp_path, capsys, monkeypatch):
    """변경 내용이 너무 짧으면 스킵한다."""
    monkeypatch.setattr(rag_hook, "BM25_CACHE_PATH", tmp_path / "nonexistent.pkl")

    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": "f.ts", "old_string": "x", "new_string": "y"},
    })
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload))

    try:
        rag_hook.main()
    except SystemExit:
        pass

    assert capsys.readouterr().out == ""


def test_main_handles_invalid_json(capsys, monkeypatch):
    """stdin이 유효하지 않은 JSON이면 조용히 종료한다."""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    try:
        rag_hook.main()
    except SystemExit:
        pass
    assert capsys.readouterr().out == ""
