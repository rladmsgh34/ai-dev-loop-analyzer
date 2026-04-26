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
    repo: str | None = None,
    origin_confidence: str = "explicit",
) -> list[str]:
    """
    새 규칙을 히스토리에 등록.
    이미 존재하는 규칙은 건너뜀.

    repo: 이 규칙이 induce된 레포 (owner/repo). 새 rule은 항상 explicit fact로 기록.
          None이면 'unknown' (legacy / single-repo 호출자 호환).
    origin_confidence: 'explicit'(분석 시점 fact) | 'inferred'(휴리스틱) | 'unknown'.

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
            "origin_repo": repo or "unknown",
            "origin_confidence": origin_confidence if repo else "unknown",
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
    repo: str | None = None,
) -> None:
    """매일 현재 fix-rate를 모든 활성 규칙의 스냅샷으로 기록.

    repo: 이 스냅샷이 어느 레포 분석에서 나왔는지 (owner/repo). efficacy 계산에서
          rule.origin_repo와 매칭되는 snapshot만 골라야 confounding이 제거됨.
    """
    history = load_history()

    history.setdefault("snapshots", []).append({
        "date": date,
        "repo": repo or "unknown",
        "total_fix_rate": total_fix_rate,
        **domain_fix_rates,
    })
    # 중복 (date, repo) 제거 — 같은 날 같은 레포는 가장 최신만 유지
    seen = {}
    for s in history["snapshots"]:
        seen[(s["date"], s.get("repo", "unknown"))] = s
    history["snapshots"] = list(seen.values())

    for rule in history["rules"]:
        # rule이 이 레포에서 induce된 경우에만 snapshot 누적 — cross-repo pollution 차단.
        # origin_repo 미지정인 legacy rule은 모든 snapshot 받음 (best-effort 후방 호환).
        rule_origin = rule.get("origin_repo", "unknown")
        if repo and rule_origin not in ("unknown", repo):
            continue
        rule.setdefault("snapshots", []).append({
            "date": date,
            "repo": repo or "unknown",
            "total": total_fix_rate,
            **domain_fix_rates,
        })
        rule["snapshots"] = rule["snapshots"][-180:]

    save_history(history)


def compute_effectiveness(
    min_days: int = 7,
    repo: str | None = None,
    include_self: bool = False,
    include_inferred: bool = True,
) -> list[dict]:
    """
    규칙 추가 전후 fix-rate 비교.
    규칙에 도메인이 있으면 해당 도메인 fix-rate 변화를 사용.
    도메인 데이터가 없으면 전체 fix-rate로 폴백.
    min_days 이상 경과된 규칙만 평가.

    repo: 특정 레포 origin rule만 보려면 'owner/repo'. None이면 전부.
    include_self: analyzer 자기 자신에서 induce된 self-referential rule 포함 여부 (기본 제외).
                  self-rule efficacy는 분석 도구가 자기 자신을 분석한 결과로 측정되므로
                  재귀 구조 신뢰도 문제. 별도 트랙으로 봐야 함.
    include_inferred: 휴리스틱으로 origin 추정한 rule 포함 여부 (기본 포함).
                      엄격한 baseline이 필요하면 False로 explicit만 사용.
    """
    history = load_history()
    results = []

    for rule in history["rules"]:
        # origin 필터
        rule_origin = rule.get("origin_repo", "unknown")
        rule_conf = rule.get("origin_confidence", "unknown")
        if not include_self and rule_origin == "self":
            continue
        if not include_inferred and rule_conf == "inferred":
            continue
        if repo and rule_origin != repo:
            continue

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
            "origin_repo": rule_origin,
            "origin_confidence": rule_conf,
            "scope": scope,
            "date_added": rule["date_added"],
            "fix_rate_at_add": before,
            "fix_rate_recent": after,
            "delta": delta,
            "effective": delta < 0,
        })

    return sorted(results, key=lambda x: x["delta"])


def effectiveness_summary(
    repo: str | None = None,
    include_self: bool = False,
    include_inferred: bool = True,
) -> str:
    results = compute_effectiveness(
        repo=repo, include_self=include_self, include_inferred=include_inferred
    )
    if not results:
        scope_desc = f" for {repo}" if repo else ""
        return f"아직 측정 가능한 데이터 없음{scope_desc} (규칙 추가 후 최소 7일 필요)"

    lines = ["### 📈 규칙 효과 측정 (living document — 데이터 누적과 함께 정확도 상승)"]
    if repo:
        lines.append(f"_repo filter: {repo}_")
    for r in results:
        sign = "▼" if r["effective"] else "▲"
        label = "개선" if r["effective"] else "미변화"
        delta_str = f"{sign} {abs(r['delta'])}%p ({label}, {r['scope']} 기준)"
        conf_marker = "" if r["origin_confidence"] == "explicit" else f" _[{r['origin_confidence']}]_"
        lines.append(
            f"- **{r['date_added']}** | origin: `{r['origin_repo']}`{conf_marker} | "
            f"fix율 {r['fix_rate_at_add']}% → {r['fix_rate_recent']}% {delta_str}\n"
            f"  규칙: {r['rule']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=None, help="filter by origin_repo (owner/repo)")
    p.add_argument("--include-self", action="store_true",
                   help="include self-referential analyzer rules (excluded by default)")
    p.add_argument("--strict", action="store_true",
                   help="exclude inferred-origin rules; explicit only")
    args = p.parse_args()
    print(effectiveness_summary(
        repo=args.repo,
        include_self=args.include_self,
        include_inferred=not args.strict,
    ))
