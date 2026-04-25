#!/usr/bin/env python3
"""
CLAUDE.md 패치 생성기.

분석 결과에서 신규 규칙만 추출해 대상 레포의 CLAUDE.md에
'## 🤖 AI Dev Loop 자동 규칙' 섹션을 생성/업데이트한다.
"""

import json
import re
import sys

SECTION_HEADER = "## 🤖 AI Dev Loop 자동 규칙"
SECTION_FOOTER = "<!-- /ai-dev-loop -->"


def load_existing_rules(claude_md: str) -> set[str]:
    """CLAUDE.md 전체 텍스트에서 이미 존재하는 규칙 키워드 추출"""
    keywords: set[str] = set()
    for line in claude_md.splitlines():
        # 한글/영문 단어 2자 이상 추출
        words = re.findall(r'[가-힣a-zA-Z]{2,}', line)
        keywords.update(w.lower() for w in words)
    return keywords


def is_duplicate(rule: str, existing_keywords: set[str]) -> bool:
    """규칙의 핵심 키워드가 이미 CLAUDE.md에 있으면 중복으로 판정"""
    words = re.findall(r'[가-힣a-zA-Z]{3,}', rule)
    if not words:
        return False
    # 핵심 단어 3개 이상이 이미 존재하면 중복
    matches = sum(1 for w in words if w.lower() in existing_keywords)
    return matches >= min(3, len(words))


def build_section(rules: list[str], date: str, fix_rate: float) -> str:
    lines = [
        SECTION_HEADER,
        f"> 자동 생성: [ai-dev-loop-analyzer](https://github.com/rladmsgh34/ai-dev-loop-analyzer) | {date} | fix율 {fix_rate}%",
        "",
    ]
    for rule in rules:
        lines.append(rule)
    lines.append("")
    lines.append(SECTION_FOOTER)
    return "\n".join(lines)


def patch(claude_md: str, new_rules: list[str], date: str, fix_rate: float) -> tuple[str, list[str]]:
    """
    CLAUDE.md에 신규 규칙 섹션을 삽입/갱신한다.
    반환: (수정된 전체 텍스트, 실제로 추가된 규칙 목록)
    """
    existing_keywords = load_existing_rules(claude_md)
    fresh_rules = [r for r in new_rules if not is_duplicate(r, existing_keywords)]

    if not fresh_rules:
        return claude_md, []

    new_section = build_section(fresh_rules, date, fix_rate)

    # 기존 섹션 교체
    pattern = re.compile(
        rf"{re.escape(SECTION_HEADER)}.*?{re.escape(SECTION_FOOTER)}",
        re.DOTALL,
    )
    if pattern.search(claude_md):
        updated = pattern.sub(new_section, claude_md)
    else:
        # 파일 끝에 추가
        updated = claude_md.rstrip() + "\n\n" + new_section + "\n"

    return updated, fresh_rules


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, help="분석 결과 JSON 경로")
    parser.add_argument("--claude-md", required=True, help="CLAUDE.md 파일 경로")
    parser.add_argument("--date", required=True, help="날짜 문자열 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="변경 내용만 출력")
    args = parser.parse_args()

    report = json.load(open(args.report))
    rules = report.get("claude_md_suggestions", [])
    fix_rate = report["summary"]["fix_rate"]

    with open(args.claude_md) as f:
        original = f.read()

    patched, added = patch(original, rules, args.date, fix_rate)

    if not added:
        print("신규 규칙 없음 — CLAUDE.md 변경 불필요")
        sys.exit(0)

    print(f"신규 규칙 {len(added)}개:")
    for r in added:
        print(f"  {r}")

    if args.dry_run:
        print("\n--- CLAUDE.md diff (dry-run) ---")
        import difflib
        diff = difflib.unified_diff(
            original.splitlines(), patched.splitlines(),
            fromfile="CLAUDE.md (before)", tofile="CLAUDE.md (after)", lineterm=""
        )
        print("\n".join(diff))
    else:
        with open(args.claude_md, "w") as f:
            f.write(patched)
        print("CLAUDE.md 업데이트 완료")
