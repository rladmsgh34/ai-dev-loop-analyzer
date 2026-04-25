#!/bin/bash
# RAG 동기화 스크립트 — VM 크론에서 실행
# crontab: 0 12 * * 0 /home/rladmsgh34/ai-dev-loop-analyzer/scripts/rag-sync.sh

set -e
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO_DIR/data/rag-sync.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] RAG 동기화 시작" >> "$LOG"

# 최신 데이터 pull
cd "$REPO_DIR"
git pull origin main >> "$LOG" 2>&1

# ChromaDB 재인제스트 (새 데이터만 추가)
python3 src/rag/ingest.py --append >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] RAG 동기화 완료" >> "$LOG"
