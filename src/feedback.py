#!/usr/bin/env python3
"""
경고 피드백 루프 — rag_hook.py 경고가 실제 회귀를 예측했는지 측정.

흐름:
  1. rag_hook.py가 경고 발생 시 warning-log.jsonl에 기록
  2. evolve-rules.yml 실행 시 evaluate()로 warning-log와 fix PR 교차 검증
  3. 결과를 feedback-stats.json에 저장 (MCP / 리포트에 노출)

피드백 판정 기준:
  - TRUE_POSITIVE:  경고 후 14일 이내 같은 파일/도메인에 fix PR 등장
  - FALSE_POSITIVE: 경고 후 14일 경과 후에도 fix PR 없음 (확정 오탐)
  - PENDING:        14일 미경과 (아직 판정 불가)
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
WARNING_LOG = DATA_DIR / "warning-log.jsonl"
FEEDBACK_STATS = DATA_DIR / "feedback-stats.json"

_VERDICT_WINDOW_DAYS = 14


def record_warning(
    file_path: str,
    bm25_score: float,
    matched_id: str,
    matched_header: str,
) -> None:
    """경고 발생 시 즉시 호출 — warning-log.jsonl에 한 줄 append."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "file": file_path,
        "score": round(bm25_score, 3),
        "matched_id": matched_id,
        "matched_header": matched_header,
        "verdict": "PENDING",
    }
    DATA_DIR.mkdir(exist_ok=True)
    with WARNING_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_warnings() -> list[dict]:
    if not WARNING_LOG.exists():
        return []
    warnings = []
    for line in WARNING_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                warnings.append(json.loads(line))
            except Exception:
                pass
    return warnings


def _save_warnings(warnings: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with WARNING_LOG.open("w", encoding="utf-8") as f:
        for w in warnings:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")


def evaluate(fix_prs: list[dict]) -> dict:
    """
    warning-log와 fix PR 목록을 교차 검증해 verdict를 갱신하고
    정확도 통계를 반환한다.

    fix_prs 항목 형식: {"files": [...], "domain": "...", "merged_at": "ISO8601", "title": "..."}
    """
    warnings = _load_warnings()
    now = datetime.now(timezone.utc)
    cutoff = timedelta(days=_VERDICT_WINDOW_DAYS)

    for w in warnings:
        if w.get("verdict") != "PENDING":
            continue

        try:
            warned_at = datetime.fromisoformat(w["ts"].replace("Z", "+00:00"))
        except Exception:
            continue

        elapsed = now - warned_at

        # fix PR과 교차 검증: 경고 이후 머지된 fix PR이 같은 파일/도메인을 건드렸는가
        matched_fix = False
        for pr in fix_prs:
            try:
                pr_merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            if pr_merged < warned_at:
                continue

            # 파일 경로 일치: 경고 파일이 fix PR 변경 파일 중 하나인지
            warn_file = w.get("file", "")
            pr_files = pr.get("files", [])
            file_hit = any(
                warn_file.endswith(f) or f.endswith(warn_file)
                for f in pr_files
            )

            # 도메인 일치: matched_id가 도메인 접두사를 포함하는지 (휴리스틱)
            matched_id = w.get("matched_id", "")
            pr_domain = pr.get("domain", "")
            domain_hint = _extract_domain_from_id(matched_id)
            domain_hit = domain_hint and domain_hint == pr_domain

            if file_hit or domain_hit:
                matched_fix = True
                break

        if matched_fix:
            w["verdict"] = "TRUE_POSITIVE"
        elif elapsed > cutoff:
            w["verdict"] = "FALSE_POSITIVE"
        # else: 아직 PENDING 유지

    _save_warnings(warnings)

    # 통계 집계
    total = len(warnings)
    tp = sum(1 for w in warnings if w["verdict"] == "TRUE_POSITIVE")
    fp = sum(1 for w in warnings if w["verdict"] == "FALSE_POSITIVE")
    pending = sum(1 for w in warnings if w["verdict"] == "PENDING")
    judged = tp + fp

    precision = round(tp / judged * 100, 1) if judged else None

    # 도메인별 분류
    domain_stats: dict[str, dict] = {}
    for w in warnings:
        d = _extract_domain_from_id(w.get("matched_id", "")) or "unknown"
        s = domain_stats.setdefault(d, {"tp": 0, "fp": 0, "pending": 0})
        s[w["verdict"].lower() if w["verdict"] != "PENDING" else "pending"] += 1

    # 오탐이 많은 도메인 (threshold 조정 후보)
    noisy_domains = [
        d for d, s in domain_stats.items()
        if s["fp"] > s["tp"] and s["fp"] >= 2
    ]

    stats = {
        "updated_at": now.isoformat(),
        "total_warnings": total,
        "true_positives": tp,
        "false_positives": fp,
        "pending": pending,
        "precision_pct": precision,
        "domain_stats": domain_stats,
        "noisy_domains": noisy_domains,
        "threshold_suggestion": _suggest_threshold(warnings),
    }

    FEEDBACK_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


def _extract_domain_from_id(matched_id: str) -> str:
    """diff_repo_N 형태의 ID에서 도메인 힌트를 추출한다 (휴리스틱)."""
    domain_keywords = [
        "auth", "payment", "database", "ci", "cd", "security",
        "api", "ui", "config", "test", "maintenance", "docs",
    ]
    lower = matched_id.lower()
    for kw in domain_keywords:
        if kw in lower:
            return kw
    return ""


def _suggest_threshold(warnings: list[dict]) -> dict | None:
    """
    FALSE_POSITIVE가 많은 경우 BM25 임계값을 높이도록 제안.
    점수 분포를 분석해 TP와 FP의 경계 점수를 추정.
    """
    tp_scores = [w["score"] for w in warnings if w["verdict"] == "TRUE_POSITIVE"]
    fp_scores = [w["score"] for w in warnings if w["verdict"] == "FALSE_POSITIVE"]

    if len(tp_scores) < 3 or len(fp_scores) < 3:
        return None

    tp_min = min(tp_scores)
    fp_max = max(fp_scores)

    if fp_max < tp_min:
        # TP와 FP가 완전히 분리된 이상적 케이스 → 현재 임계값 유지
        return {"action": "keep", "reason": f"TP/FP 점수가 완전 분리 (FP max {fp_max:.2f} < TP min {tp_min:.2f})"}

    # 겹치는 경우 → TP 최솟값을 새 임계값으로 제안
    suggested = round(tp_min, 1)
    return {
        "action": "raise",
        "current": 1.5,
        "suggested": suggested,
        "reason": f"FP max({fp_max:.2f})가 TP min({tp_min:.2f})과 겹침",
    }


def feedback_report() -> str:
    """MCP / CLI에서 출력할 피드백 요약 문자열."""
    if not FEEDBACK_STATS.exists():
        return "피드백 데이터 없음 — evolve-rules 워크플로우 실행 후 생성됩니다."

    s = json.loads(FEEDBACK_STATS.read_text())
    precision = s.get("precision_pct")
    prec_str = f"{precision}%" if precision is not None else "측정 중"

    lines = [
        f"### 🎯 경고 피드백 통계 (갱신: {s.get('updated_at', '?')[:10]})",
        f"- 전체 경고: {s['total_warnings']}건",
        f"- 진짜 회귀 예측 (TP): {s['true_positives']}건",
        f"- 오탐 (FP): {s['false_positives']}건",
        f"- 판정 대기: {s['pending']}건",
        f"- **정밀도(Precision): {prec_str}**",
    ]

    if s.get("noisy_domains"):
        lines.append(f"- 오탐 많은 도메인: {', '.join(s['noisy_domains'])}")

    suggestion = s.get("threshold_suggestion")
    if suggestion and suggestion.get("action") == "raise":
        lines.append(
            f"- ⚙️  임계값 조정 제안: {suggestion['current']} → {suggestion['suggested']} "
            f"({suggestion['reason']})"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print(feedback_report())
