import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import repo_store


# ── repo_slug ─────────────────────────────────────────────────────────────────

def test_repo_slug_basic():
    assert repo_store.repo_slug("owner/repo") == "owner__repo"


def test_repo_slug_underscore_in_owner():
    """이중 underscore 슬러그는 owner에 underscore가 있어도 round-trip 안전."""
    assert repo_store.repo_slug("my_org/my-repo") == "my_org__my-repo"


def test_repo_slug_no_collision():
    """과거 단일 underscore 슬러그가 일으켰던 충돌이 발생하지 않는다."""
    a = repo_store.repo_slug("owner/repo_a")
    b = repo_store.repo_slug("owner_repo/a")
    assert a != b


def test_repo_slug_invalid_format():
    """슬래시 없는 입력도 안전한 문자만 남김."""
    assert "/" not in repo_store.repo_slug("just-a-name")


# ── list_registered_repos ─────────────────────────────────────────────────────

def test_list_registered_repos_reads_from_cache_field(tmp_path, monkeypatch):
    """슬러그 역변환에 의존하지 않고 cache 안의 'repo' 필드를 읽는다."""
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    # owner에 underscore가 들어간 케이스도 정확히 복원돼야 함
    slug_dir = repos_dir / "my_org__my-repo"
    slug_dir.mkdir()
    (slug_dir / "analysis-cache.json").write_text(
        json.dumps({"repo": "my_org/my-repo", "fix_rate": 10})
    )

    result = repo_store.list_registered_repos()
    assert "my_org/my-repo" in result


def test_list_registered_repos_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    assert repo_store.list_registered_repos() == []


def test_list_registered_repos_skips_dirs_without_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    (repos_dir / "empty_dir").mkdir()  # cache 파일 없음
    assert repo_store.list_registered_repos() == []


# ── load_cache ────────────────────────────────────────────────────────────────

def test_load_cache_specific_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(repo_store, "_LEGACY_CACHE", tmp_path / "legacy.json")

    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    (repos_dir / "owner__repo").mkdir()
    (repos_dir / "owner__repo" / "analysis-cache.json").write_text(
        json.dumps({"repo": "owner/repo", "fix_rate": 12.5})
    )

    cache = repo_store.load_cache("owner/repo")
    assert cache["fix_rate"] == 12.5


def test_load_cache_unspecified_with_one_repo(tmp_path, monkeypatch):
    """등록 레포 1개면 무엇을 의미하는지 모호하지 않으므로 자동 선택."""
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(repo_store, "_LEGACY_CACHE", tmp_path / "legacy.json")

    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    (repos_dir / "owner__repo").mkdir()
    (repos_dir / "owner__repo" / "analysis-cache.json").write_text(
        json.dumps({"repo": "owner/repo", "fix_rate": 8.1})
    )

    cache = repo_store.load_cache(None)
    assert cache["fix_rate"] == 8.1


def test_load_cache_unspecified_with_multiple_repos_raises(tmp_path, monkeypatch):
    """등록 레포 ≥2 + repo 미지정 → ValueError (무음 오답 차단)."""
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(repo_store, "_LEGACY_CACHE", tmp_path / "legacy.json")

    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    for slug, repo in [("owner__a", "owner/a"), ("owner__b", "owner/b")]:
        (repos_dir / slug).mkdir()
        (repos_dir / slug / "analysis-cache.json").write_text(
            json.dumps({"repo": repo})
        )

    with pytest.raises(ValueError, match="여러 레포"):
        repo_store.load_cache(None)


def test_load_cache_legacy_fallback(tmp_path, monkeypatch):
    """등록 레포 0개 + legacy 캐시 존재 → legacy 사용."""
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"repo": "old/repo", "fix_rate": 99}))
    monkeypatch.setattr(repo_store, "_LEGACY_CACHE", legacy)

    cache = repo_store.load_cache(None)
    assert cache["fix_rate"] == 99


def test_load_cache_missing_repo_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(repo_store, "_LEGACY_CACHE", tmp_path / "legacy.json")
    assert repo_store.load_cache("nobody/nothing") == {}


# ── repo_data_dir create=False ────────────────────────────────────────────────

def test_repo_data_dir_create_false_does_not_mkdir(tmp_path, monkeypatch):
    """read 경로에서는 phantom 디렉토리를 만들지 않는다."""
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    p = repo_store.repo_data_dir("phantom/repo", create=False)
    assert not p.exists()


def test_repo_data_dir_create_true_does_mkdir(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_store, "REPOS_DIR", tmp_path / "repos")
    p = repo_store.repo_data_dir("real/repo", create=True)
    assert p.exists()


# ── detect_current_repo 캐싱 ──────────────────────────────────────────────────

def test_detect_current_repo_caches_result(monkeypatch):
    """동일 cwd에서 두 번째 호출은 subprocess를 안 돈다."""
    repo_store._REPO_CACHE.clear()
    call_count = [0]

    class FakeResult:
        stdout = "https://github.com/owner/repo.git\n"

    def fake_run(*args, **kwargs):
        call_count[0] += 1
        return FakeResult()

    monkeypatch.setattr(repo_store.subprocess, "run", fake_run)

    r1 = repo_store.detect_current_repo()
    r2 = repo_store.detect_current_repo()

    assert r1 == r2 == "owner/repo"
    assert call_count[0] == 1  # 두 번째는 캐시 히트
