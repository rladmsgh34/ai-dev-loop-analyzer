#!/usr/bin/env bash
#
# Production smoke test — 매 deploy 후 + 6시간 cron으로 실행.
# 목표: first-of-its-kind 런타임 버그 (회귀 분석으로는 못 잡는 종류)를 사용자보다 먼저 발견.
#
# 설계 원칙:
#   1. 빠르고 단순 (의존성 curl + jq만)
#   2. 카테고리별 다른 검증 — tracked 필수 성공, untracked 5xx만 차단 (rate limit은 정당한 4xx)
#   3. fail 시 정확히 어느 URL이 깨졌는지 한 줄로 보고
#
# 사용:
#   ./web/scripts/smoke.sh                  # 기본 prod URL
#   BASE_URL=https://other.example ./...    # 다른 environment

set -uo pipefail

BASE_URL="${BASE_URL:-https://ai-dev-loop-analyzer.rladmsgh34.org}"
FAILED=0
RESULTS=()

# Untracked repo의 정당한 4xx (rate limit, 404 등)는 fail 처리하지 않음 — 외부 제약.
# 5xx만이 우리 코드 버그 신호.
RATE_LIMIT_MSG="API 요청 한도 초과"

pass() { RESULTS+=("✅ $1"); }
warn() { RESULTS+=("⚠️  $1"); }
fail() { RESULTS+=("❌ $1"); FAILED=1; }

# 5xx response인데 body가 알려진 외부 제약(rate limit) 메시지면 warning, 그 외엔 fail.
# 현재 API는 rate limit을 500으로 매핑 — 진짜 429로 바꾸면 이 휴리스틱 제거 가능.
classify_5xx_body() {
  local label="$1" body="$2"
  if echo "$body" | grep -q "$RATE_LIMIT_MSG"; then
    warn "$label (rate limit — 알려진 외부 제약, 무시)"
  else
    fail "$label (server error: $(echo "$body" | head -c 120))"
  fi
}

# HTTP status가 정확히 expected_code인지 (homepage, static API)
check_status_eq() {
  local url="$1" expected="$2" label="$3"
  local actual
  actual=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [ "$actual" = "$expected" ]; then
    pass "$label ($actual)"
  else
    fail "$label (expected $expected, got $actual)"
  fi
}

# HTTP status가 5xx 아닌지만. 5xx면 body 보고 rate limit인지 진짜 에러인지 분류.
check_no_5xx() {
  local url="$1" label="$2"
  local status body
  status=$(curl -s -o /tmp/smoke_body -w "%{http_code}" "$url")
  body=$(cat /tmp/smoke_body)
  if [ "$status" -ge 500 ] && [ "$status" -lt 600 ]; then
    classify_5xx_body "$label ($status)" "$body"
  else
    pass "$label ($status)"
  fi
}

# JSON 응답 확인 — 200이고 .error 필드 없거나 rate limit 메시지면 OK
check_json_ok() {
  local url="$1" label="$2"
  local body status err
  status=$(curl -s -o /tmp/smoke_body -w "%{http_code}" "$url")
  body=$(cat /tmp/smoke_body)
  if [ "$status" -ge 500 ]; then
    classify_5xx_body "$label (HTTP $status)" "$body"
    return
  fi
  err=$(echo "$body" | jq -r '.error // empty' 2>/dev/null || echo "PARSE_FAIL")
  if [ "$err" = "PARSE_FAIL" ]; then
    fail "$label (response not JSON)"
  elif [ -n "$err" ] && [[ "$err" != *"$RATE_LIMIT_MSG"* ]]; then
    fail "$label (error: $err)"
  else
    pass "$label (json ok)"
  fi
}

echo "Smoke target: $BASE_URL"
echo ""

# 1. 정적 페이지 / API
check_status_eq  "$BASE_URL/"                     200 "homepage"
check_status_eq  "$BASE_URL/api/badge/stats"      200 "api/badge/stats"
check_status_eq  "$BASE_URL/api/languages"        200 "api/languages"
check_status_eq  "$BASE_URL/compare"              200 "compare page"
check_status_eq  "$BASE_URL/languages"            200 "languages page"

# 2. tracked 레포 — cache 경로, 반드시 성공해야 함
check_json_ok    "$BASE_URL/api/analyze?owner=vuejs&repo=core"      "tracked vuejs/core"
check_json_ok    "$BASE_URL/api/analyze?owner=vercel&repo=next.js"  "tracked vercel/next.js"
check_no_5xx     "$BASE_URL/r/vuejs/core"                            "page render vuejs/core"

# 3. untracked 레포 — live 경로, 5xx만 차단 (rate limit 등 4xx는 외부 제약)
# 이게 PR #38 (?i) regex 사고를 잡았을 케이스.
check_no_5xx     "$BASE_URL/api/analyze?owner=facebook&repo=react"  "untracked facebook/react api"
check_no_5xx     "$BASE_URL/r/shadcn-ui/ui"                          "untracked shadcn-ui/ui page"

# 4. badge SVG 렌더
check_status_eq  "$BASE_URL/api/badge/vuejs/core" 200 "badge vuejs/core"

echo ""
printf '%s\n' "${RESULTS[@]}"
echo ""

if [ $FAILED -ne 0 ]; then
  echo "FAIL: $(printf '%s\n' "${RESULTS[@]}" | grep -c '^❌') check(s) failed against $BASE_URL"
  exit 1
fi
echo "PASS: all $(printf '%s\n' "${RESULTS[@]}" | grep -c '^✅') checks ok"
