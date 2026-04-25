#!/usr/bin/env python3
"""
규칙 효과 측정 트래커.

규칙이 CLAUDE.md에 추가된 날짜를 기록하고,
이후 도메인별 fix-rate 변화를 스냅샷으로 누적해
"이 규칙이 실제로 회귀를 줄였는가"를 측정한다.
"""

import json
import hashlib
import re
from pathlib import Path

HISTORY_FILE = Path(__file__).parent.parent / "data" / "rules-history.json"

# 규칙 텍스트에서 도메인 힌트를 추출하는 패턴
_DOMAIN_HINTS = [
    ("ci/cd",        r"CI/CD|Docker|deploy|dockerfile|healthcheck|compose|buildx"),
    ("auth",         r"인증|auth|login|session|signin|credential"),
    ("payment",      r"결제|payment|portone|checkout|order"),
    ("database",     r"Prisma|schema|migration|DB"),
    ("security",     r"CSP|XSS|rate.limit|sanitize|allowlist"),
    ("external-api", r"Kakao|PortOne|GCS|외부.API"),
    ("test/e2e",     r"E2E|테스트|playwright|vitest|coverage|standalone"),
    ("config",       r"next\.config|env\.ts|tsconfig|biome"),
    ("api",          r"API Route|route\.ts"),
    ("ui",           r"컴포넌트|component|page\.tsx"),
]


def _rule_id(rule: str) -> str:
    return hashlib.md5(rule.strip().encode()).hexdigest()[:8]


def _infer_domain(rule: str) -> str:
    """규칙 텍스트에서 도메인을 추론. 매칭 없으면 'general'."""
    for domain, pattern in _DOMAIN_HINTS:
        if re.search(pattern, rule, re.I):
            return domain
    return "general"


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"rules": [], "snapshots": []}


def save_history(history: dict) -> None:
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def record_new_rules(
    rules: list[str],
    domain_fix_rates: dict[str, float],
    total_fix_rate: float,
    date: str,
) -> list[str]:
    """
    새 규칙을 히스토리에 등록.
    이미 존재하는 규칙은 건너뜀.
    반환: 새로 등록된 rule_id 목록
    """
    history = load_history()
    existing_ids = {r["id"] for r in history["rules"]}
    added = []

    for rule in rules:
        rid = _rule_id(rule)
        if rid in existing_ids:
            continue
        domain = _infer_domain(rule)
        history["rules"].append({
            "id": rid,
            "rule": rule,
            "domain": domain,
            "date_added": date,
            "fix_rate_at_add": {
                "total": total_fix_rate,
                **domain_fix_rates,
            },
            "snapshots": [],
        })
        added.append(rid)

    save_history(history)
    return added


def record_snapshot(
    domain_fix_rates: dict[str, float],
    total_fix_rate: float,
    date: str,
) -> None:
    """매일 현재 fix-rate를 모든 활성 규칙의 스냅샷으로 기록"""
    history = load_history()

    history.setdefault("snapshots", []).append({
        "date": date,
        "total_fix_rate": total_fix_rate,
        **domain_fix_rates,
    })
    # 중복 날짜 제거 (가장 최신만 유지)
    seen = {}
    for s in history["snapshots"]:
        seen[s["date"]] = s
    history["snapshots"] = list(seen.values())

    for rule in history["rules"]:
        rule.setdefault("snapshots", []).append({
            "date": date,
            "total": total_fix_rate,
            **domain_fix_rates,
        })
        rule["snapshots"] = rule["snapshots"][-180:]

    save_history(history)


def compute_effectiveness(min_days: int = 7) -> list[dict]:
    """
    규칙 추가 전후 fix-rate 비교.
    규칙에 도메인이 있으면 해당 도메인 fix-rate 변화를 사용.
    도메인 데이터가 없으면 전체 fix-rate로 폴백.
    min_days 이상 경과된 규칙만 평가.
    """
    history = load_history()
    results = []

    for rule in history["rules"]:
        snapshots = rule.get("snapshots", [])
        if len(snapshots) < min_days:
            continue

        at_add = rule["fix_rate_at_add"]
        domain = rule.get("domain", "general")
        recent = snapshots[-7:]

        # 도메인별 fix-rate가 스냅샷에 있으면 우선 사용
        if domain != "general" and domain in at_add and all(domain in s for s in recent):
            before = at_add[domain]
            after = round(sum(s[domain] for s in recent) / len(recent), 1)
            scope = f"도메인({domain})"
        else:
            before = at_add.get("total", 0)
            after = round(sum(s.get("total", 0) for s in recent) / len(recent), 1)
            scope = "전체"

        delta = round(after - before, 1)
        results.append({
            "rule": rule["rule"][:80],
            "domain": domain,
            "scope": scope,
            "date_added": rule["date_added"],
            "fix_rate_at_add": before,
            "fix_rate_recent": after,
            "delta": delta,
            "effective": delta < 0,
        })

    return sorted(results, key=lambda x: x["delta"])


def effectiveness_summary() -> str:
    results = compute_effectiveness()
    if not results:
        return "아직 측정 가능한 데이터 없음 (규칙 추가 후 최소 7일 필요)"

    lines = ["### 📈 규칙 효과 측정"]
    for r in results:
        sign = "▼" if r["effective"] else "▲"
        label = "개선" if r["effective"] else "미변화"
        delta_str = f"{sign} {abs(r['delta'])}%p ({label}, {r['scope']} 기준)"
        lines.append(
            f"- **{r['date_added']}** 추가 | "
            f"fix율 {r['fix_rate_at_add']}% → {r['fix_rate_recent']}% {delta_str}\n"
            f"  규칙: {r['rule']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(effectiveness_summary())
