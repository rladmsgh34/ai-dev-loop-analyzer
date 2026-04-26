#!/usr/bin/env python3
"""
경고 피드백 루프 — rag_hook.py 경고가 실제 회귀를 예측했는지 측정.

흐름:
  1. rag_hook.py가 경고 발생 시 레포별 warning-log.jsonl에 기록
  2. evolve-rules.yml 실행 시 evaluate()로 warning-log와 fix PR 교차 검증
  3. 결과를 레포별 feedback-stats.json에 저장 (MCP / 리포트에 노출)

피드백 판정 기준:
  - TRUE_POSITIVE:  경고 후 14일 이내 같은 파일/도메인에 fix PR 등장
  - FALSE_POSITIVE: 경고 후 14일 경과 후에도 fix PR 없음 (확정 오탐)
  - PENDING:        14일 미경과 (아직 판정 불가)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_store import (
    detect_current_repo,
    warning_log_path,
    feedback_stats_path,
    repo_data_dir,
)

_VERDICT_WINDOW_DAYS = 14


def _resolve_repo(repo: str | None) -> str | None:
    """repo 파라미터가 없으면 환경변수 → git remote 순으로 자동 감지."""
    return repo or os.environ.get("AI_DEV_LOOP_REPO") or detect_current_repo()


def record_warning(
    file_path: str,
    bm25_score: float,
    matched_id: str,
    matched_header: str,
    repo: str | None = None,
) -> None:
    """경고 발생 시 즉시 호출 — 레포별 warning-log.jsonl에 한 줄 append."""
    resolved = _resolve_repo(repo)
    if not resolved:
        return  # 레포를 특정할 수 없으면 로깅 생략

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "file": file_path,
        "score": round(bm25_score, 3),
        "matched_id": matched_id,
        "matched_header": matched_header,
        "verdict": "PENDING",
    }
    log_path = warning_log_path(resolved)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_warnings(repo: str) -> list[dict]:
    log_path = warning_log_path(repo)
    if not log_path.exists():
        return []
    warnings = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                warnings.append(json.loads(line))
            except Exception:
                pass
    return warnings


def _save_warnings(repo: str, warnings: list[dict]) -> None:
    log_path = warning_log_path(repo)
    with log_path.open("w", encoding="utf-8") as f:
        for w in warnings:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")


def evaluate(fix_prs: list[dict], repo: str | None = None) -> dict:
    """
    레포별 warning-log와 fix PR 목록을 교차 검증해 verdict를 갱신하고
    정확도 통계를 반환한다.

    fix_prs 항목 형식: {"files": [...], "domain": "...", "merged_at": "ISO8601", "title": "..."}
    """
    resolved = _resolve_repo(repo)
    if not resolved:
        return {}

    warnings = _load_warnings(resolved)
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
        matched_fix = False

        for pr in fix_prs:
            try:
                pr_merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            if pr_merged < warned_at:
                continue

            warn_file = w.get("file", "")
            pr_files = pr.get("files", [])
            file_hit = any(
                warn_file.endswith(f) or f.endswith(warn_file) for f in pr_files
            )

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

    _save_warnings(resolved, warnings)

    total = len(warnings)
    tp = sum(1 for w in warnings if w["verdict"] == "TRUE_POSITIVE")
    fp = sum(1 for w in warnings if w["verdict"] == "FALSE_POSITIVE")
    pending = sum(1 for w in warnings if w["verdict"] == "PENDING")
    judged = tp + fp
    precision = round(tp / judged * 100, 1) if judged else None

    domain_stats: dict[str, dict] = {}
    for w in warnings:
        d = _extract_domain_from_id(w.get("matched_id", "")) or "unknown"
        s = domain_stats.setdefault(d, {"tp": 0, "fp": 0, "pending": 0})
        s[w["verdict"].lower() if w["verdict"] != "PENDING" else "pending"] += 1

    noisy_domains = [
        d for d, s in domain_stats.items()
        if s["fp"] > s["tp"] and s["fp"] >= 2
    ]

    stats = {
        "updated_at": now.isoformat(),
        "repo": resolved,
        "total_warnings": total,
        "true_positives": tp,
        "false_positives": fp,
        "pending": pending,
        "precision_pct": precision,
        "domain_stats": domain_stats,
        "noisy_domains": noisy_domains,
        "threshold_suggestion": _suggest_threshold(warnings),
    }

    feedback_stats_path(resolved).write_text(
        json.dumps(stats, ensure_ascii=False, indent=2)
    )
    return stats


def _extract_domain_from_id(matched_id: str) -> str:
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
    tp_scores = [w["score"] for w in warnings if w["verdict"] == "TRUE_POSITIVE"]
    fp_scores = [w["score"] for w in warnings if w["verdict"] == "FALSE_POSITIVE"]

    if len(tp_scores) < 3 or len(fp_scores) < 3:
        return None

    tp_min = min(tp_scores)
    fp_max = max(fp_scores)

    if fp_max < tp_min:
        return {
            "action": "keep",
            "reason": f"TP/FP 점수 완전 분리 (FP max {fp_max:.2f} < TP min {tp_min:.2f})",
        }

    suggested = round(tp_min, 1)
    return {
        "action": "raise",
        "current": 1.5,
        "suggested": suggested,
        "reason": f"FP max({fp_max:.2f})가 TP min({tp_min:.2f})과 겹침",
    }


def feedback_report(repo: str | None = None) -> str:
    """MCP / CLI에서 출력할 피드백 요약 문자열."""
    from repo_store import list_registered_repos, feedback_stats_path as fsp

    resolved = _resolve_repo(repo)

    # 단일 레포 지정
    if resolved:
        p = fsp(resolved)
        if not p.exists():
            return f"[{resolved}] 피드백 데이터 없음 — evolve-rules 실행 후 생성됩니다."
        return _format_stats(json.loads(p.read_text()))

    # 전체 레포 요약
    repos = list_registered_repos()
    if not repos:
        return "등록된 레포 없음 — analyze_pr_history를 먼저 실행하세요."

    lines = ["## 전체 레포 경고 정밀도 요약\n"]
    for r in repos:
        p = fsp(r)
        if p.exists():
            s = json.loads(p.read_text())
            prec = s.get("precision_pct")
            prec_str = f"{prec}%" if prec is not None else "측정 중"
            lines.append(
                f"- **{r}**: TP {s['true_positives']} / FP {s['false_positives']} "
                f"/ 대기 {s['pending']} | 정밀도 {prec_str}"
            )
        else:
            lines.append(f"- **{r}**: 피드백 데이터 없음")
    return "\n".join(lines)


def _format_stats(s: dict) -> str:
    precision = s.get("precision_pct")
    prec_str = f"{precision}%" if precision is not None else "측정 중"
    repo = s.get("repo", "?")

    lines = [
        f"### 🎯 [{repo}] 경고 피드백 통계 (갱신: {s.get('updated_at', '?')[:10]})",
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
