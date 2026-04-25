# AI Dev Loop Analyzer

[![patterns learned](https://ai-dev-loop-analyzer.rladmsgh34.org/api/badge/stats)](https://ai-dev-loop-analyzer.rladmsgh34.org/languages)

> PR 히스토리에서 회귀 패턴을 감지하고, AI 코딩 어시스턴트(Claude Code 등)의 규칙을 자동으로 제안합니다.

AI-assisted development에서 같은 실수가 반복되는 이유는 **과거 데이터가 피드백 루프에 연결되지 않기** 때문입니다.  
이 도구는 PR 히스토리를 분석해 위험한 도메인과 회귀 클러스터를 감지하고, `CLAUDE.md` 또는 `.github/copilot-instructions.md`에 추가할 규칙을 자동 생성합니다.

---

## 왜 단순 키워드 매칭이 아닌 RAG인가

초기 버전은 "fix PR 비율 높음 → ci/cd 규칙 추가" 같은 템플릿 기반 규칙을 생성했습니다. 이 방식의 한계는 **컨텍스트 부재**입니다. "TypeScript + Next.js + Docker" 스택의 ci/cd 회귀는 "Python + FastAPI + GitHub Actions" 스택의 ci/cd 회귀와 원인이 다릅니다.

현재 시스템은 **생태계 지식 DB**로 진화했습니다:

```
8개 언어 × 30개 상위 레포 = 240개 레포 크롤링 (매주 자동)
        ↓
언어/도메인별 회귀 패턴 → ChromaDB 벡터 임베딩
        ↓
"TypeScript ci/cd 회귀" 쿼리 시 → 가장 유사한 실제 사례 검색
        ↓
Claude로 데이터 기반 정밀 규칙 생성
```

단순 통계가 아니라 "TypeScript 레포 상위 30개에서 ci/cd 도메인 평균 fix율 18%, 가장 흔한 트리거: Docker 이미지 태그 변경·musl 바이너리 누락" 같은 구체적 패턴을 컨텍스트로 주입합니다. **데이터가 쌓일수록 규칙 품질이 자동으로 향상됩니다.**

---

## 작동 원리

```
merged PR 히스토리
        ↓
fix PR 클러스터 감지 (연속으로 같은 도메인에서 버그 발생)
        ↓
고위험 도메인·파일 순위 산출
        ↓
ChromaDB에서 유사 언어/도메인 패턴 검색 (RAG)
        ↓
Claude로 데이터 기반 CLAUDE.md 규칙 생성
        ↓
PR 코멘트 or 주간 이슈로 자동 게시
```

---

## 자동화 스케줄

세 개의 GitHub Actions 워크플로우가 자동으로 실행됩니다.

| 워크플로우 | 스케줄 | 역할 |
|-----------|--------|------|
| `evolve-rules.yml` | 매일 KST 10:00 | gwangcheon-shop PR 분석 → 일일 이슈 리포트 → CLAUDE.md 패치 PR |
| `learn-patterns.yml` | 매주 일요일 KST 11:00 | 8개 언어 × 30개 레포 크롤링 → `data/language-patterns.json` 누적 |
| `lint.yml` | push / PR | `src/**/*.py` 문법 검사 + `.github/workflows/*.yml` YAML 검증 |

워크플로우는 모두 `workflow_dispatch`로 수동 실행도 가능합니다.

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
  - CI/CD·Docker 변경 전 verify-build.sh 실행 필수 — 11회 회귀 감지
  - 결제 플로우 변경 시 Opus 모델로 설계 검토 후 구현 — 4회 회귀
  - 외부 API(Kakao·PortOne) 연동은 스테이징 배포 후 검증 — 3회 회귀
```

---

## 데모 사이트

**🌐 [ai-dev-loop-analyzer.rladmsgh34.org](https://ai-dev-loop-analyzer.rladmsgh34.org)**

GitHub 레포 URL을 입력하면 즉시 분석 결과를 확인할 수 있습니다. 별도 설치 없이 브라우저에서 바로 사용 가능합니다.

- **단일 분석**: `https://ai-dev-loop-analyzer.rladmsgh34.org/r/vercel/next.js`
- **레포 비교**: `https://ai-dev-loop-analyzer.rladmsgh34.org/compare`
- **REST API**: `https://ai-dev-loop-analyzer.rladmsgh34.org/api/analyze?owner=vercel&repo=next.js`

---

## README 배지

분석 결과를 배지로 README에 추가할 수 있습니다.

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
          threshold: '10'   # fix율 10% 이상 도메인에 경고
```

자세한 예시는 `examples/pr-risk-check.yml` 참고.

---

## MCP 서버

Claude Code에 연결하면 코드 작성 시점에 실시간으로 위험 도메인을 경고합니다.

```bash
# 설치
pip install mcp
claude mcp add ai-dev-loop-analyzer -- python3 /path/to/src/mcp_server.py
```

사용 가능한 툴:
| 툴 | 설명 |
|----|------|
| `check_risk_zones` | 편집하려는 파일이 회귀 다발 도메인인지 사전 경고 |
| `analyze_pr_history` | 레포 전체 분석 실행 |
| `get_active_rules` | 현재 적용 중인 규칙 조회 |

---

## 사용법

### CLI (로컬)

```bash
# gh CLI 인증 필요
pip install -r requirements.txt  # 없음, 표준 라이브러리만 사용

# 현재 레포 분석
python3 src/analyze.py

# 파일 목록까지 수집 (느리지만 더 정확)
python3 src/analyze.py --fetch-files

# JSON 출력
python3 src/analyze.py --format json > report.json

# 옵션
python3 src/analyze.py --help
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
      - uses: your-username/ai-dev-loop-analyzer@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          limit: "200"
          post-comment: "true"
```

주간 리포트 예시는 `examples/weekly-report.yml` 참고.

---

## 지원 도메인

| 도메인 | 감지 키워드 |
|--------|-------------|
| ci/cd | deploy, docker, dockerfile, workflow, compose |
| auth | auth, login, session, jwt, credential |
| payment | payment, checkout, order, cart |
| database | prisma, migration, schema |
| security | csp, xss, csrf, rate-limit |
| external-api | kakao, portone, gcs, sentry |
| test/e2e | e2e, playwright, vitest, coverage |
| config | next.config, env.ts, tsconfig |

### fix PR 감지 패턴

PR 제목이 아래 접두사로 시작하면 fix PR로 분류됩니다.

```
fix / hotfix / bugfix / revert / regression / bug
```

예: `fix: 장바구니 수량 버그`, `revert: 결제 로직 롤백`, `regression: 로그인 세션 만료 이슈`

---

## AI 어시스턴트 통합

### Claude Code (`CLAUDE.md`)
생성된 규칙을 `CLAUDE.md`의 `## 🐛 Claude가 했던 실수` 섹션에 추가하면 다음 세션부터 즉시 적용됩니다.

### GitHub Copilot (`.github/copilot-instructions.md`)
동일한 규칙을 Copilot 지시 파일에도 사용할 수 있습니다.

### Cursor (`.cursorrules`)
Cursor 규칙 파일에도 동일하게 적용 가능합니다.

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

# 모델 지정
python3 src/analyze.py --model gpt-4o
```

## Requirements

- Python 3.10+
- `gh` CLI (인증된 상태)
- 표준 라이브러리만 사용 (추가 패키지 불필요)

RAG 기능 사용 시 추가 설치:

```bash
pip install chromadb sentence-transformers
```

RAG 없이도 GitHub Models / Anthropic API / 템플릿 폴백으로 규칙 생성이 가능합니다.

---

## License

MIT
