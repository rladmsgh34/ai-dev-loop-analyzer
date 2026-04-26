# AI Dev Loop Analyzer

[![patterns learned](https://ai-dev-loop-analyzer.rladmsgh34.org/api/badge/stats)](https://ai-dev-loop-analyzer.rladmsgh34.org/languages)

> PR 히스토리에서 회귀 패턴을 감지하고, AI 코딩 어시스턴트(Claude Code 등)의 규칙을 자동으로 제안합니다.

AI-assisted development에서 같은 실수가 반복되는 이유는 **과거 데이터가 피드백 루프에 연결되지 않기** 때문입니다.  
이 도구는 PR 히스토리를 분석해 위험한 도메인과 회귀 클러스터를 감지하고, `CLAUDE.md` 또는 `.github/copilot-instructions.md`에 추가할 규칙을 자동 생성합니다.

---

## 작동 원리

```
merged PR 히스토리 (제목만, 빠름)
        ↓
fix PR 클러스터 감지 (연속으로 같은 도메인에서 버그 발생)
        ↓
클러스터 PR만 자동 fetch — 파일 경로 + diff + 리뷰 코멘트 (smart-fetch)
        ↓
고위험 도메인·파일 순위 산출 + 도메인 재분류
        ↓
ChromaDB에서 유사 diff 패턴 검색 (RAG)
        ↓
Claude로 데이터 기반 CLAUDE.md 규칙 생성
        ↓
PR 코멘트 or 주간 이슈로 자동 게시 + rule_tracker로 효과 측정
```

### smart-fetch: 플래그 없이 diff 기반 분석

기존에는 `--fetch-files` 플래그를 써야만 파일 경로와 diff를 수집했습니다. 이제는 **기본 동작**입니다.

| 방식 | API 호출 (fix PR 50개 기준) | diff 포함 |
|------|----------------------------|-----------|
| 기존 기본 | 0회 (제목만) | ❌ |
| `--fetch-files` | ~100회 순차 | ✅ |
| **smart-fetch (현재 기본)** | **클러스터 PR × 1회 병렬** | ✅ |

클러스터에 속한 PR만 fetch하므로 전체 fix PR을 순회하는 것보다 훨씬 빠릅니다.

---

## 왜 단순 키워드 매칭이 아닌 RAG인가

초기 버전은 "fix PR 비율 높음 → ci/cd 규칙 추가" 같은 템플릿 기반 규칙을 생성했습니다. 이 방식의 한계는 **컨텍스트 부재**입니다.

현재 시스템은 두 가지 컨텍스트 소스를 사용합니다.

**1. 실제 diff 패턴** (새로운 주요 소스)
```
[gwangcheon-shop] fix PR #58 (ci/cd): Dockerfile deps 스테이지 수정
변경 파일: Dockerfile
diff:
-COPY package.json pnpm-lock.yaml ./
+COPY package.json pnpm-lock.yaml .npmrc ./
 RUN pnpm install --frozen-lockfile
```
→ "`.npmrc`를 deps 스테이지에 COPY하지 않으면 사설 패키지 설치 실패"라는 규칙이 나옵니다.

**2. 생태계 통계**
```
8개 언어 × 30개 상위 레포 = 240개 레포 크롤링 (매주 자동)
→ 언어/도메인별 회귀 패턴 → ChromaDB 벡터 임베딩
```

규칙 생성 시 diff 패턴이 먼저 검색되고, 없으면 통계로 보완합니다. **데이터가 쌓일수록 규칙 품질이 자동으로 향상됩니다.**

---

## 자동화 스케줄

세 개의 GitHub Actions 워크플로우가 자동으로 실행됩니다.

| 워크플로우 | 스케줄 | 역할 |
|-----------|--------|------|
| `evolve-rules.yml` | 매일 KST 10:00 | gwangcheon-shop PR 분석 → 일일 이슈 리포트 → CLAUDE.md 패치 PR → diff 패턴 누적 저장 → 규칙 효과 측정 |
| `learn-patterns.yml` | 매주 일요일 KST 11:00 | 8개 언어 × 30개 레포 크롤링 → `data/language-patterns.json` 누적 |
| `lint.yml` | push / PR | `src/**/*.py` 문법 검사 + `.github/workflows/*.yml` YAML 검증 |

---

## 실제 데이터 예시

165개 PR 분석 결과 (Next.js + Prisma + Docker 커머스 프로젝트):

```
총 PR: 165개  |  fix PR: 26개 (15.8%)

📍 회귀 클러스터
  [ci/cd      ]  #52 → #53 → #54 → #56 → #58 → #59 → #60 → #61
  [ci/cd      ]  #62 → #66 → #68 → #78
  [payment    ]  #140 → #142 → #150
  [external-api]  #308 → #310

💡 CLAUDE.md 추가 규칙 제안
  - Dockerfile deps 스테이지에 .npmrc COPY 누락 시 사설 패키지 설치 실패 — 4회 회귀
  - CI/CD·Docker 변경 전 verify-build.sh 실행 필수 — 11회 회귀 감지
  - 결제 플로우 변경 시 Opus 모델로 설계 검토 후 구현 — 4회 회귀
  - 외부 API(Kakao·PortOne) 연동은 스테이징 배포 후 검증 — 3회 회귀
```

---

## 데모 사이트

**🌐 [ai-dev-loop-analyzer.rladmsgh34.org](https://ai-dev-loop-analyzer.rladmsgh34.org)**

GitHub 레포 URL을 입력하면 즉시 분석 결과를 확인할 수 있습니다.

- **단일 분석**: `https://ai-dev-loop-analyzer.rladmsgh34.org/r/vercel/next.js`
- **레포 비교**: `https://ai-dev-loop-analyzer.rladmsgh34.org/compare`
- **REST API**: `https://ai-dev-loop-analyzer.rladmsgh34.org/api/analyze?owner=vercel&repo=next.js`

---

## README 배지

```markdown
[![AI fix rate](https://ai-dev-loop-analyzer.rladmsgh34.org/api/badge/owner/repo)](https://ai-dev-loop-analyzer.rladmsgh34.org/r/owner/repo)
```

fix율에 따라 색상이 자동으로 변경됩니다 (녹색 ≤10% / 노란색 ≤20% / 빨간색 >20%).

---

## PR 자동 경고 코멘트

PR에 회귀 다발 도메인 파일이 포함되면 자동으로 경고 코멘트를 달아주는 GitHub Action입니다.

```yaml
# .github/workflows/risk-check.yml
name: PR Risk Check
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  risk-check:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: rladmsgh34/ai-dev-loop-analyzer/.github/actions/check-risk-zones@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          threshold: '10'
```

---

## MCP 서버

Claude Code에 연결하면 코드 작성 시점에 실시간으로 위험 도메인을 경고합니다.

```bash
pip install mcp

# 기본 (범용 패턴)
claude mcp add ai-dev-loop-analyzer -- python3 /path/to/src/mcp_server.py

# 프로파일 적용 (프로젝트별 키워드 사용)
claude mcp add ai-dev-loop-analyzer \
  -e AI_DEV_LOOP_PROFILE=/path/to/my-project.json \
  -- python3 /path/to/src/mcp_server.py
```

### check_risk_zones 출력 예시

```
🔴 Dockerfile
   회귀 이력: 4회 | 도메인: ci/cd
   → verify-build.sh 실행 권장

   📌 마지막 수정 (fix: Dockerfile deps 스테이지 수정):
   ```diff
   -COPY package.json pnpm-lock.yaml ./
   +COPY package.json pnpm-lock.yaml .npmrc ./
    RUN pnpm install --frozen-lockfile
   ```
```

"4번 회귀됐음"에서 "이런 패턴이 문제였음"으로 — 같은 실수를 반복하지 않도록 구체적 컨텍스트를 제공합니다.

| 툴 | 설명 |
|----|------|
| `check_risk_zones` | 편집하려는 파일의 회귀 이력 + 마지막 fix diff 표시 |
| `analyze_pr_history` | 레포 전체 분석 (smart-fetch 포함) |
| `get_active_rules` | 현재 적용 중인 규칙 + 효과 측정 결과 조회 |

---

## 규칙 효과 측정

규칙이 CLAUDE.md에 추가된 시점의 도메인별 fix-rate를 기준점으로 저장하고, 이후 매일 변화를 측정합니다.

```
### 📈 규칙 효과 측정
- 2026-04-01 추가 | fix율 30.0% → 15.0% ▼ 15.0%p (개선, 도메인(ci/cd) 기준)
  규칙: Dockerfile deps 스테이지에 .npmrc COPY 필수 — 4회 회귀
```

규칙 추가 7일 후부터 측정이 시작되며, 도메인별 fix-rate 변화를 우선 사용합니다.

---

## 사용법

### CLI

```bash
pip install -r requirements.txt  # 표준 라이브러리만, 추가 패키지 불필요

# 현재 레포 분석 (smart-fetch 기본 포함)
python3 src/analyze.py

# 전체 fix PR 대상 정밀 분석 (느림)
python3 src/analyze.py --fetch-files

# smart-fetch 비활성화 (제목만 분석)
python3 src/analyze.py --no-smart-fetch

# JSON 출력
python3 src/analyze.py --format json > report.json
```

### GitHub Action

```yaml
# .github/workflows/pr-quality.yml
name: PR Quality Check
on:
  pull_request:
    types: [closed]

jobs:
  analyze:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: rladmsgh34/ai-dev-loop-analyzer@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          limit: "200"
          post-comment: "true"
```

---

## 프로파일 시스템

도메인 키워드·규칙 템플릿·fix PR 패턴을 JSON 프로파일로 교체할 수 있습니다.  
**엔진 코드는 스택 무관** — 프로젝트별 설정은 프라이빗 레포에만 둡니다.

```
profiles/
├── default.json                # 범용 프리셋 (빌트인)
└── examples/
    └── nextjs-prisma.json      # Next.js + Prisma 스택 프리셋
```

프로파일 구조:

```json
{
  "name": "my-project",
  "fix_pr_regex": "^(fix|hotfix|revert)",
  "domain_patterns": [
    ["payment", "payment|stripe|checkout|order"],
    ["external-api", "stripe|sendgrid|s3"]
  ],
  "rule_templates": {
    "payment": "결제 플로우 변경 시 신중한 검토 필수 — {count}회 회귀"
  },
  "rule_hints": {
    "payment": "→ 결제 도메인: Stripe Webhook 검증 누락 여부 확인"
  },
  "prompt_hints": {
    "language": "en",
    "ai_assistant": "Cursor",
    "config_file": ".cursorrules"
  }
}
```

`nextjs-prisma.json`을 시작점으로 복사해서 프로젝트별 외부 서비스 키워드를 추가하세요.

---

## 지원 도메인 (기본값)

기본 프로파일(`default.json`) 기준. 프로파일로 전부 교체 가능합니다.

| 도메인 | 감지 키워드 (기본) |
|--------|--------------------|
| ci/cd | deploy, docker, dockerfile, workflow, compose |
| auth | auth, login, session, jwt, credential |
| payment | payment, checkout, order, cart |
| database | migration, schema, migrate |
| security | csp, xss, csrf, rate-limit, content-security |
| external-api | stripe, twilio, sendgrid, s3, cloudfront, firebase |
| test/e2e | e2e, playwright, vitest, jest, coverage, flaky |
| config | .config., env.ts, tsconfig, biome, tailwind |

> **프로젝트별 키워드** (kakao, portone, gcs 등)는 프로파일 파일에만 추가하세요.  
> 퍼블릭 레포 코드에 서비스명이 하드코딩되지 않습니다.

도메인 분류는 PR 제목과 변경 파일 경로를 함께 봅니다. smart-fetch로 수집된 파일 경로가 있으면 제목만 볼 때보다 정확도가 높아집니다.

### fix PR 감지 패턴

PR 제목에 아래 패턴이 포함되면 fix PR로 분류됩니다.

```json
"fix_pr_regex": "^(fix|hotfix|bugfix|revert)"
```
fix / hotfix / revert / regression / bug
수정 / 버그  (한국어 지원)
```

---

## AI 규칙 생성

별도 API 키 없이 **GitHub Token만으로** AI 규칙 생성이 가능합니다.

| 방식 | 필요한 것 | 모델 |
|------|-----------|------|
| GitHub Models (기본) | `GITHUB_TOKEN` — Actions에서 자동 제공 | gpt-4o-mini |
| Anthropic API (선택) | `ANTHROPIC_API_KEY` | claude-haiku |
| 템플릿 폴백 | 없음 | — |

```bash
# GitHub Models (gh CLI 토큰 자동 사용)
python3 src/analyze.py

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-... python3 src/analyze.py

# AI 없이 템플릿만
python3 src/analyze.py --no-ai
```

## Requirements

- Python 3.10+
- `gh` CLI (인증된 상태)
- 표준 라이브러리만 사용 (추가 패키지 불필요)

RAG 기능 사용 시 추가 설치:

```bash
pip install chromadb sentence-transformers
```

---

## License

MIT
