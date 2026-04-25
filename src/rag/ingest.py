#!/usr/bin/env python3
"""
수집된 데이터를 청크로 변환해 ChromaDB에 임베딩 저장합니다.

실행:
  python3 src/rag/ingest.py           # 전체 재인제스트
  python3 src/rag/ingest.py --append  # 새 데이터만 추가
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CHROMA_DIR = DATA_DIR / "chroma"

EMBED_MODEL = "all-MiniLM-L6-v2"  # 90MB, CPU 동작, 다국어 지원


def get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    return client.get_or_create_collection(
        name="ai_dev_loop",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def load_language_patterns() -> list[dict]:
    """language-patterns.json → 청크 리스트"""
    path = DATA_DIR / "language-patterns.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    chunks = []

    for lang, stats in data.get("languages", {}).items():
        # 언어별 요약 청크
        top = ", ".join(stats["top_domains"][:3])
        chunks.append({
            "id": f"lang_{lang}_summary",
            "text": (
                f"{lang} 오픈소스 레포 {stats['repos_analyzed']}개 분석 결과: "
                f"평균 fix율 {stats['avg_fix_rate']}%, "
                f"평균 회귀 클러스터 {stats['avg_clusters']}개. "
                f"가장 취약한 도메인: {top}. "
                f"대표 레포: {', '.join(stats['sample_repos'][:3])}."
            ),
            "metadata": {
                "type": "language_summary",
                "language": lang,
                "avg_fix_rate": stats["avg_fix_rate"],
                "repos_analyzed": stats["repos_analyzed"],
                "top_domain": stats["top_domains"][0] if stats["top_domains"] else "",
                "date": data.get("updated_at", ""),
            },
        })

        # 도메인별 상세 청크
        for domain, rate in stats.get("domain_avg_fix_rates", {}).items():
            chunks.append({
                "id": f"lang_{lang}_domain_{domain}",
                "text": (
                    f"{lang} 레포에서 {domain} 도메인의 평균 fix율은 {rate}%입니다. "
                    f"({stats['repos_analyzed']}개 레포 기준)"
                ),
                "metadata": {
                    "type": "domain_rate",
                    "language": lang,
                    "domain": domain,
                    "fix_rate": rate,
                    "date": data.get("updated_at", ""),
                },
            })

    # 개별 레포 결과 청크
    for r in data.get("repo_results", []):
        top_domain = max(r.get("domain_fix_rates", {}).items(),
                         key=lambda x: x[1].get("fix_count", 0),
                         default=("unknown", {}))[0]
        chunks.append({
            "id": f"repo_{r['owner']}_{r['repo']}",
            "text": (
                f"{r['owner']}/{r['repo']} ({r.get('language', 'unknown')}, "
                f"⭐{r.get('stars', 0):,}): "
                f"총 {r['total_prs']}개 PR, fix율 {r['fix_rate']}%, "
                f"회귀 클러스터 {r.get('cluster_count', 0)}개. "
                f"가장 취약한 도메인: {top_domain}."
            ),
            "metadata": {
                "type": "repo_result",
                "language": r.get("language", ""),
                "fix_rate": r["fix_rate"],
                "top_domain": top_domain,
                "repo": f"{r['owner']}/{r['repo']}",
                "date": "",
            },
        })

    return chunks


def load_rules_history() -> list[dict]:
    """rules-history.json → 청크 리스트"""
    path = DATA_DIR / "rules-history.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    chunks = []

    for entry in data.get("rules", []):
        for rule in entry.get("rules", []):
            rid = f"rule_{entry.get('date', 'unknown')}_{abs(hash(rule)) % 100000}"
            chunks.append({
                "id": rid,
                "text": (
                    f"[{entry.get('date', '')}] AI 규칙 추가: {rule} "
                    f"(추가 당시 전체 fix율: {entry.get('total_fix_rate', '?')}%)"
                ),
                "metadata": {
                    "type": "rule",
                    "date": entry.get("date", ""),
                    "fix_rate_at_add": entry.get("total_fix_rate", 0),
                },
            })

    for snap in data.get("snapshots", []):
        top = sorted(
            snap.get("domain_fix_rates", {}).items(),
            key=lambda x: -x[1]
        )[:3]
        top_text = ", ".join(f"{d}({r}%)" for d, r in top)
        chunks.append({
            "id": f"snapshot_{snap.get('date', 'unknown')}",
            "text": (
                f"[{snap.get('date', '')}] 스냅샷: "
                f"전체 fix율 {snap.get('total_fix_rate', '?')}%. "
                f"상위 도메인: {top_text}."
            ),
            "metadata": {
                "type": "snapshot",
                "date": snap.get("date", ""),
                "total_fix_rate": snap.get("total_fix_rate", 0),
            },
        })

    return chunks


def load_analysis_cache() -> list[dict]:
    """analysis-cache.json → 청크 리스트"""
    path = DATA_DIR / "analysis-cache.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []

    chunks = []
    summary = data.get("summary", {})
    if summary:
        chunks.append({
            "id": "cache_summary",
            "text": (
                f"gwangcheon-shop 최신 분석: "
                f"총 PR {summary.get('total_prs', '?')}개, "
                f"fix PR {summary.get('fix_prs', '?')}개, "
                f"fix율 {summary.get('fix_rate', '?')}%."
            ),
            "metadata": {
                "type": "project_summary",
                "repo": "gwangcheon-shop",
                "fix_rate": summary.get("fix_rate", 0),
                "date": data.get("analyzed_at", ""),
            },
        })

    for cluster in data.get("clusters", []):
        chunks.append({
            "id": f"cache_cluster_{cluster.get('start', 0)}_{cluster.get('end', 0)}",
            "text": (
                f"gwangcheon-shop 회귀 클러스터: "
                f"{cluster.get('domain', 'unknown')} 도메인에서 "
                f"#{cluster.get('start')} ~ #{cluster.get('end')} "
                f"({cluster.get('size', '?')}개 연속 fix PR)."
            ),
            "metadata": {
                "type": "cluster",
                "domain": cluster.get("domain", ""),
                "repo": "gwangcheon-shop",
                "date": data.get("analyzed_at", ""),
            },
        })

    return chunks


def ingest(append: bool = False):
    collection = get_collection()

    if not append:
        # 전체 재구축
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        client.delete_collection("ai_dev_loop")
        ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
        collection = client.create_collection(
            name="ai_dev_loop",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        print("🗑️  기존 컬렉션 삭제 후 재구축")

    existing_ids = set(collection.get(include=[])["ids"]) if append else set()

    all_chunks: list[dict] = []
    all_chunks.extend(load_language_patterns())
    all_chunks.extend(load_rules_history())
    all_chunks.extend(load_analysis_cache())

    new_chunks = [c for c in all_chunks if c["id"] not in existing_ids]

    if not new_chunks:
        print("✅ 추가할 새 청크 없음")
        return

    print(f"📥 {len(new_chunks)}개 청크 임베딩 중...")
    batch_size = 100
    for i in range(0, len(new_chunks), batch_size):
        batch = new_chunks[i:i + batch_size]
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        print(f"   {min(i + batch_size, len(new_chunks))}/{len(new_chunks)}")

    total = collection.count()
    print(f"✅ 완료 — ChromaDB 총 {total}개 청크 저장됨")
    print(f"   경로: {CHROMA_DIR}")


def main():
    parser = argparse.ArgumentParser(description="데이터를 ChromaDB에 인제스트합니다")
    parser.add_argument("--append", action="store_true", help="기존 데이터 유지하고 새 항목만 추가")
    args = parser.parse_args()
    ingest(append=args.append)


if __name__ == "__main__":
    main()
