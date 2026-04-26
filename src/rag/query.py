#!/usr/bin/env python3
"""
ChromaDB에서 관련 패턴을 검색하고 Claude Code CLI로 규칙을 생성합니다.

사용법:
  from src.rag.query import RagEngine

  engine = RagEngine()
  rules = engine.generate_rules(domain="ci/cd", fix_rate=18.5, language="typescript")
  context = engine.get_context(query="ci/cd docker 회귀 패턴")
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CHROMA_DIR = DATA_DIR / "chroma"
EMBED_MODEL = "all-MiniLM-L6-v2"


class RagEngine:
    def __init__(self):
        if not CHROMA_DIR.exists():
            raise FileNotFoundError(
                f"ChromaDB가 없습니다. 먼저 `python3 src/rag/ingest.py` 를 실행하세요."
            )
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
        self.collection = client.get_collection("ai_dev_loop", embedding_function=ef)

    def retrieve(self, query: str, n_results: int = 5, where: Optional[dict] = None) -> list[str]:
        """쿼리와 유사한 청크를 검색합니다."""
        kwargs = {"query_texts": [query], "n_results": min(n_results, self.collection.count())}
        if where:
            kwargs["where"] = where
        results = self.collection.query(**kwargs)
        return results["documents"][0] if results["documents"] else []

    def get_context(self, query: str, n_results: int = 5) -> str:
        """쿼리 관련 컨텍스트를 자연어로 반환합니다."""
        docs = self.retrieve(query, n_results)
        return "\n".join(f"- {d}" for d in docs)

    def generate_rules(
        self,
        domain: str,
        fix_rate: float,
        language: str = "",
        extra_context: str = "",
        model: str = "claude-haiku-4-5-20251001",
        n_retrieve: int = 8,
    ) -> list[str]:
        """RAG 컨텍스트를 활용해 Claude Code CLI로 규칙을 생성합니다."""

        # 1. diff 패턴 우선 검색 — 실제 코드 변경이 가장 구체적인 컨텍스트
        diff_query = f"{domain} fix 코드 변경 패턴 {language}".strip()
        where_diff = {"type": "diff_pattern"} if self._has_diff_patterns() else None
        diff_docs = self.retrieve(diff_query, n_retrieve, where=where_diff)

        # 2. 통계/요약 검색 — diff가 없거나 부족할 때 보완
        stat_docs = self.retrieve(f"{domain} 회귀 취약 도메인 {language}".strip(), n_retrieve // 2)

        # diff 패턴을 앞에 배치 (더 구체적이므로 우선)
        all_docs = list(dict.fromkeys(diff_docs + stat_docs))[:n_retrieve]

        diff_section = ""
        stat_section = ""
        for doc in all_docs:
            if "diff:" in doc:
                diff_section += f"\n---\n{doc}"
            else:
                stat_section += f"\n  - {doc}"

        context_block = ""
        if diff_section:
            context_block += f"\n## 유사 레포의 실제 fix diff\n{diff_section}"
        if stat_section:
            context_block += f"\n## 통계 기반 패턴\n{stat_section}"
        if not context_block:
            context_block = "\n## 참고 데이터\n  (아직 수집된 데이터 없음)"

        prompt = f"""당신은 AI 코딩 어시스턴트 규칙 전문가입니다.
아래 데이터를 참고해서 CLAUDE.md에 추가할 실용적인 규칙을 생성하세요.

## 현재 상황
- 분석 대상 도메인: {domain}
- 현재 fix율: {fix_rate}%
- 언어: {language or "미지정"}
{f"- 추가 컨텍스트: {extra_context}" if extra_context else ""}
{context_block}

## 요청
위 데이터를 바탕으로 {domain} 도메인의 회귀를 줄이기 위한 CLAUDE.md 규칙을 3개 생성하세요.

요구사항:
- 각 규칙은 한 문장으로 명확하게 (구체적인 행동 지침 포함)
- diff가 있으면 그 안의 구체적인 함수명·파일명·설정값을 규칙에 반영
- 번호 없이 한 줄씩 출력

규칙만 출력하고 설명은 생략하세요."""

        return self._call_claude(prompt, model)

    def _has_diff_patterns(self) -> bool:
        """ChromaDB에 diff_pattern 타입 청크가 있는지 확인."""
        try:
            results = self.collection.get(where={"type": "diff_pattern"}, limit=1)
            return len(results["ids"]) > 0
        except Exception:
            return False

    def explain_cluster(
        self,
        domain: str,
        prs: list[dict],
        language: str = "",
        model: str = "claude-haiku-4-5-20251001",
    ) -> str:
        """회귀 클러스터를 RAG 컨텍스트로 설명합니다."""
        query = f"{domain} 회귀 클러스터 원인 패턴"
        docs = self.retrieve(query, n_results=5)
        context_text = "\n".join(f"  - {d}" for d in docs)

        pr_list = "\n".join(f"  - #{p['number']}: {p['title']}" for p in prs[:10])

        prompt = f"""다음 회귀 클러스터를 분석하고 원인과 방지책을 간단히 설명하세요.

## 클러스터 정보
- 도메인: {domain}
- PR 목록:
{pr_list}

## 유사 사례 (다른 레포에서 수집)
{context_text or "  (데이터 없음)"}

2-3문장으로 간결하게 원인과 방지책을 설명하세요."""

        results = self._call_claude(prompt, model)
        return " ".join(results) if results else ""

    def _call_claude(self, prompt: str, model: str) -> list[str]:
        """Claude Code CLI를 subprocess로 호출합니다."""
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--model", model],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                # Claude CLI 실패 시 GitHub Models API 폴백
                return self._fallback_github_models(prompt)
            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            return [l.lstrip("•-–* ") for l in lines if len(l) > 10]
        except FileNotFoundError:
            return self._fallback_github_models(prompt)
        except subprocess.TimeoutExpired:
            return []

    def _fallback_github_models(self, prompt: str) -> list[str]:
        """Claude CLI 실패 시 GitHub Models API로 폴백합니다."""
        sys.path.insert(0, str(Path(__file__).parent.parent))
        try:
            from analyze import _get_gh_token, _call_github_models
            token = _get_gh_token()
            if not token:
                return []
            return _call_github_models(prompt, token, "gpt-4o-mini")
        except Exception:
            return []

    def stats(self) -> dict:
        """ChromaDB 상태를 반환합니다."""
        total = self.collection.count()
        results = self.collection.get(include=["metadatas"])
        type_counts: dict[str, int] = {}
        for meta in results["metadatas"]:
            t = meta.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {"total_chunks": total, "by_type": type_counts}
